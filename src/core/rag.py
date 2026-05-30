"""Dual-collection RAG: platform knowledge + sector-specific knowledge."""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from core.config import (
    DEFAULT_SECTOR,
    EMBEDDING_MODEL,
    GCP_LOCATION,
    GCP_PROJECT,
    LLM_MODEL,
    LLM_TEMPERATURE,
    PLATFORM_COLLECTION,
    PLATFORM_K,
    QDRANT_TIMEOUT_SEC,
    QDRANT_URL,
    SECTOR_K,
    collection_for_sector,
    sector_slugify,
)
from core.prompts import HUMAN_PROMPT, MASTER_PROMPT, get_sector_prompt

logger = logging.getLogger(__name__)

_META_LINE = re.compile(r"^-?\s*([A-Za-z0-9_\[\]\.]+)\s*:\s*(.+)$")
_SECTOR_HEADER = re.compile(r"^\[Sector:.*\]\s*$", re.MULTILINE)

# Candidate ingest keys -> display dimension (first non-empty wins)
_HOTEL_KEYS = ("vendorName", "projectName", "hotelName", "propertyName", "hotel", "Property")
_DATE_KEYS = ("SubmittedAt", "ReviewSubmissionDate", "date", "sk")
_CATEGORY_KEYS = ("category", "Category", "topic", "subTopic", "subtopic")


