"""Tests for the Sonic Prospect Commerce (Shopify) route: auth and wiring.

The router is mounted on a bare FastAPI app so these tests do not pull in the
advisor agent stack, and the generation call is stubbed so nothing reaches
Vertex AI.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import commerce_shopify_routes as routes

SECRET = "test-commerce-secret"

PAYLOAD = {
    "shop_domain": "demo.myshopify.com",
    "session_id": "sp_1",
    "language": "en",
    "system_prompt": "You are the shop assistant.",
    "context_blocks": [
        {"kind": "product", "title": "Liquid", "text": "749.95 USD, in stock."}
    ],
    "message": "how much is the liquid snowboard?",
    "history": [],
}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_answer_returns_generation_and_forwards_context(monkeypatch):
    seen: dict = {}

    def fake_answer(**kwargs):
        seen.update(kwargs)
        return {
            "answer": "It is 749.95 USD.",
            "model": "gemini-2.5-flash",
            "usage": {"input_tokens": 5, "output_tokens": 6},
            "finish_reason": "stop",
            "shop_domain": kwargs["shop_domain"],
            "blocks_used": len(kwargs["context_blocks"]),
        }

    monkeypatch.setattr(routes, "COMMERCE_SECRET", SECRET)
    monkeypatch.setattr(routes, "answer_commerce_question", fake_answer)

    response = _client().post(
        "/v1/commerce-shopify/answer",
        json=PAYLOAD,
        headers={"X-Commerce-Key": SECRET},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "It is 749.95 USD."
    assert body["blocks_used"] == 1
    assert seen["context_blocks"][0]["title"] == "Liquid"
    assert seen["system_prompt"] == "You are the shop assistant."


def test_answer_rejects_wrong_and_missing_key(monkeypatch):
    monkeypatch.setattr(routes, "COMMERCE_SECRET", SECRET)
    monkeypatch.setattr(
        routes, "answer_commerce_question", lambda **_: {"answer": "should not run"}
    )
    client = _client()

    assert (
        client.post(
            "/v1/commerce-shopify/answer",
            json=PAYLOAD,
            headers={"X-Commerce-Key": "wrong"},
        ).status_code
        == 401
    )
    assert client.post("/v1/commerce-shopify/answer", json=PAYLOAD).status_code == 401


def test_answer_unavailable_without_configured_secret(monkeypatch):
    monkeypatch.setattr(routes, "COMMERCE_SECRET", "")
    response = _client().post(
        "/v1/commerce-shopify/answer",
        json=PAYLOAD,
        headers={"X-Commerce-Key": SECRET},
    )
    assert response.status_code == 503


def test_answer_requires_message(monkeypatch):
    monkeypatch.setattr(routes, "COMMERCE_SECRET", SECRET)
    payload = {**PAYLOAD, "message": ""}
    response = _client().post(
        "/v1/commerce-shopify/answer",
        json=payload,
        headers={"X-Commerce-Key": SECRET},
    )
    assert response.status_code == 422


def test_model_failure_surfaces_as_500(monkeypatch):
    def boom(**_):
        raise RuntimeError("vertex unavailable")

    monkeypatch.setattr(routes, "COMMERCE_SECRET", SECRET)
    monkeypatch.setattr(routes, "answer_commerce_question", boom)

    response = _client().post(
        "/v1/commerce-shopify/answer",
        json=PAYLOAD,
        headers={"X-Commerce-Key": SECRET},
    )
    assert response.status_code == 500
