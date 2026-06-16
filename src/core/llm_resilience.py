"""Safe LLM streaming with retry on empty turns and Vertex rate limits."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

logger = logging.getLogger(__name__)

MAX_STREAM_TURN_RETRIES = 1
MAX_RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_SEC = (2.0, 4.0, 8.0)

PROCESSING_USER_MESSAGE = "Verileri işliyorum, lütfen bir an bekleyin…"
RATE_LIMIT_USER_MESSAGE = (
    "Şu anda yapay zeka servisi yoğun (istek limiti aşıldı). "
    "Lütfen birkaç saniye bekleyip tekrar deneyin."
)
GENERIC_LLM_ERROR_MESSAGE = (
    "Yanıt oluşturulurken bir hata oluştu. Lütfen tekrar deneyin."
)


class LlmTurnFailed(Exception):
    """LLM turn failed after retries; carries a user-safe message."""

    def __init__(self, user_message: str) -> None:
        self.user_message = user_message
        super().__init__(user_message)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True for Vertex/Gemini 429 RESOURCE_EXHAUSTED."""
    code = getattr(exc, "code", None)
    if code == 429:
        return True
    resp = getattr(exc, "response", None)
    if getattr(resp, "status_code", None) == 429:
        return True

    try:
        from google.genai.errors import ClientError
    except ImportError:
        ClientError = ()  # type: ignore[misc, assignment]

    if isinstance(exc, ClientError):
        return True

    text = str(exc)
    return "429" in text and "RESOURCE_EXHAUSTED" in text


def user_message_for_llm_error(exc: BaseException) -> str:
    if is_rate_limit_error(exc):
        return RATE_LIMIT_USER_MESSAGE
    return GENERIC_LLM_ERROR_MESSAGE


def _collect_stream_turn_once(
    turn_factory: Callable[[], Iterator[dict[str, Any]]],
    *,
    max_retries: int,
) -> tuple[list[dict[str, Any]], Any, list[Any]]:
    model_content = None
    function_calls: list[Any] = []
    for attempt in range(max_retries + 1):
        turn_gen = turn_factory()
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(next(turn_gen))
            except StopIteration as stop:
                model_content, function_calls = stop.value
                break
        has_parts = bool(getattr(model_content, "parts", None))
        has_calls = bool(function_calls)
        if has_parts or has_calls:
            return events, model_content, function_calls
        if attempt < max_retries:
            logger.warning(
                "Empty LLM stream turn (attempt %s/%s), retrying…",
                attempt + 1,
                max_retries + 1,
            )
    logger.error("LLM stream turn empty after %s attempt(s)", max_retries + 1)
    return events, model_content, function_calls


def collect_stream_turn(
    turn_factory: Callable[[], Iterator[dict[str, Any]]],
    *,
    max_retries: int = MAX_STREAM_TURN_RETRIES,
) -> tuple[list[dict[str, Any]], Any, list[Any]]:
    """
    Run a streaming model turn, collecting intermediate events.

    Retries empty turns and 429 rate-limit errors with backoff.
    Raises LlmTurnFailed with a user-safe message when the turn cannot complete.
    """
    last_exc: BaseException | None = None
    for rate_attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return _collect_stream_turn_once(turn_factory, max_retries=max_retries)
        except Exception as exc:
            if is_rate_limit_error(exc) and rate_attempt < MAX_RATE_LIMIT_RETRIES:
                wait = RATE_LIMIT_BACKOFF_SEC[
                    min(rate_attempt, len(RATE_LIMIT_BACKOFF_SEC) - 1)
                ]
                logger.warning(
                    "LLM 429 rate limit (attempt %s/%s), retrying in %.1fs",
                    rate_attempt + 1,
                    MAX_RATE_LIMIT_RETRIES + 1,
                    wait,
                    exc_info=True,
                )
                time.sleep(wait)
                last_exc = exc
                continue
            logger.error("LLM stream turn failed: %s", exc, exc_info=True)
            raise LlmTurnFailed(user_message_for_llm_error(exc)) from exc

    raise LlmTurnFailed(RATE_LIMIT_USER_MESSAGE) from last_exc
