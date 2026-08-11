"""Qdrant operations for Sonic Prospect — org_id + bot_id isolation."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from core.config import VECTOR_SIZE
from core.rag import build_embeddings, create_qdrant_client
from prospect.config import PROSPECT_COLLECTION, PROSPECT_RETRIEVER_K
from prospect.point_ids import prospect_point_id

logger = logging.getLogger(__name__)


def tenant_filter(org_id: str, bot_id: str | int) -> Filter:
    return Filter(
        must=[
            FieldCondition(key="org_id", match=MatchValue(value=str(org_id))),
            FieldCondition(key="bot_id", match=MatchValue(value=str(bot_id))),
        ]
    )


def ensure_collection(client: QdrantClient) -> None:
    names = {c.name for c in client.get_collections().collections}
    if PROSPECT_COLLECTION in names:
        return
    client.create_collection(
        collection_name=PROSPECT_COLLECTION,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    logger.info("Created Qdrant collection %s", PROSPECT_COLLECTION)


def delete_bot_points(
    client: QdrantClient,
    *,
    org_id: str,
    bot_id: str | int,
) -> None:
    ensure_collection(client)
    client.delete(
        collection_name=PROSPECT_COLLECTION,
        points_selector=FilterSelector(filter=tenant_filter(org_id, bot_id)),
    )


def upsert_documents(
    client: QdrantClient,
    embeddings: GoogleGenerativeAIEmbeddings,
    documents: list[Document],
    *,
    org_id: str,
    bot_id: str | int,
    bot_slug: str = "",
) -> int:
    if not documents:
        return 0
    ensure_collection(client)
    texts = [doc.page_content for doc in documents]
    vectors = embeddings.embed_documents(texts)
    points: list[PointStruct] = []
    for doc, vector in zip(documents, vectors):
        meta = dict(doc.metadata or {})
        source_type = meta.get("source_type", "text")
        source_id = meta.get("source_id", "unknown")
        chunk_index = int(meta.get("chunk_index", 0))
        payload = {
            "org_id": str(org_id),
            "bot_id": str(bot_id),
            "bot_slug": bot_slug or "",
            "source_type": source_type,
            "source_id": source_id,
            "chunk_index": chunk_index,
            "title": meta.get("title") or "",
            "page_content": doc.page_content,
        }
        points.append(
            PointStruct(
                id=prospect_point_id(
                    org_id=str(org_id),
                    bot_id=bot_id,
                    source_type=source_type,
                    source_id=source_id,
                    chunk_index=chunk_index,
                ),
                vector=vector,
                payload=payload,
            )
        )
    client.upsert(collection_name=PROSPECT_COLLECTION, points=points)
    return len(points)


def search_bot_knowledge(
    *,
    org_id: str,
    bot_id: str | int,
    query: str,
    k: int | None = None,
    client: QdrantClient | None = None,
    embeddings: GoogleGenerativeAIEmbeddings | None = None,
) -> list[dict[str, Any]]:
    client = client or create_qdrant_client()
    embeddings = embeddings or build_embeddings()
    ensure_collection(client)
    vector = embeddings.embed_query(query)
    hits = client.search(
        collection_name=PROSPECT_COLLECTION,
        query_vector=vector,
        query_filter=tenant_filter(org_id, bot_id),
        limit=k or PROSPECT_RETRIEVER_K,
        with_payload=True,
    )
    results: list[dict[str, Any]] = []
    for hit in hits:
        payload = hit.payload or {}
        results.append(
            {
                "score": hit.score,
                "source_type": payload.get("source_type"),
                "source_id": payload.get("source_id"),
                "chunk_index": payload.get("chunk_index"),
                "snippet": (payload.get("page_content") or "")[:500],
            }
        )
    return results
