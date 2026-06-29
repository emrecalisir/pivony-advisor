"""Normalize advisor metrics API payloads for safe LLM consumption."""

from __future__ import annotations

from typing import Any


def normalize_metrics_response(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Clarify when NPS=0 means 'no data' vs a real score."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    nps = out.get("nps")
    try:
        review_count = int(out.get("review_count") or 0)
    except (TypeError, ValueError):
        review_count = 0
    dash_count = out.get("dashboard_count")
    try:
        dash_count_i = int(dash_count) if dash_count is not None else 1
    except (TypeError, ValueError):
        dash_count_i = 1

    if out.get("nps_status"):
        return out

    if out.get("dashboard_id") is None and dash_count_i != 1:
        out["nps"] = None
        out["nps_status"] = "requires_single_dashboard"
        out["nps_available"] = False
        out["nps_guidance"] = (
            "NPS yalnızca tek bir dashboard seçildiğinde hesaplanır. "
            "Kullanıcıdan dashboard seçmesini isteyin; org-wide özet için NPS vermeyin."
        )
    elif nps is not None and nps == 0 and review_count == 0:
        out["nps"] = None
        out["nps_status"] = "no_reviews_in_period"
        out["nps_available"] = False
        out["nps_guidance"] = (
            "Seçilen dönemde NPS hesaplanacak yorum yok. 0 puan olarak raporlama; "
            "dönemi genişletmeyi veya dashboard seçimini doğrulamayı öner."
        )
    elif nps is None:
        out["nps_status"] = "unavailable"
        out["nps_available"] = False
    else:
        out["nps_status"] = "ok"
        out["nps_available"] = True
    return out
