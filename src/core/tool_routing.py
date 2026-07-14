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


def invalid_dashboard_scope_message(state: HardAgentState) -> str | None:
    """User-facing hint when scope is locked but dashboard id is invalid or missing."""
    if state.dashboard_id is not None and state.dashboard_id <= 0:
        return (
            "Geçersiz bir dashboard seçimi algılandı (dashboard_id=0). "
            "Lütfen listeden geçerli bir dashboard seçin veya mevcut "
            "dashboard'ların listesini isteyin."
        )
    if state.dashboard_locked and not state.has_dashboard and not state.org_wide:
        return (
            "Dashboard kapsamı geçersiz veya eksik. "
            "Lütfen geçerli bir dashboard seçin veya dashboard listesini isteyin."
        )
    return None


def should_expose_list_dashboards(state: HardAgentState) -> bool:
    """Hide list_dashboards when scope already pins a dashboard or org-wide mode."""
    if invalid_dashboard_scope_message(state) is not None:
        return True
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
        out.pop("org_wide", None)
    elif state.org_wide:
        out.pop("dashboard_id", None)
        if tool_name == METRICS:
            out["org_wide"] = True
        else:
            out.pop("org_wide", None)
    else:
        out.pop("dashboard_id", None)
        # org_wide is only valid for get_pivony_metrics; strip it from other
        # dashboard tools so validation does not fail with a misleading mix.
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
            detail = str(exc)
            user_message = (
                "Maalesef, talebinizdeki bazı parametreleri anlayamadım. "
                "Lütfen isteğinizi farklı bir şekilde ifade etmeyi veya detayları netleştirmeyi deneyin."
            )
            if "dashboard_id" in detail and "Field required" in detail:
                if state is not None and state.has_dashboard:
                    user_message = (
                        f"Dashboard kapsamı (id={state.dashboard_id}) sunucu tarafından "
                        "ayarlandı ancak araç çağrısı doğrulanamadı. Lütfen tekrar deneyin."
                    )
                elif "org_wide" in str(args or {}):
                    user_message = (
                        "Bu araç tek bir dashboard gerektirir; org_wide yalnızca "
                        "get_pivony_metrics için geçerlidir. Dashboard seçimini doğrulayın "
                        "veya list_dashboards ile tekrar seçin."
                    )
                else:
                    user_message = (
                        "Bu işlem için bir dashboard seçilmesi gerekiyor. "
                        "Lütfen önce bir dashboard seçin veya dashboard listesini isteyin."
                    )
            return json.dumps(
                {
                    "error": "invalid_tool_arguments",
                    "tool": tool.name,
                    "detail": detail,
                    "user_message": user_message,
                    "instruction": (
                        "Fix arguments and retry the tool once. The `user_message` field "
                        "contains a user-friendly version of the error. Do NOT tell the user "
                        "that data is missing when this error indicates a parameter or scope "
                        "problem — explain the technical issue and suggest retrying or "
                        "selecting a dashboard / wider date range."
                    ),
                },
                ensure_ascii=False,
            )
    try:
        return tool.invoke(args)
    except Exception as exc:
        logger.error("Tool %s invocation failed: %s", tool.name, exc, exc_info=True)
        detail_str = str(exc).lower()
        user_facing_error = "Yanıt oluşturulurken bir hata oluştu. Lütfen tekrar deneyin."

        if "no data" in detail_str or "veri bulunamadı" in detail_str or "insufficient data" in detail_str or "yeterli veri bulunamadı" in detail_str:
            user_facing_error = f"Maalesef, '{tool.name}' aracı için istenen dönemde veya kapsamda veri bulunamadı. Lütfen farklı bir dönem veya dashboard seçmeyi deneyin."
        elif "timeout" in detail_str or "connection refused" in detail_str or "connection reset" in detail_str or "service unavailable" in detail_str:
            user_facing_error = "Maalesef, sistemlerimize erişirken geçici bir sorun oluştu. Lütfen kısa bir süre sonra tekrar deneyin."
        elif "permission denied" in detail_str or "unauthorized" in detail_str:
            user_facing_error = "Bu işlemi gerçekleştirmek için yetkiniz bulunmamaktadır. Lütfen yöneticinizle iletişime geçin."
        elif (
            "doesn't exist" in detail_str
            or "does not exist" in detail_str
            or ("collection" in detail_str and "not found" in detail_str)
        ):
            user_facing_error = (
                "Seçilen dashboard için veri koleksiyonu bulunamadı veya geçersiz bir "
                "dashboard kullanılıyor olabilir (ör. dashboard_id=0). Lütfen geçerli bir "
                "dashboard seçin veya list_dashboards ile mevcut dashboard'ları görüntüleyin."
            )
        elif "dashboard_not_accessible" in detail_str or "dashboard'a erişilemiyor" in detail_str:
            user_facing_error = (
                "Seçtiğiniz veya belirtilen dashboard'a erişim yetkiniz bulunmamaktadır "
                "veya böyle bir dashboard mevcut değildir. Lütfen başka bir dashboard "
                "seçmeyi deneyin veya erişim yetkilerinizi kontrol edin."
            )
        elif "invalid argument" in detail_str or "geçersiz argüman" in detail_str or "invalid dashboard id" in detail_str:
            user_facing_error = (
                "Araç çağrısı sırasında geçersiz bir argüman tespit edildi (örn. geçersiz dashboard ID'si). "
                "Lütfen girdiğiniz bilgileri kontrol edin veya farklı bir sorgu deneyin."
            )


        return json.dumps(
            {
                "error": "tool_execution_failed",
                "tool": tool.name,
                "detail": str(exc),
                "user_message": user_facing_error,
                "instruction": (
                    "The tool encountered an error during execution. Analyze the "
                    "'detail' to understand the cause and retry with corrected "
                    "parameters if applicable, or inform the user about the issue. "
                    "Do NOT endlessly retry the same failed call. "
                    "The `user_message` field contains a user-friendly version of the error."
                ),
            },
            ensure_ascii=False,
        )


