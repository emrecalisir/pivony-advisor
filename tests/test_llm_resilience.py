"""Tests for LLM resilience helpers."""

import importlib.util
import sys
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "llm_resilience.py"
    spec = importlib.util.spec_from_file_location("core.llm_resilience", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core.llm_resilience"] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
is_rate_limit_error = _mod.is_rate_limit_error
LlmTurnFailed = _mod.LlmTurnFailed
RATE_LIMIT_USER_MESSAGE = _mod.RATE_LIMIT_USER_MESSAGE
RATE_LIMIT_RETRY_USER_MESSAGE = _mod.RATE_LIMIT_RETRY_USER_MESSAGE
collect_stream_turn = _mod.collect_stream_turn
make_rate_limit_retry_status = _mod.make_rate_limit_retry_status
is_terminal_llm_user_message = _mod.is_terminal_llm_user_message


class _FakeClientError(Exception):
    code = 429


class _Fake400ClientError(Exception):
    code = 400


def test_is_rate_limit_detects_429_client_error():
    assert is_rate_limit_error(_FakeClientError("RESOURCE_EXHAUSTED"))


def test_is_rate_limit_rejects_400_client_error():
    assert not is_rate_limit_error(
        _Fake400ClientError(
            "400 INVALID_ARGUMENT. function response parts mismatch"
        )
    )


def test_is_rate_limit_detects_message_text():
    assert is_rate_limit_error(
        RuntimeError(
            "429 RESOURCE_EXHAUSTED. Please try again later."
        )
    )


def test_llm_turn_failed_carries_user_message():
    err = LlmTurnFailed(RATE_LIMIT_USER_MESSAGE)
    assert err.user_message == RATE_LIMIT_USER_MESSAGE


def test_make_rate_limit_retry_status():
    event = make_rate_limit_retry_status(2, 4)
    assert event == {
        "type": "status",
        "phase": "retry",
        "detail": "rate_limit",
        "message": RATE_LIMIT_RETRY_USER_MESSAGE,
        "attempt": 2,
        "max_attempts": 4,
    }


def test_is_terminal_llm_user_message():
    assert is_terminal_llm_user_message(RATE_LIMIT_USER_MESSAGE)
    assert is_terminal_llm_user_message(_mod.GENERIC_LLM_ERROR_MESSAGE)
    assert is_terminal_llm_user_message(_mod.PROCESSING_USER_MESSAGE)
    assert not is_terminal_llm_user_message("Normal answer")


def test_is_incomplete_advisor_reply():
    incomplete = _mod.is_incomplete_advisor_reply
    assert incomplete("")
    assert incomplete("   ")
    assert incomplete(_mod.PROCESSING_USER_MESSAGE)
    assert incomplete(_mod.GENERIC_LLM_ERROR_MESSAGE)
    assert not incomplete("Prima dashboard için NPS trendi şöyle.")


def test_collect_stream_turn_invokes_retry_callback_then_succeeds():
    from types import SimpleNamespace

    attempts = {"n": 0}
    retry_calls = []

    def turn_factory():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        def gen():
            yield {"type": "thought", "delta": "ok"}
            model_content = SimpleNamespace(parts=[SimpleNamespace(text="done")])
            return model_content, []

        return gen()

    original_sleep = _mod.time.sleep
    _mod.time.sleep = lambda _s: None
    try:
        events, _content, _calls = collect_stream_turn(
            turn_factory,
            on_rate_limit_retry=lambda a, m, w: retry_calls.append((a, m, w)),
        )
    finally:
        _mod.time.sleep = original_sleep

    assert retry_calls == [(1, 4, 2.0)]
    assert events == [{"type": "thought", "delta": "ok"}]


def test_collect_stream_turn_retries_function_call_mismatch():
    attempts = {"n": 0}
    original_sleep = _mod.time.sleep
    _mod.time.sleep = lambda _s: None
    try:

        def turn_factory():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError(
                    "400 INVALID_ARGUMENT. Please ensure that the number of function "
                    "response parts is equal to the number of function call parts of "
                    "the function call turn."
                )

            def gen():
                from types import SimpleNamespace

                yield {"type": "thought", "delta": "ok"}
                model_content = SimpleNamespace(parts=[SimpleNamespace(text="done")])
                return model_content, []

            return gen()

        events, _content, _calls = collect_stream_turn(turn_factory)
        assert attempts["n"] == 2
        assert events == [{"type": "thought", "delta": "ok"}]
    finally:
        _mod.time.sleep = original_sleep


def test_collect_stream_turn_raises_after_retry_exhaustion():
    def turn_factory():
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    original_sleep = _mod.time.sleep
    _mod.time.sleep = lambda _s: None
    try:
        try:
            collect_stream_turn(turn_factory)
            assert False, "expected LlmTurnFailed"
        except LlmTurnFailed as exc:
            assert exc.user_message == RATE_LIMIT_USER_MESSAGE
    finally:
        _mod.time.sleep = original_sleep


def test_user_message_for_function_call_mismatch():
    exc = RuntimeError(
        "400 INVALID_ARGUMENT. Please ensure that the number of function "
        "response parts is equal to the number of function call parts of "
        "the function call turn."
    )
    assert _mod.user_message_for_llm_error(exc) == _mod.FUNCTION_CALL_MISMATCH_USER_MESSAGE


def test_user_message_for_invalid_argument():
    exc = _Fake400ClientError("400 INVALID_ARGUMENT. bad request")
    assert _mod.user_message_for_llm_error(exc) == _mod.INVALID_ARGUMENT_USER_MESSAGE
