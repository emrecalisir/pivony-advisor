"""Tests for LLM resilience helpers."""

import importlib.util
import sys
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "llm_resilience.py"
    spec = importlib.util.spec_from_file_location("core.llm_resilience", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
is_rate_limit_error = _mod.is_rate_limit_error
LlmTurnFailed = _mod.LlmTurnFailed
RATE_LIMIT_USER_MESSAGE = _mod.RATE_LIMIT_USER_MESSAGE


class _FakeClientError(Exception):
    code = 429


def test_is_rate_limit_detects_429_client_error():
    assert is_rate_limit_error(_FakeClientError("RESOURCE_EXHAUSTED"))


def test_is_rate_limit_detects_message_text():
    assert is_rate_limit_error(
        RuntimeError(
            "429 RESOURCE_EXHAUSTED. Please try again later."
        )
    )


def test_llm_turn_failed_carries_user_message():
    err = LlmTurnFailed(RATE_LIMIT_USER_MESSAGE)
    assert err.user_message == RATE_LIMIT_USER_MESSAGE
