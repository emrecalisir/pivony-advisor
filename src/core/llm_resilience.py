"""Safe LLM streaming with retry on empty or malformed turns."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

logger = logging.getLogger(__name__)

MAX_STREAM_TURN_RETRIES = 1
PROCESSING_USER_MESSAGE = "Verileri işliyorum, lütfen bir an bekleyin…"


def collect_stream_turn(
    turn_factory: Callable[[], Iterator[dict[str, Any]]],
    *,
    max_retries: int = MAX_STREAM_TURN_RETRIES,
) -> tuple[list[dict[str, Any]], Any, list[Any]]:
    """
    Run a streaming model turn, collecting intermediate events.

    Retries when the model returns empty parts and no function calls.
    Returns (events, model_content, function_calls).
    """
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
