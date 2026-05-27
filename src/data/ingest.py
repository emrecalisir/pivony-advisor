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

INGEST_BUILD = "month-by-month-file-stream-v3"
from core.ingest_utils import (
    documents_from_file,
    list_markdown_files,
    load_bucket_documents,
)
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


class _CollectionIndexer:
    """Reuse Qdrant store per collection; index small doc lists and release memory."""

    def __init__(
        self,
        client: QdrantClient,
        embeddings: GoogleGenerativeAIEmbeddings,
        logger,
    ) -> None:
        self.client = client
        self.embeddings = embeddings
        self.logger = logger
        self._stores: dict[str, QdrantVectorStore] = {}
        self._ready: set[str] = set()
        self.totals: dict[str, int] = {}

    def _ensure_collection(self, collection_name: str, *, recreate: bool) -> None:
        if collection_name in self._ready:
            return
        if recreate:
            self.logger.info("Recreating collection '%s'...", collection_name)
            self.client.recreate_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
        else:
            try:
                self.client.get_collection(collection_name)
            except Exception:
                self.logger.info("Creating collection '%s'...", collection_name)
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
        self._ready.add(collection_name)
        self._stores[collection_name] = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

    def index_documents(
        self,
        collection_name: str,
        docs: list,
        *,
        recreate: bool = False,
    ) -> int:
        if not docs:
            return 0
        self._ensure_collection(collection_name, recreate=recreate)
        store = self._stores[collection_name]
        indexed = 0
        batch_started = time.monotonic()
        for offset in range(0, len(docs), INGEST_BATCH_SIZE):
            batch = docs[offset : offset + INGEST_BATCH_SIZE]
            store.add_documents(batch)
            indexed += len(batch)
            elapsed = time.monotonic() - batch_started
            self.logger.info(
                "Indexing %s: %s chunks this file (%.1fs)",
                collection_name,
                indexed,
                elapsed,
            )
        self.totals[collection_name] = self.totals.get(collection_name, 0) + indexed
        return indexed


def _ingest_local_path(
    local_dir: str,
    local_prefix: str,
    indexer: _CollectionIndexer,
    logger,
    *,
    recreate_first_file: bool,
) -> None:
    """One part file at a time — never hold a full month of chunks in RAM."""
    root = Path(local_dir)
    files = list_markdown_files(root)
    if not files:
        logger.warning("No .md files under %s", local_dir)
        return

    logger.info(
        "File-stream ingest: %s part file(s) under %s (batch=%s)",
        len(files),
        local_dir,
        INGEST_BATCH_SIZE,
    )
    month_chunks = 0
    for file_idx, path in enumerate(files, start=1):
        rel = path.relative_to(root).as_posix()
        blob_name = f"{local_prefix}/{rel}" if local_prefix else rel
        collection_name, _sector, docs = documents_from_file(path, blob_name)
        n = indexer.index_documents(
            collection_name,
            docs,
            recreate=recreate_first_file and file_idx == 1,
        )
        month_chunks += n
        del docs
        if file_idx % max(1, INGEST_PROGRESS_EVERY) == 0 or file_idx == len(files):
            logger.info(
                "File %s/%s: %s (%s chunks, %s month total, collection %s)",
                file_idx,
                len(files),
                path.name,
                n,
                month_chunks,
                indexer.totals.get(collection_name, 0),
            )
        if file_idx % 20 == 0:
            gc.collect()
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
    indexer = _CollectionIndexer(client, embeddings, logger)

    if not months:
        logger.warning("No YYYY-MM subfolders under %s; ingesting as single tree.", root)
        _ingest_local_path(
            root_dir,
            local_prefix,
            indexer,
            logger,
            recreate_first_file=RECREATE_COLLECTIONS,
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
            indexer,
            logger,
            recreate_first_file=RECREATE_COLLECTIONS and idx == 0,
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
    logger.info("Process PID: %s", os.getpid())
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
                indexer = _CollectionIndexer(client, embeddings, logger)
                _ingest_local_path(
                    local_dir,
                    local_prefix,
                    indexer,
                    logger,
                    recreate_first_file=RECREATE_COLLECTIONS,
                )
        else:
            logger.info("Scanning bucket '%s'...", GCS_BUCKET_NAME)
            storage_client = storage.Client(project=GCP_PROJECT)
            bucket = storage_client.bucket(GCS_BUCKET_NAME)
            by_collection = load_bucket_documents(bucket)
            if not by_collection:
                logger.warning("No .txt/.md files found.")
                sys.exit(0)
            indexer = _CollectionIndexer(client, embeddings, logger)
            first = True
            for collection_name, docs in by_collection.items():
                indexer.index_documents(
                    collection_name,
                    docs,
                    recreate=RECREATE_COLLECTIONS and first,
                )
                first = False
                del docs
            gc.collect()
    except Exception as exc:
        logger.error("Ingest failed: %s", exc)
        sys.exit(1)

    logger.info("All collections indexed successfully in %.1fs.", time.monotonic() - started)


if __name__ == "__main__":
    main()
