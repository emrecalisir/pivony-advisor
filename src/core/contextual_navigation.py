"""Contextual follow-ups and Cursor-style guidance via Vertex AI Gemini."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from core.followups import generate_followups as rule_based_followups
from core.guidance import generate_contextual_guidance as template_guidance

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

NAVIGATION_SYSTEM = """You are the Pivony Advisor navigation assistant.
After the user receives an answer about the Pivony customer experience platform, suggest what they might explore next.

Rules:
- Match the user's language (Turkish by default).
- Propose exactly 2 or 3 specific follow-up questions the user could ask next.
- Write one short Cursor-style closing paragraph (guidance) that naturally offers those directions.
- Use **bold** markdown only inside guidance for topic names.
- Ground suggestions in the conversation — Pivony features such as dashboards, VoC, Market Intelligence, Zendesk, My Workspace, AI Insights, reports, filters.
- Do not repeat the user's exact question.
- Do not invent product features not implied by the exchange.
- If the assistant could not answer, suggest general onboarding questions instead."""


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
    if _is_refusal(answer):
        return _fallback_navigation(question, answer, context_hint=context_hint)

    if not use_vertex or llm is None:
        return _fallback_navigation(question, answer, context_hint=context_hint)

    try:
        structured_llm = llm.with_structured_output(
            ContextualNavigationResult,
            method="json_schema",
        )
        result = structured_llm.invoke(
            [
                SystemMessage(content=NAVIGATION_SYSTEM),
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

        followups = _dedupe_followups(result.followups, question, limit=3)
        guidance = (result.guidance or "").strip()
        if len(followups) < 2 or not guidance:
            raise ValueError("Incomplete navigation result from Vertex AI")

        return followups, guidance
    except Exception as exc:
        logger.warning("Vertex contextual navigation failed, using fallback: %s", exc)
        return _fallback_navigation(question, answer, context_hint=context_hint)
