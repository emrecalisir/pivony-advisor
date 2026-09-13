"""Answer generation for Sonic Prospect Commerce (Shopify vertical).

Unlike prospect/rag.py this module never retrieves. The Shopify app owns
catalog, variant, policy and cart retrieval and sends the ranked context with
every turn, so there is no Qdrant client, no embeddings and no persistence of
what the caller sends.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from core.config import GCP_LOCATION, GCP_PROJECT, LLM_TEMPERATURE

COMMERCE_LLM_MODEL = (
    os.environ.get("SONIC_COMMERCE_LLM_MODEL")
    or os.environ.get("ADVISOR_LLM_MODEL")
    or os.environ.get("LLM_MODEL")
    or "gemini-2.5-flash"
).strip()

COMMERCE_SECRET = os.environ.get("SONIC_COMMERCE_SECRET", "").strip()

MAX_HISTORY_TURNS = 8
MAX_CONTEXT_BLOCKS = 12

HUMAN_TEMPLATE = """Store context read from Shopify just now:
{context}

Conversation so far:
{chat_history}

Shopper message: {question}

Answer:"""


def _format_context(blocks: list[dict[str, Any]]) -> str:
    if not blocks:
        return "(No store context available.)"
    parts: list[str] = []
    for index, block in enumerate(blocks[:MAX_CONTEXT_BLOCKS], start=1):
        kind = (block.get("kind") or "context").strip()
        title = (block.get("title") or "").strip()
        url = (block.get("url") or "").strip()
        fresh_at = (block.get("fresh_at") or "").strip()
        text = (block.get("text") or "").strip()
        if not text:
            continue
        header = f"[{index}] {kind}"
        if title:
            header += f" — {title}"
        if fresh_at:
            header += f" (read {fresh_at})"
        if url:
            header += f"\n{url}"
        parts.append(f"{header}\n{text}")
    return "\n\n".join(parts) if parts else "(No store context available.)"


def _format_history(history: list[dict[str, str]] | None) -> str:
    if not history:
        return "(No prior messages.)"
    lines: list[str] = []
    for turn in history[-MAX_HISTORY_TURNS:]:
        role = (turn.get("role") or "user").strip()
        content = (turn.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(No prior messages.)"


def _message_text(content: Any) -> str:
    """Gemini returns a string, or a list of parts when the reply is chunked."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        ]
        return "".join(parts).strip()
    return str(content or "").strip()


def _usage(message: Any) -> dict[str, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
    }


def answer_commerce_question(
    *,
    shop_domain: str,
    message: str,
    system_prompt: str,
    context_blocks: list[dict[str, Any]] | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    question = (message or "").strip()
    if not question:
        raise ValueError("message is required")
    system = (system_prompt or "").strip()
    if not system:
        raise ValueError("system_prompt is required")

    blocks = context_blocks or []
    llm = ChatGoogleGenerativeAI(
        model=COMMERCE_LLM_MODEL,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        vertexai=True,
        temperature=LLM_TEMPERATURE,
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", system), ("human", HUMAN_TEMPLATE)]
    )
    reply = (prompt | llm).invoke(
        {
            "context": _format_context(blocks),
            "chat_history": _format_history(chat_history),
            "question": question,
        }
    )
    metadata = getattr(reply, "response_metadata", None) or {}
    return {
        "answer": _message_text(getattr(reply, "content", reply)),
        "model": COMMERCE_LLM_MODEL,
        "usage": _usage(reply),
        # Gemini reports STOP / MAX_TOKENS / SAFETY; the caller contract is lowercase.
        "finish_reason": str(metadata.get("finish_reason") or "stop").lower(),
        "shop_domain": shop_domain,
        "blocks_used": min(len(blocks), MAX_CONTEXT_BLOCKS),
    }
