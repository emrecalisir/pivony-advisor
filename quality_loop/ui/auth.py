"""Signed session cookie auth for the quality-loop UI."""

from __future__ import annotations

import base64
import hmac
import hashlib
import os
import time

from fastapi import Request, Response

COOKIE_NAME = "ql_auth"
_SESSION_DAYS = int(os.environ.get("QUALITY_LOOP_UI_SESSION_DAYS", "7") or "7")


def _secret() -> str:
    return os.environ.get("QUALITY_LOOP_UI_TOKEN", "").strip()


def auth_required() -> bool:
    return bool(_secret())


def cookie_path(request: Request) -> str:
    if "/quality-loop" in request.url.path:
        return "/quality-loop"
    return "/"


def create_session_token() -> str:
    secret = _secret()
    if not secret:
        return ""
    exp = int(time.time()) + _SESSION_DAYS * 86400
    payload = f"v1:{exp}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_session_token(token: str) -> bool:
    secret = _secret()
    if not secret or not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(":", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        _, exp_str = payload.split(":", 1)
        return int(exp_str) > time.time()
    except Exception:
        return False


def request_authenticated(request: Request) -> bool:
    if not auth_required():
        return True
    cookie = request.cookies.get(COOKIE_NAME, "")
    if verify_session_token(cookie):
        return True
    header = request.headers.get("x-quality-loop-token", "")
    if header and hmac.compare_digest(header, _secret()):
        return True
    query = request.query_params.get("token", "")
    if query and hmac.compare_digest(query, _secret()):
        return True
    return False


def set_session_cookie(response: Response, request: Request) -> None:
    token = create_session_token()
    if not token:
        return
    secure = os.environ.get("QUALITY_LOOP_UI_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=_SESSION_DAYS * 86400,
        path=cookie_path(request),
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(key=COOKIE_NAME, path=cookie_path(request))
