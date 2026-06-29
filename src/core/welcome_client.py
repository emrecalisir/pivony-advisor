"""HTTP client for Pivony API Welcome worker endpoints (Advisor tools)."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from core.config import (
    WELCOME_WORKER_API_BASE_URL,
    WELCOME_WORKER_PREFIX,
    WELCOME_WORKER_SECRET,
)

logger = logging.getLogger(__name__)


def _worker_url(path: str) -> str:
    base = WELCOME_WORKER_API_BASE_URL.rstrip("/")
    prefix = WELCOME_WORKER_PREFIX if WELCOME_WORKER_PREFIX.startswith("/") else f"/{WELCOME_WORKER_PREFIX}"
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{prefix}{suffix}"


def post_worker(path: str, body: dict[str, Any], *, timeout: int = 90) -> dict[str, Any]:
    if not WELCOME_WORKER_API_BASE_URL or not WELCOME_WORKER_SECRET:
        return {
            "error": "worker_not_configured",
            "message": "WELCOME_WORKER_API_BASE_URL or WELCOME_WORKER_SECRET is missing",
        }
    url = _worker_url(path)
    headers = {
        "Content-Type": "application/json",
        "X-Welcome-Worker-Key": WELCOME_WORKER_SECRET,
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        logger.error("Welcome worker request failed path=%s: %s", path, exc)
        return {"error": "worker_unreachable", "message": str(exc)}
    try:
        data = resp.json()
    except ValueError:
        data = {"error": "invalid_json", "message": (resp.text or "")[:500]}
    if resp.status_code >= 400:
        if isinstance(data, dict) and not data.get("error"):
            data["error"] = f"http_{resp.status_code}"
        return data if isinstance(data, dict) else {"error": f"http_{resp.status_code}"}
    return data if isinstance(data, dict) else {"result": data}


def compact_json(data: Any, *, max_len: int = 12000) -> str:
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "…[truncated]"
