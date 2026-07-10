"""Normalize advisor metrics API payloads for safe LLM consumption."""

from __future__ import annotations

from typing import Any


def _sentiment_pct(data: dict[str, Any], field: str) -> Any:
    sentiment = data.get("sentiment")
    if isinstance(sentiment, dict):
        return sentiment.get(field)
    return None


def normalize_metrics_response(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Clarify when NPS=0 means 'no data' vs a real score, and flag sentiment anomalies."""
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

    if out.get("nps_status") is None:
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

    positive_pct = _sentiment_pct(out, "positive_pct")
    neutral_pct = _sentiment_pct(out, "neutral_pct")
    negative_pct = _sentiment_pct(out, "negative_pct")
    mixed_pct = _sentiment_pct(out, "mixed_pct")

    if (mixed_pct == 100.0 or mixed_pct == 100) and (
        positive_pct == 0.0 and neutral_pct == 0.0 and negative_pct == 0.0
    ):
        out["sentiment_status"] = "suspiciously_100_percent_mixed"
        out["sentiment_guidance"] = (
            "Tüm yorumların sentiment'ı %100 Karışık olarak raporlanmıştır. "
            "Bu durum, duygu analizi modelinin bazı yorumları doğru "
            "sınıflandıramadığı veya varsayılan olarak 'Karışık' atadığı "
            "durumlarda ortaya çıkabilir. Lütfen bu sentiment skorunu ve "
            "örnek yorumları dikkatle değerlendirin."
        )
    elif mixed_pct is not None and (
        positive_pct is None or neutral_pct is None or negative_pct is None
    ):
        out["sentiment_status"] = "partial_sentiment_data"
        out["sentiment_guidance"] = (
            "Sentiment verilerinde eksiklikler bulunmaktadır. "
            "Pozitif, Nötr veya Negatif yüzdeler eksik olduğu için "
            "tam bir duygu analizi yapılamayabilir."
        )
    else:
        out["sentiment_status"] = "ok"

    return out
