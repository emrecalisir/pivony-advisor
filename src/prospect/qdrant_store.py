"""Qdrant operations for Sonic Prospect — strict org_id + bot_id tenant isolation."""

from __future__ import annotations

import logging
import re
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
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from core.config import VECTOR_SIZE
from core.rag import build_embeddings, create_qdrant_client
from prospect.config import PROSPECT_COLLECTION, PROSPECT_RETRIEVER_K
from prospect.point_ids import prospect_point_id

logger = logging.getLogger(__name__)

_TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")


def _validate_tenant_ids(org_id: str, bot_id: str | int) -> tuple[str, str]:
    org = str(org_id or "").strip()
    bot = str(bot_id or "").strip()
    if not org or not bot:
        raise ValueError("org_id and bot_id are required for tenant-scoped Qdrant access")
    if not _TENANT_ID_PATTERN.match(org):
        raise ValueError("invalid org_id for Qdrant tenant filter")
    if not _TENANT_ID_PATTERN.match(bot):
        raise ValueError("invalid bot_id for Qdrant tenant filter")
    return org, bot


def tenant_filter(org_id: str, bot_id: str | int) -> Filter:
    org, bot = _validate_tenant_ids(org_id, bot_id)
    return Filter(
        must=[
            FieldCondition(key="org_id", match=MatchValue(value=org)),
            FieldCondition(key="bot_id", match=MatchValue(value=bot)),
        ]
    )


def ensure_collection(client: QdrantClient) -> None:
    names = {c.name for c in client.get_collections().collections}
    if PROSPECT_COLLECTION not in names:
        client.create_collection(
            collection_name=PROSPECT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection %s", PROSPECT_COLLECTION)
    for field_name in ("org_id", "bot_id"):
        try:
            client.create_payload_index(
                collection_name=PROSPECT_COLLECTION,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:
            logger.debug(
                "Payload index %s on %s skipped: %s",
                field_name,
                PROSPECT_COLLECTION,
                exc,
            )


def delete_bot_points(
    client: QdrantClient,
    *,
    org_id: str,
    bot_id: str | int,
) -> None:
    org, bot = _validate_tenant_ids(org_id, bot_id)
    ensure_collection(client)
    client.delete(
        collection_name=PROSPECT_COLLECTION,
        points_selector=FilterSelector(filter=tenant_filter(org, bot)),
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
    org, bot = _validate_tenant_ids(org_id, bot_id)
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
            "org_id": org,
            "bot_id": bot,
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
                    org_id=org,
                    bot_id=bot,
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
    org, bot = _validate_tenant_ids(org_id, bot_id)
    client = client or create_qdrant_client()
    embeddings = embeddings or build_embeddings()
    ensure_collection(client)
    vector = embeddings.embed_query(query)
    response = client.query_points(
        collection_name=PROSPECT_COLLECTION,
        query=vector,
        query_filter=tenant_filter(org, bot),
        limit=k or PROSPECT_RETRIEVER_K,
        with_payload=True,
    )
    hits = response.points or []
    results: list[dict[str, Any]] = []
    for hit in hits:
        payload = hit.payload or {}
        hit_org = str(payload.get("org_id") or "")
        hit_bot = str(payload.get("bot_id") or "")
        if hit_org != org or hit_bot != bot:
            logger.error(
                "Qdrant tenant leak blocked org=%s bot=%s hit_org=%s hit_bot=%s",
                org,
                bot,
                hit_org,
                hit_bot,
            )
            continue
        results.append(
            {
                "score": hit.score,
                "source_type": payload.get("source_type"),
                "source_id": payload.get("source_id"),
                "chunk_index": payload.get("chunk_index"),
                "title": payload.get("title"),
                "url": payload.get("url"),
                "snippet": (payload.get("page_content") or "")[:500],
            }
        )
    return results
