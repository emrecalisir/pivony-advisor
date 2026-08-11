"""Deterministic Qdrant point IDs for Sonic Prospect chunks."""

from __future__ import annotations

import uuid

_NAMESPACE = uuid.UUID("b7e4f1a2-9c3d-4f8e-a1b2-3c4d5e6f7081")


def prospect_point_id(
    *,
    org_id: str,
    bot_id: str | int,
    source_type: str,
    source_id: str,
    chunk_index: int,
) -> str:
    key = f"{org_id}|{bot_id}|{source_type}|{source_id}|{chunk_index}"
    return str(uuid.uuid5(_NAMESPACE, key))
