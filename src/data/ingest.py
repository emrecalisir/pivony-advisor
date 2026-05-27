"""
Ingest GCS knowledge files into Qdrant collections.

Bucket layout:
  gs://pivony-advisor/master/     -> pivony_platform_knowledge
  gs://pivony-advisor/general/    -> pivony_platform_knowledge
  gs://pivony-advisor/hospitality/ -> pivony_sector_hospitality
  gs://pivony-advisor/{sector}/   -> pivony_sector_{sector}

Root-level .txt/.md files are treated as platform knowledge (legacy).
"""

from __future__ import annotations

import gc
import os
import re
import sys
import time
from pathlib import Path

# Allow imports from src/ (core package lives here)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.dirname(os.path.abspath(__file__))
for _path in (_BASE, _DATA):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from google.cloud import storage
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from core.config import (
    CREDS_PATH,
    GCP_LOCATION,
    GCP_PROJECT,
    GCS_BUCKET_NAME,
    QDRANT_HOST,
    QDRANT_TIMEOUT_SEC,
    QDRANT_URL,
    VECTOR_SIZE,
    load_project_env,
)

INGEST_BUILD = "month-by-month-v2"
from core.ingest_utils import load_bucket_documents, load_local_documents
from ingest_logging import INGEST_LOG_PATH, setup_ingest_logger

if not os.path.exists(CREDS_PATH):
    print(f"ERROR: google_creds.json not found at {CREDS_PATH}")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDS_PATH

RECREATE_COLLECTIONS = False
INGEST_PROGRESS_EVERY = 25
INGEST_BATCH_SIZE = 100
_MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")


def _reload_settings_from_env() -> None:
    """Read .env then refresh module settings (call at start of main)."""
    global RECREATE_COLLECTIONS, INGEST_PROGRESS_EVERY, INGEST_BATCH_SIZE
    load_project_env()
    RECREATE_COLLECTIONS = _parse_bool_env("RECREATE_COLLECTIONS", False)
    INGEST_PROGRESS_EVERY = int(os.environ.get("INGEST_PROGRESS_EVERY", "25"))
    INGEST_BATCH_SIZE = int(os.environ.get("INGEST_BATCH_SIZE", "100"))


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


def _discover_month_dirs(root: Path) -> list[Path]:
    return sorted(
        p for p in root.iterdir() if p.is_dir() and _MONTH_DIR_RE.match(p.name)
    )


def _index_collection_batched(
    collection_name: str,
    docs: list,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    logger,
    *,
    recreate: bool = False,
) -> None:
    total = len(docs)
    if recreate:
        logger.info("Recreating collection '%s'...", collection_name)
        client.recreate_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
    else:
        try:
            client.get_collection(collection_name)
        except Exception:
            logger.info("Creating collection '%s'...", collection_name)
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )
    indexed = 0
    batch_started = time.monotonic()
    for offset in range(0, total, INGEST_BATCH_SIZE):
        batch = docs[offset : offset + INGEST_BATCH_SIZE]
        store.add_documents(batch)
        indexed += len(batch)
        elapsed = time.monotonic() - batch_started
        logger.info(
            "Indexing %s: %s/%s chunks (%.1fs elapsed)",
            collection_name,
            indexed,
            total,
            elapsed,
        )


def _ingest_local_path(
    local_dir: str,
    local_prefix: str,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    logger,
    *,
    recreate: bool,
) -> None:
    by_collection = load_local_documents(
        local_dir,
        path_prefix=local_prefix,
        progress_every=INGEST_PROGRESS_EVERY,
        on_progress=logger.info,
    )
    if not by_collection:
        logger.warning("No chunks from %s", local_dir)
        return

    for collection_name, docs in by_collection.items():
        logger.info(
            "Start indexing '%s' (%s chunks, batch=%s)",
            collection_name,
            len(docs),
            INGEST_BATCH_SIZE,
        )
        _index_collection_batched(
            collection_name,
            docs,
            embeddings,
            client,
            logger,
            recreate=recreate,
        )
        logger.info("SUCCESS: %s (%s chunks).", collection_name, len(docs))
    del by_collection
    gc.collect()


def _filter_month_dirs(months: list[Path], logger) -> list[Path]:
    only_month = os.environ.get("INGEST_ONLY_MONTH", "").strip()
    from_month = os.environ.get("INGEST_FROM_MONTH", "").strip()
    selected: list[Path] = []
    for month_path in months:
        if only_month and month_path.name != only_month:
            continue
        if from_month and month_path.name < from_month:
            logger.info(
                "Skip month %s (INGEST_FROM_MONTH=%s)",
                month_path.name,
                from_month,
            )
            continue
        selected.append(month_path)
    if only_month and not selected:
        logger.warning("INGEST_ONLY_MONTH=%s not found under output.", only_month)
    return selected