def tool_result_indicates_failure(result: str) -> bool:
    """True when a tool returned a structured error payload."""
    if not result:
        return False
    try:
        payload = json.loads(result)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("error")) or bool(payload.get("skipped"))


def repeated_tool_failure_result(tool_name: str, prior_failures: set[str]) -> str | None:
    """Block a second attempt at the same tool after a system-level failure this turn."""
    if tool_name not in prior_failures:
        return None
    return json.dumps(
        {
            "skipped": True,
            "tool": tool_name,
            "error": "tool_already_failed",
            "user_message": (
                f"'{tool_name}' aracı bu turda zaten başarısız oldu. "
                "Aynı aracı tekrar çağırmayın; kullanıcıya hatayı açıklayın veya "
                "farklı bir yaklaşım önerin."
            ),
            "instruction": (
                "Do NOT call this tool again in this turn. Explain the prior failure "
                "to the user and suggest contacting support if the issue persists."
            ),
        },
        ensure_ascii=False,
    )


def blocked_tool_result(tool_name: str, state: HardAgentState) -> str | None:
    """Return a synthetic tool result when a call is blocked by routing rules."""
    if tool_name not in _DASHBOARD_LISTING_TOOLS:
        return None
    if should_expose_list_dashboards(state):
        return None
    user_message = (
        f"Dashboard kapsamı zaten id={state.dashboard_id} ile kilitli. "
        "Analiz araçlarını bu dashboard ile kullanın."
    )
    return json.dumps(
        {
            "skipped": True,
            "tool": tool_name,
            "dashboard_id": state.dashboard_id,
            "user_message": user_message,
            "instruction": (
                f"Dashboard scope is already locked to id={state.dashboard_id}. "
                "Do not call list_dashboards. Use get_pivony_metrics and other analysis tools."
            ),
        },
        ensure_ascii=False,
    )
