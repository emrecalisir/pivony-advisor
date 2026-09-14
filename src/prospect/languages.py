"""Sonic Prospect multilingual response rules (mirrors pivony.com locales)."""

from __future__ import annotations

# Keep in sync with pivony-api-dev/api/utils/prospect_languages.py
SUPPORTED_LANGUAGES = ("tr", "en", "it", "ar", "sr", "de", "es", "pt", "fr")


def normalize_page_locale(code: str | None) -> str:
    raw = (code or "en").strip().lower().split("-")[0]
    return raw if raw in SUPPORTED_LANGUAGES else "en"


def supported_languages_display() -> str:
    return ", ".join(SUPPORTED_LANGUAGES)


def build_language_instruction(
    *,
    page_locale: str | None = None,
    conversation_locale: str | None = None,
) -> str:
    priority = supported_languages_display()
    conv = (conversation_locale or "").strip() or None
    lines = [
        "LANGUAGE RULE:",
        (
            f"Respond entirely in the conversation language: {conv}."
            if conv
            else "Detect which language the visitor wrote in this turn and respond entirely in that language."
        ),
        "Do not follow the page/bot default locale or earlier assistant messages if they differ.",
        "If this turn's visitor message is a full sentence in a different language, switch to that language.",
        "If this turn is too short to detect (email address, a number, a sector chip), keep the conversation language.",
        "If the visitor asks to switch language (e.g. 'can we speak Italian?'), acknowledge "
        "in that language and continue — never treat a language-switch request as a knowledge gap.",
        "If uncertain (ambiguous language, mixed languages, no conversation language yet), default to English.",
        f"These languages have verified content quality and are priority-supported: {priority}.",
        "If the visitor writes in any other language, still answer in that language to the best "
        "of your ability — never say the language is unsupported.",
    ]
    if page_locale:
        lines.append(
            f"Page/session default locale (greeting tone only, not a response constraint): {page_locale}."
        )
    return "\n".join(lines)


def build_pivony_commercial_instruction() -> str:
    return (
        "PIVONY / SONIC PROSPECT COMMERCIAL (only when the visitor asks about Pivony or "
        "Sonic Prospect as a Pivony product — not the host company's own product or prices):\n"
        "- You don't pay for conversations. You pay for qualified prospects.\n"
        "- Standard: $9 per Qualified Prospect.\n"
        "- Launch incentive: $5.99 per Qualified Prospect for the first 1,000 QPs "
        "(attached rate — not a plan, tier, package, allowance, or subscription).\n"
        "- After the first 1,000 QPs: $9 per Qualified Prospect.\n"
        "- Access: Request Access (approval-gated). Enterprise: Talk to Sales "
        '(custom economics, never "unlimited").\n'
        "- NEVER describe Sonic Prospect as Free, Plus, Pro, Pro+, Live Sales Handoff packs, "
        "session quotas, conversation billing, or $49/$149 subscriptions.\n"
        "- Sonic Survey still has Free/Plus/Pro/Pro+ — never mix those into Sonic Prospect answers.\n"
        "- If retrieved knowledge contradicts this block for Pivony/Sonic Prospect, this block wins.\n"
        "- If the visitor asks about THIS website's product (the company hosting the widget, "
        "not Pivony), use knowledge context and do not quote Pivony Qualified Prospect rates."
    )


def build_knowledge_fallback_instruction() -> str:
    return (
        "KNOWLEDGE GAP RULE:\n"
        "If the knowledge context does not contain a direct answer:\n"
        "- Respond in the conversation language (same LANGUAGE RULE as above).\n"
        "- Do not invent facts, prices, metrics, or customer names.\n"
        "- If related context exists (even in another language), summarize the closest useful "
        "information in the conversation language.\n"
        "- For Pivony / Sonic Prospect pricing, use the PIVONY / SONIC PROSPECT COMMERCIAL "
        "block — do not say plans depend on use case or recommend Free/Plus/Pro.\n"
        "- For the host company's own product pricing, use knowledge figures if present; "
        "otherwise share what is known and offer Talk to Sales / a next step.\n"
        "- End with a concrete next step (e.g. Request Access, Talk to Sales, book a demo) — "
        "avoid a generic 'contact the team' only message."
    )


def augment_prospect_system_prompt(
    system_prompt: str | None,
    *,
    page_locale: str | None = None,
    conversation_locale: str | None = None,
) -> str:
    parts: list[str] = []
    base = (system_prompt or "").strip()
    if base:
        parts.append(base)
    parts.append(
        build_language_instruction(
            page_locale=page_locale,
            conversation_locale=conversation_locale,
        )
    )
    parts.append(build_pivony_commercial_instruction())
    parts.append(build_knowledge_fallback_instruction())
    return "\n\n".join(parts)
