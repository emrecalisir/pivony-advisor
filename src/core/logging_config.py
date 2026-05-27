"""Dual-file logging: history.log (conversations) and advisor.log (everything else)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from core.config import ADVISOR_LOG_PATH, HISTORY_LOG_PATH, LOGS_DIR

_HISTORY_LOGGER_NAME = "pivony.advisor.history"
_ADVISOR_LOGGER_NAMES = (
    "pivony.advisor",
    "pivony.advisor.api",
    "pivony.advisor.rag",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "fastapi",
)

_configured = False


def setup_logging() -> None:
    """Configure advisor.log and history.log under project logs/."""
    global _configured
    if _configured:
        return

    os.makedirs(LOGS_DIR, exist_ok=True)

    advisor_formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    advisor_handler = RotatingFileHandler(
        ADVISOR_LOG_PATH,
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    advisor_handler.setFormatter(advisor_formatter)

    for name in _ADVISOR_LOGGER_NAMES:
        log = logging.getLogger(name)
        log.handlers.clear()
        log.addHandler(advisor_handler)
        log.setLevel(logging.INFO)
        log.propagate = False

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(advisor_handler)
    root.setLevel(logging.INFO)

    history_handler = RotatingFileHandler(
        HISTORY_LOG_PATH,
        maxBytes=50 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    history_handler.setFormatter(logging.Formatter("%(message)s"))

    history_log = logging.getLogger(_HISTORY_LOGGER_NAME)
    history_log.handlers.clear()
    history_log.addHandler(history_handler)
    history_log.setLevel(logging.INFO)
    history_log.propagate = False

    _configured = True
    get_advisor_logger(__name__).info("Logging initialized (advisor=%s history=%s)", ADVISOR_LOG_PATH, HISTORY_LOG_PATH)


def get_advisor_logger(name: str) -> logging.Logger:
    if name.startswith("pivony.advisor"):
        return logging.getLogger(name)
    return logging.getLogger(f"pivony.advisor.{name}")


def log_conversation(
    *,
    user_id: str | None,
    user_email: str | None,
    sector: str,
    model: str,
    messages: list[dict[str, str]],
    assistant_response: str,
    suggested_followups: list[str] | None = None,
    endpoint: str = "/v1/chat/completions",
) -> None:
    """Append one JSON line to logs/history.log."""
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "user_id": user_id or "",
        "user_email": user_email or "",
        "sector": sector,
        "model": model,
        "messages": messages,
        "assistant_response": assistant_response,
        "suggested_followups": suggested_followups or [],
    }
    logging.getLogger(_HISTORY_LOGGER_NAME).info(
        json.dumps(record, ensure_ascii=False)
    )
