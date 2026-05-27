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

# Allow imports from src/
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.dirname(_BASE)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

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
from core.ingest_utils import load_bucket_documents

if not os.path.exists(CREDS_PATH):
    print(f"ERROR: google_creds.json not found at {CREDS_PATH}")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDS_PATH

RECREATE_COLLECTIONS = os.environ.get("RECREATE_COLLECTIONS", "").lower() in (
    "1",
    "true",
    "yes",
)


def main() -> None:
    print("Pivony Advisor - Multi-collection ingestion started...")
    print(f"Scanning bucket '{GCS_BUCKET_NAME}'...")

    storage_client = storage.Client(project=GCP_PROJECT)
    try:
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        by_collection = load_bucket_documents(bucket)
    except Exception as exc:
        print(f"ERROR: Failed to read GCS bucket: {exc}")
        sys.exit(1)

    if not by_collection:
        print("WARNING: No .txt/.md files found.")
        print("Example layout (use real KC docs, not bucket-root test files):")
        print(f"  gs://{GCS_BUCKET_NAME}/master/PIVONY_MASTER_GUIDE.md")
        print(f"  gs://{GCS_BUCKET_NAME}/hospitality/your-sector-docs.md")
        sys.exit(0)

    for collection_name, docs in by_collection.items():
        print(f"  {collection_name}: {len(docs)} chunk(s)")

    print("Loading Vertex AI embeddings (text-embedding-004)...")
    embeddings = GoogleGenerativeAIEmbeddings(
        model="text-embedding-004",
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        vertexai=True,
    )

    print(f"Connecting to Qdrant at {QDRANT_URL}...")
    try:
        client = QdrantClient(url=QDRANT_URL, timeout=QDRANT_TIMEOUT_SEC)
        client.get_collections()
        print("Qdrant is reachable.")
    except Exception as exc:
        print(f"ERROR: Cannot reach Qdrant: {exc}")
        sys.exit(1)

    for collection_name, docs in by_collection.items():
        if RECREATE_COLLECTIONS:
            print(f"Recreating collection '{collection_name}'...")
            client.recreate_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

        print(f"Indexing {len(docs)} chunks into '{collection_name}'...")
        try:
            QdrantVectorStore.from_documents(
                documents=docs,
                embedding=embeddings,
                url=QDRANT_URL,
                collection_name=collection_name,
                timeout=QDRANT_TIMEOUT_SEC,
            )
            print(f"SUCCESS: {collection_name} ({len(docs)} chunks).")
        except Exception as exc:
            print(f"ERROR: Failed to index {collection_name}: {exc}")
            sys.exit(1)

    print("All collections indexed successfully.")


if __name__ == "__main__":
    main()
