"""Server-side conversation export (mirrors static/exportConversation.js)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


def _slugify_filename(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", (title or "conversation").strip()[:48])
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug or "conversation"


def turns_to_messages(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for turn in turns or []:
        user = turn.get("user")
        assistant = turn.get("assistant")
        turn_no = turn.get("turn")
        if user:
            messages.append(
                {
                    "role": "user",
                    "content": user.get("content"),
                    "ts": user.get("ts"),
                    "dashboardSelection": user.get("dashboardSelection"),
                    "turn": turn_no,
                }
            )
        if assistant:
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant.get("content"),
                    "ts": assistant.get("ts"),
                    "reasoning": assistant.get("reasoning"),
                    "toolActions": assistant.get("toolActions"),
                    "suggestedFollowups": assistant.get("suggestedFollowups"),
                    "guidance": assistant.get("guidance"),
                    "dashboardPicker": assistant.get("dashboardPicker"),
                    "turn": turn_no,
                    "qa_issues": turn.get("qa_issues"),
                }
            )
    return messages


def _normalize_export_message(msg: dict[str, Any], index: int) -> dict[str, Any] | None:
    content = str(msg.get("content") or "").strip()
    ts = msg.get("ts")
    if not isinstance(ts, (int, float)):
        ts = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    role = "advisor" if msg.get("role") == "assistant" else "cx_director"
    entry: dict[str, Any] = {
        "id": f"msg_{ts}_{index}",
        "role": role,
        "content": content,
        "timestamp": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
    }
    if msg.get("turn") is not None:
        entry["turn"] = msg["turn"]
    for src, dst in (
        ("suggestedFollowups", "suggested_followups"),
        ("toolActions", "tool_actions"),
    ):
        val = msg.get(src)
        if isinstance(val, list) and val:
            entry[dst] = [str(v).strip() for v in val if str(v).strip()]
    for key in ("guidance", "reasoning"):
        val = msg.get(key)
        if isinstance(val, str) and val.strip():
            entry[key] = val.strip()
    dash_sel = msg.get("dashboardSelection")
    if isinstance(dash_sel, dict) and dash_sel.get("id") is not None:
        entry["dashboard_selection"] = {
            "id": dash_sel["id"],
            **({"name": dash_sel["name"]} if dash_sel.get("name") else {}),
        }
    picker = msg.get("dashboardPicker")
    if isinstance(picker, dict) and picker.get("dashboards"):
        entry["dashboard_picker"] = picker
    qa_issues = msg.get("qa_issues")
    if isinstance(qa_issues, list) and qa_issues:
        entry["qa_issues"] = qa_issues
    if not any(
        (
            entry.get("content"),
            entry.get("dashboard_picker"),
            entry.get("dashboard_selection"),
            entry.get("suggested_followups"),
            entry.get("reasoning"),
            entry.get("qa_issues"),
        )
    ):
        return None
    return entry


def build_conversation_export_json(
    *,
    session_id: str,
    title: str,
    messages: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    normalized = [
        normed
        for i, msg in enumerate(messages)
        if (normed := _normalize_export_message(msg, i)) is not None
    ]
    body: dict[str, Any] = {
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "product": "pivony-quality-loop",
        "session_id": session_id,
        "title": title or "Quality Loop Conversation",
        "sector": meta.get("sector"),
        "user_email": meta.get("user_email"),
        "user_id": meta.get("user_id"),
        "job_id": meta.get("job_id"),
        "run_id": meta.get("run_id"),
        "turn_count": meta.get("turn_count"),
        "messages": normalized,
    }
    qa = meta.get("qa_report")
    if isinstance(qa, dict):
        body["qa_report"] = {
            "overall_verdict": qa.get("overall_verdict"),
            "priority_fix": qa.get("priority_fix"),
            "scores": qa.get("scores"),
            "issues": qa.get("issues") or [],
        }
    return body


def build_conversation_export_markdown(
    *,
    title: str,
    messages: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> str:
    meta = meta or {}
    export_json = build_conversation_export_json(
        session_id=str(meta.get("session_id") or ""),
        title=title,
        messages=messages,
        meta=meta,
    )
    lines = [
        f"# Pivony Quality Loop — {title or 'Conversation'}",
        f"Exported: {datetime.now().strftime('%d %B %Y %H:%M')}",
    ]
    for key, label in (
        ("session_id", "Session"),
        ("sector", "Sector"),
        ("user_email", "User"),
        ("job_id", "Job"),
        ("run_id", "Run"),
    ):
        if meta.get(key):
            lines.append(f"{label}: {meta[key]}")
    if meta.get("turn_count"):
        lines.append(f"Turns: {meta['turn_count']}")
    qa = export_json.get("qa_report") or {}
    if qa.get("overall_verdict"):
        lines.append(f"QA verdict: {qa['overall_verdict']}")
    if qa.get("priority_fix"):
        lines.append(f"Priority fix: {qa['priority_fix']}")
    lines.extend(["", "---", ""])

    role_labels = {"cx_director": "CX Director", "advisor": "Advisor"}
    for msg in export_json.get("messages") or []:
        label = role_labels.get(msg.get("role"), msg.get("role"))
        turn_prefix = f" · Tur {msg['turn']}" if msg.get("turn") is not None else ""
        lines.append(f"**{label}**{turn_prefix}")
        if msg.get("content"):
            lines.append(str(msg["content"]))
        if msg.get("dashboard_selection"):
            sel = msg["dashboard_selection"]
            name = sel.get("name") or f"Dashboard {sel.get('id')}"
            lines.append(f"\n**Dashboard selected:** {name} (id: {sel.get('id')})")
        if msg.get("reasoning"):
            lines.extend(["", "**Reasoning:**", str(msg["reasoning"])])
        if msg.get("tool_actions"):
            lines.extend(["", "**Tool actions:**"])
            lines.extend(f"- {t}" for t in msg["tool_actions"])
        if msg.get("suggested_followups"):
            lines.extend(["", "**Suggested follow-ups:**"])
            lines.extend(f"- {q}" for q in msg["suggested_followups"])
        if msg.get("guidance"):
            lines.extend(["", "**Guidance:**", str(msg["guidance"])])
        if msg.get("dashboard_picker", {}).get("dashboards"):
            lines.extend(["", "**Dashboards:**"])
            for d in msg["dashboard_picker"]["dashboards"]:
                lines.append(f"- {d.get('name')} (id: {d.get('id')})")
        if msg.get("qa_issues"):
            lines.extend(["", "**QA issues:**"])
            for issue in msg["qa_issues"]:
                sev = issue.get("severity")
                prefix = f"[{sev}] " if sev else ""
                lines.append(f"- {prefix}{issue.get('category', 'issue')}: {issue.get('description', '')}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_qa_export_json(
    *,
    session_id: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    qa = meta.get("qa_report")
    body: dict[str, Any] = {
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "product": "pivony-quality-loop-qa",
        "session_id": session_id,
        "sector": meta.get("sector"),
        "user_email": meta.get("user_email"),
        "user_id": meta.get("user_id"),
        "job_id": meta.get("job_id"),
        "run_id": meta.get("run_id"),
        "turn_count": meta.get("turn_count"),
    }
    if isinstance(qa, dict):
        body["qa_report"] = {
            "overall_verdict": qa.get("overall_verdict"),
            "priority_fix": qa.get("priority_fix"),
            "scores": qa.get("scores"),
            "issues": qa.get("issues") or [],
            "summary": qa.get("summary"),
        }
    else:
        body["qa_report"] = None
    fixes = meta.get("fixes")
    if isinstance(fixes, dict):
        body["fixes"] = fixes
    summary = meta.get("summary")
    if isinstance(summary, dict):
        body["summary"] = summary
    return body


def export_filename(
    session_id: str,
    ext: str,
    *,
    kind: str = "conversation",
    run_id: str | None = None,
) -> str:
    date = datetime.now().strftime("%Y-%m-%d")
    slug_source = run_id if kind == "qa" and run_id else session_id
    slug = _slugify_filename(slug_source)
    labels = {
        "qa": "pivony-quality-loop-qa",
        "conversation": "pivony-quality-loop-conversation",
        "all": "pivony-quality-loop-full",
    }
    prefix = labels.get(kind, "pivony-quality-loop")
    return f"{prefix}-{slug}-{date}.{ext}"


def export_payload_from_session_detail(
    detail: dict[str, Any], extra: dict[str, Any] | None = None, *, scope: str = "all"
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    extra = extra or {}
    turns = detail.get("turns") or []
    messages = turns_to_messages(turns)
    session_id = str(detail.get("session_id") or "")
    linked = detail.get("linked_runs") or []
    run_id = extra.get("run_id") or detail.get("run_id") or (linked[0].get("run_id") if linked else None)
    qa_report = extra.get("qa_report")
    if qa_report is None:
        qa_report = detail.get("qa_report")
    meta = {
        "session_id": session_id,
        "sector": detail.get("sector"),
        "user_email": detail.get("user_email"),
        "user_id": detail.get("user_id"),
        "run_id": run_id,
        "job_id": extra.get("job_id"),
        "turn_count": len(turns),
        "qa_report": qa_report,
        "fixes": extra.get("fixes"),
        "summary": extra.get("summary"),
    }
    title = session_id[:18] + "…" if len(session_id) > 20 else session_id
    if scope == "qa":
        payload = build_qa_export_json(session_id=session_id, meta=meta)
        return payload, messages
    conversation_meta = dict(meta)
    if scope == "conversation":
        conversation_meta["qa_report"] = None
    payload = build_conversation_export_json(
        session_id=session_id,
        title=title,
        messages=messages,
        meta=conversation_meta,
    )
    return payload, messages
