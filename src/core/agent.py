"""Agentic RAG: Gemini orchestrates tools (Qdrant reviews + pivony metrics)."""

from __future__ import annotations

import json
import logging
import re
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
from core.analytics_scope import EstablishedAnalyticsScope
from core.agent_state import (
    HardAgentState,
    hard_context_prompt_block,
    resolve_hard_agent_state,
)
from core.tool_routing import (
    blocked_tool_result,
    filter_tools_for_state,
    sanitize_tool_calls,
    validated_tool_invoke,
)
from core.compute import compare_pivot_ratings
from core.metrics_normalize import normalize_metrics_response
from core.pivony_platform import (
    fetch_dashboards,
    fetch_decisions,
    fetch_digital_experience_score,
    fetch_distribution,
    fetch_emergent_topics,
    fetch_hotterms,
    fetch_key_drivers,
    fetch_metrics,
    fetch_pivots,
    fetch_reviews,
    fetch_root_causes,
    fetch_stored_genai,
    fetch_topic_intent_distribution,
    fetch_topic_participation,
    fetch_topic_ratings,
    fetch_topic_sentiment,
    fetch_topic_trends,
    fetch_trends,
    request_plan_upgrade,
)
from core.pivot_resolve import looks_like_pivot_scoped_search, semantic_search_pivot_redirect
from core.prompts import build_agent_system_prompt
from core.rag import search_reviews
from core.tier_gating import industry_expert_gate

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
    query: str | None = Field(
        default=None,
        description=(
            "Fuzzy lookup for a hotel/brand/segment name (e.g. 'voyage torba'). "
            "Searches ALL pivot values, not just the top-25 list."
        ),
    )
    pivot_key: str | None = Field(
        default=None,
        description=(
            "Optional pivot key scope for query (e.g. 'vendorName'). "
            "Aliases like vendor_name are normalized automatically."
        ),
    )


class ListReviewsArgs(BaseModel):
    dashboard_id: int = Field(
        ..., description="Dashboard ID (from list_dashboards / get_pivony_metrics)."
    )
    topic_id: int | None = Field(
        default=None,
        description="Topic id from get_pivony_metrics complaint_topics to scope to.",
    )
    topic: str | None = Field(
        default=None,
        description=(
            "Topic name to scope reviews to (e.g. 'Acente') when topic_id is unknown — "
            "resolved server-side on the locked dashboard."
        ),
    )
    sentiment: str | None = Field(
        default=None,
        description="Filter by sentiment: 'negative', 'neutral', or 'positive'.",
    )
    pivot_key: str | None = Field(default=None, description="Optional pivot key.")
    pivot_value: str | None = Field(default=None, description="Optional pivot value.")
    days: int | None = Field(default=None, description="Look-back window in days.")
    since: str | None = Field(
        default=None, description="Exact start date YYYY-MM-DD (page's since when known)."
    )
    until: str | None = Field(
        default=None, description="Exact end date YYYY-MM-DD (page's until when known)."
    )


class PlanUpgradeArgs(BaseModel):
    message: str | None = Field(
        default=None,
        description="Short note describing what the user wants to do/analyze.",
    )


class ScopedDashboardArgs(BaseModel):
    dashboard_id: int = Field(
        ..., description="Dashboard ID (from list_dashboards / get_pivony_metrics)."
    )
    pivot_key: str | None = Field(default=None, description="Optional pivot/filter key.")
    pivot_value: str | None = Field(
        default=None, description="Optional pivot/filter value within pivot_key."
    )
    days: int | None = Field(
        default=None, description="Look-back window in days, e.g. 7, 30, 90, 180."
    )
    since: str | None = Field(
        default=None,
        description="Exact start date YYYY-MM-DD (use the page's since when known).",
    )
    until: str | None = Field(
        default=None,
        description="Exact end date YYYY-MM-DD (use the page's until when known).",
    )


class HottermsArgs(ScopedDashboardArgs):
    limit: int | None = Field(
        default=None, description="Max number of terms to return (<=50)."
    )


