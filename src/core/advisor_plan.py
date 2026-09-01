"""Advisor Basic vs Advisor Pro — mirrors pivony-api api.utils.advisor_plan."""

from __future__ import annotations

ADVISOR_MODE_BASIC = "advisor"
ADVISOR_MODE_PRO = "industry_expert"

ADVISOR_BASIC_TOOLS = frozenset(
    {
        "list_dashboards",
        "get_pivony_metrics",
        "get_root_causes",
        "get_trends",
        "get_topic_trends",
        "list_reviews",
        "request_plan_upgrade",
    }
)

ADVISOR_PRO_ONLY_TOOLS = frozenset(
    {
        "search_reviews",
        "analyze_root_cause_live",
        "get_pivots",
        "list_kpi_teams",
        "list_kpi_cards",
        "get_kpi_metric_list",
        "create_kpi_view_metric",
    }
)

ADVISOR_PRO_TOOLS = ADVISOR_BASIC_TOOLS | ADVISOR_PRO_ONLY_TOOLS


def is_pro_mode(advisor_mode: str | None) -> bool:
    return (advisor_mode or "").strip() == ADVISOR_MODE_PRO


def allowed_tools(advisor_mode: str | None) -> frozenset[str]:
    return ADVISOR_PRO_TOOLS if is_pro_mode(advisor_mode) else ADVISOR_BASIC_TOOLS


def tier_label(advisor_mode: str | None) -> str:
    return "Advisor Pro" if is_pro_mode(advisor_mode) else "Advisor Basic"
