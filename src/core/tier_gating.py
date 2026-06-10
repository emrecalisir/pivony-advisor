"""Freemium vs Industry-Expert capability gates for advisor tools."""

from __future__ import annotations

INDUSTRY_EXPERT_UPGRADE_MESSAGE = (
    "Bu tür karşılaştırmalı analizler Industry-Expert planında sunulmaktadır. "
    "Industry-Expert planına sahip olarak istediğiniz cevapları alabilirsiniz. "
    "Plan değişikliği için aksiyon almak ister misiniz?"
)

_UPGRADE_INSTRUCTION = (
    "Relay user_message to the user verbatim (in Turkish). Do NOT perform the "
    "analysis or invent numbers. If the user clearly confirms they want to "
    "upgrade (e.g. 'evet', 'isterim'), call request_plan_upgrade(message=...) "
    "with a short note of what they asked for."
)


def industry_expert_gate(feature: str, *, detail: str | None = None) -> dict:
    """Structured payload returned by Industry-Expert-only tools on freemium."""
    out: dict = {
        "requires_industry_expert": True,
        "feature": feature,
        "user_message": INDUSTRY_EXPERT_UPGRADE_MESSAGE,
        "instruction": _UPGRADE_INSTRUCTION,
    }
    if detail:
        out["detail"] = detail
    return out
