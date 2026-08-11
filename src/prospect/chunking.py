"""FAQ and free-text chunking for Sonic Prospect ingest."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from prospect.config import CHUNK_OVERLAP, CHUNK_SIZE


def _prefix(org_id: str, bot_id: str | int, source_type: str, source_id: str) -> str:
    return f"[Org: {org_id}][Bot: {bot_id}][Source: {source_type}:{source_id}]\n"


def faq_documents(
    *,
    org_id: str,
    bot_id: str | int,
    faq_items: list[dict],
) -> list[Document]:
    docs: list[Document] = []
    for index, item in enumerate(faq_items or []):
        q = (item.get("q") or "").strip()
        a = (item.get("a") or "").strip()
        if not q or not a:
            continue
        source_id = f"faq_{index}"
        body = f"Q: {q}\nA: {a}"
        docs.append(
            Document(
                page_content=_prefix(org_id, bot_id, "faq", source_id) + body,
                metadata={
                    "org_id": org_id,
                    "bot_id": str(bot_id),
                    "source_type": "faq",
                    "source_id": source_id,
                    "chunk_index": 0,
                },
            )
        )
    return docs


def text_documents(
    *,
    org_id: str,
    bot_id: str | int,
    source_type: str,
    source_id: str,
    title: str,
    text: str,
) -> list[Document]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(cleaned)
    docs: list[Document] = []
    for index, chunk in enumerate(chunks):
        header = _prefix(org_id, bot_id, source_type, source_id)
        if title:
            header += f"Title: {title}\n"
        docs.append(
            Document(
                page_content=header + chunk,
                metadata={
                    "org_id": org_id,
                    "bot_id": str(bot_id),
                    "source_type": source_type,
                    "source_id": source_id,
                    "chunk_index": index,
                    "title": title,
                },
            )
        )
    return docs
