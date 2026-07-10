"""Advisor server logs for QA root-cause analysis (history.log + advisor.log)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from quality_loop.session_store import load_session

_LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_ERROR_MARKERS = (
    "ERROR",
    "WARNING",
    "CRITICAL",
    "Traceback",
    "Exception",
    "rate limit",
    "429",
    "500",
    "failed",
)


def _project_root() -> Path:
    env = os.environ.get("PIVONY_REPO_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _logs_dir() -> Path:
    override = os.environ.get("QUALITY_LOOP_ADVISOR_LOGS_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _project_root() / "logs"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _session_bounds(session: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    times: list[datetime] = []
    for msg in session.get("messages") or []:
        ts = msg.get("ts")
        if isinstance(ts, (int, float)) and ts > 0:
            sec = ts / 1000 if ts > 1e12 else ts
            times.append(datetime.fromtimestamp(sec, tz=timezone.utc))
    for key in ("created_at", "updated_at"):
        dt = _parse_iso(session.get(key))
        if dt:
            times.append(dt)
    if not times:
        return None, None
    return min(times), max(times)


def _user_message_fingerprints(session: dict[str, Any]) -> list[str]:
    fps: list[str] = []
    for msg in session.get("messages") or []:
        if msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "").strip()
        if len(content) >= 24:
            fps.append(content[:120])
        elif content:
            fps.append(content)
    return fps


def _history_record_matches(
    record: dict[str, Any],
    *,
    user_id: str,
    user_email: str,
    fingerprints: list[str],
) -> bool:
    uid_match = bool(user_id and record.get("user_id") == user_id)
    email_match = bool(user_email and record.get("user_email") == user_email)
    if not (uid_match or email_match):
        return False
    if not fingerprints:
        return uid_match or email_match
    blob = json.dumps(record.get("messages") or [], ensure_ascii=False)
    return any(fp in blob for fp in fingerprints)


def _read_history_for_session(
    session: dict[str, Any],
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    path = _logs_dir() / "history.log"
    if not path.exists():
        return []

    user_id = str(session.get("user_id") or "")
    user_email = str(session.get("user_email") or "")
    fingerprints = _user_message_fingerprints(session)
    start, end = _session_bounds(session)
    matches: list[dict[str, Any]] = []

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if not _history_record_matches(
            record,
            user_id=user_id,
            user_email=user_email,
            fingerprints=fingerprints,
        ):
            continue
        rec_ts = _parse_iso(record.get("ts"))
        if start and end and rec_ts and (rec_ts < start - timedelta(minutes=15) or rec_ts > end + timedelta(minutes=15)):
            continue
        matches.append(
            {
                "ts": record.get("ts"),
                "user_id": record.get("user_id"),
                "user_email": record.get("user_email"),
                "model": record.get("model"),
                "endpoint": record.get("endpoint"),
                "messages": record.get("messages"),
                "assistant_response": record.get("assistant_response"),
                "suggested_followups": record.get("suggested_followups"),
                "guidance": record.get("guidance"),
            }
        )
        if len(matches) >= limit:
            break
    return list(reversed(matches))


def _log_line_ts(line: str) -> datetime | None:
    m = _LOG_TS_RE.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_error_line(line: str) -> bool:
    upper = line.upper()
    return any(marker.upper() in upper for marker in _ERROR_MARKERS)


def _read_advisor_log_excerpt(
    session: dict[str, Any],
    *,
    max_lines: int = 150,
    errors_only: bool = False,
    padding_minutes: int = 3,
) -> dict[str, Any]:
    start, end = _session_bounds(session)
    logs_dir = _logs_dir()
    files = [logs_dir / "advisor.log"]
    for i in range(1, 4):
        rotated = logs_dir / f"advisor.log.{i}"
        if rotated.exists():
            files.append(rotated)

    if start and end:
        window_start = start - timedelta(minutes=padding_minutes)
        window_end = end + timedelta(minutes=padding_minutes)
    else:
        window_start = None
        window_end = None

    collected: list[str] = []
    files_read: list[str] = []

    for path in files:
        if not path.exists():
            continue
        files_read.append(str(path))
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for line in lines:
            if errors_only and not _is_error_line(line):
                continue
            if window_start and window_end:
                ts = _log_line_ts(line)
                if ts and (ts < window_start or ts > window_end):
                    continue
            collected.append(line)

    if not collected and window_start and window_end:
        for path in files:
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                if errors_only and not _is_error_line(line):
                    continue
                ts = _log_line_ts(line)
                if ts and window_start <= ts <= window_end:
                    collected.append(line)

    if len(collected) > max_lines:
        collected = collected[-max_lines:]

    return {
        "files": files_read,
        "window_utc": {
            "start": window_start.isoformat() if window_start else None,
            "end": window_end.isoformat() if window_end else None,
        },
        "errors_only": errors_only,
        "line_count": len(collected),
        "lines": collected,
    }


class FetchAdvisorLogsInput(BaseModel):
    session_id: str = Field(description="Quality-loop session id (sess_*)")
    history_limit: int = Field(
        default=25,
        description="Max matching JSON records from logs/history.log",
    )
    advisor_log_lines: int = Field(
        default=150,
        description="Max lines from logs/advisor.log in the session time window",
    )
    errors_only: bool = Field(
        default=False,
        description="If true, advisor.log excerpt filters ERROR/WARNING/traceback lines",
    )


class FetchAdvisorLogsTool(BaseTool):
    name: str = "fetch_advisor_logs"
    description: str = (
        "Load pivony-advisor server logs for root-cause analysis. "
        "Returns logs/history.log JSON audit lines correlated to the session "
        "and logs/advisor.log excerpts (errors, tracebacks, API failures) "
        "around the session timeframe. Always use after fetch_conversation — "
        "especially when advisor responses are generic errors or omit dashboard_picker."
    )
    args_schema: Type[BaseModel] = FetchAdvisorLogsInput

    def _run(
        self,
        session_id: str,
        history_limit: int = 25,
        advisor_log_lines: int = 150,
        errors_only: bool = False,
    ) -> str:
        session = load_session(session_id)
        if not session:
            return json.dumps(
                {
                    "error": f"session not found: {session_id}",
                    "hint": "fetch_conversation ile aynı session_id kullanın.",
                },
                ensure_ascii=False,
            )

        logs_dir = _logs_dir()
        history = _read_history_for_session(session, limit=max(1, min(history_limit, 50)))
        advisor_excerpt = _read_advisor_log_excerpt(
            session,
            max_lines=max(20, min(advisor_log_lines, 400)),
            errors_only=errors_only,
        )
        advisor_errors = _read_advisor_log_excerpt(
            session,
            max_lines=max(20, min(advisor_log_lines, 200)),
            errors_only=True,
        )

        start, end = _session_bounds(session)
        if not start:
            start = _parse_iso(session.get("created_at"))
        if not end:
            end = _parse_iso(session.get("updated_at"))
        return json.dumps(
            {
                "session_id": session_id,
                "logs_dir": str(logs_dir),
                "history_log_path": str(logs_dir / "history.log"),
                "advisor_log_path": str(logs_dir / "advisor.log"),
                "session_bounds_utc": {
                    "start": start.isoformat() if start else None,
                    "end": end.isoformat() if end else None,
                },
                "history_records": history,
                "history_record_count": len(history),
                "advisor_log_excerpt": advisor_excerpt,
                "advisor_error_excerpt": advisor_errors,
                "hint": (
                    "history.log = gerçek API request/response audit (aynı session zaman penceresi). "
                    "advisor.log = sunucu hataları, traceback, rate limit. "
                    "history_records başka session'dan olabilir — message_index için YALNIZCA "
                    "fetch_conversation.messages[] kullan; log satırlarını yalnızca evidence'da cite et."
                ),
            },
            ensure_ascii=False,
            default=str,
        )
