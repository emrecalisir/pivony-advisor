"""Advisor → pivony-api worker client (read-only platform capabilities).

Exposes the few platform endpoints the agent drives during a guided drill-down:
  - fetch_dashboards : which dashboards the org can see
  - fetch_pivots     : pivot keys + top values for one dashboard
  - fetch_metrics    : aggregate CX metrics (avg_rating, top_root_causes)

Sibling worker URLs are derived from PIVONY_API_METRICS_URL
(".../worker/advisor-metrics") so no extra env var is needed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from core.config import (
    PIVONY_API_METRICS_URL,
    PIVONY_API_TIMEOUT_SEC,
    PIVONY_API_WORKER_SECRET,
    PIVONY_METRICS_DEFAULT_DAYS,
)

logger = logging.getLogger(__name__)

# Returned (instead of None) when a worker call exceeds PIVONY_API_TIMEOUT_SEC.
# It carries a user-facing instruction so the agent asks the user to narrow the
# scope (shorter date range / single dashboard) rather than emitting a generic
# "service unavailable" dead-end. Tools json.dumps() this straight to the LLM.
WORKER_TIMEOUT_RESULT: dict[str, Any] = {
    "error": "timeout",
    "message": (
        "Bu sorgu seçili kapsam için zaman aşımına uğradı. Daha kısa bir tarih "
        "aralığı (ör. son 7 veya 30 gün) ya da tek bir dashboard seçerseniz "
        "hemen yanıtlayabilirim."
    ),
    "advisor_action": "ask_user_to_narrow_scope",
}


def _worker_base() -> Optional[str]:
    """'.../worker' base derived from the configured advisor-metrics URL."""
    if not PIVONY_API_METRICS_URL:
        return None
    return PIVONY_API_METRICS_URL.rsplit("/", 1)[0]


def _post_worker(url: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """POST to a pivony-api worker endpoint with the shared secret. Returns the
    parsed JSON dict, or None on misconfiguration / network / HTTP / parse error."""
    if not url or not PIVONY_API_WORKER_SECRET:
        logger.warning(
            "pivony platform not configured (PIVONY_API_METRICS_URL / "
            "PIVONY_API_WORKER_SECRET missing)"
        )
        return None
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={
                "X-Welcome-Worker-Key": PIVONY_API_WORKER_SECRET,
                "Content-Type": "application/json",
            },
            timeout=PIVONY_API_TIMEOUT_SEC,
        )
    except requests.exceptions.Timeout:
        logger.warning(
            "pivony platform request timed out (%s) after %ss",
            url, PIVONY_API_TIMEOUT_SEC,
        )
        return dict(WORKER_TIMEOUT_RESULT)
    except requests.exceptions.RequestException as exc:
        logger.error("pivony platform request failed (%s): %s", url, exc)
        return None
    if resp.status_code != 200:
        logger.error(
            "pivony platform HTTP %s (%s): %s",
            resp.status_code, url, (resp.text or "")[:300],
        )
        try:
            err = resp.json()
            if isinstance(err, dict):
                err.setdefault("error", "worker_http_error")
                err["http_status"] = resp.status_code
                return err
        except ValueError:
            pass
        return {
            "error": "worker_http_error",
            "http_status": resp.status_code,
            "message": (resp.text or "")[:300],
        }
    try:
        data = resp.json()
    except ValueError:
        logger.warning("pivony platform returned non-JSON response (%s)", url)
        return None
    return data if isinstance(data, dict) else None


def fetch_dashboards(user_id: Optional[str]) -> Optional[dict[str, Any]]:
    """List dashboards visible to the user's org: {dashboards:[{id,name}], count}."""
    if not user_id:
        logger.warning("fetch_dashboards called without user_id")
        return None
    return _post_worker(f"{_worker_base()}/advisor/dashboards", {"user_id": user_id})


def fetch_pivots(
    user_id: Optional[str], dashboard_id: int
) -> Optional[dict[str, Any]]:
    """Pivot keys + top values for one dashboard: {dashboard_id, pivots:{key:[...]}}."""
    if not user_id:
        logger.warning("fetch_pivots called without user_id")
        return None
    return _post_worker(
        f"{_worker_base()}/advisor/pivots",
        {"user_id": user_id, "dashboard_id": dashboard_id},
    )


