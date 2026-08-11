"""Runtime RAG for Sonic Prospect visitor chat."""

from __future__ import annotations

from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from core.config import GCP_LOCATION, GCP_PROJECT, LLM_TEMPERATURE
from core.rag import build_embeddings, build_llm, create_qdrant_client
from prospect.config import PROSPECT_LLM_MODEL
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
    sources = search_bot_knowledge(
        org_id=org_id,
        bot_id=bot_id,
        query=question,
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
