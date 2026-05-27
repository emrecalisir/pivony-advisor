"""Shared Pivony Advisor configuration, prompts, and RAG utilities."""

from core.config import (
    PLATFORM_COLLECTION,
    PLATFORM_K,
    PLATFORM_PREFIXES,
    SECTOR_K,
    collection_for_sector,
    resolve_blob_target,
    sector_slugify,
)
from core.prompts import MASTER_PROMPT, SECTOR_PROMPTS, get_sector_prompt
from core.rag import (
    build_embeddings,
    build_llm,
    build_rag_chain,
    create_qdrant_client,
    retrieve_merged_context,
)

__all__ = [
    "MASTER_PROMPT",
    "SECTOR_PROMPTS",
    "PLATFORM_COLLECTION",
    "PLATFORM_K",
    "PLATFORM_PREFIXES",
    "SECTOR_K",
    "build_embeddings",
    "build_llm",
    "build_rag_chain",
    "collection_for_sector",
    "create_qdrant_client",
    "get_sector_prompt",
    "resolve_blob_target",
    "retrieve_merged_context",
    "sector_slugify",
]
