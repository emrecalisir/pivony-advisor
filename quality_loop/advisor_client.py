"""HTTP client for Pivony Advisor /v1/chat/completions (SSE + non-stream)."""

from __future__ import annotations

import json
import os
from typing import Any

import requests

DEFAULT_MODEL = os.environ.get("PIVONY_ADVISOR_MODEL", "pivony-local-llm")
DEFAULT_TIMEOUT = int(os.environ.get("PIVONY_ADVISOR_TIMEOUT_SEC", "120"))


def _base_url() -> str:
    return os.environ.get("PIVONY_ADVISOR_URL", "http://127.0.0.1:8000").rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    token = os.environ.get("PIVONY_ADVISOR_API_TOKEN") or os.environ.get("PIVONY_API_KEY")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _identity_headers(user_id: str | None, user_email: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if user_id:
        out["x-pivony-user-id"] = user_id
    if user_email:
        out["x-pivony-user-email"] = user_email
    return out


def build_page_context(
    *,
    analytics_scope: dict | None = None,
    dashboard_id: int | None = None,
    dashboard_name: str | None = None,
    last_dashboard_selection: dict | None = None,
    since: str | None = None,
    until: str | None = None,
    days: int | None = None,
) -> dict[str, Any]:
    """Mirror pivony-web-platform → pivony-api page_context shape."""
    pc: dict[str, Any] = {}
    if dashboard_id is not None:
        pc["dashboard_id"] = dashboard_id
    if since:
        pc["since"] = since
    if until:
        pc["until"] = until
    if days is not None:
        pc["days"] = days

    asc: dict[str, Any] = {}
    if analytics_scope and isinstance(analytics_scope, dict):
        dash = analytics_scope.get("dashboardId") or analytics_scope.get("dashboard_id")
        if dash is not None:
            try:
                asc["dashboard_id"] = int(dash)
            except (TypeError, ValueError):
                pass
        if analytics_scope.get("orgWide") or analytics_scope.get("org_wide"):
            asc["org_wide"] = True
        for key, out_key in (("days", "days"), ("since", "since"), ("until", "until")):
            val = analytics_scope.get(key)
            if val is not None:
                asc[out_key] = val
    elif dashboard_id is not None:
        asc["dashboard_id"] = dashboard_id
        asc["org_wide"] = False

    if asc:
        pc["analytics_scope"] = asc

    if last_dashboard_selection and last_dashboard_selection.get("id") is not None:
        pc["last_dashboard_selection"] = {
            "id": int(last_dashboard_selection["id"]),
            "name": last_dashboard_selection.get("name"),
        }
    if dashboard_id is not None and dashboard_name:
        pc["dashboard_selection"] = {"id": dashboard_id, "name": dashboard_name}

    return pc


def messages_for_api(session_messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Advisor accepts role + content only in the messages array."""
    out: list[dict[str, str]] = []
    for msg in session_messages:
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant") and content is not None:
            out.append({"role": role, "content": str(content)})
    return out


def chat_stream(
    messages: list[dict[str, str]],
    *,
    user_id: str | None = None,
    user_email: str | None = None,
    sector: str = "hospitality",
    advisor_mode: str = "advisor",
    page_context: dict | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Stream a chat turn; aggregate thought/content/tool events.

    Returns dict with: content, reasoning, tool_actions, suggested_followups,
    guidance, dashboard_picker.
    """
    payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "stream": True,
        "pivony_sector": sector,
        "pivony_advisor_mode": advisor_mode,
    }
    if user_id:
        payload["pivony_user_id"] = user_id
    if user_email:
        payload["pivony_user_email"] = user_email
    if page_context:
        payload["pivony_page_context"] = page_context

    headers = {**_headers(), **_identity_headers(user_id, user_email)}
    url = f"{_base_url()}/v1/chat/completions"

    reasoning_parts: list[str] = []
    content_parts: list[str] = []
    tool_actions: list[str] = []
    suggested_followups: list[str] = []
    guidance = ""
    dashboard_picker = None
    final_content = ""

    with requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
        stream=True,
    ) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            data_str = raw_line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            etype = event.get("type")
            if etype == "thought":
                delta = event.get("delta") or event.get("content") or ""
                if delta:
                    reasoning_parts.append(str(delta))
            elif etype == "status":
                if event.get("phase") == "retry":
                    msg = str(event.get("message") or "").strip()
                    if msg:
                        content_parts = [msg]
                else:
                    tool = event.get("tool") or event.get("name") or event.get("detail") or ""
                    if tool and (not tool_actions or tool_actions[-1] != tool):
                        tool_actions.append(str(tool))
            elif etype == "content":
                delta = event.get("delta") or ""
                if delta:
                    if event.get("replace"):
                        content_parts = [str(delta)]
                    else:
                        content_parts.append(str(delta))
            elif etype == "dashboard_picker":
                picker = event.get("picker")
                if isinstance(picker, dict):
                    dashboard_picker = picker
            elif etype == "done":
                final_content = str(event.get("content") or "")
                raw_fu = event.get("pivony_suggested_followups")
                if isinstance(raw_fu, list):
                    suggested_followups = [str(x).strip() for x in raw_fu if str(x).strip()]
                guidance = str(event.get("pivony_guidance") or "")
                picker = event.get("pivony_dashboard_picker")
                if isinstance(picker, dict):
                    dashboard_picker = picker
            elif etype == "error":
                raise RuntimeError(event.get("message") or "advisor stream error")

    content = final_content or "".join(content_parts)
    return {
        "content": content,
        "reasoning": "".join(reasoning_parts).strip(),
        "tool_actions": tool_actions,
        "suggested_followups": suggested_followups,
        "guidance": guidance,
        "dashboard_picker": dashboard_picker,
    }


def chat(
    messages: list[dict[str, str]],
    *,
    user_id: str | None = None,
    user_email: str | None = None,
    sector: str = "hospitality",
    advisor_mode: str = "advisor",
    page_context: dict | None = None,
    model: str | None = None,
    use_stream: bool = True,
) -> dict[str, Any]:
    """Send one advisor turn. Defaults to streaming for reasoning/tool capture."""
    if use_stream:
        return chat_stream(
            messages,
            user_id=user_id,
            user_email=user_email,
            sector=sector,
            advisor_mode=advisor_mode,
            page_context=page_context,
            model=model,
        )

    payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "stream": False,
        "pivony_sector": sector,
        "pivony_advisor_mode": advisor_mode,
    }
    if user_id:
        payload["pivony_user_id"] = user_id
    if user_email:
        payload["pivony_user_email"] = user_email
    if page_context:
        payload["pivony_page_context"] = page_context

    headers = {**_headers(), **_identity_headers(user_id, user_email)}
    url = f"{_base_url()}/v1/chat/completions"
    resp = requests.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {
        "content": message.get("content") or "",
        "reasoning": "",
        "tool_actions": [],
        "suggested_followups": data.get("pivony_suggested_followups") or [],
        "guidance": data.get("pivony_guidance") or "",
        "dashboard_picker": data.get("pivony_dashboard_picker"),
    }
