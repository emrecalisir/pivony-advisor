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

import os
import sys
import time

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
)
from core.ingest_utils import load_bucket_documents, load_local_documents
from ingest_logging import INGEST_LOG_PATH, setup_ingest_logger

if not os.path.exists(CREDS_PATH):
    print(f"ERROR: google_creds.json not found at {CREDS_PATH}")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDS_PATH

RECREATE_COLLECTIONS = os.environ.get("RECREATE_COLLECTIONS", "").lower() in (
    "1",
    "true",
    "yes",
)
INGEST_PROGRESS_EVERY = int(os.environ.get("INGEST_PROGRESS_EVERY", "25"))
INGEST_BATCH_SIZE = int(os.environ.get("INGEST_BATCH_SIZE", "200"))


def _index_collection_batched(
    collection_name: str,
    docs: list,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: QdrantClient,
    logger,
) -> None:
    total = len(docs)
    if RECREATE_COLLECTIONS:
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


def main() -> None:
    logger = setup_ingest_logger()
    started = time.monotonic()
    logger.info("Pivony Advisor - Multi-collection ingestion started")
    logger.info("Log file: %s", INGEST_LOG_PATH)

    local_dir = os.environ.get("INGEST_LOCAL_DIR", "").strip()
    local_prefix = os.environ.get("INGEST_LOCAL_PREFIX", "hospitality").strip()

    if local_dir:
        logger.info(
            "Loading local files from '%s' (prefix=%s, progress_every=%s)",
            local_dir,
            local_prefix or "(none)",
            INGEST_PROGRESS_EVERY,
        )
        try:
            by_collection = load_local_documents(
                local_dir,
                path_prefix=local_prefix,
                progress_every=INGEST_PROGRESS_EVERY,
                on_progress=logger.info,
            )
        except Exception as exc:
            logger.error("Failed to read local directory: %s", exc)
            sys.exit(1)
    else:
        logger.info("Scanning bucket '%s'...", GCS_BUCKET_NAME)
        storage_client = storage.Client(project=GCP_PROJECT)
        try:
            bucket = storage_client.bucket(GCS_BUCKET_NAME)
            by_collection = load_bucket_documents(bucket)
        except Exception as exc:
            logger.error("Failed to read GCS bucket: %s", exc)
            sys.exit(1)

    if not by_collection:
        logger.warning("No .txt/.md files found.")
        sys.exit(0)

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

    for collection_name, docs in by_collection.items():
        logger.info("Start indexing '%s' (%s chunks, batch=%s)", collection_name, len(docs), INGEST_BATCH_SIZE)
        try:
            _index_collection_batched(collection_name, docs, embeddings, client, logger)
            logger.info("SUCCESS: %s (%s chunks).", collection_name, len(docs))
        except Exception as exc:
            logger.error("Failed to index %s: %s", collection_name, exc)
            sys.exit(1)

    logger.info("All collections indexed successfully in %.1fs.", time.monotonic() - started)


if __name__ == "__main__":
    main()
