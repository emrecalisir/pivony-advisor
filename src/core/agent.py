"""Agentic RAG: Gemini orchestrates tools (Qdrant reviews + pivony metrics)."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient

from core.config import AGENT_MAX_TOOL_ITERATIONS, DEFAULT_SECTOR, sector_slugify
from core.pivony_platform import fetch_dashboards, fetch_metrics, fetch_pivots
from core.prompts import build_agent_system_prompt
from core.rag import search_reviews

logger = logging.getLogger(__name__)

# Advisor product tiers (forwarded from pivony-api as pivony_advisor_mode).
#   industry_expert : paid — raw-review RAG (Qdrant) + aggregate metrics
#   advisor         : freemium — aggregate metrics only (no raw-review indexing)
MODE_INDUSTRY_EXPERT = "industry_expert"
MODE_ADVISOR = "advisor"
DEFAULT_ADVISOR_MODE = MODE_INDUSTRY_EXPERT


class SearchReviewsArgs(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Search query in the user's language. For follow-up questions, include the "
            "topic and hotel from the prior conversation (e.g. 'temizlik şikayetleri X Otel')."
        ),
    )


class DashboardPivotsArgs(BaseModel):
    dashboard_id: int = Field(
        ...,
        description="The dashboard ID (from list_dashboards) to inspect filters for.",
    )


class MetricsArgs(BaseModel):
    dashboard_id: int | None = Field(
        default=None,
        description=(
            "Dashboard ID (from list_dashboards) to scope metrics to. Omit only for "
            "an explicit organization-wide overview."
        ),
    )
    pivot_key: str | None = Field(
        default=None,
        description="Pivot/filter key (from get_dashboard_pivots), e.g. 'Marka' or 'Şehir'.",
    )
    pivot_value: str | None = Field(
        default=None,
        description="Pivot/filter value within pivot_key, e.g. 'Voyage Torba'.",
    )
    days: int | None = Field(
        default=None, description="Look-back window in days, e.g. 30, 90, 180."
    )


def _build_tools(
    *,
    sector_slug: str,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    advisor_mode: str = DEFAULT_ADVISOR_MODE,
    user_id: str | None = None,
) -> list[StructuredTool]:
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)

    def _search(query: str) -> str:
        return search_reviews(query, slug, embeddings=embeddings, client=client)

    def _list_dashboards() -> str:
        data = fetch_dashboards(user_id)
        if data is None:
            return json.dumps(
                {"error": "Dashboard servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _dashboard_pivots(dashboard_id: int) -> str:
        data = fetch_pivots(user_id, dashboard_id)
        if data is None:
            return json.dumps(
                {"error": "Pivot servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _metrics(
        dashboard_id: int | None = None,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
    ) -> str:
        data = fetch_metrics(
            user_id,
            dashboard_id=dashboard_id,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
        )
        if data is None:
            return json.dumps(
                {"error": "Metrik servisi şu anda kullanılamıyor; veri çekilemedi."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    search_tool = StructuredTool.from_function(
        func=_search,
        name="search_qdrant_reviews",
        description=(
            "Search guest reviews for specific complaints, praise, evidence, or details. "
            "Returns review snippets prefixed with [Metadata -> Otel: ... | Tarih: ... | "
            "Kategori: ...]. Use for qualitative, example-based questions."
        ),
        args_schema=SearchReviewsArgs,
    )
    list_dashboards_tool = StructuredTool.from_function(
        func=_list_dashboards,
        name="list_dashboards",
        description=(
            "List the dashboards the user's organization can analyze (id + name). "
            "Call this first when a metrics question does not yet name a dashboard, "
            "then ask the user which one they mean."
        ),
    )
    dashboard_pivots_tool = StructuredTool.from_function(
        func=_dashboard_pivots,
        name="get_dashboard_pivots",
        description=(
            "List a dashboard's filter dimensions (pivot keys) and their top values. "
            "Use to resolve a user's free-text filter (e.g. 'voyage torba') to a "
            "(pivot_key, pivot_value) pair before calling get_pivony_metrics."
        ),
        args_schema=DashboardPivotsArgs,
    )
    metrics_tool = StructuredTool.from_function(
        func=_metrics,
        name="get_pivony_metrics",
        description=(
            "Get aggregate CX metrics scoped to a dashboard and optional pivot filter: "
            "sentiment (positive/neutral/negative %), complaint_topics (most negative "
            "themes), review_count, and best-effort avg_rating/top_root_causes. Provide "
            "dashboard_id (and pivot_key/pivot_value when the user named a brand/branch/"
            "city). Use for satisfaction/complaints and 'why is X happening' summaries."
        ),
        args_schema=MetricsArgs,
    )
    # Discovery + metrics tools ground every Advisor tier in Pivony's existing
    # analysis outputs. Raw-review search is an Industry-Expert (paid) capability.
    base_tools = [list_dashboards_tool, dashboard_pivots_tool, metrics_tool]
    if advisor_mode == MODE_ADVISOR:
        return base_tools
    return [search_tool, *base_tools]


def _to_langchain_messages(
    system_prompt: str,
    turns: list[tuple[str, str]],
) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    for role, content in turns:
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


def run_advisor_agent(
    *,
    turns: list[tuple[str, str]],
    sector_slug: str = DEFAULT_SECTOR,
    extra_system_prompt: str | None = None,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    llm: ChatGoogleGenerativeAI,
    advisor_mode: str = DEFAULT_ADVISOR_MODE,
    user_id: str | None = None,
    max_iterations: int | None = None,
) -> str:
    """
    Run the tool-calling loop and return the final assistant text.

    `turns` is an ordered list of (role, content) user/assistant messages
    ending with the latest user message. `advisor_mode` selects the product
    tier ('industry_expert' = raw-review RAG + metrics, 'advisor' = metrics only).
    `user_id` scopes get_pivony_metrics to the caller's organization.
    """
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)
    mode = advisor_mode or DEFAULT_ADVISOR_MODE
    tools = _build_tools(
        sector_slug=slug,
        embeddings=embeddings,
        client=client,
        advisor_mode=mode,
        user_id=user_id,
    )
    tool_map = {tool.name: tool for tool in tools}
    llm_with_tools = llm.bind_tools(tools)

    system_prompt = build_agent_system_prompt(slug, extra_system_prompt)
    messages = _to_langchain_messages(system_prompt, turns)

    limit = max_iterations or AGENT_MAX_TOOL_ITERATIONS
    for step in range(limit):
        ai_message = llm_with_tools.invoke(messages)
        messages.append(ai_message)

        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if not tool_calls:
            return _message_text(ai_message)

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            tool = tool_map.get(name)
            if tool is None:
                result = f"Bilinmeyen araç: {name}"
            else:
                try:
                    result = tool.invoke(args)
                except Exception as exc:  # tool failure should not crash the turn
                    logger.warning("Tool %s failed: %s", name, exc)
                    result = f"Araç hatası ({name}): {exc}"
            messages.append(
                ToolMessage(content=str(result), tool_call_id=call.get("id", name or ""))
            )
        logger.info("Agent step %s: executed %s tool call(s)", step + 1, len(tool_calls))

    # Tool budget exhausted — force a plain (no-tool) final answer.
    final = llm.invoke(messages)
    return _message_text(final)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "".join(parts).strip()
    return str(content or "").strip()
