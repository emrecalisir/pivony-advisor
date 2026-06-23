"""Contextual follow-up question suggestions after Advisor answers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.chip_capabilities import (
    DEFAULT_CHIP_QUESTIONS,
    sanitize_chip_questions,
)


@dataclass(frozen=True)
class _TopicRule:
    q_keywords: tuple[str, ...]
    followups: tuple[str, ...]
    a_keywords: tuple[str, ...] = ()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _score(text: str, keywords: tuple[str, ...]) -> int:
    if not text or not keywords:
        return 0
    return sum(1 for kw in keywords if kw in text)


def _dedupe(items: list[str], question: str, limit: int = 3) -> list[str]:
    seen: set[str] = set()
    q_norm = _normalize(question)
    out: list[str] = []
    for item in items:
        cleaned = (item or "").strip()
        if not cleaned:
            continue
        key = _normalize(cleaned)
        if key == q_norm or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


# Capability-aligned follow-ups: every suggestion is a DATA question the
# Advisor's analytics tools can actually answer about the user's own dashboard
# (no UI how-to / onboarding / integration prompts).
_TOPIC_RULES: tuple[_TopicRule, ...] = (
    _TopicRule(
        q_keywords=(
            "duyarlılık", "duyarlilik", "sentiment", "memnuniyet", "satisfaction",
            "pozitif", "positive", "negatif", "negative", "skor", "score",
        ),
        followups=(
            "Bu dönemde en çok şikayet edilen konular neler?",
            "NPS son dönemde nasıl bir trend izliyor?",
            "Şikayetlerin temel nedenleri neler?",
        ),
        a_keywords=("duyarlılık", "sentiment", "pozitif", "memnuniyet"),
    ),
    _TopicRule(
        q_keywords=(
            "şikayet", "sikayet", "complaint", "sorun", "problem", "şikâyet",
        ),
        followups=(
            "Bu şikayetlerin temel nedenleri (kök neden) neler?",
            "Bu konuyla ilgili birkaç örnek yorum gösterir misin?",
            "Şikayet konuları önceki döneme göre arttı mı, azaldı mı?",
        ),
        a_keywords=("şikayet", "complaint", "negatif"),
    ),
    _TopicRule(
        q_keywords=("kök neden", "kok neden", "root cause", "neden", "sebep"),
        followups=(
            "Bu konuda birkaç örnek yorum gösterir misin?",
            "Bu konu önceki döneme göre arttı mı?",
            "Genel duyarlılık dağılımı nasıl?",
        ),
        a_keywords=("kök neden", "root cause"),
    ),
    _TopicRule(
        q_keywords=("nps", "rating", "puan", "yıldız", "yildiz", "ortalama"),
        followups=(
            "NPS zaman içinde nasıl bir trend izliyor?",
            "Hangi konular en düşük puana sahip?",
            "Bu dönemde en çok şikayet edilen konular neler?",
        ),
        a_keywords=("nps", "rating", "puan"),
    ),
    _TopicRule(
        q_keywords=(
            "trend", "zaman", "artıyor", "artiyor", "azalıyor", "azaliyor",
            "değişti", "degisti", "yükseliyor", "yukseliyor", "düşüyor", "dusuyor",
        ),
        followups=(
            "Hangi konular yükseliyor, hangileri düşüyor?",
            "Yeni ortaya çıkan konular neler?",
            "Öne çıkan anahtar kelimeler (hot terms) neler?",
        ),
        a_keywords=("trend", "rising", "falling"),
    ),
    _TopicRule(
        q_keywords=(
            "kaç yorum", "kac yorum", "yorum sayısı", "yorum sayisi", "hacim",
            "volume", "konu", "topic",
        ),
        followups=(
            "Bu konuda birkaç örnek yorum gösterir misin?",
            "Bu konunun duyarlılık kırılımı nasıl?",
            "Bu konu önceki döneme göre nasıl değişti?",
        ),
        a_keywords=("topic", "konu", "yorum"),
    ),
    _TopicRule(
        q_keywords=("örnek yorum", "ornek yorum", "yorum göster", "review", "yazmışlar"),
        followups=(
            "Bu yorumların duyarlılık dağılımı nasıl?",
            "En çok şikayet edilen konular neler?",
            "Bu konunun kök nedenleri neler?",
        ),
    ),
    _TopicRule(
        q_keywords=(
            "aksiyon", "vaka", "case", "takeaction", "action", "decision", "karar",
        ),
        followups=(
            "Bu dönemde kaç yorum aksiyon gerektiriyor?",
            "En çok şikayet edilen konular neler?",
            "Şikayetlerin kök nedenleri neler?",
        ),
    ),
    _TopicRule(
        q_keywords=(
            "kanal", "channel", "platform", "intent", "amaç", "amac", "dağılım", "dagilim",
        ),
        followups=(
            "Yorumlar hangi kanallardan (platform) geliyor?",
            "Müşteriler en çok hangi amaçla (intent) yazıyor?",
            "Konu bazında şikayet oranları neler?",
        ),
    ),
    _TopicRule(
        q_keywords=(
            "konu bazında şikayet", "topiclerin şikayet", "şikayet oranı", "sikayet orani",
            "intent", "niyet",
        ),
        followups=(
            "Hangi konularda şikayet oranı en yüksek?",
            "Bu konuların kök nedenleri neler?",
            "Bu konularda birkaç örnek yorum gösterir misin?",
        ),
    ),
    _TopicRule(
        q_keywords=(
            "katılım", "katilim", "participation", "pay", "ses",
        ),
        followups=(
            "Hangi konularda en çok yorum var?",
            "Konu bazında duygu skorları nasıl?",
            "Bu konuların ortalama puanları nedir?",
        ),
    ),
    _TopicRule(
        q_keywords=(
            "temel etken", "key driver", "kda", "etken analiz",
        ),
        followups=(
            "En çok şikayet edilen konular neler?",
            "NPS son dönemde nasıl bir trend izliyor?",
            "Şikayetlerin kök nedenleri neler?",
        ),
    ),
    _TopicRule(
        q_keywords=(
            "otel", "hotel", "marka", "şube", "sube", "vendor", "pivot", "karşılaştır", "karsilastir",
        ),
        followups=(
            "Hangi otellerde rating en çok düştü?",
            "Bu otelde en çok şikayet edilen konular neler?",
            "Bu otelin NPS trendi nasıl?",
        ),
    ),
    _TopicRule(
        q_keywords=("fraud", "sahte", "bot", "yıldız dağılım", "yildiz dagilim"),
        followups=(
            "Yıldız (rating) dağılımı nasıl?",
            "Genel duyarlılık dağılımı nasıl?",
            "Bu dönemde en çok şikayet edilen konular neler?",
        ),
    ),
)

# Capability-aligned defaults: data questions the Advisor worker APIs can answer.
_DEFAULT_FOLLOWUPS: tuple[str, ...] = DEFAULT_CHIP_QUESTIONS

_REFUSAL_MARKERS: tuple[str, ...] = (
    "bu bilgiye sahip değilim",
    "bu konuda bilgim yok",
    "yeterli bilgi",
    "cannot answer",
    "don't have information",
)


def generate_followups(
    question: str,
    answer: str,
    *,
    context_hint: str | None = None,
) -> list[str]:
    """
    Return up to 3 Turkish follow-up questions based on the user question,
    assistant answer, and optional UI context from pivony-api.
    """
    answer_norm = _normalize(answer)
    if not answer_norm or any(marker in answer_norm for marker in _REFUSAL_MARKERS):
        return list(_DEFAULT_FOLLOWUPS)

    combined = _normalize(f"{question}\n{answer}\n{context_hint or ''}")

    scored: list[tuple[int, _TopicRule]] = []
    for rule in _TOPIC_RULES:
        score = _score(combined, rule.q_keywords) * 2 + _score(combined, rule.a_keywords)
        if score > 0:
            scored.append((score, rule))

    scored.sort(key=lambda item: item[0], reverse=True)

    candidates: list[str] = []
    for _, rule in scored:
        candidates.extend(rule.followups)

    if len(candidates) < 3:
        candidates.extend(_DEFAULT_FOLLOWUPS)

    return sanitize_chip_questions(
        _dedupe(candidates, question, limit=3),
        user_question=question,
        limit=3,
    )