def fetch_metrics(
    user_id: Optional[str],
    dashboard_id: Optional[int] = None,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Aggregate CX metrics (avg_rating, top_root_causes, period) scoped to a
    dashboard and/or pivot. Returns the parsed dict or None on failure."""
    if not user_id:
        logger.warning("fetch_metrics called without user_id")
        return None
    payload: dict[str, Any] = {
        "user_id": user_id,
        "days": days or PIVONY_METRICS_DEFAULT_DAYS,
    }
    if dashboard_id is not None:
        payload["dashboard_id"] = dashboard_id
    if pivot_key and str(pivot_key).strip():
        payload["pivot_key"] = str(pivot_key).strip()
    if pivot_value and str(pivot_value).strip():
        payload["pivot_value"] = str(pivot_value).strip()
    if since and str(since).strip():
        payload["since"] = str(since).strip()
    if until and str(until).strip():
        payload["until"] = str(until).strip()
    return _post_worker(PIVONY_API_METRICS_URL, payload)


from core.metrics_normalize import normalize_metrics_response


def fetch_root_causes(
    user_id: Optional[str],
    dashboard_id: int,
    topic: Optional[str] = None,
    topic_id: Optional[int] = None,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Root causes for a dashboard/topic. Returns {status, root_causes, ...} where
    status is ok | none_for_topic | not_generated, or None on failure."""
    if not user_id:
        logger.warning("fetch_root_causes called without user_id")
        return None
    payload: dict[str, Any] = {"user_id": user_id, "dashboard_id": dashboard_id}
    if topic and str(topic).strip():
        payload["topic"] = str(topic).strip()
    if topic_id is not None:
        payload["topic_id"] = topic_id
    if pivot_key and str(pivot_key).strip():
        payload["pivot_key"] = str(pivot_key).strip()
    if pivot_value and str(pivot_value).strip():
        payload["pivot_value"] = str(pivot_value).strip()
    return _post_worker(f"{_worker_base()}/advisor/root-causes", payload)


def fetch_reviews(
    user_id: Optional[str],
    dashboard_id: int,
    topic_id: Optional[int] = None,
    sentiment: Optional[str] = None,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """List example reviews (text) for a dashboard scoped by topic/sentiment/pivot.
    Returns {dashboard_id, reviews:[{text,rating,vendor,date}], count} or None."""
    if not user_id:
        logger.warning("fetch_reviews called without user_id")
        return None
    payload: dict[str, Any] = {"user_id": user_id, "dashboard_id": dashboard_id}
    if topic_id is not None:
        payload["topic_id"] = topic_id
    if sentiment and str(sentiment).strip():
        payload["sentiment"] = str(sentiment).strip().lower()
    if pivot_key and str(pivot_key).strip():
        payload["pivot_key"] = str(pivot_key).strip()
    if pivot_value and str(pivot_value).strip():
        payload["pivot_value"] = str(pivot_value).strip()
    if since and str(since).strip():
        payload["since"] = str(since).strip()
    if until and str(until).strip():
        payload["until"] = str(until).strip()
    if days:
        payload["days"] = days
    if limit:
        payload["limit"] = limit
    return _post_worker(f"{_worker_base()}/advisor/reviews", payload)


def request_plan_upgrade(
    user_id: Optional[str], message: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Record + email an Industry-Expert plan-upgrade request. Returns
    {ok, emailed} or None on failure."""
    if not user_id:
        logger.warning("request_plan_upgrade called without user_id")
        return None
    payload: dict[str, Any] = {"user_id": user_id}
    if message and str(message).strip():
        payload["message"] = str(message).strip()
    return _post_worker(f"{_worker_base()}/advisor/plan-request", payload)


def _scoped_payload(
    user_id: Optional[str],
    dashboard_id: int,
    pivot_key: Optional[str],
    pivot_value: Optional[str],
    days: Optional[int],
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict[str, Any]:
    """Common worker payload for dashboard-scoped read-only capabilities."""
    payload: dict[str, Any] = {"user_id": user_id, "dashboard_id": dashboard_id}
    if pivot_key and str(pivot_key).strip():
        payload["pivot_key"] = str(pivot_key).strip()
    if pivot_value and str(pivot_value).strip():
        payload["pivot_value"] = str(pivot_value).strip()
    # Explicit since/until (e.g. the dashboard's exact page range) takes precedence
    # over a relative `days` window when both are present.
    if since and str(since).strip():
        payload["since"] = str(since).strip()
    if until and str(until).strip():
        payload["until"] = str(until).strip()
    if days:
        payload["days"] = days
    return payload


def fetch_trends(
    user_id: Optional[str],
    dashboard_id: int,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Overall KPI time-series (volume/sentiment daily + avg_rating, avg_sentiment,
    NPS) for a dashboard. Answers trend / 'neden düşüyor' questions."""
    if not user_id:
        logger.warning("fetch_trends called without user_id")
        return None
    payload = _scoped_payload(
        user_id, dashboard_id, pivot_key, pivot_value, days, since=since, until=until
    )
    return _post_worker(f"{_worker_base()}/advisor/trends", payload)


def fetch_topic_trends(
    user_id: Optional[str],
    dashboard_id: int,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Rising / falling topics vs the preceding window of equal length."""
    if not user_id:
        logger.warning("fetch_topic_trends called without user_id")
        return None
    payload = _scoped_payload(
        user_id, dashboard_id, pivot_key, pivot_value, days, since=since, until=until
    )
    return _post_worker(f"{_worker_base()}/advisor/topic-trends", payload)


def fetch_hotterms(
    user_id: Optional[str],
    dashboard_id: int,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Trending keywords / phrases (1-4 grams) for a dashboard."""
    if not user_id:
        logger.warning("fetch_hotterms called without user_id")
        return None
    payload = _scoped_payload(
        user_id, dashboard_id, pivot_key, pivot_value, days, since=since, until=until
    )
    if limit:
        payload["limit"] = limit
    return _post_worker(f"{_worker_base()}/advisor/hotterms", payload)


def fetch_decisions(
    user_id: Optional[str],
    dashboard_id: int,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Decision distribution (publish / opencase / takeaction true-false counts)."""
    if not user_id:
        logger.warning("fetch_decisions called without user_id")
        return None
    payload = _scoped_payload(
        user_id, dashboard_id, pivot_key, pivot_value, days, since=since, until=until
    )
    return _post_worker(f"{_worker_base()}/advisor/decisions", payload)


def fetch_distribution(
    user_id: Optional[str],
    dashboard_id: int,
    kind: str = "sentiment",
    pivot_column: Optional[str] = None,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Distribution breakdown: kind in {sentiment, intent, platform, pivot}.
    For kind='pivot', pivot_column names the Pivot Analysis column (e.g.
    'hasChild', 'channel'); omit it to discover the available columns."""
    if not user_id:
        logger.warning("fetch_distribution called without user_id")
        return None
    payload = _scoped_payload(
        user_id, dashboard_id, pivot_key, pivot_value, days, since=since, until=until
    )
    payload["kind"] = (kind or "sentiment").strip().lower()
    if pivot_column and str(pivot_column).strip():
        payload["pivot_column"] = str(pivot_column).strip()
    return _post_worker(f"{_worker_base()}/advisor/distribution", payload)


def fetch_topic_ratings(
    user_id: Optional[str],
    dashboard_id: int,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Average rating per topic (which topics score highest / lowest)."""
    if not user_id:
        logger.warning("fetch_topic_ratings called without user_id")
        return None
    payload = _scoped_payload(
        user_id, dashboard_id, pivot_key, pivot_value, days, since=since, until=until
    )
    return _post_worker(f"{_worker_base()}/advisor/topic-ratings", payload)


def fetch_emergent_topics(
    user_id: Optional[str],
    dashboard_id: int,
    pivot_key: Optional[str] = None,
    pivot_value: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Emergent / newly surfacing topics for a dashboard."""
    if not user_id:
        logger.warning("fetch_emergent_topics called without user_id")
        return None
    payload = _scoped_payload(
        user_id, dashboard_id, pivot_key, pivot_value, days, since=since, until=until
    )
    return _post_worker(f"{_worker_base()}/advisor/emergent-topics", payload)
