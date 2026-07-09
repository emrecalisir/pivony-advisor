"""Vertex AI rate-limit resilience for CrewAI / LiteLLM quality loop runs.

Layers:
1. Exponential backoff retries on 429 (same idea as src/core/llm_resilience.py).
2. Circuit breaker: after a 429, pause *new* Vertex calls for a cooldown window
   instead of hammering the API — job status is updated so the UI can notify users.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

MAX_RATE_LIMIT_RETRIES = int(os.environ.get("QUALITY_LOOP_VERTEX_MAX_RETRIES", "4"))
RATE_LIMIT_BACKOFF_SEC = tuple(
    float(x)
    for x in os.environ.get("QUALITY_LOOP_VERTEX_BACKOFF_SEC", "2,4,8,16").split(",")
    if x.strip()
) or (2.0, 4.0, 8.0, 16.0)
CIRCUIT_BASE_COOLDOWN_SEC = float(
    os.environ.get("QUALITY_LOOP_VERTEX_CIRCUIT_COOLDOWN_SEC", "45")
)
CIRCUIT_MAX_COOLDOWN_SEC = float(
    os.environ.get("QUALITY_LOOP_VERTEX_CIRCUIT_MAX_COOLDOWN_SEC", "180")
)
THROTTLE_NOTIFY_INTERVAL_SEC = float(
    os.environ.get("QUALITY_LOOP_VERTEX_NOTIFY_INTERVAL_SEC", "5")
)

RATE_LIMIT_RETRY_MESSAGE = (
    "Vertex AI yoğun — otomatik tekrar deneniyor ({attempt}/{max_attempts}, "
    "{wait_seconds:.0f} sn bekleniyor)"
)
RATE_LIMIT_THROTTLE_MESSAGE = (
    "Vertex AI yoğun — yeni istekler geçici olarak bekletiliyor "
    "({remaining_seconds:.0f} sn)"
)
RATE_LIMIT_EXHAUSTED_MESSAGE = (
    "Vertex AI yoğun — tüm denemeler tükendi. "
    "Lütfen birkaç dakika bekleyip run'ı tekrar başlatın."
)

StatusCallback = Callable[[dict[str, Any]], None]

_patched = False
_status_callback: StatusCallback | None = None
_breaker_lock = threading.Lock()


class _VertexCircuitBreaker:
    """Opens after 429; blocks new Vertex calls until cooldown expires."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open_until = 0.0
        self._consecutive_opens = 0

    def record_rate_limit(self) -> float:
        with self._lock:
            self._consecutive_opens += 1
            exponent = min(self._consecutive_opens - 1, 3)
            cooldown = min(
                CIRCUIT_BASE_COOLDOWN_SEC * (2**exponent),
                CIRCUIT_MAX_COOLDOWN_SEC,
            )
            self._open_until = max(self._open_until, time.monotonic() + cooldown)
            return cooldown

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_opens = 0
            self._open_until = 0.0

    def remaining_seconds(self) -> float:
        with self._lock:
            return max(0.0, self._open_until - time.monotonic())

    def wait_while_open(self, *, on_wait: Callable[[float], None]) -> None:
        while True:
            remaining = self.remaining_seconds()
            if remaining <= 0:
                return
            on_wait(remaining)
            time.sleep(min(remaining, THROTTLE_NOTIFY_INTERVAL_SEC))


_breaker = _VertexCircuitBreaker()


def is_rate_limit_error(exc: BaseException) -> bool:
    """True for Vertex/Gemini/LiteLLM 429 RESOURCE_EXHAUSTED."""
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code == 429:
        return True
    resp = getattr(exc, "response", None)
    if getattr(resp, "status_code", None) == 429:
        return True

    exc_name = type(exc).__name__.lower()
    if "ratelimit" in exc_name or exc_name == "ratelimiterror":
        return True

    text = str(exc).upper()
    return "429" in text and (
        "RESOURCE_EXHAUSTED" in text or "RATE" in text or "QUOTA" in text
    )


def is_vertex_model(model: str | None) -> bool:
    if not model:
        return False
    m = model.lower()
    return m.startswith("vertex_ai/") or m.startswith("vertex_ai.") or m.startswith("gemini/")


def user_message_for_rate_limit_exhausted() -> str:
    return RATE_LIMIT_EXHAUSTED_MESSAGE


def set_status_callback(callback: StatusCallback | None) -> None:
    global _status_callback
    _status_callback = callback


