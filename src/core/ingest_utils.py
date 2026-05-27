"""GCS document loading and chunking for multi-collection ingest."""

from __future__ import annotations

import re
from collections import defaultdict

from google.cloud import storage
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    SUPPORTED_SUFFIXES,
    resolve_blob_target,
)

HEADER_PATTERN = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def split_by_markdown_sections(text: str, source: str) -> list[Document]:
    matches = list(HEADER_PATTERN.finditer(text))
    if not matches:
        return [Document(page_content=text, metadata={"source": source, "section": "root"})]

    docs: list[Document] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_title = match.group(2).strip()
        body = text[start:end].strip()
        if body:
            docs.append(
                Document(
                    page_content=body,
                    metadata={"source": source, "section": section_title},
                )
            )
    return docs


def enrich_chunk_content(doc: Document, sector: str) -> Document:
    section = doc.metadata.get("section", "")
    source = doc.metadata.get("source", "")
    prefix = f"[Sector: {sector} | Source: {source}"
    if section:
        prefix += f" | Section: {section}"
    prefix += "]\n\n"
    return Document(
        page_content=prefix + doc.page_content,
        metadata={**doc.metadata, "sector": sector},
    )


def load_bucket_documents(
    bucket: storage.Bucket,
) -> dict[str, list[Document]]:
    """Group chunked documents by target Qdrant collection name."""
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    by_collection: dict[str, list[Document]] = defaultdict(list)

    for blob in bucket.list_blobs():
        if not any(blob.name.endswith(suffix) for suffix in SUPPORTED_SUFFIXES):
            continue
        collection_name, sector = resolve_blob_target(blob.name)
        text_content = blob.download_as_text(encoding="utf-8")
        sections = split_by_markdown_sections(text_content, blob.name)
        chunks = char_splitter.split_documents(sections)
        by_collection[collection_name].extend(
            enrich_chunk_content(doc, sector) for doc in chunks
        )

    return dict(by_collection)
