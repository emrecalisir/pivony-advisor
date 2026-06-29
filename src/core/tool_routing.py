"""Deterministic tool routing guardrails for the advisor agent."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from core.agent_state import HardAgentState
from core.pivot_resolve import (
    apply_pivot_to_tool_args,
    looks_like_pivot_scoped_search,
    semantic_search_pivot_redirect,
)

logger = logging.getLogger(__name__)

LIST_DASHBOARDS = "list_dashboards"
METRICS = "get_pivony_metrics"
_DASHBOARD_LISTING_TOOLS = frozenset({LIST_DASHBOARDS})
_DASHBOARD_ARG_TOOLS = frozenset(
    {
        METRICS,
        "get_dashboard_pivots",
        "get_trends",
        "compare_pivot_ratings",
        "get_topic_trends",
        "get_hotterms",
        "get_decision_distribution",
        "get_distribution",
        "get_topic_intent_distribution",
        "get_topic_sentiment",
        "get_topic_participation",
        "get_topic_sentiment_daily",
        "get_topic_participation_daily",
        "get_topic_trends_view",
        "get_review_statistics",
        "get_topic_ratings",
        "get_emergent_topics",
        "get_key_drivers",
        "get_digital_experience_score",
        "get_stored_genai_insights",
        "get_root_causes",
        "list_reviews",
    }
)


def should_expose_list_dashboards(state: HardAgentState) -> bool:
    """Hide list_dashboards when scope already pins a dashboard or org-wide mode."""
    if state.dashboard_locked or state.has_dashboard:
        return False
    if state.org_wide:
        return False
    return True


def filter_tools_for_state(
    tools: list[StructuredTool],
    state: HardAgentState,
) -> list[StructuredTool]:
    if should_expose_list_dashboards(state):
        return tools
    filtered = [t for t in tools if t.name not in _DASHBOARD_LISTING_TOOLS]
    logger.info(
        "Tool routing: list_dashboards hidden (dashboard_id=%s locked=%s org_wide=%s source=%s)",
        state.dashboard_id,
        state.dashboard_locked,
        state.org_wide,
        state.source,
    )
    return filtered


def sanitize_tool_calls(
    calls: list[dict[str, Any]],
    state: HardAgentState,
) -> list[dict[str, Any]]:
    """
    Drop conflicting tool calls before execution.

    When dashboard scope is resolved, strip list_dashboards. If the model requested
    list_dashboards together with analysis tools, keep analysis calls only.
    """
    if not calls:
        return calls
    if should_expose_list_dashboards(state):
        return calls

    names = [c.get("name") for c in calls if c.get("name")]
    has_list = LIST_DASHBOARDS in names
    if not has_list:
        return calls

    kept = [c for c in calls if c.get("name") not in _DASHBOARD_LISTING_TOOLS]
    if kept:
        logger.info(
            "Tool routing: suppressed list_dashboards (%s call(s) total, kept %s)",
            len(calls),
            len(kept),
        )
        return kept

    logger.info("Tool routing: suppressed sole list_dashboards call (scope resolved)")
    return []


def sanitize_function_calls(
    function_calls: list[Any],
    state: HardAgentState,
) -> list[Any]:
    """Streaming path: filter GenAI FunctionCall objects."""
    if should_expose_list_dashboards(state) or not function_calls:
        return function_calls
    names = [getattr(fc, "name", None) for fc in function_calls]
    if LIST_DASHBOARDS not in names:
        return function_calls
    kept = [fc for fc in function_calls if getattr(fc, "name", None) not in _DASHBOARD_LISTING_TOOLS]
    if kept:
        logger.info(
            "Tool routing (stream): suppressed list_dashboards (%s → %s calls)",
            len(function_calls),
            len(kept),
        )
        return kept
    return []


def pin_tool_args_for_state(
    tool_name: str,
    args: dict[str, Any],
    state: HardAgentState,
) -> dict[str, Any]:
    """
    Authoritative dashboard scope: inject the user-selected id, or strip any
    dashboard_id the model guessed from list_dashboards output.
    """
    if tool_name not in _DASHBOARD_ARG_TOOLS:
        return dict(args or {})
    out = dict(args or {})
    if state.has_dashboard and state.dashboard_id is not None:
        out["dashboard_id"] = state.dashboard_id
    else:
        out.pop("dashboard_id", None)
        if tool_name == METRICS and not state.org_wide:
            out.pop("org_wide", None)
    return out


def validated_tool_invoke(
    tool: StructuredTool,
    raw_args: dict[str, Any],
    state: HardAgentState | None = None,
    user_id: str | None = None,
) -> str:
    """Validate tool args with Pydantic before invoke; return JSON error on bad schema."""
    args = dict(raw_args or {})
    if state is not None:
        args = pin_tool_args_for_state(tool.name, args, state)
    if tool.name == "search_qdrant_reviews":
        query = args.get("query") or ""
        if looks_like_pivot_scoped_search(str(query)):
            return semantic_search_pivot_redirect()
    if user_id and state is not None and state.has_dashboard:
        args = apply_pivot_to_tool_args(
            tool.name,
            args,
            user_id=user_id,
            dashboard_id=state.dashboard_id,
        )
        args.pop("_pivot_resolution", None)
    schema = getattr(tool, "args_schema", None)
    if schema is not None:
        try:
            parsed = schema.model_validate(args)
            args = parsed.model_dump(exclude_none=True)
        except ValidationError as exc:
            logger.warning("Tool %s arg validation failed: %s", tool.name, exc)
            return json.dumps(
                {
                    "error": "invalid_tool_arguments",
                    "tool": tool.name,
                    "detail": exc.errors(),
                    "instruction": "Fix arguments and retry the tool once.",
                },
                ensure_ascii=False,
            )
    return tool.invoke(args)


def blocked_tool_result(tool_name: str, state: HardAgentState) -> str | None:
    """Return a synthetic tool result when a call is blocked by routing rules."""
    if tool_name not in _DASHBOARD_LISTING_TOOLS:
        return None
    if should_expose_list_dashboards(state):
        return None
    return json.dumps(
        {
            "skipped": True,
            "tool": tool_name,
            "dashboard_id": state.dashboard_id,
            "instruction": (
                f"Dashboard scope is already locked to id={state.dashboard_id}. "
                "Do not call list_dashboards. Use get_pivony_metrics and other analysis tools."
            ),
        },
        ensure_ascii=False,
    )
