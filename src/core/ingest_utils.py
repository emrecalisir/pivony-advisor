"""GCS document loading and chunking for multi-collection ingest."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

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
REVIEW_META_LINE = re.compile(r"^- ([A-Za-z0-9_\[\]\.]+): (.+)$")


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


def extract_review_metadata_block(section_text: str) -> str:
    """
    Header lines under ### Review N (- Key: value) until review body starts.
    Copied onto every chunk so hotel/date/pivot fields survive text splitting.
    """
    meta_lines: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if REVIEW_META_LINE.match(stripped):
            meta_lines.append(stripped)
            continue
        if meta_lines:
            break
    return "\n".join(meta_lines)


def enrich_chunk_content(
    doc: Document,
    sector: str,
    *,
    review_metadata: str = "",
) -> Document:
    section = doc.metadata.get("section", "")
    source = doc.metadata.get("source", "")
    header = f"[Sector: {sector} | Source: {source}"
    if section:
        header += f" | Section: {section}"
    header += "]"
    parts = [header]
    if review_metadata.strip():
        parts.append(review_metadata.strip())
    prefix = "\n".join(parts) + "\n\n"
    return Document(
        page_content=prefix + doc.page_content,
        metadata={**doc.metadata, "sector": sector},
    )


def chunk_sections_to_documents(
    sections: list[Document],
    char_splitter: RecursiveCharacterTextSplitter,
    sector: str,
) -> list[Document]:
    docs: list[Document] = []
    for section in sections:
        review_meta = extract_review_metadata_block(section.page_content)
        for chunk in char_splitter.split_documents([section]):
            docs.append(
                enrich_chunk_content(chunk, sector, review_metadata=review_meta)
            )
    return docs


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
        by_collection[collection_name].extend(
            chunk_sections_to_documents(sections, char_splitter, sector)
        )

    return dict(by_collection)


ProgressCallback = Callable[[str], None]


def load_local_documents(
    root_dir: str,
    *,
    path_prefix: str = "hospitality",
    progress_every: int = 50,
    on_progress: ProgressCallback | None = None,
) -> dict[str, list[Document]]:
    """
    Load .md/.txt from a local directory (same layout as GCS hospitality/YYYY-MM/).

    Example: INGEST_LOCAL_DIR=output/hospitality -> blob names hospitality/2025-05/part.md
    """
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    by_collection: dict[str, list[Document]] = defaultdict(list)
    root = Path(root_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"INGEST_LOCAL_DIR not found: {root}")

    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.name.endswith(SUPPORTED_SUFFIXES)
    )
    def _emit(message: str) -> None:
        if on_progress:
            on_progress(message)

    _emit(f"Local ingest: {len(files)} file(s) under {root}")
    started = time.monotonic()

    for file_idx, path in enumerate(files, start=1):
        rel = path.relative_to(root).as_posix()
        blob_name = f"{path_prefix}/{rel}" if path_prefix else rel
        collection_name, sector = resolve_blob_target(blob_name)
        text_content = path.read_text(encoding="utf-8")
        sections = split_by_markdown_sections(text_content, blob_name)
        by_collection[collection_name].extend(
            chunk_sections_to_documents(sections, char_splitter, sector)
        )
        if progress_every > 0 and (
            file_idx % progress_every == 0 or file_idx == len(files)
        ):
            chunks_so_far = sum(len(v) for v in by_collection.values())
            elapsed = time.monotonic() - started
            _emit(
                f"Chunking progress: {file_idx}/{len(files)} files, "
                f"{chunks_so_far} chunks, {elapsed:.1f}s — last: {rel}"
            )

    for name, docs in by_collection.items():
        _emit(f"Collection {name}: {len(docs)} chunk(s) ready")

    return dict(by_collection)


def list_markdown_files(root_dir: str | Path) -> list[Path]:
    root = Path(root_dir)
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.name.endswith(SUPPORTED_SUFFIXES)
    )


def documents_from_file(path: Path, blob_name: str) -> tuple[str, str, list[Document]]:
    """Chunk a single file; returns (collection_name, sector, documents)."""
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    collection_name, sector = resolve_blob_target(blob_name)
    text_content = path.read_text(encoding="utf-8")
    sections = split_by_markdown_sections(text_content, blob_name)
    docs = chunk_sections_to_documents(sections, char_splitter, sector)
    return collection_name, sector, docs
