"""Unified cycle manifest: session ≡ run (single cycle_id, one JSON file)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from quality_loop.session_store import (
    SESSIONS_DIR,
    load_session,
    new_session_id,
    save_session,
    _utcnow_iso,
)


def cycle_id_for(session: dict[str, Any]) -> str:
    return str(
        session.get("cycle_id")
        or session.get("session_id")
        or ""
    )


def cycle_as_run(session: dict[str, Any]) -> dict[str, Any]:
    """Shape a unified cycle file like a legacy run manifest for API compat."""
    cid = cycle_id_for(session)
    fixes = session.get("fixes")
    if not isinstance(fixes, dict):
        fixes = {"fixes_applied": [], "fixes_skipped": []}
    return {
        "run_id": cid,
        "cycle_id": cid,
        "session_id": cid,
        "mode": session.get("mode"),
        "iteration": session.get("iteration"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "job_id": session.get("job_id"),
        "advisor_url": session.get("advisor_url"),
        "status": session.get("status"),
        "phases": session.get("phases") or [],
        "qa_report": session.get("qa_report"),
        "fixes": fixes,
        "final_result": session.get("final_result") or "",
        "summary": session.get("summary") or {},
        "issue_traceability": session.get("issue_traceability") or [],
        "verification": session.get("verification"),
    }


def is_completed_cycle(session: dict[str, Any] | None) -> bool:
    if not session:
        return False
    if session.get("status") == "done":
        return True
    qa = session.get("qa_report")
    return isinstance(qa, dict) and bool(qa.get("overall_verdict") or qa.get("issues"))


def create_cycle_for_job(
    *,
    job_id: str,
    sector: str = "default",
    mode: str = "full",
    advisor_mode: str = "advisor",
    user_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    cid = new_session_id()
    session = {
        "session_id": cid,
        "cycle_id": cid,
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
        "user_id": user_id,
        "user_email": user_email,
        "sector": sector,
        "advisor_mode": advisor_mode,
        "job_id": job_id,
        "mode": mode,
        "status": "conversation",
        "messages": [],
        "page_context": {},
        "analytics_scope": None,
        "last_dashboard_selection": None,
        "phases": None,
        "qa_report": None,
        "fixes": None,
        "summary": None,
        "final_result": None,
        "advisor_url": None,
        "iteration": None,
    }
    save_session(session)
    return session


def finalize_cycle(session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    session = load_session(session_id)
    if session is None:
        raise KeyError(f"cycle not found: {session_id}")
    cid = cycle_id_for(session) or session_id
    session["cycle_id"] = cid
    session["session_id"] = cid
    for key, value in patch.items():
        if value is not None:
            session[key] = value
    session["status"] = patch.get("status") or "done"
    save_session(session)
    return session


def mark_cycle_failed(session_id: str, *, message: str | None = None) -> dict[str, Any] | None:
    session = load_session(session_id)
    if session is None:
        return None
    session["status"] = "failed"
    if message:
        session["failure_message"] = message
    save_session(session)
    return session


def list_completed_cycles() -> list[dict[str, Any]]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for path in sorted(SESSIONS_DIR.glob("sess_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (ValueError, OSError, json.JSONDecodeError):
            continue
        if not is_completed_cycle(data):
            continue
        run_view = cycle_as_run(data)
        rows.append(
            {
                "run_id": run_view["run_id"],
                "cycle_id": run_view["cycle_id"],
                "session_id": run_view["session_id"],
                "mode": run_view.get("mode"),
                "iteration": run_view.get("iteration"),
                "created_at": run_view.get("created_at"),
                "summary": run_view.get("summary") or {},
                "file": path.name,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                .isoformat(timespec="seconds"),
            }
        )
    return rows