def _notify(patch: dict[str, Any]) -> None:
    cb = _status_callback
    if cb is None:
        return
    try:
        cb(patch)
    except Exception:
        logger.debug("vertex status callback failed", exc_info=True)


def _notify_throttle(remaining_seconds: float) -> None:
    _notify(
        {
            "vertex": {
                "state": "throttle",
                "remaining_seconds": round(remaining_seconds, 1),
                "message": RATE_LIMIT_THROTTLE_MESSAGE.format(
                    remaining_seconds=remaining_seconds
                ),
            },
            "message": RATE_LIMIT_THROTTLE_MESSAGE.format(
                remaining_seconds=remaining_seconds
            ),
        }
    )


def _notify_retry(attempt: int, max_attempts: int, wait_seconds: float) -> None:
    msg = RATE_LIMIT_RETRY_MESSAGE.format(
        attempt=attempt,
        max_attempts=max_attempts,
        wait_seconds=wait_seconds,
    )
    _notify(
        {
            "vertex": {
                "state": "retry",
                "attempt": attempt,
                "max_attempts": max_attempts,
                "wait_seconds": wait_seconds,
                "message": msg,
            },
            "message": msg,
        }
    )


def _notify_ok() -> None:
    _notify({"vertex": {"state": "ok"}, "message": None})


def _extract_model(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    model = kwargs.get("model")
    if model:
        return str(model)
    if args:
        return str(args[0])
    return None


def call_with_vertex_resilience(fn: Callable[[], Any], *, model: str | None) -> Any:
    """Run an LLM call with throttle + retry for Vertex models only."""
    if not is_vertex_model(model):
        return fn()

    _breaker.wait_while_open(on_wait=_notify_throttle)

    last_exc: BaseException | None = None
    max_attempts = MAX_RATE_LIMIT_RETRIES + 1

    for attempt in range(max_attempts):
        try:
            result = fn()
            _breaker.record_success()
            _notify_ok()
            return result
        except Exception as exc:
            if not is_rate_limit_error(exc):
                raise
            last_exc = exc
            cooldown = _breaker.record_rate_limit()
            logger.warning(
                "Vertex 429 on model=%s attempt=%s/%s; circuit cooldown=%.1fs",
                model,
                attempt + 1,
                max_attempts,
                cooldown,
                exc_info=True,
            )
            if attempt >= MAX_RATE_LIMIT_RETRIES:
                break
            wait = RATE_LIMIT_BACKOFF_SEC[min(attempt, len(RATE_LIMIT_BACKOFF_SEC) - 1)]
            wait += random.uniform(0, min(wait * 0.25, 2.0))
            _notify_retry(attempt + 1, max_attempts, wait)
            time.sleep(wait)

    assert last_exc is not None
    _notify(
        {
            "vertex": {
                "state": "exhausted",
                "message": RATE_LIMIT_EXHAUSTED_MESSAGE,
            },
            "message": RATE_LIMIT_EXHAUSTED_MESSAGE,
        }
    )
    raise last_exc


def _wrap_completion(original: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        model = _extract_model(args, kwargs)
        return call_with_vertex_resilience(
            lambda: original(*args, **kwargs),
            model=model,
        )

    return wrapper


def configure_vertex_resilience() -> bool:
    """Patch LiteLLM completion entry points once per process."""
    global _patched
    if _patched:
        return True

    try:
        import litellm
    except ImportError:
        logger.warning("vertex resilience skipped: litellm not installed")
        return False

    if not getattr(litellm, "_quality_loop_vertex_patched", False):
        litellm.completion = _wrap_completion(litellm.completion)
        if hasattr(litellm, "acompletion"):
            litellm.acompletion = _wrap_completion(litellm.acompletion)
        litellm._quality_loop_vertex_patched = True

    _patched = True
    logger.info(
        "Vertex resilience enabled (retries=%s, circuit_cooldown=%.0fs)",
        MAX_RATE_LIMIT_RETRIES,
        CIRCUIT_BASE_COOLDOWN_SEC,
    )
    return True


def resilience_status() -> dict[str, Any]:
    remaining = _breaker.remaining_seconds()
    return {
        "enabled": _patched,
        "max_retries": MAX_RATE_LIMIT_RETRIES,
        "circuit_cooldown_sec": CIRCUIT_BASE_COOLDOWN_SEC,
        "circuit_open": remaining > 0,
        "circuit_remaining_sec": round(remaining, 1) if remaining > 0 else 0,
    }
