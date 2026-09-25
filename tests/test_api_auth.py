"""Tests for the Advisor API shared-secret middleware on a bare FastAPI app."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import install_api_token_check

TOKEN = "test-advisor-token"


def _app(token: str) -> FastAPI:
    app = FastAPI()
    install_api_token_check(app, token)

    @app.get("/v1/models")
    def models():
        return {"data": []}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/v1/prospect/chat")
    def prospect_chat():
        return {"ok": True}

    return app


def test_rejects_missing_and_wrong_token():
    client = TestClient(_app(TOKEN))
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_accepts_correct_token():
    client = TestClient(_app(TOKEN))
    r = client.get("/v1/models", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_health_and_self_authenticated_routes_are_not_gated():
    client = TestClient(_app(TOKEN))
    assert client.get("/health").status_code == 200
    assert client.post("/v1/prospect/chat").status_code == 200


def test_loopback_callers_are_not_gated():
    client = TestClient(_app(TOKEN), client=("127.0.0.1", 50000))
    assert client.get("/v1/models").status_code == 200


def test_no_token_configured_leaves_api_open():
    client = TestClient(_app(""))
    assert client.get("/v1/models").status_code == 200
