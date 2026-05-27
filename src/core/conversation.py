"""Multi-turn chat helpers: history formatting and contextual retrieval queries."""

from __future__ import annotations

import re
from typing import Any

_MAX_HISTORY_TURNS = 6
_MAX_ASSISTANT_SNIPPET = 400

_FOLLOW_UP_MARKERS = (
    "peki",
    "peki ya",
    "o zaman",
    "bunu",
    "onu",
    "bunun",
    "onun",
    "aynı",
    "devam",
    "daha",
    "instead",
    "also",
    "what about",
    "how about",
    "and then",
    "same",
    "that",
    "this",
    "it",
)


def _message_role(message: Any) -> str | None:
    role = getattr(message, "role", None)
    if role is None and isinstance(message, dict):
        role = message.get("role")
    return str(role).strip().lower() if role else None


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return str(content or "").strip()


def _non_system_messages(messages: list[Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for message in messages:
        role = _message_role(message)
        content = _message_content(message)
        if role in ("user", "assistant") and content:
            out.append((role, content))
    return out


def _is_follow_up(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", question.lower()).strip()
    if not normalized:
        return False
    if len(normalized) <= 45:
        return True
    if normalized.startswith(_FOLLOW_UP_MARKERS):
        return True
    return any(f" {marker} " in f" {normalized} " for marker in _FOLLOW_UP_MARKERS)


def _truncate(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def format_chat_history(messages: list[Any], *, max_turns: int = _MAX_HISTORY_TURNS) -> str:
    """Format prior user/assistant turns (excluding the latest user message)."""
    turns = _non_system_messages(messages)
    if not turns or turns[-1][0] != "user":
        return "(No prior conversation.)"

    prior = turns[:-1]
    if not prior:
        return "(No prior conversation.)"

    selected = prior[-max_turns:]
    lines: list[str] = []
    for role, content in selected:
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {_truncate(content, 900)}")
    return "\n".join(lines)


def build_retrieval_query(messages: list[Any]) -> str:
    """
    Build a search query that keeps topic context for short follow-up questions.

    Example:
      User: dashboard nasıl silebilirimi?
      User: peki nasıl oluştururm
      -> "dashboard nasıl silebilirimi? peki nasıl oluştururm"
    """
    turns = _non_system_messages(messages)
    user_messages = [content for role, content in turns if role == "user"]
    if not user_messages:
        return ""

    current = user_messages[-1]
    if len(user_messages) >= 2 and _is_follow_up(current):
        previous = user_messages[-2]
        parts = [previous, current]

        for role, content in reversed(turns[:-1]):
            if role == "assistant":
                parts.append(_truncate(content, _MAX_ASSISTANT_SNIPPET))
                break

        return "\n".join(parts)

    return current


def prepare_conversational_input(messages: list[Any]) -> dict[str, str]:
    """Normalize OpenAI-style messages into RAG chain inputs."""
    turns = _non_system_messages(messages)
    if not turns or turns[-1][0] != "user":
        raise ValueError("No user message with content found in messages")

    question = turns[-1][1]
    return {
        "question": question,
        "chat_history": format_chat_history(messages),
        "retrieval_query": build_retrieval_query(messages),
    }
