"""Runtime RAG for Sonic Prospect visitor chat."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from core.config import GCP_LOCATION, GCP_PROJECT, LLM_TEMPERATURE
from core.rag import build_embeddings, create_qdrant_client
from prospect.config import PROSPECT_LLM_MODEL, PROSPECT_RETRIEVER_K
from prospect.qdrant_store import search_bot_knowledge

DEFAULT_SYSTEM = (
    "You are a helpful site assistant. Answer using ONLY the provided knowledge context. "
    "If the answer is not in the context, say you do not have that information and suggest "
    "contacting the team. Be concise, friendly, and match the visitor language when possible."
)

HUMAN_TEMPLATE = """Knowledge context:
{context}

Conversation so far:
{chat_history}

Visitor question: {question}

Answer:"""

# Cross-language retrieval hints for common visitor topics.
_QUERY_EXPANSIONS: list[tuple[re.Pattern[str], list[str]]] = [
    (
        re.compile(r"adults?[- ]only|yetişkin|18\+|yetişkinlere\s+özel", re.I),
        ["adults-only", "adults only", "18+", "adult only wing", "ANT-205", "Royal Palm"],
    ),
    (
        re.compile(r"iptal|cancellation|cancel", re.I),
        ["cancellation", "free cancel", "72 hours", "flexible rate"],
    ),
    (
        re.compile(r"en ucuz|cheapest|ucuz otel", re.I),
        ["cheapest", "ANT-113", "Alanya Sunrise Beach", "48 EUR", "lowest price"],
    ),
    (
        re.compile(r"429|rate limit|hız sınır", re.I),
        ["429", "rate limit", "120 req/min", "Too Many Requests"],
    ),
    (
        re.compile(r"shuttle|transfer|havaliman|ayt", re.I),
        ["shuttle", "AYT", "Lara", "12 EUR", "airport transfer"],
    ),
    (
        re.compile(r"loyalty|acme plus|üyelik", re.I),
        ["Acme Plus", "loyalty", "room upgrade", "Navigator", "Explorer"],
    ),
]


def _expand_queries(question: str) -> list[str]:
    """Build primary + expanded queries for multi-query retrieval."""
    queries = [question.strip()]
    extras: list[str] = []
    for pattern, terms in _QUERY_EXPANSIONS:
        if pattern.search(question):
            extras.extend(terms)
    extras.extend(re.findall(r"ANT-\d{3}", question, flags=re.I))
    if "royal palm" in question.lower():
        extras.extend(["ANT-205", "Royal Palm Ultra Lara", "adults-only wing"])
    if extras:
        unique = list(dict.fromkeys(extras))
        queries.append(f"{question}\nRelated keywords: {', '.join(unique)}")
    return queries


def _merge_search_results(
    result_sets: list[list[dict[str, Any]]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int | None]] = set()
    for results in result_sets:
        for hit in results:
            key = (hit.get("source_id"), hit.get("chunk_index"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
    merged.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return merged[:limit]


def _retrieve_sources(
    *,
    org_id: str,
    bot_id: str | int,
    question: str,
    client: Any,
    embeddings: Any,
) -> list[dict[str, Any]]:
    per_query_k = max(PROSPECT_RETRIEVER_K, 6)
    result_sets = [
        search_bot_knowledge(
            org_id=org_id,
            bot_id=bot_id,
            query=query,
            k=per_query_k,
            client=client,
            embeddings=embeddings,
        )
        for query in _expand_queries(question)
    ]
    return _merge_search_results(result_sets, limit=PROSPECT_RETRIEVER_K)


def _format_history(history: list[dict[str, str]] | None) -> str:
    if not history:
        return "(No prior messages.)"
    lines: list[str] = []
    for turn in history[-8:]:
        role = (turn.get("role") or "user").strip()
        content = (turn.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(No prior messages.)"


def _format_context(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "(No knowledge chunks retrieved.)"
    parts: list[str] = []
    for index, src in enumerate(sources, start=1):
        snippet = (src.get("snippet") or "").strip()
        label = f"{src.get('source_type')}:{src.get('source_id')}"
        parts.append(f"[{index}] ({label})\n{snippet}")
    return "\n\n".join(parts)


def answer_visitor_question(
    *,
    org_id: str,
    bot_id: str | int,
    message: str,
    system_prompt: str | None = None,
    language: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    question = (message or "").strip()
    if not question:
        raise ValueError("message is required")

    client = create_qdrant_client()
    embeddings = build_embeddings()
    sources = _retrieve_sources(
        org_id=org_id,
        bot_id=bot_id,
        question=question,
        client=client,
        embeddings=embeddings,
    )
    context = _format_context(sources)
    history = _format_history(chat_history)

    system = (system_prompt or "").strip() or DEFAULT_SYSTEM
    if language:
        system += f"\nPreferred response language: {language}."

    llm = ChatGoogleGenerativeAI(
        model=PROSPECT_LLM_MODEL,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        vertexai=True,
        temperature=LLM_TEMPERATURE,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("human", HUMAN_TEMPLATE),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    answer = chain.invoke(
        {
            "context": context,
            "chat_history": history,
            "question": question,
        }
    )
    return {
        "answer": answer.strip(),
        "sources_used": sources,
    }
