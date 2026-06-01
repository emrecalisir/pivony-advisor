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
    except requests.exceptions.RequestException as exc:
        logger.error("pivony platform request failed (%s): %s", url, exc)
        return None
    if resp.status_code != 200:
        logger.error(
            "pivony platform HTTP %s (%s): %s",
            resp.status_code, url, (resp.text or "")[:300],
        )
        return None
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
    return _post_worker(PIVONY_API_METRICS_URL, payload)


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
