"""Cursor-style contextual next-step guidance prose from follow-up topics."""

from __future__ import annotations

import re


def _topic_phrase(question: str) -> str:
    """Turn a follow-up question into a short topic phrase for prose."""
    text = (question or "").strip().rstrip("?").lower()
    for prefix in ("peki ", "o zaman "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    for suffix in (
        " nasıl yapılır",
        " nasıl oluşturulur",
        " nasıl oluşturabilirim",
        " nasıl alınır",
        " nasıl ayarlanır",
        " nereden indirebilirim",
        " nerede görüntülenir",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return text or question.strip().rstrip("?")


def generate_contextual_guidance(followups: list[str]) -> str:
    """
    Build a short Turkish guidance paragraph like Cursor's closing offers.

    Example:
      "İstersen bir sonraki adımda dashboard oluşturma, Zendesk entegrasyonu
       veya AI Insights konusuna geçebiliriz."
    """
    topics = [_topic_phrase(item) for item in followups if (item or "").strip()]
    topics = [t for t in topics if t]
    if not topics:
        return ""

    if len(topics) == 1:
        return (
            f"İstersen bir sonraki adımda **{topics[0]}** konusunda yardımcı olabilirim."
        )
    if len(topics) == 2:
        return (
            f"İstersen bir sonraki adımda **{topics[0]}** veya **{topics[1]}** "
            "konusuna geçebiliriz."
        )

    joined = ", ".join(f"**{t}**" for t in topics[:-1])
    return (
        f"İstersen bir sonraki adımda {joined} veya **{topics[-1]}** "
        "konusunda devam edebiliriz."
    )
