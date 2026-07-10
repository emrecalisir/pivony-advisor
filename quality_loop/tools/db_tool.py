"""Read conversations from quality-loop store, history.log, or optional Postgres."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from quality_loop.session_store import (
    list_recent_session_ids,
    session_messages_for_qa,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _history_log_path() -> Path:
    return _project_root() / "logs" / "history.log"


def _fetch_from_postgres(session_id: str) -> list[dict] | None:
    """
    Optional: read cx_gpt_chat_messages when QUALITY_LOOP_DATABASE_URL is set.
    Schema: pivony-api-dev (cx_gpt_chat_sessions / cx_gpt_chat_messages).
    """
    db_url = os.environ.get("QUALITY_LOOP_DATABASE_URL", "").strip()
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return None

    engine = create_engine(db_url)
    query = text(
        """
        SELECT role, content, message_metadata, created_at, sort_index
        FROM cx_gpt_chat_messages
        WHERE session_id = :sid
        ORDER BY sort_index ASC, created_at ASC
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"sid": session_id}).mappings().all()

    out: list[dict] = []
    for row in rows:
        meta = row.get("message_metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                meta = {}
        out.append(
            {
                "role": row.get("role"),
                "content": row.get("content"),
                "tool_actions": meta.get("toolActions") or [],
                "reasoning": meta.get("reasoning") or "",
                "suggested_followups": meta.get("suggestedFollowups") or [],
                "dashboard_selection": meta.get("dashboardSelection"),
                "dashboard_picker": meta.get("dashboardPicker"),
                "created_at": str(row.get("created_at")),
            }
        )
    return out


def _fetch_from_history_log(limit: int = 5) -> list[dict]:
    """Return recent advisor audit records from logs/history.log."""
    path = _history_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    records: list[dict] = []
    for line in reversed(lines[-500:]):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(records) >= limit:
            break
    return list(reversed(records))


class FetchSessionInput(BaseModel):
    session_id: str = Field(description="Session id (quality_loop sess_* or pivony-api sess_*)")


class FetchSessionTool(BaseTool):
    name: str = "fetch_conversation"
    description: str = (
        "Load all messages for a session. Tries quality_loop local store first, "
        "then optional Postgres (QUALITY_LOOP_DATABASE_URL), "
        "including role, content, tool_actions, reasoning, dashboard_selection."
    )
    args_schema: Type[BaseModel] = FetchSessionInput

    def _run(self, session_id: str) -> str:
        try:
            rows = session_messages_for_qa(session_id)
            source = "quality_loop_sessions"
        except KeyError:
            rows = None
            source = None

        if not rows:
            pg_rows = _fetch_from_postgres(session_id)
            if pg_rows:
                rows = pg_rows
                source = "postgres_cx_gpt_chat_messages"

        if not rows:
            return json.dumps(
                {
                    "error": f"session not found: {session_id}",
                    "hint": (
                        "Use a session_id from create_advisor_session or "
                        "fetch_recent_sessions. For prod UI sessions set "
                        "QUALITY_LOOP_DATABASE_URL to pivony-api Postgres."
                    ),
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "session_id": session_id,
                "source": source,
                "message_count": len(rows),
                "indexing_rules": (
                    "message_index is 0-based over the messages[] array below ONLY. "
                    "Each issue.message_index MUST reference an advisor or user row from THIS session. "
                    "Do NOT use history_log_samples, fetch_recent_sessions, or other sessions."
                ),
                "messages": rows,
            },
            ensure_ascii=False,
            default=str,
        )


class FetchRecentSessionsInput(BaseModel):
    limit: int = Field(default=5, description="How many recent sessions to list")


class FetchRecentSessionsTool(BaseTool):
    name: str = "fetch_recent_sessions"
    description: str = (
        "List recent quality-loop session ids (local JSON). "
        "Also includes last entries from logs/history.log when present."
    )
    args_schema: Type[BaseModel] = FetchRecentSessionsInput

    def _run(self, limit: int = 5) -> str:
        local_ids = list_recent_session_ids(limit=limit)
        history = _fetch_from_history_log(limit=min(limit, 3))
        return json.dumps(
            {
                "quality_loop_sessions": local_ids,
                "history_log_samples": [
                    {
                        "ts": h.get("ts"),
                        "user_id": h.get("user_id"),
                        "message_count": len(h.get("messages") or []),
                        "assistant_preview": (h.get("assistant_response") or "")[:200],
                    }
                    for h in history
                ],
            },
            ensure_ascii=False,
        )
