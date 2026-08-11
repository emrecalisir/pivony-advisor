"""Sonic Prospect RAG configuration."""

from __future__ import annotations

import os

PROSPECT_COLLECTION = os.environ.get(
    "SONIC_PROSPECT_QDRANT_COLLECTION", "sonic_prospect_knowledge"
)
PROSPECT_RETRIEVER_K = int(os.environ.get("SONIC_PROSPECT_RETRIEVER_K", "8"))
CHUNK_SIZE = int(os.environ.get("SONIC_PROSPECT_CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.environ.get("SONIC_PROSPECT_CHUNK_OVERLAP", "150"))
SONIC_PROSPECT_RAG_SECRET = os.environ.get("SONIC_PROSPECT_RAG_SECRET", "").strip()
PROSPECT_LLM_MODEL = (
    os.environ.get("SONIC_PROSPECT_LLM_MODEL")
    or os.environ.get("ADVISOR_LLM_MODEL")
    or os.environ.get("LLM_MODEL")
    or "gemini-2.5-flash"
).strip()
