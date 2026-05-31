"""Environment and multi-tenant sector/collection configuration."""

from __future__ import annotations

import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env_file_manual(env_path: str) -> None:
    """Parse .env without python-dotenv (KEY=VALUE, optional quotes)."""
    with open(env_path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_project_env() -> None:
    """Load pivony-advisor/.env if present (does not override existing env vars)."""
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except ImportError:
        _load_env_file_manual(env_path)


load_project_env()
CREDS_PATH = os.path.join(BASE_DIR, "config", "google_creds.json")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
ADVISOR_LOG_PATH = os.path.join(LOGS_DIR, "advisor.log")
HISTORY_LOG_PATH = os.path.join(LOGS_DIR, "history.log")

GCP_PROJECT = os.environ.get("GCP_PROJECT", "pivony-ab6d2")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "pivony-advisor")

QDRANT_HOST = os.environ.get("QDRANT_HOST", "127.0.0.1")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_TIMEOUT_SEC = int(os.environ.get("QDRANT_TIMEOUT_SEC", "30"))
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-004")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
NAVIGATION_LLM_TEMPERATURE = float(os.environ.get("NAVIGATION_LLM_TEMPERATURE", "0.3"))
USE_VERTEX_CONTEXTUAL_NAVIGATION = os.environ.get(
    "USE_VERTEX_CONTEXTUAL_NAVIGATION", "true"
).lower() in ("1", "true", "yes")

PLATFORM_K = int(os.environ.get("PLATFORM_RETRIEVER_K", "3"))
SECTOR_K = int(os.environ.get("SECTOR_RETRIEVER_K", "8"))
VECTOR_SIZE = 768

# Agentic RAG: Gemini orchestrates tools (search_qdrant_reviews, get_pivony_metrics)
USE_AGENT = os.environ.get("ADVISOR_USE_AGENT", "true").lower() in ("1", "true", "yes")
AGENT_MAX_TOOL_ITERATIONS = int(os.environ.get("AGENT_MAX_TOOL_ITERATIONS", "4"))

# Faz 3: real freemium-Advisor metrics from pivony-api worker endpoint.
# Full URL to the advisor-metrics route, e.g.
#   http://<pivony-api-host>/api/v1/welcome/worker/advisor-metrics  (production)
#   http://<pivony-api-host>/api/welcome/worker/advisor-metrics     (development)
PIVONY_API_METRICS_URL = os.environ.get("PIVONY_API_METRICS_URL", "").strip()
# Shared secret == pivony-api WELCOME_WORKER_SECRET (X-Welcome-Worker-Key header).
PIVONY_API_WORKER_SECRET = os.environ.get("PIVONY_API_WORKER_SECRET", "").strip()
PIVONY_API_TIMEOUT_SEC = int(os.environ.get("PIVONY_API_TIMEOUT_SEC", "20"))
PIVONY_METRICS_DEFAULT_DAYS = int(os.environ.get("PIVONY_METRICS_DEFAULT_DAYS", "90"))

# GCS folder prefixes → platform knowledge (shared across all sectors)
PLATFORM_PREFIXES = frozenset({"master", "general", "platform"})
PLATFORM_COLLECTION = "pivony_platform_knowledge"
DEFAULT_SECTOR = os.environ.get("DEFAULT_SECTOR", "hospitality")

SUPPORTED_SUFFIXES = (".txt", ".md")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1400"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "200"))


def sector_slugify(industry_name: str) -> str:
    """Normalize Industries.Industry text to a GCS folder / collection slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", (industry_name or "").lower()).strip("-")
    return slug or DEFAULT_SECTOR


def collection_for_sector(sector_slug: str) -> str:
    return f"pivony_sector_{sector_slugify(sector_slug)}"


def resolve_blob_target(blob_name: str) -> tuple[str, str]:
    """
    Map a GCS object path to (collection_name, logical_sector).

    Examples:
      master/guide.txt -> (pivony_platform_knowledge, platform)
      hospitality/ops.txt -> (pivony_sector_hospitality, hospitality)
      pivony_sss.txt (root) -> (pivony_platform_knowledge, platform)
    """
    name = (blob_name or "").strip().lstrip("/")
    if "/" not in name:
        return PLATFORM_COLLECTION, "platform"

    folder = name.split("/", 1)[0].lower()
    if folder in PLATFORM_PREFIXES:
        return PLATFORM_COLLECTION, "platform"

    slug = sector_slugify(folder)
    return collection_for_sector(slug), slug
