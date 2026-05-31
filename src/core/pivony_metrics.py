"""Faz 3: real freemium-Advisor metrics from pivony-api.

Calls the pivony-api worker endpoint (advisor-metrics) which aggregates the
organization's existing analysis outputs (avg rating, sentiment, top root
causes). This is what grounds the freemium Advisor tier — no raw-review access.
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


def fetch_pivony_metrics(
    user_id: Optional[str],
    vendor_name: Optional[str] = None,
    days: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """
    Fetch aggregate CX metrics for a user's organization from pivony-api.

    Returns the parsed JSON dict (vendorName, avg_rating, sentiment_score,
    top_root_causes, period, dashboard_count) or None on misconfiguration,
    network/HTTP error, or invalid response.
    """
    if not PIVONY_API_METRICS_URL or not PIVONY_API_WORKER_SECRET:
        logger.warning(
            "pivony metrics not configured (PIVONY_API_METRICS_URL / "
            "PIVONY_API_WORKER_SECRET missing)"
        )
        return None
    if not user_id:
        logger.warning("pivony metrics requested without user_id")
        return None

    payload: dict[str, Any] = {
        "user_id": user_id,
        "days": days or PIVONY_METRICS_DEFAULT_DAYS,
    }
    if vendor_name and str(vendor_name).strip():
        payload["vendor_name"] = str(vendor_name).strip()

    try:
        resp = requests.post(
            PIVONY_API_METRICS_URL,
            json=payload,
            headers={
                "X-Welcome-Worker-Key": PIVONY_API_WORKER_SECRET,
                "Content-Type": "application/json",
            },
            timeout=PIVONY_API_TIMEOUT_SEC,
        )
    except requests.exceptions.RequestException as exc:
        logger.error("pivony metrics request failed: %s", exc)
        return None

    if resp.status_code != 200:
        logger.error(
            "pivony metrics HTTP %s: %s", resp.status_code, (resp.text or "")[:300]
        )
        return None

    try:
        return resp.json()
    except ValueError:
        logger.warning("pivony metrics returned non-JSON response")
        return None
