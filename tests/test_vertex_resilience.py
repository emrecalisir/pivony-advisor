"""Tests for quality loop Vertex resilience."""

from __future__ import annotations

import pytest

from quality_loop import vertex_resilience as vr


class _RateLimitError(Exception):
    status_code = 429


def test_is_rate_limit_detects_429():
    assert vr.is_rate_limit_error(_RateLimitError("RESOURCE_EXHAUSTED"))
    assert vr.is_rate_limit_error(RuntimeError("429 RESOURCE_EXHAUSTED"))


def test_is_vertex_model():
    assert vr.is_vertex_model("vertex_ai/gemini-2.5-flash")
    assert vr.is_vertex_model("gemini/gemini-2.0-flash")
    assert not vr.is_vertex_model("anthropic/claude-sonnet-4-20250514")


def test_call_with_vertex_resilience_retries_then_succeeds(monkeypatch):
    attempts = {"n": 0}
    notices: list[dict] = []

    def fn():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return "ok"

    monkeypatch.setattr(vr, "MAX_RATE_LIMIT_RETRIES", 2)
    monkeypatch.setattr(vr, "RATE_LIMIT_BACKOFF_SEC", (0.0,))
    monkeypatch.setattr(vr.time, "sleep", lambda _s: None)
    vr.set_status_callback(lambda patch: notices.append(patch))

    result = vr.call_with_vertex_resilience(fn, model="vertex_ai/gemini-2.5-flash")
    assert result == "ok"
    assert attempts["n"] == 2
    assert any(n.get("vertex", {}).get("state") == "retry" for n in notices)


def test_circuit_breaker_blocks_new_vertex_calls(monkeypatch):
    vr._breaker.record_success()
    notices: list[float] = []
    vr._breaker._open_until = 100.0

    monkeypatch.setattr(vr, "THROTTLE_NOTIFY_INTERVAL_SEC", 0.01)
    sleeps: list[float] = []
    monkeypatch.setattr(vr.time, "sleep", lambda s: sleeps.append(s))

    clock = {"t": 0.0}

    def monotonic():
        clock["t"] += 10.0
        return clock["t"]

    monkeypatch.setattr(vr.time, "monotonic", monotonic)

    vr._breaker.wait_while_open(on_wait=lambda r: notices.append(r))
    assert sleeps
    assert any(r > 0 for r in notices)


def test_non_vertex_models_bypass_resilience(monkeypatch):
    monkeypatch.setattr(
        vr._breaker,
        "wait_while_open",
        lambda **_: pytest.fail("should not throttle non-vertex"),
    )
    assert vr.call_with_vertex_resilience(lambda: 42, model="anthropic/claude") == 42
