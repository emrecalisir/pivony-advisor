"""Resolve pivot_key / pivot_value aliases and fuzzy hotel/vendor names."""

from __future__ import annotations

import json
import re
from typing import Any

from core.pivony_platform import fetch_pivots

# Common LLM aliases → dashboard pivot column names (camelCase in ETS data).
PIVOT_KEY_ALIASES: dict[str, str] = {
    "vendor_name": "vendorName",
    "vendorname": "vendorName",
    "hotel_name": "vendorName",
    "hotelname": "vendorName",
    "hotel": "vendorName",
    "otel": "vendorName",
    "vendor": "vendorName",
}

TOOLS_WITH_PIVOT_SCOPE = frozenset(
    {
        "get_pivony_metrics",
        "list_reviews",
        "get_root_causes",
        "get_trends",
        "get_topic_trends",
        "get_hotterms",
        "get_decision_distribution",
        "compare_pivot_ratings",
        "get_distribution",
        "get_topic_intent_distribution",
        "get_topic_sentiment",
        "get_topic_participation",
        "get_topic_sentiment_daily",
        "get_topic_participation_daily",
        "get_topic_trends_view",
        "get_review_statistics",
        "get_topic_ratings",
        "get_key_drivers",
        "get_digital_experience_score",
        "get_emergent_topics",
    }
)


def _compact_key(key: str) -> str:
    return re.sub(r"[\s_.-]+", "", key.strip().lower())


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_pivot_key(
    key: str | None,
    available_keys: list[str] | None = None,
) -> str | None:
    if not key or not str(key).strip():
        return None
    k = str(key).strip()
    alias = PIVOT_KEY_ALIASES.get(_compact_key(k))
    if alias:
        return alias
    if available_keys:
        ck = _compact_key(k)
        for ak in available_keys:
            if ak.lower() == k.lower() or _compact_key(ak) == ck:
                return ak
    return k


def resolve_pivot_scope(
    user_id: str | None,
    dashboard_id: int | None,
    pivot_key: str | None,
    pivot_value: str | None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Return canonical (pivot_key, pivot_value) using the pivots worker."""
    meta: dict[str, Any] = {}
    raw_key = pivot_key
    raw_value = pivot_value
    if not user_id or dashboard_id is None:
        return (
            normalize_pivot_key(raw_key),
            str(raw_value).strip() if raw_value else None,
            meta,
        )

    query = str(raw_value).strip() if raw_value and str(raw_value).strip() else None
    data = fetch_pivots(
        user_id,
        dashboard_id,
        query=query,
        pivot_key=normalize_pivot_key(raw_key),
    )
    if not isinstance(data, dict):
        return (
            normalize_pivot_key(raw_key),
            str(raw_value).strip() if raw_value else None,
            meta,
        )

    available = list((data.get("pivots") or {}).keys())
    resolved_key = normalize_pivot_key(raw_key, available)

    if query:
        matches = data.get("matches") or []
        if matches:
            best = matches[0]
            resolved_key = best.get("pivot_key") or resolved_key
            resolved_value = best.get("pivot_value") or query
            if resolved_key != raw_key or resolved_value != query:
                meta["pivot_resolved"] = {
                    "from": {"pivot_key": raw_key, "pivot_value": raw_value},
                    "to": {
                        "pivot_key": resolved_key,
                        "pivot_value": resolved_value,
                    },
                }
            return resolved_key, resolved_value, meta

        if resolved_key and resolved_key in (data.get("pivots") or {}):
            for top_val in data["pivots"][resolved_key]:
                if _norm_text(str(top_val)) == _norm_text(query):
                    return resolved_key, str(top_val), meta

    return resolved_key, query, meta


def apply_pivot_to_tool_args(
    tool_name: str,
    args: dict[str, Any],
    *,
    user_id: str | None,
    dashboard_id: int | None,
) -> dict[str, Any]:
    if tool_name not in TOOLS_WITH_PIVOT_SCOPE:
        return args
    pk = args.get("pivot_key")
    pv = args.get("pivot_value")
    if not pk and not pv:
        return args
    out = dict(args)
    resolved_key, resolved_value, meta = resolve_pivot_scope(
        user_id, dashboard_id, pk, pv
    )
    if resolved_key:
        out["pivot_key"] = resolved_key
    if resolved_value:
        out["pivot_value"] = resolved_value
    if meta.get("pivot_resolved"):
        out["_pivot_resolution"] = meta["pivot_resolved"]
    elif pk and not pv:
        out["pivot_key"] = normalize_pivot_key(str(pk))
    return out


_PIVOT_SCOPED_SEARCH = re.compile(
    r"(voyage|torba|bodrum|otel|hotel|vendor|marka|şube|branch|pivot)",
    re.IGNORECASE,
)
_TOPIC_OR_COMPLAINT = re.compile(
    r"(oda|room|f\s*&\s*b|fnb|temizlik|clean|şikayet|complaint|problem|kök|neden|root|topic|konu)",
    re.IGNORECASE,
)


def looks_like_pivot_scoped_search(query: str) -> bool:
    """True when semantic search should be blocked in favour of pivot tools."""
    if not query or len(query.strip()) < 4:
        return False
    q = query.strip()
    if re.search(r"pivot[_\s-]*(key|value)|vendor[_\s-]*name", q, re.I):
        return True
    return bool(_PIVOT_SCOPED_SEARCH.search(q) and _TOPIC_OR_COMPLAINT.search(q))


def semantic_search_pivot_redirect() -> str:
    return json.dumps(
        {
            "error": "use_pivot_tools",
            "instruction": (
                "Do NOT use search_qdrant_reviews for hotel/vendor + topic questions. "
                "Call get_dashboard_pivots(dashboard_id, query=<hotel name>) to resolve "
                "the pivot, then list_reviews or get_pivony_metrics or get_root_causes "
                "with pivot_key='vendorName' (or the key returned) and pivot_value=<exact name>."
            ),
        },
        ensure_ascii=False,
    )
