"""Ingest FAQ + PDF knowledge for a single Sonic Prospect bot."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.documents import Document
from qdrant_client import QdrantClient

from core.rag import build_embeddings, create_qdrant_client
from prospect.chunking import faq_documents, text_documents
from prospect.pdf_extract import extract_pdf_text
from prospect.qdrant_store import delete_bot_points, upsert_documents

logger = logging.getLogger(__name__)


def build_documents_from_payload(payload: dict[str, Any]) -> tuple[list[Document], list[str]]:
    org_id = str(payload.get("org_id") or "").strip()
    bot_id = payload.get("bot_id")
    if not org_id or bot_id is None:
        raise ValueError("org_id and bot_id are required")

    docs: list[Document] = []
    errors: list[str] = []

    docs.extend(
        faq_documents(
            org_id=org_id,
            bot_id=bot_id,
            faq_items=payload.get("faq_items") or [],
        )
    )

    for pdf in payload.get("pdf_documents") or []:
        doc_id = (pdf.get("id") or "").strip()
        name = (pdf.get("name") or "document.pdf").strip()
        url = (pdf.get("url") or "").strip()
        if not doc_id or not url:
            continue
        try:
            text = extract_pdf_text(url)
            docs.extend(
                text_documents(
                    org_id=org_id,
                    bot_id=bot_id,
                    source_type="pdf",
                    source_id=f"pdf_{doc_id}",
                    title=name,
                    text=text,
                )
            )
        except Exception as exc:
            msg = f"PDF ingest failed for {name}: {exc}"
            logger.warning(msg)
            errors.append(msg)

    return docs, errors


def ingest_bot_knowledge(
    payload: dict[str, Any],
    *,
    client: QdrantClient | None = None,
) -> dict[str, Any]:
    org_id = str(payload.get("org_id") or "").strip()
    bot_id = payload.get("bot_id")
    bot_slug = (payload.get("bot_slug") or "").strip()
    if not org_id or bot_id is None:
        raise ValueError("org_id and bot_id are required")

    client = client or create_qdrant_client()
    embeddings = build_embeddings()

    delete_bot_points(client, org_id=org_id, bot_id=bot_id)
    documents, pdf_errors = build_documents_from_payload(payload)
    count = upsert_documents(
        client,
        embeddings,
        documents,
        org_id=org_id,
        bot_id=bot_id,
        bot_slug=bot_slug,
    )

    status = "ready" if not pdf_errors else ("ready" if count else "failed")
    return {
        "status": status,
        "chunk_count": count,
        "pdf_errors": pdf_errors,
        "org_id": org_id,
        "bot_id": bot_id,
    }
