"""Contextual follow-up question suggestions after Advisor answers."""

from __future__ import annotations

import re
from dataclasses import dataclass


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


_TOPIC_RULES: tuple[_TopicRule, ...] = (
    _TopicRule(
        q_keywords=("dashboard", "oluştur", "create dashboard", "yeni dashboard", "new dashboard"),
        followups=(
            "Zendesk entegrasyonu nasıl yapılır?",
            "Dashboard hazır olunca AI Insights nasıl oluşturulur?",
            "Data Overview'da hangi filtreleri kullanmalıyım?",
        ),
        a_keywords=("new dashboard", "source wizard", "mydashboards", "journey"),
    ),
    _TopicRule(
        q_keywords=(
            "dış veri",
            "dis veri",
            "market intelligence",
            "rakip",
            "competitor",
            "public",
            "outside-in",
            "dış kaynak",
        ),
        followups=(
            "Competitor Analysis'te markaları nasıl karşılaştırırım?",
            "My Workspace'e rakip widget'ı nasıl eklerim?",
            "Digital Experience Score (DES) nerede görüntülenir?",
        ),
        a_keywords=("industrytopics", "competitor analysis", "market intelligence"),
    ),
    _TopicRule(
        q_keywords=(
            "iç veri",
            "ic veri",
            "voc",
            "voice of customer",
            "inside-out",
            "destek",
            "ticket",
            "zendesk",
            "csv",
        ),
        followups=(
            "Zendesk entegrasyonu nasıl yapılır?",
            "CSV ile dashboard nasıl oluşturulur?",
            "AI Insights raporu nasıl alınır?",
        ),
        a_keywords=("voice of customer", "zendesk", "csv upload", "inside-out"),
    ),
    _TopicRule(
        q_keywords=("zendesk", "entegrasyon", "integration", "oauth"),
        followups=(
            "Zendesk bağlandıktan sonra dashboard nasıl oluşturulur?",
            "Ticket filtrelerini dashboard'da nasıl kullanırım?",
            "My Workspace'e VoC widget'ı nasıl eklerim?",
        ),
    ),
    _TopicRule(
        q_keywords=("my workspace", "workspace", "widget", "metric", "metrik"),
        followups=(
            "Aylık otomatik rapor nasıl ayarlanır?",
            "Executive sunum (KPI Views) nasıl hazırlanır?",
            "Dashboard PDF export nasıl yapılır?",
        ),
    ),
    _TopicRule(
        q_keywords=("rapor", "report", "pdf", "csv export", "download", "indir"),
        followups=(
            "Aylık AI Insights raporu nasıl oluşturulur?",
            "Ad hoc rapor ile periyodik rapor arasındaki fark nedir?",
            "My Workspace PDF export nasıl yapılır?",
        ),
        a_keywords=("reportpdf", "auto-refresh", "downloads"),
    ),
    _TopicRule(
        q_keywords=("ai insight", "ai insights", "otomatik", "auto refresh", "monthly"),
        followups=(
            "Auto Refresh ayarlarını nereden yapılandırırım?",
            "Aylık raporları nereden indiririm?",
            "My Workspace ile Auto Refresh arasındaki fark nedir?",
        ),
    ),
    _TopicRule(
        q_keywords=("full intelligence", "full plan", "her iki", "voc ve market"),
        followups=(
            "Dış veriyi nasıl analiz ederim?",
            "İç veriyi nasıl analiz ederim?",
            "Full Intelligence ile hangi entegrasyonlar kullanılabilir?",
        ),
    ),
    _TopicRule(
        q_keywords=("filtre", "filter", "data overview", "sentiment", "topic"),
        followups=(
            "Dashboard'da konu (topic) hiyerarşisi nasıl çalışır?",
            "AI Insights ile filtrelenmiş veriyi nasıl özetlerim?",
            "My Workspace widget'ında filtre nasıl uygulanır?",
        ),
    ),
    _TopicRule(
        q_keywords=("adım", "step", "nasıl yap", "how to", "ne yapmalı"),
        followups=(
            "Dış veriyi nasıl analiz ederim?",
            "İç veriyi nasıl analiz ederim?",
            "Dashboard nasıl oluşturabilirim?",
        ),
    ),
)

_DEFAULT_FOLLOWUPS: tuple[str, ...] = (
    "Dashboard nasıl oluşturabilirim?",
    "Dış veriyi nasıl analiz ederim?",
    "Raporları nereden indirebilirim?",
)

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

    return _dedupe(candidates, question, limit=3)
