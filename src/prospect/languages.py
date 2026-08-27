"""Sonic Prospect multilingual response rules (mirrors pivony.com locales)."""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("tr", "en", "ar", "sr", "de", "es", "pt", "fr")


def normalize_page_locale(code: str | None) -> str:
    raw = (code or "en").strip().lower().split("-")[0]
    return raw if raw in SUPPORTED_LANGUAGES else "en"


def supported_languages_display() -> str:
    return ", ".join(SUPPORTED_LANGUAGES)


def build_language_instruction(*, page_locale: str | None = None) -> str:
    priority = supported_languages_display()
    lines = [
        "LANGUAGE RULE:",
        "Detect which language the visitor wrote in their latest message (this turn only) "
        "and respond entirely in that language.",
        "If uncertain (ambiguous language, very short message, mixed languages), default to English.",
        "Earlier messages do NOT set the response language — ONLY this turn's visitor message does.",
        f"These languages have verified content quality and are priority-supported: {priority}.",
        "If the visitor writes in any other language, still answer in that language to the best "
        "of your ability — never say the language is unsupported.",
    ]
    if page_locale:
        lines.append(
            f"Page/session default locale (greeting tone only, not a response constraint): {page_locale}."
        )
    return "\n".join(lines)


def build_knowledge_fallback_instruction() -> str:
    return (
        "KNOWLEDGE GAP RULE:\n"
        "If the knowledge context does not contain a direct answer:\n"
        "- Respond in the visitor's language (same LANGUAGE RULE as above).\n"
        "- Do not invent facts, prices, metrics, or customer names.\n"
        "- If related context exists (even in another language), summarize the closest useful "
        "information in the visitor's language.\n"
        "- End with a concrete next step (e.g. book a demo, contact sales, pricing page) — "
        "avoid a generic 'contact the team' only message."
    )


def augment_prospect_system_prompt(
    system_prompt: str | None,
    *,
    page_locale: str | None = None,
) -> str:
    parts: list[str] = []
    base = (system_prompt or "").strip()
    if base:
        parts.append(base)
    parts.append(build_language_instruction(page_locale=page_locale))
    parts.append(build_knowledge_fallback_instruction())
    return "\n\n".join(parts)