def _ingest_local_by_month(
    root_dir: str,
    local_prefix: str,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    logger,
) -> None:
    root = Path(root_dir)
    months = _filter_month_dirs(_discover_month_dirs(root), logger)
    if not months:
        logger.warning("No YYYY-MM subfolders under %s; ingesting as single tree.", root)
        _ingest_local_path(
            root_dir,
            local_prefix,
            embeddings,
            client,
            logger,
            recreate=RECREATE_COLLECTIONS,
        )
        return

    logger.info(
        "Month-by-month ingest: %s folder(s) | RECREATE_COLLECTIONS=%s (append if false)",
        len(months),
        RECREATE_COLLECTIONS,
    )
    for idx, month_path in enumerate(months):
        prefix = f"{local_prefix}/{month_path.name}" if local_prefix else month_path.name
        logger.info("=== Month %s (%s/%s) ===", month_path.name, idx + 1, len(months))
        _ingest_local_path(
            str(month_path),
            prefix,
            embeddings,
            client,
            logger,
            recreate=RECREATE_COLLECTIONS and idx == 0,
        )
        logger.info(
            "=== Month %s COMPLETE (%s/%s) ===",
            month_path.name,
            idx + 1,
            len(months),
        )


def main() -> None:
    _reload_settings_from_env()
    logger = setup_ingest_logger()
    started = time.monotonic()
    logger.info("Pivony Advisor - Multi-collection ingestion started")
    logger.info("Ingest build: %s (expect month-by-month logs below)", INGEST_BUILD)
    logger.info("Log file: %s", INGEST_LOG_PATH)
    logger.info(
        "Settings: RECREATE_COLLECTIONS=%s INGEST_BATCH_SIZE=%s INGEST_PROGRESS_EVERY=%s",
        RECREATE_COLLECTIONS,
        INGEST_BATCH_SIZE,
        INGEST_PROGRESS_EVERY,
    )

    local_dir = os.environ.get("INGEST_LOCAL_DIR", "").strip()
    local_prefix = os.environ.get("INGEST_LOCAL_PREFIX", "hospitality").strip()

    logger.info("Loading Vertex AI embeddings (text-embedding-004)...")
    embeddings = GoogleGenerativeAIEmbeddings(
        model="text-embedding-004",
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        vertexai=True,
    )

    logger.info("Connecting to Qdrant at %s...", QDRANT_URL)
    try:
        client = QdrantClient(url=QDRANT_URL, timeout=QDRANT_TIMEOUT_SEC)
        client.get_collections()
        logger.info("Qdrant is reachable.")
    except Exception as exc:
        logger.error("Cannot reach Qdrant: %s", exc)
        sys.exit(1)

    try:
        if local_dir:
            root = Path(local_dir)
            month_dirs = _discover_month_dirs(root)
            by_month_default = bool(month_dirs)
            ingest_by_month = _parse_bool_env("INGEST_BY_MONTH", by_month_default)
            logger.info(
                "Local ingest '%s' prefix=%s progress_every=%s by_month=%s",
                local_dir,
                local_prefix or "(none)",
                INGEST_PROGRESS_EVERY,
                ingest_by_month,
            )
            if ingest_by_month:
                _ingest_local_by_month(local_dir, local_prefix, embeddings, client, logger)
            else:
                _ingest_local_path(
                    local_dir,
                    local_prefix,
                    embeddings,
                    client,
                    logger,
                    recreate=RECREATE_COLLECTIONS,
                )
        else:
            logger.info("Scanning bucket '%s'...", GCS_BUCKET_NAME)
            storage_client = storage.Client(project=GCP_PROJECT)
            bucket = storage_client.bucket(GCS_BUCKET_NAME)
            by_collection = load_bucket_documents(bucket)
            if not by_collection:
                logger.warning("No .txt/.md files found.")
                sys.exit(0)
            for collection_name, docs in by_collection.items():
                _index_collection_batched(
                    collection_name,
                    docs,
                    embeddings,
                    client,
                    logger,
                    recreate=RECREATE_COLLECTIONS,
                )
    except Exception as exc:
        logger.error("Ingest failed: %s", exc)
        sys.exit(1)

    logger.info("All collections indexed successfully in %.1fs.", time.monotonic() - started)


if __name__ == "__main__":
    main()
