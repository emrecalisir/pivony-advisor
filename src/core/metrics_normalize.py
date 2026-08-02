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

    # Pipeline NPS disabled → search often returns sentinel 0; never treat as a score.
    if out.get("nps_enabled") is False:
        out["nps"] = None
        out["nps_status"] = "unavailable"
        out["nps_available"] = False
        out["nps_guidance"] = (
            "Bu dashboard için NPS yapılandırılmamış. NPS'i 0 olarak raporlama. "
            "avg_rating varsa memnuniyet puanı olarak onu kullan; "
            "positive_sentiment_score rating / NPS değildir."
        )
    elif out.get("nps_status") is None:
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


def _topic_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("topics", "topic_intent", "topic_sentiment"):
        rows = data.get(key)
        if isinstance(rows, list) and rows:
            return [r for r in rows if isinstance(r, dict)]
    return []


def normalize_topic_intent_response(
    data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Flag empty complaint-intent topics and guide fallback via reviews/metrics."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    rows = _topic_rows(out)
    if not rows:
        out["intent_status"] = "no_topics"
        out["intent_guidance"] = (
            "Konu bazında niyet verisi bulunamadı. list_reviews(sentiment='negative') "
            "ile örnek şikayet yorumlarını çekip temaları özetleyin; gerekirse "
            "get_pivony_metrics → complaint_topics veya daha geniş bir dönem deneyin."
        )
        return out

    complaint_topics = [
        r
        for r in rows
        if float(r.get("complaint_pct") or 0) > 0
        or float((r.get("intent_pcts") or {}).get("complaint") or 0) > 0
    ]
    if not complaint_topics:
        out["intent_status"] = "no_complaint_intent_topics"
        out["intent_guidance"] = (
            "Yapılandırılmış veride şikayet niyeti olan konu bulunamadı; bu, intent "
            "sınıflandırmasının eksik/yanlış olabileceğini gösterir. list_reviews "
            "(sentiment='negative') ile gerçek şikayet örneklerini gösterin ve "
            "get_pivony_metrics → complaint_topics ile çapraz kontrol edin. "
            "Örnek yorumlarda açık şikayet varsa bunu kullanıcıya belirtin."
        )
    else:
        out["intent_status"] = "ok"
    return out


def normalize_topic_sentiment_response(
    data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Highlight per-topic 100% Mixed sentiment that likely masks negativity."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    rows = _topic_rows(out)
    suspicious: list[str] = []
    for row in rows:
        name = str(row.get("topic") or row.get("name") or row.get("topic_id") or "")
        pos = float(row.get("positive_pct") or 0)
        neu = float(row.get("neutral_pct") or 0)
        neg = float(row.get("negative_pct") or 0)
        mixed = float(row.get("mixed_pct") or 0)
        if (mixed == 100.0 or mixed == 100) and pos == 0.0 and neu == 0.0 and neg == 0.0:
            suspicious.append(name or "unknown")
    if suspicious:
        out["sentiment_status"] = "suspiciously_100_percent_mixed_topics"
        out["sentiment_guidance"] = (
            f"Şu konularda tüm yorumlar %100 Karışık görünüyor: {', '.join(suspicious)}. "
            "Bu, negatif yorumların Karışık olarak etiketlendiğini gösterebilir. "
            "list_reviews(sentiment='negative') ile örnekleri gösterip tutarsızlığı "
            "kullanıcıya açıkça belirtin."
        )
    else:
        out["sentiment_status"] = "ok"
    return out


def normalize_root_causes_response(
    data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Guide in-chat synthesis when stored root-cause analysis is missing."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    status = str(out.get("status") or "").strip().lower()
    if status == "not_generated":
        out["synthesis_guidance"] = (
            "Kök neden analizi henüz oluşturulmamış. Kullanıcıya DashboardData → "
            "'Generate AI Insights' ile oluşturabileceğini söyleyin; ayrıca "
            "get_pivony_metrics (complaint_topics) ve list_reviews(sentiment='negative') "
            "ile mevcut veriden nitel kök neden özeti sunun — sohbeti dış sayfaya "
            "yönlendirmeden kalın."
        )
    elif status == "none_for_topic":
        out["synthesis_guidance"] = (
            "Bu konu için kayıtlı kök neden yok. list_reviews ve complaint_topics "
            "üzerinden nitel özet sunmayı deneyin."
        )
    return out


def normalize_key_drivers_response(
    data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Guide synthesis from topic metrics when KDA is not configured."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    status = str(out.get("status") or "").strip().lower()
    if status in ("no_config", "unavailable", "not_configured"):
        out["synthesis_guidance"] = (
            "Ana Etkenler Analizi yapılandırılmamış. get_topic_sentiment, "
            "get_topic_participation ve get_pivony_metrics ile konu bazında "
            "performansı özetleyerek sohbet içinde alternatif içgörü sunun; "
            "yalnızca DashboardData sayfasına yönlendirmeyin."
        )
    return out
