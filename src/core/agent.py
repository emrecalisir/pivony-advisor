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


class MetricsArgs(BaseModel):
    vendor_name: str | None = Field(
        default=None, description="Hotel name to scope metrics, if the user named one."
    )
    period: str | None = Field(
        default=None, description="Time range, e.g. 'son 3 ay' or '2025-01..2025-03'."
    )


def _mock_metrics(vendor_name: str | None, period: str | None) -> str:
    """Placeholder metrics until a real analytics endpoint is wired (Faz 3)."""
    payload = {
        "vendorName": vendor_name or "Tüm Oteller",
        "avg_rating": 4.1,
        "top_root_causes": [
            "Oda temizliği",
            "Check-in bekleme süresi",
            "Kahvaltı çeşitliliği",
        ],
        "period": period or "Son 3 ay",
        "note": "Mock veri — gerçek metrik entegrasyonu (Faz 3) henüz bağlı değil.",
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_tools(
    *,
    sector_slug: str,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    advisor_mode: str = DEFAULT_ADVISOR_MODE,
) -> list[StructuredTool]:
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)

    def _search(query: str) -> str:
        return search_reviews(query, slug, embeddings=embeddings, client=client)

    def _metrics(vendor_name: str | None = None, period: str | None = None) -> str:
        return _mock_metrics(vendor_name, period)

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
    metrics_tool = StructuredTool.from_function(
        func=_metrics,
        name="get_pivony_metrics",
        description=(
            "Get aggregate satisfaction metrics (avg_rating/NPS, top_root_causes, period) "
            "for a hotel or overall. Use for trends, scores, and recurring-issue summaries."
        ),
        args_schema=MetricsArgs,
    )
    # Freemium Advisor is grounded only in Pivony's existing analysis outputs
    # (metrics API); raw-review search is an Industry-Expert (paid) capability.
    if advisor_mode == MODE_ADVISOR:
        return [metrics_tool]
    return [search_tool, metrics_tool]


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
    max_iterations: int | None = None,
) -> str:
    """
    Run the tool-calling loop and return the final assistant text.

    `turns` is an ordered list of (role, content) user/assistant messages
    ending with the latest user message. `advisor_mode` selects the product
    tier ('industry_expert' = raw-review RAG + metrics, 'advisor' = metrics only).
    """
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)
    mode = advisor_mode or DEFAULT_ADVISOR_MODE
    tools = _build_tools(
        sector_slug=slug, embeddings=embeddings, client=client, advisor_mode=mode
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
