"""Deterministic Qdrant point IDs — re-indexing the same chunk replaces, not duplicates."""

from __future__ import annotations

import uuid

# Fixed namespace for stable UUID5 ids across runs.
_NAMESPACE = uuid.UUID("a3f8c2e1-7b4d-4e9a-9c1f-8e2d6b5a4f30")


def stable_point_id(collection_name: str, source_blob: str, chunk_index: int) -> str:
    key = f"{collection_name}|{source_blob}|{chunk_index}"
    return str(uuid.uuid5(_NAMESPACE, key))
