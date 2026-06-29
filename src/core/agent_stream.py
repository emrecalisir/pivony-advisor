"""
Tool-calling Advisor agent with SSE streaming.

Advisor Basic: precomputed metrics / stored root causes only.
Advisor Pro: adds live review search and on-the-fly root-cause vendor breakdown.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from core.advisor_plan import allowed_tools, is_pro_mode, tier_label
from core.config import ADVISOR_AGENT_MAX_TOOL_ROUNDS
from core.contextual_navigation import generate_contextual_navigation
from core.rag import build_llm
from core.welcome_client import compact_json, post_worker

logger = logging.getLogger(__name__)

AGENT_SYSTEM = """You are Pivony Advisor ({tier}).

Use tools to answer questions about the user's Voice of Customer data.
Respond in the same language as the user. Be concise and actionable.

{pivot_hint}
"""


class EmptyArgs(BaseModel):
    pass


class DashboardIdArgs(BaseModel):
    dashboard_id: int = Field(description="Dashboard id")
    days: int | None = Field(default=1, description="Lookback days when since/until omitted")


class RootCausesArgs(BaseModel):
    dashboard_id: int
    topic: str | None = None
    limit: int | None = 5


class ReviewsArgs(BaseModel):
    dashboard_id: int
    topic_id: int | None = None
    pivot_key: str | None = None
    pivot_value: str | None = None
    days: int | None = 90
    limit: int | None = None


class SearchReviewsArgs(BaseModel):
    dashboard_id: int
    query: str
    days: int | None = 90


class AnalyzeRootCauseArgs(BaseModel):
    dashboard_id: int
    root_cause_text: str
    days: int | None = 90


class PlanUpgradeArgs(BaseModel):
    message: str | None = None


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _build_tools(
    *,
    user_id: str,
    advisor_mode: str | None,
    page_context: dict[str, Any] | None,
) -> list[StructuredTool]:
    pc = page_context if isinstance(page_context, dict) else {}
    base = {"user_id": user_id, "advisor_mode": advisor_mode or "advisor"}
    if pc.get("since"):
        base["since"] = pc["since"]
    if pc.get("until"):
        base["until"] = pc["until"]
    if pc.get("days") is not None:
        base["days"] = pc["days"]
    default_dash = pc.get("dashboard_id")

    def _merge(extra: dict[str, Any]) -> dict[str, Any]:
        body = {**base}
        if default_dash is not None and "dashboard_id" not in extra:
            body["dashboard_id"] = default_dash
        body.update(extra)
        return body

    tools: list[StructuredTool] = []

    def _add(name: str, description: str, fn, args_schema):
        if name not in allowed_tools(advisor_mode):
            return
        tools.append(
            StructuredTool.from_function(
                func=fn,
                name=name,
                description=description,
                args_schema=args_schema,
            )
        )

    def list_dashboards() -> str:
        return compact_json(post_worker("/worker/advisor/dashboards", _merge({})))

    def get_pivony_metrics(dashboard_id: int, days: int | None = 1) -> str:
        return compact_json(
            post_worker(
                "/worker/advisor-metrics",
                _merge({"dashboard_id": dashboard_id, "days": days or 1}),
            )
        )

    def get_root_causes(dashboard_id: int, topic: str | None = None, limit: int | None = 5) -> str:
        body = _merge({"dashboard_id": dashboard_id, "limit": limit or 5})
        if topic:
            body["topic"] = topic
        return compact_json(post_worker("/worker/advisor/root-causes", body))

    def list_reviews(
        dashboard_id: int,
        topic_id: int | None = None,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = 90,
        limit: int | None = None,
    ) -> str:
        body = _merge({"dashboard_id": dashboard_id, "days": days or 90})
        if topic_id is not None:
            body["topic_id"] = topic_id
        if pivot_key and pivot_value:
            body["pivot_key"] = pivot_key
            body["pivot_value"] = pivot_value
        if limit is not None:
            body["limit"] = limit
        return compact_json(post_worker("/worker/advisor/reviews", body))

    def search_reviews(dashboard_id: int, query: str, days: int | None = 90) -> str:
        return compact_json(
            post_worker(
                "/worker/advisor/search-reviews",
                _merge({"dashboard_id": dashboard_id, "query": query, "days": days or 90}),
            )
        )

    def analyze_root_cause_live(
        dashboard_id: int, root_cause_text: str, days: int | None = 90
    ) -> str:
        return compact_json(
            post_worker(
                "/worker/advisor/analyze-root-cause-live",
                _merge(
                    {
                        "dashboard_id": dashboard_id,
                        "root_cause_text": root_cause_text,
                        "days": days or 90,
                    }
                ),
            )
        )

    def request_plan_upgrade(message: str | None = None) -> str:
        body = _merge({})
        if message:
            body["message"] = message
        return compact_json(post_worker("/worker/advisor/plan-request", body))

    _add(
        "list_dashboards",
        "List dashboards the user can access. Use when dashboard context is missing.",
        list_dashboards,
        EmptyArgs,
    )
    _add(
        "get_pivony_metrics",
        "Headline KPIs, sentiment, complaint topics, and precomputed top root causes for a dashboard.",
        get_pivony_metrics,
        DashboardIdArgs,
    )
    _add(
        "get_root_causes",
        "Stored (precomputed) root causes from GenAI/MCP pipeline with scope, pivot, and date_period.",
        get_root_causes,
        RootCausesArgs,
    )
    _add(
        "list_reviews",
        "Fetch a small sample of example review texts (Basic: max 10, Pro: max 50).",
        list_reviews,
        ReviewsArgs,
    )
    _add(
        "search_reviews",
        "Advisor Pro: keyword search across reviews with vendor distribution.",
        search_reviews,
        SearchReviewsArgs,
    )
    _add(
        "analyze_root_cause_live",
        "Advisor Pro: live vendor/hotel breakdown for a root-cause phrase by searching matching reviews.",
        analyze_root_cause_live,
        AnalyzeRootCauseArgs,
    )
    _add(
        "request_plan_upgrade",
        "Email Pivony team to upgrade the org to Advisor Pro.",
        request_plan_upgrade,
        PlanUpgradeArgs,
    )
    return tools


def _messages_from_openai(raw_messages: list[dict[str, Any]]) -> list:
    out = []
    for msg in raw_messages:
        role = (msg.get("role") or "").strip()
        content = msg.get("content") or ""
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant" and content:
            out.append(AIMessage(content=content))
    return out


def stream_agent_chat(
    *,
    messages: list[dict[str, Any]],
    advisor_mode: str | None,
    user_id: str | None,
    page_context: dict[str, Any] | None,
    api_system: str | None,
) -> Iterator[str]:
    uid = (user_id or "").strip()
    if not uid:
        yield _sse({"type": "error", "message": "Missing pivony_user_id"})
        yield "data: [DONE]\n\n"
        return

    tools = _build_tools(user_id=uid, advisor_mode=advisor_mode, page_context=page_context)
    llm = build_llm().bind_tools(tools)

    pivot_hint = ""
    if is_pro_mode(advisor_mode):
        pivot_hint = (
            "You may use search_reviews and analyze_root_cause_live for live analysis. "
            "Prefer get_root_causes for precomputed RCA first."
        )
    else:
        pivot_hint = (
            "You are on Advisor Basic: use only precomputed tools. "
            "For hotel/vendor live breakdown or custom RCA, call request_plan_upgrade."
        )

    system = AGENT_SYSTEM.format(tier=tier_label(advisor_mode), pivot_hint=pivot_hint)
    if api_system:
        system = f"{system}\n\n{api_system}"

    lc_messages = [SystemMessage(content=system)] + _messages_from_openai(messages)

    answer = ""
    tool_actions: list[str] = []

    for _round in range(ADVISOR_AGENT_MAX_TOOL_ROUNDS):
        ai_msg = llm.invoke(lc_messages)
        lc_messages.append(ai_msg)

        if not getattr(ai_msg, "tool_calls", None):
            answer = (ai_msg.content or "").strip()
            break

        for call in ai_msg.tool_calls:
            name = call.get("name") or ""
            tool_actions.append(name)
            yield _sse({"type": "status", "phase": "tool", "detail": name})
            tool_fn = next((t for t in tools if t.name == name), None)
            if tool_fn is None:
                result = json.dumps(
                    {"error": "tool_not_allowed", "tool": name}, ensure_ascii=False
                )
            else:
                try:
                    result = tool_fn.invoke(call.get("args") or {})
                except Exception as exc:
                    logger.exception("Tool %s failed: %s", name, exc)
                    result = json.dumps({"error": str(exc)}, ensure_ascii=False)
            lc_messages.append(
                ToolMessage(content=str(result), tool_call_id=call.get("id") or name)
            )
    else:
        answer = "I could not complete the analysis within the tool step limit."

    if answer:
        yield _sse({"type": "content", "delta": answer})

    question = ""
    for msg in reversed(messages):
        if msg.get("role") == "user" and msg.get("content"):
            question = str(msg["content"])
            break

    followups, guidance = generate_contextual_navigation(
        question,
        answer,
        context_hint=api_system,
        llm=build_llm(),
    )

    yield _sse(
        {
            "type": "done",
            "content": answer,
            "pivony_suggested_followups": followups,
            "pivony_guidance": guidance,
            "pivony_tool_actions": tool_actions,
        }
    )
    yield "data: [DONE]\n\n"