class DistributionArgs(ScopedDashboardArgs):
    kind: str = Field(
        default="sentiment",
        description=(
            "Which breakdown: 'sentiment', 'intent', 'platform' (channel), "
            "'pivot' (Pivot Analysis column), 'rating' (star-rating doughnut), "
            "'fraud' (fraud flag mix), or 'praise_intent' (Appraisal intent score)."
        ),
    )
    pivot_column: str | None = Field(
        default=None,
        description=(
            "Only for kind='pivot': the pivot column name (e.g. 'hasChild', "
            "'channel'). Omit to discover the available columns first."
        ),
    )


class ComparePivotRatingsArgs(BaseModel):
    dashboard_id: int = Field(
        ..., description="Dashboard ID (from list_dashboards / get_pivony_metrics)."
    )
    pivot_key: str = Field(
        ...,
        description=(
            "Pivot dimension whose values to rank (from get_dashboard_pivots), "
            "e.g. 'Marka', 'Otel', 'Şube'."
        ),
    )
    days: int | None = Field(
        default=None, description="Look-back window in days, e.g. 30 for last month."
    )
    since: str | None = Field(
        default=None,
        description="Exact start date YYYY-MM-DD for the current comparison window.",
    )
    until: str | None = Field(
        default=None,
        description="Exact end date YYYY-MM-DD for the current comparison window.",
    )
    limit: int | None = Field(
        default=None,
        description="Max pivot values to compare in parallel (default 20).",
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
    since: str | None = Field(
        default=None,
        description="Exact start date YYYY-MM-DD (use the page's since when known).",
    )
    until: str | None = Field(
        default=None,
        description="Exact end date YYYY-MM-DD (use the page's until when known).",
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
    page_context: dict | None = None,
    turns: list[tuple[str, str]] | None = None,
    hard_state: HardAgentState | None = None,
) -> list[StructuredTool]:
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)
    _hard = hard_state or resolve_hard_agent_state(turns or [], page_context)

    # Page scope (dashboard + date window the user is actually looking at). Used
    # as a deterministic default so we don't depend on the LLM copying dates out
    # of the prose context block.
    _pc = page_context if isinstance(page_context, dict) else {}
    _pc_since = _hard.since or _pc.get("since") or None
    _pc_until = _hard.until or _pc.get("until") or None
    _pc_days = _hard.days or _pc.get("days") or _pc.get("selectedDaysRange")

    def _authorized_dashboard_id(dashboard_id: int | None = None) -> int | None:
        """Only use a dashboard id when scope is locked server-side — never trust
        the model to pick one from list_dashboards output."""
        if _hard.dashboard_id is not None:
            return _hard.dashboard_id
        return None

    def _dashboard_selection_required() -> str:
        dash = fetch_dashboards(user_id)
        options = dash.get("dashboards") if isinstance(dash, dict) else None
        return json.dumps(
            {
                "need_dashboard_selection": True,
                "dashboards": options or [],
                "instruction": (
                    "Kullanıcı henüz bir dashboard seçmedi. list_dashboards "
                    "çıktısından dashboard_id tahmin ETME — yalnızca kullanıcının "
                    "picker'dan seçtiği dashboard geçerlidir."
                ),
            },
            ensure_ascii=False,
        )

    def _require_locked_dashboard(_llm_dashboard_id: int | None = None) -> int | str:
        authorized = _authorized_dashboard_id(_llm_dashboard_id)
        if authorized is not None:
            return authorized
        return _dashboard_selection_required()

    def _eff_dates(since: str | None, until: str | None, days: int | None):
        """Explicit dates/days from the tool call win; otherwise inherit the
        page's exact since/until so answers match what the user sees."""
        if since or until:
            return since, until, days
        if days:
            return since, until, days
        if _pc_since or _pc_until:
            return _pc_since, _pc_until, days
        if _pc_days:
            try:
                return since, until, int(_pc_days)
            except (TypeError, ValueError):
                pass
        return _pc_since, _pc_until, days

    def _search(query: str) -> str:
        if looks_like_pivot_scoped_search(query):
            return semantic_search_pivot_redirect()
        return search_reviews(query, slug, embeddings=embeddings, client=client)

    def _list_dashboards() -> str:
        data = fetch_dashboards(user_id)
        if data is None:
            return json.dumps(
                {"error": "Dashboard servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _dashboard_pivots(
        dashboard_id: int,
        query: str | None = None,
        pivot_key: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        data = fetch_pivots(
            user_id,
            resolved,
            query=query,
            pivot_key=pivot_key,
        )
        if data is None:
            return json.dumps(
                {"error": "Pivot servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _list_reviews(
        dashboard_id: int,
        topic_id: int | None = None,
        topic: str | None = None,
        sentiment: str | None = None,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_reviews(
            user_id,
            dashboard_id=resolved,
            topic_id=topic_id,
            topic=topic,
            sentiment=sentiment,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
            since=since,
            until=until,
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

    def _trends(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_trends(
            user_id, dashboard_id=resolved,
            pivot_key=pivot_key, pivot_value=pivot_value, days=days,
            since=since, until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Trend servisi şu anda kullanılamıyor."}, ensure_ascii=False
            )
        return json.dumps(data, ensure_ascii=False)

    def _compare_pivot_ratings(
        dashboard_id: int,
        pivot_key: str,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        if advisor_mode == MODE_ADVISOR:
            return json.dumps(
                industry_expert_gate(
                    "compare_pivot_ratings",
                    detail=(
                        "Birden fazla otel/segment arasında rating değişimini "
                        "karşılaştırma ve sıralama."
                    ),
                ),
                ensure_ascii=False,
            )
        since, until, days = _eff_dates(since, until, days)
        data = compare_pivot_ratings(
            user_id,
            resolved,
            pivot_key,
            days=days,
            since=since,
            until=until,
            limit=limit,
        )
        return json.dumps(data, ensure_ascii=False)

    def _topic_trends(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_topic_trends(
            user_id, dashboard_id=resolved,
            pivot_key=pivot_key, pivot_value=pivot_value, days=days,
            since=since, until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Topic trend servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _hotterms(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        since: str | None = None,
        until: str | None = None,
        days: int | None = None,
        limit: int | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_hotterms(
            user_id, dashboard_id=resolved,
            pivot_key=pivot_key, pivot_value=pivot_value, days=days,
            since=since, until=until, limit=limit,
        )
        if data is None:
            return json.dumps(
                {"error": "Hotterm servisi şu anda kullanılamıyor."}, ensure_ascii=False
            )
        return json.dumps(data, ensure_ascii=False)

    def _decisions(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_decisions(
            user_id, dashboard_id=resolved,
            pivot_key=pivot_key, pivot_value=pivot_value, days=days,
            since=since, until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Karar dağılımı servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _distribution(
        dashboard_id: int,
        kind: str = "sentiment",
        pivot_column: str | None = None,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_distribution(
            user_id, dashboard_id=resolved, kind=kind, pivot_column=pivot_column,
            pivot_key=pivot_key, pivot_value=pivot_value, days=days,
            since=since, until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Dağılım servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _topic_ratings(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_topic_ratings(
            user_id, dashboard_id=resolved,
            pivot_key=pivot_key, pivot_value=pivot_value, days=days,
            since=since, until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Topic puan servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _emergent_topics(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_emergent_topics(
            user_id, dashboard_id=resolved,
            pivot_key=pivot_key, pivot_value=pivot_value, days=days,
            since=since, until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Emergent topic servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _topic_intent_distribution(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_topic_intent_distribution(
            user_id,
            dashboard_id=resolved,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
            since=since,
            until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Konu bazında niyet servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _topic_sentiment(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_topic_sentiment(
            user_id,
            dashboard_id=resolved,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
            since=since,
            until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Konu bazında duygu servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _topic_participation(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_topic_participation(
            user_id,
            dashboard_id=resolved,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
            since=since,
            until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Konu katılım servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _key_drivers(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_key_drivers(
            user_id,
            dashboard_id=resolved,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
            since=since,
            until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Temel etkenler (KDA) servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _digital_experience_score(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_digital_experience_score(
            user_id,
            dashboard_id=resolved,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
            since=since,
            until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Digital Experience Score servisi şu anda kullanılamıyor."},
                ensure_ascii=False,
            )
        return json.dumps(data, ensure_ascii=False)

    def _stored_genai(
        dashboard_id: int,
        pivot_key: str | None = None,
        pivot_value: str | None = None,
        days: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        since, until, days = _eff_dates(since, until, days)
        data = fetch_stored_genai(
            user_id,
            dashboard_id=resolved,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
            since=since,
            until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "GenAI özet servisi şu anda kullanılamıyor."},
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
        resolved = _require_locked_dashboard(dashboard_id)
        if isinstance(resolved, str):
            return resolved
        data = fetch_root_causes(
            user_id,
            dashboard_id=resolved,
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
        since: str | None = None,
        until: str | None = None,
        org_wide: bool = False,
    ) -> str:
        # Pin to the page's dashboard + date window when the model didn't specify
        # them, so the answer matches exactly what the user is looking at.
        dashboard_id = _authorized_dashboard_id(dashboard_id)
        since, until, days = _eff_dates(since, until, days)
        if dashboard_id is None and not org_wide and _hard.org_wide:
            org_wide = True
            if days is None and _hard.days is not None:
                days = _hard.days
            if not since and _hard.since:
                since = _hard.since
            if not until and _hard.until:
                until = _hard.until
        # Never honor model org_wide unless scope was explicitly established server-side.
        if org_wide and not _hard.org_wide:
            org_wide = False
        if dashboard_id is None and not org_wide:
            return _dashboard_selection_required()
        data = fetch_metrics(
            user_id,
            dashboard_id=dashboard_id,
            pivot_key=pivot_key,
            pivot_value=pivot_value,
            days=days,
            since=since,
            until=until,
        )
        if data is None:
            return json.dumps(
                {"error": "Metrik servisi şu anda kullanılamıyor; veri çekilemedi."},
                ensure_ascii=False,
            )
        if isinstance(data, dict) and data.get("error"):
            return json.dumps(data, ensure_ascii=False)
        return json.dumps(
            normalize_metrics_response(data),
            ensure_ascii=False,
        )

    search_tool = StructuredTool.from_function(
        func=_search,
        name="search_qdrant_reviews",
        description=(
            "Search guest reviews for specific complaints, praise, evidence, or details "
            "when NO hotel/vendor pivot filter applies. Do NOT use for hotel+topic "
            "questions — use list_reviews with pivot_key/pivot_value instead. "
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
            "Pass query=<hotel name> to fuzzy-resolve a free-text filter (e.g. "
            "'voyage torba') to a (pivot_key, pivot_value) pair — essential because "
            "the top-25 list may omit low-volume hotels. ETS dashboards use "
            "pivot_key='vendorName' for hotel names."
        ),
        args_schema=DashboardPivotsArgs,
    )
    metrics_tool = StructuredTool.from_function(
        func=_metrics,
        name="get_pivony_metrics",
        description=(
            "Get aggregate CX metrics scoped to a dashboard and optional pivot filter: "
            "sentiment (positive/neutral/negative %), topics (EVERY topic with its TOTAL "
            "review count regardless of sentiment — use for 'how many X reviews'), "
            "complaint_topics (only negative themes, each with a topic_id), review_count "
            "(dashboard total), avg_rating, nps, positive_sentiment_score, and best-effort "
            "top_root_causes. sentiment/score/rating/review_count/nps are read straight from "
            "the dashboard's own search engine so they match the DashboardData page 1:1. "
            "Provide dashboard_id (and pivot_key/pivot_value when the user named a brand/"
            "branch/city), plus the page's since/until when known. Use for satisfaction/"
            "complaints summaries and topic review counts."
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
            "List a few example review texts for a dashboard, scoped by topic_id or "
            "topic name, sentiment ('negative' for complaints), and optional pivot. "
            "Use to show real customer voice examples behind a topic. Returns at most "
            "a handful of reviews (freemium cap)."
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
    trends_tool = StructuredTool.from_function(
        func=_trends,
        name="get_trends",
        description=(
            "Get the over-time KPI series for ONE scoped pivot value on a dashboard: "
            "volume_daily, sentiment_daily, ratings_daily, plus avg_rating, "
            "avg_sentiment and NPS. Use for a single hotel/branch/segment trend "
            "(e.g. 'Voyage Torba rating trendi'). For ranking or comparing MANY "
            "pivot values (e.g. 'en çok düşen otel'), use compare_pivot_ratings instead."
        ),
        args_schema=ScopedDashboardArgs,
    )
    compare_pivot_ratings_tool = StructuredTool.from_function(
        func=_compare_pivot_ratings,
        name="compare_pivot_ratings",
        description=(
            "Rank pivot values (hotels, branches, brands) by avg_rating change between "
            "two equal time windows on one dashboard. Use for 'en çok düşen otel', "
            "'hangi otel en kötü performans', 'otelleri karşılaştır', 'rating "
            "sıralaması'. Requires dashboard_id and pivot_key from get_dashboard_pivots. "
            "On freemium (Advisor) plans the tool returns an Industry-Expert upgrade "
            "prompt — relay user_message to the user."
        ),
        args_schema=ComparePivotRatingsArgs,
    )
    topic_trends_tool = StructuredTool.from_function(
        func=_topic_trends,
        name="get_topic_trends",
        description=(
            "Get rising and falling topics: compares each topic's review count for "
            "the window against the preceding window of equal length. Returns `rising` "
            "and `falling` lists with current/previous/change. Use for 'hangi konular "
            "artıyor/azalıyor', 'yükselen şikayetler', 'what changed'."
        ),
        args_schema=ScopedDashboardArgs,
    )
    hotterms_tool = StructuredTool.from_function(
        func=_hotterms,
        name="get_hotterms",
        description=(
            "Get trending keywords/phrases (1-4 grams) for a dashboard, keyed by ngram "
            "size. Use for 'sık geçen kelimeler', 'öne çıkan ifadeler', 'hot terms'."
        ),
        args_schema=HottermsArgs,
    )
    decisions_tool = StructuredTool.from_function(
        func=_decisions,
        name="get_decision_distribution",
        description=(
            "Get the decision distribution (publish / opencase / takeaction, each with "
            "true/false counts) for a dashboard. Use for 'kaç yorum aksiyon/vaka "
            "gerektiriyor', 'yayınlanabilir mi' type operational questions."
        ),
        args_schema=ScopedDashboardArgs,
    )
    distribution_tool = StructuredTool.from_function(
        func=_distribution,
        name="get_distribution",
        description=(
            "Get a breakdown for a dashboard by `kind`, sourced from the SAME engine "
            "as the dashboard widgets (matches the page 1:1): 'sentiment' (positive/"
            "neutral/negative/mixed split — Sentiment Analysis), 'intent' (why "
            "customers write — Intent Analysis: complaint/request/suggestion…), "
            "'platform' (channel/source mix), 'pivot' (a Pivot Analysis column "
            "such as hasChild or channel — pass pivot_column; omit it first to list "
            "the available columns), 'rating' (star-rating doughnut), 'fraud', or "
            "'praise_intent' (Appraisal intent score). Use for 'intent oranı', "
            "'duygu dağılımı', 'hangi kanaldan', 'hasChild/çocuklu oranı', "
            "'pivot dağılımı', 'yıldız dağılımı', 'fraud oranı'."
        ),
        args_schema=DistributionArgs,
    )
    topic_intent_tool = StructuredTool.from_function(
        func=_topic_intent_distribution,
        name="get_topic_intent_distribution",
        description=(
            "Get intent distribution PER TOPIC (metric 12/17): each topic includes "
            "intent_pcts and complaint_pct (Complaint intent %). Use for "
            "'topiclerin şikayet oranı', 'konu bazında niyet', 'hangi konuda ne "
            "kadar şikayet' — NOT get_distribution(intent) which is review-level only."
        ),
        args_schema=ScopedDashboardArgs,
    )
    topic_sentiment_tool = StructuredTool.from_function(
        func=_topic_sentiment,
        name="get_topic_sentiment",
        description=(
            "Get sentiment breakdown PER TOPIC (metric 14): positive/neutral/"
            "negative % per topic. Matches DashboardData 'Kategorilerin Duygu "
            "Skorları'. Use for 'konu bazında duygu', 'X konusunun sentimenti'."
        ),
        args_schema=ScopedDashboardArgs,
    )
    topic_participation_tool = StructuredTool.from_function(
        func=_topic_participation,
        name="get_topic_participation",
        description=(
            "Get participation (unique review count) PER TOPIC (metric 15). Use "
            "for 'konu katılımı', 'hangi konuda kaç yorum', topic share of voice."
        ),
        args_schema=ScopedDashboardArgs,
    )
    key_drivers_tool = StructuredTool.from_function(
        func=_key_drivers,
        name="get_key_drivers",
        description=(
            "Get Key Drivers Analysis (KDA bubble) for a dashboard using the saved "
            "KDA configuration on DashboardData. Returns status no_config when "
            "analysis has not been set up. Use for 'temel etkenler', 'key drivers', "
            "'hangi konu performansı en çok etkiliyor'."
        ),
        args_schema=ScopedDashboardArgs,
    )
    digital_experience_tool = StructuredTool.from_function(
        func=_digital_experience_score,
        name="get_digital_experience_score",
        description=(
            "Get Digital Experience Score (metric 18) when competitive VOC data "
            "exists for the org. Returns status unavailable when not configured."
        ),
        args_schema=ScopedDashboardArgs,
    )
    stored_genai_tool = StructuredTool.from_function(
        func=_stored_genai,
        name="get_stored_genai_insights",
        description=(
            "List GenAI insight job status for a dashboard (summary/highlights "
            "jobs). Use get_root_causes for stored root-cause text. Does not "
            "generate new GenAI content."
        ),
        args_schema=ScopedDashboardArgs,
    )
    topic_ratings_tool = StructuredTool.from_function(
        func=_topic_ratings,
        name="get_topic_ratings",
        description=(
            "Get the average rating per topic for a dashboard (which topics score "
            "highest/lowest), from the SAME 'Topics Rating' widget data on the page "
            "(matches 1:1). Use for 'X konusunun rating'i nedir', 'hangi konu en "
            "düşük/yüksek puanlı', 'konu bazında puanlar'."
        ),
        args_schema=ScopedDashboardArgs,
    )
    emergent_topics_tool = StructuredTool.from_function(
        func=_emergent_topics,
        name="get_emergent_topics",
        description=(
            "Get emergent / newly surfacing topics for a dashboard. Use for "
            "'yeni ortaya çıkan konular', 'emerging issues', 'gündeme gelen konular'."
        ),
        args_schema=ScopedDashboardArgs,
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
        trends_tool,
        compare_pivot_ratings_tool,
        topic_trends_tool,
        hotterms_tool,
        decisions_tool,
        distribution_tool,
        topic_intent_tool,
        topic_sentiment_tool,
        topic_participation_tool,
        topic_ratings_tool,
        key_drivers_tool,
        digital_experience_tool,
        stored_genai_tool,
        emergent_topics_tool,
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


EMPTY_AGENT_REPLY = (
    "Üzgünüm, yanıt oluşturulamadı. Lütfen sorunuzu daha dar bir kapsamla "
    "(tek dashboard veya tek otel) tekrar deneyin."
)


def _finalize_agent_reply(text: str) -> str:
    cleaned = (text or "").strip()
    return cleaned if cleaned else EMPTY_AGENT_REPLY


def _build_dashboard_picker(
    data: dict,
    default_dashboard_id: int | None,
    *,
    tool_name: str | None = None,
) -> dict | None:
    """Build UI picker artifact from list_dashboards / worker payload."""
    if tool_name == "list_dashboards" or data.get("need_dashboard_selection"):
        pass
    elif tool_name is not None:
        return None
    raw = data.get("dashboards")
    if not isinstance(raw, list):
        return None
    items = []
    for d in raw:
        if not isinstance(d, dict) or d.get("id") is None:
            continue
        entry = {"id": d.get("id"), "name": d.get("name")}
        if d.get("group_id") is not None:
            entry["group_id"] = d.get("group_id")
        items.append(entry)
    if not items:
        return None
    groups = []
    raw_groups = data.get("groups")
    if isinstance(raw_groups, list):
        for g in raw_groups:
            if isinstance(g, dict) and g.get("id") is not None:
                groups.append(
                    {
                        "id": g.get("id"),
                        "name": g.get("name"),
                        "color": g.get("color"),
                    }
                )
    return {
        "dashboards": items,
        "groups": groups,
        "default_dashboard_id": default_dashboard_id,
    }


def _extract_dashboard_picker(
    tool_name: str,
    result: Any,
    default_dashboard_id: int | None,
) -> dict | None:
    """If a tool result implies the user must pick a dashboard, build a UI picker."""
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return _build_dashboard_picker(data, default_dashboard_id, tool_name=tool_name)


_DASHBOARD_SCOPE_TOOLS = frozenset(
    {
        "get_pivony_metrics",
        "get_root_causes",
        "get_trends",
        "compare_pivot_ratings",
        "get_topic_trends",
        "get_hotterms",
        "get_decision_distribution",
        "get_distribution",
        "get_topic_intent_distribution",
        "get_topic_sentiment",
        "get_topic_participation",
        "get_topic_ratings",
        "get_key_drivers",
        "get_digital_experience_score",
        "get_stored_genai_insights",
        "get_emergent_topics",
        "list_reviews",
        "get_dashboard_pivots",
    }
)
_DASHBOARD_PICKER_FALLBACK_MAX_TEXT_LEN = 80


def _assistant_text_has_substantive_data(text: str) -> bool:
    if not text:
        return False
    if re.search(r"\d", text):
        return True
    if "%" in text:
        return True
    if re.search(r"^\s*\d+\.", text, re.MULTILINE):
        return True
    return False


def _assistant_asks_for_dashboard_choice(text: str) -> bool:
    """True when the reply is a dashboard-selection prompt, not a generic greeting."""
    lower = (text or "").strip().lower()
    if not lower or len(lower) > _DASHBOARD_PICKER_FALLBACK_MAX_TEXT_LEN:
        return False
    if "dashboard" in lower or "gösterge" in lower or "gosterge" in lower:
        return True
    return "?" in lower and "hangi" in lower


def _resolve_dashboard_picker_fallback(
    *,
    user_id: str | None,
    default_dashboard_id: int | None,
    assistant_text: str,
    tools_called: set[str],
    established_scope: EstablishedAnalyticsScope | None = None,
) -> dict | None:
    """
    Attach picker when the model asks to choose a dashboard in prose without
    calling list_dashboards(), or when a metrics tool ran without a dashboard.
    """
    if established_scope and (
        established_scope.org_wide or established_scope.dashboard_id is not None
    ):
        return None
    if not user_id or default_dashboard_id is not None:
        return None
    if "list_dashboards" in tools_called:
        return None
    text = (assistant_text or "").strip()
    if not text or _assistant_text_has_substantive_data(text):
        return None
    needs_picker = bool(tools_called & _DASHBOARD_SCOPE_TOOLS)
    if not needs_picker and _assistant_asks_for_dashboard_choice(text):
        needs_picker = True
    if not needs_picker:
        return None
    data = fetch_dashboards(user_id)
    if not isinstance(data, dict):
        return None
    return _build_dashboard_picker(data, default_dashboard_id, tool_name="list_dashboards")


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
    page_context: dict | None = None,
    max_iterations: int | None = None,
) -> tuple[str, dict | None]:
    """
    Run the tool-calling loop and return (assistant_text, dashboard_picker).

    `turns` is an ordered list of (role, content) user/assistant messages
    ending with the latest user message. `advisor_mode` selects the product
    tier ('industry_expert' = raw-review RAG + metrics, 'advisor' = metrics only).
    `user_id` scopes get_pivony_metrics to the caller's organization.
    `dashboard_picker` is non-None when the turn asks the user to choose a
    dashboard, so the UI can render a searchable/clickable list instead of prose.
    """
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)
    mode = advisor_mode or DEFAULT_ADVISOR_MODE
    _hard = resolve_hard_agent_state(turns, page_context)
    tools = filter_tools_for_state(
        _build_tools(
            sector_slug=slug,
            embeddings=embeddings,
            client=client,
            advisor_mode=mode,
            user_id=user_id,
            page_context=page_context,
            turns=turns,
            hard_state=_hard,
        ),
        _hard,
    )
    tool_map = {tool.name: tool for tool in tools}
    llm_with_tools = llm.bind_tools(tools)

    scope_hint = hard_context_prompt_block(_hard)
    system_prompt = build_agent_system_prompt(slug, extra_system_prompt, advisor_mode=mode)
    if scope_hint:
        system_prompt = f"{system_prompt}\n\n{scope_hint}"
    messages = _to_langchain_messages(system_prompt, turns)

    default_dash = _hard.dashboard_id
    if default_dash is None and isinstance(page_context, dict):
        raw = page_context.get("dashboard_id")
        try:
            default_dash = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            default_dash = None
    picker: dict | None = None
    tools_called: set[str] = set()

    limit = max_iterations or AGENT_MAX_TOOL_ITERATIONS
    for step in range(limit):
        ai_message = llm_with_tools.invoke(messages)
        messages.append(ai_message)

        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if not tool_calls:
            if picker is None:
                picker = _resolve_dashboard_picker_fallback(
                    user_id=user_id,
                    default_dashboard_id=default_dash,
                    assistant_text=_message_text(ai_message),
                    tools_called=tools_called,
                    established_scope=_hard.as_established(),
                )
            return _finalize_agent_reply(_message_text(ai_message)), picker

        tool_calls = sanitize_tool_calls(tool_calls, _hard)
        for call in tool_calls:
            name = call.get("name")
            if name:
                tools_called.add(name)
            args = call.get("args") or {}
            tool = tool_map.get(name)
            blocked = blocked_tool_result(name or "", _hard) if name else None
            if blocked:
                result = blocked
            elif tool is None:
                result = f"Bilinmeyen araç: {name}"
            else:
                try:
                    result = validated_tool_invoke(tool, args, _hard, user_id=user_id)
                except Exception as exc:  # tool failure should not crash the turn
                    logger.warning("Tool %s failed: %s", name, exc)
                    result = f"Araç hatası ({name}): {exc}"
            if picker is None:
                picker = _extract_dashboard_picker(name, result, default_dash)
            messages.append(
                ToolMessage(content=str(result), tool_call_id=call.get("id", name or ""))
            )
        logger.info("Agent step %s: executed %s tool call(s)", step + 1, len(tool_calls))

    # Tool budget exhausted — force a plain (no-tool) final answer.
    final = llm.invoke(messages)
    final_text = _message_text(final)
    if picker is None:
        picker = _resolve_dashboard_picker_fallback(
            user_id=user_id,
            default_dashboard_id=default_dash,
            assistant_text=final_text,
            tools_called=tools_called,
            established_scope=_hard.as_established(),
        )
    return _finalize_agent_reply(final_text), picker


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "".join(parts).strip()
    return str(content or "").strip()