def _scan_fields(text: str) -> dict[str, str]:
    """Collect `- key: value` / `key: value` pairs from a chunk's text prefix."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("["):
            continue
        match = _META_LINE.match(stripped)
        if not match:
            # Stop scanning once the free-text review body starts.
            if fields:
                break
            continue
        key, value = match.group(1), match.group(2).strip()
        if key not in fields and value:
            fields[key] = value
    return fields


def _pick(fields: dict[str, str], metadata: dict[str, Any], keys) -> str | None:
    for key in keys:
        value = fields.get(key) or metadata.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return None


def extract_review_dimensions(doc) -> dict[str, str | None]:
    """Pull hotel / date / category for metadata injection (page_content + metadata)."""
    fields = _scan_fields(getattr(doc, "page_content", "") or "")
    metadata = getattr(doc, "metadata", {}) or {}
    return {
        "hotel": _pick(fields, metadata, _HOTEL_KEYS),
        "date": _pick(fields, metadata, _DATE_KEYS),
        "category": _pick(fields, metadata, _CATEGORY_KEYS),
    }


def _strip_internal_header(text: str) -> str:
    return _SECTOR_HEADER.sub("", text or "", count=1).strip()


def format_docs(docs) -> str:
    """Plain concatenation (used for platform knowledge, non-review chunks)."""
    return "\n\n".join(doc.page_content for doc in docs)


def format_review_docs(docs) -> str:
    """
    Inject structured metadata so hotel/date survive into the prompt:

        [Metadata -> Otel: X | Tarih: Y | Kategori: Z]
        Misafir Yorumu: <review text>
    """
    blocks: list[str] = []
    for doc in docs:
        dims = extract_review_dimensions(doc)
        meta_parts = [f"Otel: {dims['hotel'] or 'Belirtilmemiş'}"]
        if dims["date"]:
            meta_parts.append(f"Tarih: {dims['date']}")
        if dims["category"]:
            meta_parts.append(f"Kategori: {dims['category']}")
        header = "[Metadata -> " + " | ".join(meta_parts) + "]"
        body = _strip_internal_header(getattr(doc, "page_content", "") or "")
        blocks.append(f"{header}\nMisafir Yorumu: {body}")
    return "\n\n".join(blocks)


def create_qdrant_client() -> QdrantClient:
    client = QdrantClient(url=QDRANT_URL, timeout=QDRANT_TIMEOUT_SEC)
    client.get_collections()
    return client


def build_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        vertexai=True,
    )


def build_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        vertexai=True,
        temperature=LLM_TEMPERATURE,
    )


def _search_collection(
    *,
    client: QdrantClient,
    embeddings: GoogleGenerativeAIEmbeddings,
    collection_name: str,
    question: str,
    k: int,
) -> list:
    try:
        store = QdrantVectorStore(
            client=client,
            collection_name=collection_name,
            embedding=embeddings,
        )
        return store.similarity_search(question, k=k)
    except Exception as exc:
        logger.warning("Search failed for collection %s: %s", collection_name, exc)
        return []


def retrieve_merged_context(
    question: str,
    sector_slug: str,
    *,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
) -> str:
    """Retrieve platform + sector chunks and merge into labeled context."""
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)
    parts: list[str] = []

    platform_docs = _search_collection(
        client=client,
        embeddings=embeddings,
        collection_name=PLATFORM_COLLECTION,
        question=question,
        k=PLATFORM_K,
    )
    if platform_docs:
        parts.append(
            "=== Pivony Platform Knowledge ===\n" + format_docs(platform_docs)
        )

    sector_docs = _search_collection(
        client=client,
        embeddings=embeddings,
        collection_name=collection_for_sector(slug),
        question=question,
        k=SECTOR_K,
    )
    if sector_docs:
        parts.append(
            f"=== {slug.replace('-', ' ').title()} Sector Knowledge ===\n"
            + format_review_docs(sector_docs)
        )

    if not parts:
        return "(No relevant documents retrieved from knowledge bases.)"
    return "\n\n".join(parts)


def search_reviews(
    query: str,
    sector_slug: str,
    *,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    k: int | None = None,
) -> str:
    """Sector-only review search with metadata injection (used by the agent tool)."""
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)
    docs = _search_collection(
        client=client,
        embeddings=embeddings,
        collection_name=collection_for_sector(slug),
        question=query,
        k=k or SECTOR_K,
    )
    if not docs:
        return "(Bu konuda ilgili misafir yorumu bulunamadı.)"
    return format_review_docs(docs)


def build_rag_chain(
    *,
    sector_slug: str,
    llm: ChatGoogleGenerativeAI,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    extra_system_prompt: str | None = None,
) -> Runnable:
    """
    Build LCEL chain with master + sector prompts and dual retrieval.

    extra_system_prompt: optional text from pivony-api (org override, UI context).
    """
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)

    system_messages: list[tuple[str, str]] = [("system", MASTER_PROMPT)]
    if extra_system_prompt and extra_system_prompt.strip():
        # From pivony-api: industry + optional org override + UI context (no duplicate sector prompt)
        system_messages.append(("system", extra_system_prompt.strip()))
    else:
        sector_prompt = get_sector_prompt(slug)
        if sector_prompt:
            system_messages.append(("system", sector_prompt))

    prompt = ChatPromptTemplate.from_messages(
        system_messages + [("human", HUMAN_PROMPT)]
    )

    def fetch_context(inputs: dict[str, str]) -> str:
        query = (inputs.get("retrieval_query") or inputs.get("question") or "").strip()
        return retrieve_merged_context(
            query,
            slug,
            embeddings=embeddings,
            client=client,
        )

    def pick_question(inputs: dict[str, str]) -> str:
        return (inputs.get("question") or "").strip()

    def pick_history(inputs: dict[str, str]) -> str:
        return (inputs.get("chat_history") or "(No prior conversation.)").strip()

    return (
        {
            "context": RunnableLambda(fetch_context),
            "question": RunnableLambda(pick_question),
            "chat_history": RunnableLambda(pick_history),
        }
        | prompt
        | llm
        | StrOutputParser()
    )


def invoke_advisor(
    question: str,
    *,
    sector_slug: str = DEFAULT_SECTOR,
    extra_system_prompt: str | None = None,
    chat_history: str | None = None,
    retrieval_query: str | None = None,
    embeddings: GoogleGenerativeAIEmbeddings | None = None,
    client: QdrantClient | None = None,
    llm: ChatGoogleGenerativeAI | None = None,
) -> str:
    """One-shot advisor call (CLI / tests)."""
    embeddings = embeddings or build_embeddings()
    client = client or create_qdrant_client()
    llm = llm or build_llm()
    chain = build_rag_chain(
        sector_slug=sector_slug,
        llm=llm,
        embeddings=embeddings,
        client=client,
        extra_system_prompt=extra_system_prompt,
    )
    return chain.invoke(
        {
            "question": question,
            "chat_history": chat_history or "(No prior conversation.)",
            "retrieval_query": retrieval_query or question,
        }
    )


def extract_api_system_prompt(messages: list[Any]) -> str | None:
    """Concatenate system messages sent by pivony-api (industry override, UI context)."""
    parts: list[str] = []
    for message in messages:
        role = getattr(message, "role", None) or (
            message.get("role") if isinstance(message, dict) else None
        )
        content = getattr(message, "content", None) or (
            message.get("content") if isinstance(message, dict) else None
        )
        if role == "system" and content and str(content).strip():
            parts.append(str(content).strip())
    if not parts:
        return None
    return "\n\n".join(parts)
