"""On-the-fly analytics composed from existing read-only worker endpoints."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Optional

from core.config import (
    ADVISOR_COMPARE_MAX_PIVOTS,
    ADVISOR_COMPARE_MAX_WORKERS,
)
from core.pivony_platform import fetch_pivots, fetch_trends

logger = logging.getLogger(__name__)


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _fmt_day(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def comparison_windows(
    *,
    days: int | None = None,
    since: str | None = None,
    until: str | None = None,
) -> tuple[str, str, str, str]:
    """Return (current_since, current_until, previous_since, previous_until)."""
    end = _parse_day(until)
    start = _parse_day(since)
    if start and end:
        span_days = max(1, (end - start).days + 1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span_days - 1)
        return _fmt_day(start), _fmt_day(end), _fmt_day(prev_start), _fmt_day(prev_end)

    window = max(1, int(days or 30))
    end = date.today()
    start = end - timedelta(days=window - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=window - 1)
    return _fmt_day(start), _fmt_day(end), _fmt_day(prev_start), _fmt_day(prev_end)


def _rating_for_scope(
    user_id: str,
    dashboard_id: int,
    pivot_key: str,
    pivot_value: str,
    since: str,
    until: str,
) -> float | None:
    data = fetch_trends(
        user_id,
        dashboard_id=dashboard_id,
        pivot_key=pivot_key,
        pivot_value=pivot_value,
        since=since,
        until=until,
    )
    if not isinstance(data, dict):
        return None
    rating = data.get("avg_rating")
    if rating is None:
        return None
    try:
        return float(rating)
    except (TypeError, ValueError):
        return None


def _compare_one_value(
    user_id: str,
    dashboard_id: int,
    pivot_key: str,
    pivot_value: str,
    cur_since: str,
    cur_until: str,
    prev_since: str,
    prev_until: str,
) -> dict[str, Any] | None:
    current = _rating_for_scope(
        user_id, dashboard_id, pivot_key, pivot_value, cur_since, cur_until
    )
    previous = _rating_for_scope(
        user_id, dashboard_id, pivot_key, pivot_value, prev_since, prev_until
    )
    if current is None or previous is None:
        return None
    return {
        "pivot_value": pivot_value,
        "current_rating": round(current, 3),
        "previous_rating": round(previous, 3),
        "change": round(current - previous, 3),
        "current_reviews": None,
        "previous_reviews": None,
    }


def compare_pivot_ratings(
    user_id: str,
    dashboard_id: int,
    pivot_key: str,
    *,
    days: int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Rank pivot values (e.g. hotels) by avg_rating change between two equal windows.

    Composes parallel get_trends calls — no dedicated dashboard widget API.
    """
    key = (pivot_key or "").strip()
    if not key:
        return {"error": "pivot_key is required (from get_dashboard_pivots)."}

    pivots_data = fetch_pivots(user_id, dashboard_id)
    if not isinstance(pivots_data, dict):
        return {"error": "Pivot servisi şu anda kullanılamıyor."}

    raw_values = (pivots_data.get("pivots") or {}).get(key)
    if not isinstance(raw_values, list) or not raw_values:
        return {
            "error": f"pivot_key '{key}' not found or empty on this dashboard.",
            "available_keys": list((pivots_data.get("pivots") or {}).keys()),
        }

    cap = min(max(1, int(limit or ADVISOR_COMPARE_MAX_PIVOTS)), ADVISOR_COMPARE_MAX_PIVOTS)
    values = [str(v) for v in raw_values[:cap]]

    cur_since, cur_until, prev_since, prev_until = comparison_windows(
        days=days, since=since, until=until
    )

    rankings: list[dict[str, Any]] = []
    workers = min(ADVISOR_COMPARE_MAX_WORKERS, max(1, len(values)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _compare_one_value,
                user_id,
                dashboard_id,
                key,
                val,
                cur_since,
                cur_until,
                prev_since,
                prev_until,
            ): val
            for val in values
        }
        for fut in as_completed(futures):
            try:
                row = fut.result()
            except Exception as exc:
                logger.warning("compare_pivot_ratings row failed: %s", exc)
                continue
            if row:
                rankings.append(row)

    rankings.sort(key=lambda r: r["change"])
    biggest_drop = rankings[0] if rankings else None
    biggest_gain = rankings[-1] if rankings else None

    return {
        "dashboard_id": dashboard_id,
        "pivot_key": key,
        "period_current": f"{cur_since} → {cur_until}",
        "period_previous": f"{prev_since} → {prev_until}",
        "compared_count": len(rankings),
        "rankings_by_change": rankings,
        "biggest_rating_drop": biggest_drop,
        "biggest_rating_gain": biggest_gain,
    }
