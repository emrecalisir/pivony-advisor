"""LangSmith OpenTelemetry tracing for CrewAI quality loop runs."""

from __future__ import annotations

import logging
import os

from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)
_configured = False


def langsmith_enabled() -> bool:
    if os.environ.get("QUALITY_LOOP_LANGSMITH_ENABLED", "").lower() in ("0", "false", "no"):
        return False
    if os.environ.get("LANGSMITH_TRACING", "").lower() in ("0", "false", "no"):
        return False
    return bool(os.environ.get("LANGSMITH_API_KEY", "").strip())


def langsmith_project() -> str:
    return (
        os.environ.get("LANGSMITH_PROJECT", "").strip()
        or os.environ.get("QUALITY_LOOP_LANGSMITH_PROJECT", "").strip()
        or "pivony-quality-loop"
    )


def langsmith_ui_url() -> str:
    custom = os.environ.get("LANGSMITH_PROJECT_URL", "").strip()
    if custom:
        return custom
    project = langsmith_project()
    return f"https://smith.langchain.com/?tab=2&peekProject={project}"


def configure_langsmith_tracing() -> bool:
    """Enable LangSmith OTEL tracing. Call before Crew/agents are created."""
    global _configured
    if _configured:
        return True
    if not langsmith_enabled():
        return False

    os.environ.setdefault("LANGSMITH_PROJECT", langsmith_project())
    os.environ.setdefault("LANGSMITH_TRACING", "true")

    # LiteLLM (CrewAI default LLM path) — secondary trace sink.
    os.environ.setdefault("LITELLM_SUCCESS_CALLBACKS", "langsmith")
    os.environ.setdefault("LITELLM_FAILURE_CALLBACKS", "langsmith")

    try:
        from langsmith.integrations.otel import OtelSpanProcessor
        from opentelemetry import trace
        from opentelemetry.instrumentation.crewai import CrewAIInstrumentor
        from opentelemetry.instrumentation.openai import OpenAIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError as exc:
        logger.warning("LangSmith tracing skipped (missing packages): %s", exc)
        return False

    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        tracer_provider = current
    else:
        tracer_provider = TracerProvider()
        trace.set_tracer_provider(tracer_provider)

    tracer_provider.add_span_processor(OtelSpanProcessor())
    CrewAIInstrumentor().instrument(tracer_provider=tracer_provider)
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

    _configured = True
    logger.info("LangSmith tracing enabled (project=%s)", langsmith_project())
    return True


@contextmanager
def run_trace_context(
    *,
    job_id: str | None = None,
    mode: str = "full",
    session_id: str | None = None,
) -> Iterator[None]:
    """Attach job/session metadata to LangSmith spans for the active crew run."""
    if not _configured:
        yield
        return

    try:
        from opentelemetry import trace
    except ImportError:
        yield
        return

    tracer = trace.get_tracer("quality_loop")
    with tracer.start_as_current_span("quality_loop_run") as span:
        if job_id:
            span.set_attribute("langsmith.metadata.job_id", job_id)
            span.set_attribute("langsmith.span.tags", f"quality-loop,{mode},{job_id}")
        if session_id:
            span.set_attribute("langsmith.metadata.session_id", session_id)
        span.set_attribute("langsmith.metadata.mode", mode)
        span.set_attribute("langsmith.metadata.project", langsmith_project())
        yield


def observability_status() -> dict:
    enabled = langsmith_enabled()
    configured = _configured
    if enabled and not configured:
        try:
            import langsmith.integrations.otel  # noqa: F401
            import opentelemetry.instrumentation.crewai  # noqa: F401

            configured = True
        except ImportError:
            # UI/advisor venv may lack OTEL packages; crew subprocess has them.
            configured = True
    return {
        "provider": "langsmith",
        "enabled": enabled,
        "configured": configured,
        "project": langsmith_project() if enabled else None,
        "ui_url": langsmith_ui_url() if enabled else None,
        "docs": "https://docs.langchain.com/langsmith/trace-with-crewai",
        "setup": {
            "LANGSMITH_API_KEY": "set" if os.environ.get("LANGSMITH_API_KEY") else "missing",
            "LANGSMITH_PROJECT": langsmith_project(),
            "QUALITY_LOOP_LANGSMITH_ENABLED": os.environ.get(
                "QUALITY_LOOP_LANGSMITH_ENABLED", "true (default when API key set)"
            ),
        },
    }
