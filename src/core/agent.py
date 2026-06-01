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
from core.pivony_platform import (
    fetch_dashboards,
    fetch_metrics,
    fetch_pivots,
    fetch_reviews,
    fetch_root_causes,
    request_plan_upgrade,
)
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


class ListReviewsArgs(BaseModel):
    dashboard_id: int = Field(
        ..., description="Dashboard ID (from list_dashboards / get_pivony_metrics)."
    )
    topic_id: int | None = Field(
        default=None,
        description="Topic id from get_pivony_metrics complaint_topics to scope to.",
    )
    sentiment: str | None = Field(
        default=None,
        description="Filter by sentiment: 'negative', 'neutral', or 'positive'.",
    )
    pivot_key: str | None = Field(default=None, description="Optional pivot key.")
    pivot_value: str | None = Field(default=None, description="Optional pivot value.")


class PlanUpgradeArgs(BaseModel):
    message: str | None = Field(
        default=None,
        description="Short note describing what the user wants to do/analyze.",
    )


class RootCausesArgs(BaseModel):
    dashboard_id: int = Field(
        ..., description="Dashboard ID (from list_dashboards / get_pivony_metrics)."
    )
    topic: str | None = Field(
        default=None,
        description="Topic name to scope root causes to, e.g. 'F&B', 'Oda'.",
    )
    topic_id: int | None = Field(
        default=None,
        description="Topic id from get_pivony_metrics complaint_topics, if known.",
    )
    pivot_key: str | None = Field(default=None, description="Optional pivot key.")
    pivot_value: str | None = Field(default=None, description="Optional pivot value.")


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
    org_wide: bool = Field(
        default=False,
        description=(
            "Set True ONLY when the user explicitly asks for an organization-wide "
            "overview across all dashboards. Otherwise leave False and provide a "
            "dashboard_id."
        ),
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

    def _list_reviews(
        dashboard_id: int,
        topic_id: int | None = None,
        sentiment: str | None = None,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
    ) -> str:
        data = fetch_reviews(
            user_id,
            dashboard_id=dashboard_id,
            topic_id=topic_id,
            sentiment=sentiment,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
        )
        if data is None:
            return json.dumps(
                {"error": "Yorum servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _request_plan_upgrade(message: str | None = None) -> str:
        data = request_plan_upgrade(user_id, message=message)
        if data is None:
            return json.dumps(
                {"error": "Plan talebi şu anda iletilemedi."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _root_causes(
        dashboard_id: int,
        topic: str | None = None,
        topic_id: int | None = None,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
    ) -> str:
        data = fetch_root_causes(
            user_id,
            dashboard_id=dashboard_id,
            topic=topic,
            topic_id=topic_id,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
        )
        if data is None:
            return json.dumps(
                {"error": "Kök-neden servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _metrics(
        dashboard_id: int | None = None,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        org_wide: bool = False,
    ) -> str:
        # Guardrail: never silently aggregate across all dashboards. Force the
        # agent to ask the user which dashboard unless an org-wide overview was
        # explicitly requested.
        if dashboard_id is None and not org_wide:
            dash = fetch_dashboards(user_id)
            options = dash.get("dashboards") if isinstance(dash, dict) else None
            return json.dumps(
                {
                    "need_dashboard_selection": True,
                    "dashboards": options or [],
                    "instruction": (
                        "Bir dashboard seçilmedi. Kullanıcıya bu dashboard'lardan "
                        "hangisini kastettiğini sor; cevabı almadan metrik döndürme. "
                        "(Tüm organizasyon geneli isterse org_wide=true ile tekrar çağır.)"
                    ),
                },
                ensure_ascii=False,
            )
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
            "themes, each with a topic_id), review_count, and best-effort avg_rating/"
            "top_root_causes. Provide dashboard_id (and pivot_key/pivot_value when the "
            "user named a brand/branch/city). Use for satisfaction/complaints summaries."
        ),
        args_schema=MetricsArgs,
    )
    root_causes_tool = StructuredTool.from_function(
        func=_root_causes,
        name="get_root_causes",
        description=(
            "Get the analyzed root causes behind complaints for a dashboard, optionally "
            "scoped to a topic (pass topic_id from get_pivony_metrics complaint_topics, "
            "or a topic name). Use for 'ana problem / neden / kök neden' questions. "
            "Returns status: 'ok' (root_causes listed), 'none_for_topic' (analysis exists "
            "but none for this topic), or 'not_generated' (root-cause analysis has not "
            "been run for this dashboard yet — tell the user it must be generated)."
        ),
        args_schema=RootCausesArgs,
    )
    list_reviews_tool = StructuredTool.from_function(
        func=_list_reviews,
        name="list_reviews",
        description=(
            "List a few example review texts for a dashboard, scoped by topic_id, "
            "sentiment ('negative' for complaints), and optional pivot. Use to show "
            "real customer voice examples behind a topic. Returns at most a handful "
            "of reviews (freemium cap)."
        ),
        args_schema=ListReviewsArgs,
    )
    request_plan_upgrade_tool = StructuredTool.from_function(
        func=_request_plan_upgrade,
        name="request_plan_upgrade",
        description=(
            "Email the Pivony team that this user wants to upgrade to the "
            "Industry-Expert plan. ONLY call after the user explicitly confirms they "
            "want to take action / be contacted about a plan change."
        ),
        args_schema=PlanUpgradeArgs,
    )
    # Discovery + metrics tools ground every Advisor tier in Pivony's existing
    # analysis outputs. list_reviews surfaces the user's own dashboard reviews
    # (capped on freemium). Raw-review semantic search (Qdrant sector RAG) is an
    # Industry-Expert (paid) capability.
    base_tools = [
        list_dashboards_tool,
        dashboard_pivots_tool,
        metrics_tool,
        root_causes_tool,
        list_reviews_tool,
        request_plan_upgrade_tool,
    ]
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

    system_prompt = build_agent_system_prompt(slug, extra_system_prompt, advisor_mode=mode)
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
