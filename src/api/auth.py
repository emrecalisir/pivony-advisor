"""Shared-secret check for callers of the Advisor HTTP API."""

from __future__ import annotations

import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

OPEN_PATHS = {"/", "/health"}
# These routers verify their own shared-secret header.
SELF_AUTH_PREFIXES = ("/v1/prospect/", "/v1/commerce-shopify/")
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


def install_api_token_check(app: FastAPI, token: str) -> None:
    if not token:
        return
    expected = f"Bearer {token}".encode()

    @app.middleware("http")
    async def require_api_token(request: Request, call_next):
        path = request.url.path
        host = request.client.host if request.client else ""
        if path in OPEN_PATHS or path.startswith(SELF_AUTH_PREFIXES) or host in LOOPBACK_HOSTS:
            return await call_next(request)
        provided = request.headers.get("authorization", "").encode()
        if not hmac.compare_digest(provided, expected):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)
