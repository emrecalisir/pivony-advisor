"""Contextual follow-ups and Cursor-style guidance via Vertex AI Gemini."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from core.chip_capabilities import (
    ADVISOR_CHIP_CAPABILITY_SUMMARY,
    is_kpi_creation_intent,
    sanitize_chip_questions,
)
from core.followups import generate_followups as rule_based_followups
from core.guidance import generate_contextual_guidance as template_guidance
from core.llm_resilience import is_terminal_llm_user_message

if TYPE_CHECKING:
    from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

_REFUSAL_MARKERS: tuple[str, ...] = (
    "bu bilgiye sahip değilim",
    "bu konuda bilgim yok",
    "yeterli bilgi",
    "cannot answer",
    "don't have information",
)

_GREETING_MARKERS: tuple[str, ...] = (
    "naber",
    "nasilsin",
    "nasılsın",
    "merhaba",
    "selam",
    "hello",
    "hi ",
    "hey",
    "günaydın",
    "gunaydin",
    "iyi günler",
    "teşekkür",
    "tesekkur",
    "sağol",
    "sagol",
    "how are you",
    "thanks",
    "thank you",
)

_GENERIC_ANSWER_MARKERS: tuple[str, ...] = (
    "yapay zeka",
    "asistan",
    "size nasıl yardımcı",
    "how can i help",
    "nasıl yardımcı olabilirim",
)

_DATA_ANSWER_MARKERS: tuple[str, ...] = (
    "%",
    "nps",
    "rating",
    "puan",
    "şikayet",
    "sikayet",
    "dashboard",
    "yorum",
    "sentiment",
    "duyarlılık",
    "duyarlilik",
    "review_count",
    "konu",
    "topic",
    "avg_rating",
)

CONVERSATION_STARTER_SYSTEM = f"""You suggest starter follow-up questions right after the user greeted the Advisor or made small talk — they have NOT asked a data question yet.

{ADVISOR_CHIP_CAPABILITY_SUMMARY}

Rules:
- Match the user's language (Turkish by default).
- Propose exactly 2 or 3 GENERAL, broad starter questions — overview level only (e.g. overall sentiment, top complaints, NPS trend).
- Do NOT mention specific segments, travel types, pivots, hotel/brand names, or filters — scope is not established yet.
- Do NOT invent facts from UI context; you are NOT given dashboard filters for this turn.
- Do NOT suggest UI/how-to questions (creating dashboards, integrations, downloading reports).
- Write one short welcoming guidance paragraph inviting them to explore guest-experience data.
- Every suggested question must be answerable by the Advisor worker tools once a dashboard is chosen."""

NAVIGATION_SYSTEM = f"""You are the Pivony Advisor follow-up assistant. The Advisor answers DATA questions about the user's own Voice-of-Customer dashboards by calling worker/MCP analytics tools. After it answers, suggest what the user could ask NEXT.

{ADVISOR_CHIP_CAPABILITY_SUMMARY}

