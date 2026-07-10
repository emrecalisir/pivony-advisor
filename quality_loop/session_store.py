"""Local session persistence for the quality loop (advisor is stateless)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PACKAGE_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = _PACKAGE_ROOT / "outputs"
SESSIONS_DIR = OUTPUT_DIR / "sessions"
RUNS_DIR = OUTPUT_DIR / "runs"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    return f"sess_{uuid.uuid4().hex}"


def _session_path(session_id: str) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return SESSIONS_DIR / f"{safe}.json"


def load_session(session_id: str) -> dict[str, Any] | None:
    path = _session_path(session_id)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_session(session: dict[str, Any]) -> None:
    session_id = session.get("session_id")
    if not session_id:
        raise ValueError("session_id is required")
    session["updated_at"] = _utcnow_iso()
    path = _session_path(session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def create_session(
    *,
    user_id: str | None = None,
    user_email: str | None = None,
    sector: str = "hospitality",
    advisor_mode: str = "advisor",
) -> dict[str, Any]:
    session = {
        "session_id": new_session_id(),
        "cycle_id": None,
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
        "user_id": user_id,
        "user_email": user_email,
        "sector": sector,
        "advisor_mode": advisor_mode,
        "status": "conversation",
        "messages": [],
        "page_context": {},
        "analytics_scope": None,
        "last_dashboard_selection": None,
    }
    session["cycle_id"] = session["session_id"]
    save_session(session)
    return session


def append_turn(
    session_id: str,
    *,
    user_content: str,
    assistant_content: str,
    suggested_followups: list[str] | None = None,
    guidance: str | None = None,
    dashboard_picker: dict | None = None,
    reasoning: str | None = None,
    tool_actions: list[str] | None = None,
    dashboard_selection: dict | None = None,
) -> dict[str, Any]:
    session = load_session(session_id)
    if session is None:
        raise KeyError(f"session not found: {session_id}")

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    user_msg: dict[str, Any] = {
        "role": "user",
        "content": user_content,
        "ts": now_ms,
    }
    if dashboard_selection:
        user_msg["dashboardSelection"] = dashboard_selection

    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": assistant_content,
        "ts": now_ms + 1,
    }
    if suggested_followups:
        assistant_msg["suggestedFollowups"] = suggested_followups
    if guidance:
        assistant_msg["guidance"] = guidance
    if dashboard_picker:
        assistant_msg["dashboardPicker"] = dashboard_picker
    if reasoning:
        assistant_msg["reasoning"] = reasoning
    if tool_actions:
        assistant_msg["toolActions"] = tool_actions

    session["messages"].extend([user_msg, assistant_msg])
    save_session(session)
    return session


def update_session_context(
    session_id: str,
    *,
    page_context: dict | None = None,
    analytics_scope: dict | None = None,
    last_dashboard_selection: dict | None = None,
) -> dict[str, Any]:
    session = load_session(session_id)
    if session is None:
        raise KeyError(f"session not found: {session_id}")
    if page_context is not None:
        session["page_context"] = page_context
    if analytics_scope is not None:
        session["analytics_scope"] = analytics_scope
    if last_dashboard_selection is not None:
        session["last_dashboard_selection"] = last_dashboard_selection
    save_session(session)
    return session


def list_recent_session_ids(limit: int = 10) -> list[str]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        SESSIONS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    ids: list[str] = []
    for path in files[:limit]:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            sid = data.get("session_id")
            if sid:
                ids.append(sid)
        except (json.JSONDecodeError, OSError):
            continue
    return ids


def _safe_session_stem(session_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)


def _delete_run_mirrors(session_id: str) -> list[str]:
    removed: list[str] = []
    if not RUNS_DIR.exists():
        return removed
    stem = _safe_session_stem(session_id)
    paths: list[Path] = []
    direct = RUNS_DIR / f"{stem}.json"
    if direct.exists():
        paths.append(direct)
    for path in RUNS_DIR.glob("*.json"):
        if path in paths:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        linked = str(data.get("session_id") or data.get("cycle_id") or "")
        if linked == session_id:
            paths.append(path)
    for path in paths:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            continue
    return removed


def delete_session_files(session_ids: list[str]) -> dict[str, Any]:
    """Delete session JSON files and matching legacy run mirrors."""
    deleted: list[str] = []
    missing: list[str] = []
    run_files_removed: list[str] = []
    for session_id in session_ids:
        sid = str(session_id or "").strip()
        if not sid:
            continue
        path = _session_path(sid)
        if not path.exists():
            missing.append(sid)
            continue
        try:
            path.unlink()
            deleted.append(sid)
            run_files_removed.extend(_delete_run_mirrors(sid))
        except OSError:
            missing.append(sid)
    return {
        "deleted": deleted,
        "missing": missing,
        "run_files_removed": run_files_removed,
    }


def list_all_session_ids() -> list[str]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    ids: list[str] = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            sid = str(data.get("session_id") or path.stem)
            ids.append(sid)
        except (json.JSONDecodeError, OSError):
            ids.append(path.stem)
    return ids


def session_messages_for_qa(session_id: str) -> list[dict[str, Any]]:
    """Normalize messages for QA agent (role, content, metadata fields)."""
    session = load_session(session_id)
    if session is None:
        raise KeyError(f"session not found: {session_id}")
    rows: list[dict[str, Any]] = []
    flat_index = 0
    for msg in session.get("messages") or []:
        row = {
            "message_index": flat_index,
            "role": msg.get("role"),
            "content": msg.get("content"),
            "tool_actions": msg.get("toolActions") or [],
            "reasoning": msg.get("reasoning") or "",
            "suggested_followups": msg.get("suggestedFollowups") or [],
            "dashboard_selection": msg.get("dashboardSelection"),
            "dashboard_picker": msg.get("dashboardPicker"),
            "ts": msg.get("ts"),
        }
        if msg.get("turn") is not None:
            row["turn"] = msg.get("turn")
        rows.append(row)
        flat_index += 1
    return rows
