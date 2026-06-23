"""Capability guardrails for Advisor follow-up chips (suggested questions).

Every chip must be a DATA question answerable via the Advisor worker/MCP tools —
not UI how-to, integrations, or product navigation.
"""

from __future__ import annotations

import re

# Default starter chips — each maps to get_pivony_metrics / get_root_causes / get_trends.
DEFAULT_CHIP_QUESTIONS: tuple[str, ...] = (
    "Bu dönemde en çok şikayet edilen konular neler?",
    "Genel müşteri memnuniyeti (duyarlılık) ne durumda?",
    "Şikayetlerin temel nedenleri neler?",
)

# Shown to LLM prompts so generated chips stay inside worker API scope.
ADVISOR_CHIP_CAPABILITY_SUMMARY = """\
The Advisor answers ONLY dashboard analytics via these worker tools:
- Sentiment & Positive Sentiment Score (get_pivony_metrics, get_distribution sentiment)
- Review-level intent / channel / pivot / star-rating / fraud / praise-intent distributions (get_distribution)
- Per-topic complaint intent % (get_topic_intent_distribution — "topiclerin şikayet oranı")
- Per-topic sentiment, participation, average rating (get_topic_sentiment, get_topic_participation, get_topic_ratings)
- Per-topic daily sentiment & volume trends (get_topic_sentiment_daily, get_topic_participation_daily, get_topic_trends_view)
- Review Statistics hero + volume time series (get_review_statistics — metric 8)
- Top complaint topics, review counts, NPS, avg rating (get_pivony_metrics)
- Root causes + recommendations behind complaints (get_root_causes — metric 20 table)
- Time trends: volume, sentiment, ratings, NPS (get_trends)
- Rising/falling topics (get_topic_trends), hot terms (get_hotterms), emergent topics (get_emergent_topics)
- Decision counts publish/opencase/takeaction (get_decision_distribution)
- Key Drivers Analysis bubble (get_key_drivers), Digital Experience Score (get_digital_experience_score)
- Example review texts (list_reviews)
- Pivot hotel/branch ranking by rating change (compare_pivot_ratings — Industry-Expert tier)
NOT in scope: creating dashboards, Zendesk/CSV integrations, widgets, downloading/scheduling reports, Market Intelligence setup, competitor dashboards, console navigation."""

_OUT_OF_SCOPE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"nasıl\s+(oluştur|olustur|yapılır|yapilir|bağlan|baglan|ekler|ekley|ayarla|kurulur|kurar|indir|görüntüle|goruntule|alınır|alinir|görebilir|gorebilir)",
        r"nereden\s+(indir|görüntüle|goruntule|alın|alin|bulun)",
        r"nerede\s+(görüntüle|goruntule|bulun|ayarla)",
        r"\b(zendesk|csv|oauth|entegrasyon|integration|widget)\b",
        r"\b(my\s*workspace|console/|wizard|public\s+dashboard)\b",
        r"\b(market\s+intelligence|competitor|rakip\s+analiz|rakip\s+veri)\b",
        r"\b(rapor\s+indir|indirme|schedule\s+report|pdf\s+rapor)\b",
        r"\bdashboard\s+(oluştur|olustur|yarat|create)\b",
        r"\b(ayarlar|settings)\s*[>/]",
    )
)

_IN_SCOPE_HINTS: tuple[str, ...] = (
    "şikayet",
    "sikayet",
    "duyarlılık",
    "duyarlilik",
    "sentiment",
    "memnuniyet",
    "nps",
    "rating",
    "puan",
    "yorum",
    "kök neden",
    "kok neden",
    "root cause",
    "trend",
    "konu",
    "topic",
    "intent",
    "niyet",
    "kanal",
    "platform",
    "dağılım",
    "dagilim",
    "hot term",
    "anahtar kelime",
    "yüksel",
    "yuksel",
    "düş",
    "dus",
    "ortaya çık",
    "ortaya cik",
    "emergent",
    "aksiyon",
    "vaka",
    "takeaction",
    "katılım",
    "katilim",
    "temel etken",
    "key driver",
    "fraud",
    "yıldız",
    "yildiz",
    "örnek yorum",
    "ornek yorum",
    "şikayet oranı",
    "sikayet orani",
    "digital experience",
    "dijital deneyim",
    "otel",
    "hotel",
    "pivot",
    "kaç yorum",
    "kac yorum",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def is_out_of_scope_chip(text: str) -> bool:
    """True when a chip is UI/how-to or outside worker analytics APIs."""
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    norm = _normalize(cleaned)
    if any(p.search(norm) for p in _OUT_OF_SCOPE_PATTERNS):
        return True
    if any(hint in norm for hint in _IN_SCOPE_HINTS):
        return False
    # Questions without analytics hints that look like product help.
    if re.search(
        r"\b(nasıl|nasil|nereden|nerede|oluştur|olustur|indir|entegrasyon|integration)\b",
        norm,
    ):
        return True
    return False


def sanitize_chip_questions(
    items: list[str],
    *,
    user_question: str = "",
    limit: int = 3,
) -> list[str]:
    """Drop out-of-scope chips and backfill with capability-aligned defaults."""
    seen: set[str] = set()
    q_norm = _normalize(user_question)
    out: list[str] = []

    def _append(candidates: list[str]) -> None:
        for item in candidates:
            if len(out) >= limit:
                return
            cleaned = (item or "").strip()
            if not cleaned or is_out_of_scope_chip(cleaned):
                continue
            key = _normalize(cleaned)
            if key == q_norm or key in seen:
                continue
            seen.add(key)
            out.append(cleaned)

    _append(items)
    if len(out) < limit:
        _append(list(DEFAULT_CHIP_QUESTIONS))
    return out[:limit]