Rules:
- Match the user's language (Turkish by default).
- Propose exactly 2 or 3 follow-up QUESTIONS that the Advisor can actually answer with the worker tools above, staying on the SAME dashboard and time period already in context.
- Phrase them as direct questions about the user's DATA, e.g. "Bu dönemde en çok şikayet edilen konular neler?", "Konu bazında şikayet oranları neler?" or "NPS son dönemde nasıl bir trend izliyor?".
- If the user message is ONLY a greeting, thanks, or small talk (e.g. "merhaba", "naber", "nasılsın") and the assistant reply contains NO metrics or data yet, suggest 2–3 GENERAL starter questions (sentiment overview, top complaints, NPS trend). Do NOT mention specific segments, pivots, travel types, or filters from UI context — the user has not asked about data yet.
- NEVER suggest product how-to / setup / navigation questions — creating dashboards, integrations (Zendesk, CSV), adding widgets, downloading/scheduling reports, Market Intelligence, competitor dashboards, or anything phrased as "nasıl görebilirim / nasıl oluştururum / nereden indiririm". The Advisor answers data, not UI navigation.
- Follow-up questions MUST stay within the same analytics scope as the assistant's previous answer. If the prior answer used organization-wide data (no specific dashboard named), suggest only questions answerable at that same org-wide scope — do NOT suggest dashboard-specific drill-downs that would require picking a dashboard unless the user already chose one.
- Do not repeat the user's exact question and do not invent metrics outside the worker tool capabilities above.
- Write one short closing paragraph (guidance) that naturally offers those directions. Use **bold** markdown only for metric/topic names inside guidance.
- If the Advisor could not answer (no data), suggest trying a different dashboard or a wider date range instead."""

_CONFIRMATION_MARKERS: tuple[str, ...] = (
    "onaylıyor musun",
    "onayliyor musun",
    "onaylar mısın",
    "onaylar misin",
    "onaylıyor musunuz",
    "doğru anladım",
    "dogru anladim",
    "emin olmak için",
    "emin olmak icin",
)

_TIMEOUT_MARKERS: tuple[str, ...] = (
    "zaman aşım",
    "zaman asim",
    "timeout",
    "advisor_action",
)

_SINGLE_PROMPT_MARKERS: tuple[str, ...] = (
    "hangi dashboard",
    "hangi dönem",
    "hangi donem",
    "hangi metrik",
    "hangi otel",
    "hangi pivot",
    "hangi konu",
    "belirtir misiniz",
    "belirtir misin",
    "seçer misiniz",
    "secer misiniz",
    "seçelim",
    "secelim",
)


def _is_kpi_creation_turn(question: str, answer: str) -> bool:
    q = _normalize(question)
    a = _normalize(answer)
    if is_kpi_creation_intent(q):
        return True
    if is_kpi_creation_intent(a):
        return True
    return "kpi" in q and any(
        token in a for token in ("dashboard", "hangi dashboard", "oluştur", "olustur")
    )


def _conversation_in_kpi_flow(
    question: str,
    answer: str,
    chat_history: str | None,
) -> bool:
    if _is_kpi_creation_turn(question, answer):
        return True
    hist = _normalize(chat_history or "")
    if not hist:
        return False
    if is_kpi_creation_intent(hist):
        return True
    return "kpi" in hist and any(
        token in hist
        for token in (
            "oluştur",
            "olustur",
            "metrik",
            "onay",
            "dashboard",
            "pivot",
            "kategori",
        )
    )


def _assistant_single_clear_prompt(answer: str) -> bool:
    """True when the reply is one short CTA — chips would duplicate it."""
    text = (answer or "").strip()
    if not text or len(text) > 360 or "?" not in text:
        return False
    if text.count("?") > 2:
        return False
    lower = _normalize(text)
    return any(marker in lower for marker in _SINGLE_PROMPT_MARKERS)


def _is_kpi_inventory_question(question: str) -> bool:
    q = _normalize(question)
    if not q:
        return False
    if "kpi" not in q:
        return False
    return any(
        token in q
        for token in (
            "hangi kpi",
            "kpilerim",
            "kpi'ım",
            "kpim",
            "kpi var",
            "which kpi",
            "my kpi",
            "list kpi",
        )
    )


def should_offer_navigation_chips(
    question: str,
    answer: str,
    *,
    chat_history: str | None = None,
    dashboard_picker: dict | None = None,
    period_picker: dict | None = None,
    kpi_metric_picker: dict | None = None,
    kpi_team_picker: dict | None = None,
) -> bool:
    """
    Decide whether this turn should show suggested follow-up chips + guidance.

    Chips are optional navigation — skip when the UI or assistant reply already
    provides a clear next step (picker, KPI wizard, confirmation, errors).
    """
    if dashboard_picker or period_picker or kpi_metric_picker or kpi_team_picker:
        return False
    if is_terminal_llm_user_message(answer):
        return False

    answer_norm = _normalize(answer)
    if any(marker in answer_norm for marker in _TIMEOUT_MARKERS):
        return False
    if _conversation_in_kpi_flow(question, answer, chat_history):
        return False
    if _is_kpi_inventory_question(question):
        return False
    if any(marker in answer_norm for marker in _CONFIRMATION_MARKERS):
        return False
    if _assistant_single_clear_prompt(answer):
        return False
    return True


class ContextualNavigationResult(BaseModel):
    followups: list[str] = Field(
        description="Exactly 2 or 3 follow-up questions the user might ask next.",
        min_length=2,
        max_length=3,
    )
    guidance: str = Field(
        description=(
            "One short paragraph offering next steps, e.g. "
            "'İstersen bir sonraki adımda **X** veya **Y** konusuna geçebiliriz.'"
        ),
        min_length=10,
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _is_refusal(answer: str) -> bool:
    answer_norm = _normalize(answer)
    return not answer_norm or any(marker in answer_norm for marker in _REFUSAL_MARKERS)


def _is_conversational_turn(question: str, answer: str) -> bool:
    """Greeting/small-talk with no data in the reply — skip segment-specific chips."""
    q = _normalize(question)
    a = _normalize(answer)
    if not q:
        return False
    is_greeting = any(marker in q for marker in _GREETING_MARKERS)
    if not is_greeting and len(q.split()) > 8:
        return False
    if not is_greeting:
        # Very short non-data openers ("nabe", "hey") without analytics keywords.
        is_greeting = len(q.split()) <= 4 and not any(
            kw in q
            for kw in (
                "nps",
                "rating",
                "şikayet",
                "sikayet",
                "yorum",
                "duyarlılık",
                "duyarlilik",
                "trend",
                "dashboard",
                "otel",
            )
        )
    if not is_greeting:
        return False
    has_data = any(marker in a for marker in _DATA_ANSWER_MARKERS)
    is_generic = any(marker in a for marker in _GENERIC_ANSWER_MARKERS)
    return is_generic or (not has_data and len(a) < 280)


def _dedupe_followups(items: list[str], question: str, limit: int = 3) -> list[str]:
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


def _fallback_navigation(question: str, answer: str, *, context_hint: str | None) -> tuple[list[str], str]:
    followups = rule_based_followups(question, answer, context_hint=context_hint)
    return followups, template_guidance(followups)


def _build_navigation_prompt(
    *,
    question: str,
    answer: str,
    chat_history: str | None,
    context_hint: str | None,
) -> str:
    parts = [
        "Conversation history:",
        (chat_history or "(No prior conversation.)").strip(),
        "",
        "User question:",
        question.strip(),
        "",
        "Assistant answer:",
        answer.strip(),
    ]
    if context_hint and context_hint.strip():
        parts.extend(["", "Platform / UI context:", context_hint.strip()])
    return "\n".join(parts)


def _vertex_navigation(
    *,
    system: str,
    question: str,
    answer: str,
    chat_history: str | None,
    context_hint: str | None,
    llm: ChatGoogleGenerativeAI,
) -> tuple[list[str], str]:
    structured_llm = llm.with_structured_output(
        ContextualNavigationResult,
        method="json_schema",
    )
    result = structured_llm.invoke(
        [
            SystemMessage(content=system),
            HumanMessage(
                content=_build_navigation_prompt(
                    question=question,
                    answer=answer,
                    chat_history=chat_history,
                    context_hint=context_hint,
                )
            ),
        ]
    )
    if not isinstance(result, ContextualNavigationResult):
        result = ContextualNavigationResult.model_validate(result)

    followups = sanitize_chip_questions(
        _dedupe_followups(result.followups, question, limit=3),
        user_question=question,
        limit=3,
    )
    guidance = (result.guidance or "").strip()
    if len(followups) < 2 or not guidance:
        raise ValueError("Incomplete navigation result from Vertex AI")
    return followups, guidance


def _starter_navigation(
    question: str,
    answer: str,
    *,
    llm: ChatGoogleGenerativeAI | None,
    use_vertex: bool,
) -> tuple[list[str], str]:
    """General starter chips after greeting — LLM-generated, no UI context leak."""
    if use_vertex and llm is not None:
        try:
            return _vertex_navigation(
                system=CONVERSATION_STARTER_SYSTEM,
                question=question,
                answer=answer,
                chat_history=None,
                context_hint=None,
                llm=llm,
            )
        except Exception as exc:
            logger.warning("Vertex starter navigation failed, using fallback: %s", exc)
    return _fallback_navigation(question, answer, context_hint=None)


def generate_contextual_navigation(
    question: str,
    answer: str,
    *,
    chat_history: str | None = None,
    context_hint: str | None = None,
    llm: ChatGoogleGenerativeAI | None = None,
    use_vertex: bool = True,
) -> tuple[list[str], str]:
    """
    Return (followups, guidance) using Vertex AI Gemini structured output.

    Falls back to rule-based suggestions if Vertex is disabled or the call fails.
    """
    if _is_conversational_turn(question, answer):
        return _starter_navigation(question, answer, llm=llm, use_vertex=use_vertex)

    if _is_refusal(answer):
        return _fallback_navigation(question, answer, context_hint=context_hint)

    if not use_vertex or llm is None:
        return _fallback_navigation(question, answer, context_hint=context_hint)

    try:
        return _vertex_navigation(
            system=NAVIGATION_SYSTEM,
            question=question,
            answer=answer,
            chat_history=chat_history,
            context_hint=context_hint,
            llm=llm,
        )
    except Exception as exc:
        logger.warning("Vertex contextual navigation failed, using fallback: %s", exc)
        return _fallback_navigation(question, answer, context_hint=context_hint)


def maybe_generate_contextual_navigation(
    question: str,
    answer: str,
    *,
    chat_history: str | None = None,
    context_hint: str | None = None,
    llm: ChatGoogleGenerativeAI | None = None,
    use_vertex: bool = True,
    dashboard_picker: dict | None = None,
    period_picker: dict | None = None,
    kpi_metric_picker: dict | None = None,
    kpi_team_picker: dict | None = None,
) -> tuple[list[str], str]:
    """Generate chips only when they add value for this turn."""
    if not should_offer_navigation_chips(
        question,
        answer,
        chat_history=chat_history,
        dashboard_picker=dashboard_picker,
        period_picker=period_picker,
        kpi_metric_picker=kpi_metric_picker,
        kpi_team_picker=kpi_team_picker,
    ):
        logger.info(
            "Navigation chips skipped (question=%r answer_len=%s)",
            (question or "")[:80],
            len(answer or ""),
        )
        return [], ""
    return generate_contextual_navigation(
        question,
        answer,
        chat_history=chat_history,
        context_hint=context_hint,
        llm=llm,
        use_vertex=use_vertex,
    )
