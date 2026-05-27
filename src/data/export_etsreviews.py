"""
Export MongoDB `etsreviews` (last N days) into hospitality knowledge files for RAG ingest.

Does NOT train an LLM — builds text corpora under output/hospitality/ then you run:
  gsutil -m cp -r output/hospitality gs://pivony-advisor/hospitality/
  python src/data/ingest.py

Configure field names via env (see docs/HOSPITALITY_ETSREVIEWS.md).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# core package lives under src/ (same as ingest.py)
_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_advisor_config():
    """Load config.py without importing core.__init__ (avoids RAG/LLM deps)."""
    import importlib.util

    config_path = os.path.join(_SRC, "core", "config.py")
    spec = importlib.util.spec_from_file_location("pivony_advisor_config", config_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load config from {config_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_config = _load_advisor_config()
BASE_DIR = _config.BASE_DIR
LOGS_DIR = getattr(_config, "LOGS_DIR", os.path.join(BASE_DIR, "logs"))
EXPORT_LOG_PATH = os.environ.get(
    "ETS_EXPORT_LOG_PATH", os.path.join(LOGS_DIR, "ets_export.log")
)

_logger: logging.Logger | None = None


def _setup_export_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    os.makedirs(LOGS_DIR, exist_ok=True)
    logger = logging.getLogger("pivony.export.etsreviews")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(EXPORT_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    _logger = logger
    return logger


def _log(level: int, message: str, *args: object) -> None:
    _setup_export_logger().log(level, message, *args)

# ---------------------------------------------------------------------------
# Configuration (.env) — canonical: PRODUCTION_MONGODB_URI, MONGO_COLLECTION
# ---------------------------------------------------------------------------
MONGODB_URI = (
    os.environ.get("PRODUCTION_MONGODB_URI", "")
    or os.environ.get("MONGODB_URI", "")
    or os.environ.get("MONGODB_CONNECTION_STRING", "")
)
MONGODB_DB = (
    os.environ.get("MONGODB_DB", "")
    or os.environ.get("PRODUCTION_MONGODB_DATABASE", "")
    or os.environ.get("MONGODB_DATABASE_NAME", "")
    or "production"
)
MONGODB_COLLECTION = (
    os.environ.get("MONGO_COLLECTION", "")
    or os.environ.get("MONGODB_COLLECTION", "")
    or "ETSReviews"
)

# Date: in Mongo, ReviewSubmissionDate is stored as sk ("dd-mm-yyyy HH:mm:ss")
DATE_FIELDS = [
    f.strip()
    for f in os.environ.get("ETS_DATE_FIELD", "sk,ReviewSubmissionDate").split(",")
    if f.strip()
]
DAYS_BACK = int(os.environ.get("ETS_DAYS_BACK", "365"))

# Text / metadata (ETS API schema: ReviewContent, ReviewTitle, Rating)
TEXT_FIELDS = [
    f.strip()
    for f in os.environ.get(
        "ETS_TEXT_FIELDS",
        "ReviewContent,ReviewText,reviewText,review_text,text,comment,body,content",
    ).split(",")
    if f.strip()
]
TITLE_FIELDS = [
    f.strip()
    for f in os.environ.get(
        "ETS_TITLE_FIELDS", "ReviewTitle,title,hotelName,hotel_name,propertyName"
    ).split(",")
    if f.strip()
]
RATING_FIELDS = [
    f.strip()
    for f in os.environ.get("ETS_RATING_FIELDS", "Rating,rating,score,stars,num_rating").split(
        ","
    )
    if f.strip()
]
SOURCE_FIELDS = [
    f.strip()
    for f in os.environ.get("ETS_SOURCE_FIELDS", "source,channel,platform").split(",")
    if f.strip()
]

# Export layout: output/hospitality/YYYY-MM/etsreviews_part_NNN.md (always chunked)
REVIEWS_PER_FILE = int(os.environ.get("ETS_REVIEWS_PER_FILE", "200"))
MAX_REVIEWS = int(os.environ.get("ETS_MAX_REVIEWS", "0"))  # 0 = no limit
CURSOR_BATCH_SIZE = int(os.environ.get("ETS_CURSOR_BATCH_SIZE", "100"))
SKIP_EXISTING = os.environ.get("ETS_SKIP_EXISTING", "").lower() in ("1", "true", "yes")
OUTPUT_DIR = Path(
    os.environ.get("ETS_OUTPUT_DIR", os.path.join(BASE_DIR, "output", "hospitality"))
)

# Optional Mongo filter JSON, e.g. {"status":"published"}
EXTRA_FILTER_JSON = os.environ.get("ETS_EXTRA_FILTER_JSON", "")


def _first_value(doc: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in doc and doc[key] not in (None, ""):
            return doc[key]
    return None


def _doc_review_date(doc: dict[str, Any]) -> datetime | None:
    for field in DATE_FIELDS:
        parsed = _parse_date(doc.get(field))
        if parsed:
            return parsed
    return None


def _property_name(doc: dict[str, Any]) -> str | None:
    attrs = doc.get("CustomAttributes") or {}
    if isinstance(attrs, dict):
        for key in ("vendorName", "projectName"):
            val = attrs.get(key)
            if val and str(val).strip():
                return str(val).strip()
    title = _first_value(doc, TITLE_FIELDS)
    return str(title).strip() if title else None


def _review_source(doc: dict[str, Any]) -> str | None:
    attrs = doc.get("CustomAttributes") or {}
    if isinstance(attrs, dict):
        for key in ("channel", "clientName"):
            val = attrs.get(key)
            if val and str(val).strip():
                return str(val).strip()
    source = _first_value(doc, SOURCE_FIELDS)
    return str(source).strip() if source else None


def _coalesce_date_field_expr() -> dict[str, Any]:
    """Mongo $ifNull chain: sk first, then ReviewSubmissionDate, etc."""
    expr: Any = f"${DATE_FIELDS[0]}"
    for field in DATE_FIELDS[1:]:
        expr = {"$ifNull": [expr, f"${field}"]}
    return expr


def _parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        value = value.strip()
        for fmt in ("%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _review_text(doc: dict[str, Any]) -> str | None:
    text = _first_value(doc, TEXT_FIELDS)
    if not text:
        return None
    text = str(text).strip()
    return text or None


def _write_review_lines(fh, doc: dict[str, Any], index: int) -> bool:
    """Stream one review to an open append handle (no in-memory block string)."""
    text = _review_text(doc)
    if not text:
        return False

    title = _property_name(doc)
    rating = _first_value(doc, RATING_FIELDS)
    source = _review_source(doc)
    when = _doc_review_date(doc)
    survey_id = doc.get("pk") or doc.get("sk")

    fh.write(f"### Review {index}\n")
    if survey_id:
        fh.write(f"- Survey: {survey_id}\n")
    if title:
        fh.write(f"- Property: {title}\n")
    if rating is not None:
        fh.write(f"- Rating: {rating}\n")
    if source:
        fh.write(f"- Source: {source}\n")
    if when:
        fh.write(f"- Date: {when.date().isoformat()}\n")
    fh.write("\n")
    fh.write(text)
    return True


def _base_match() -> dict[str, Any]:
    """Full review rows only (not s#0..s#4 partition pointers)."""
    text_clause = [{f: {"$exists": True, "$ne": ""}} for f in TEXT_FIELDS[:3]]
    match: dict[str, Any] = {"pk": {"$not": {"$regex": r"^s#\d+$"}}}
    if text_clause:
        match["$or"] = text_clause
    return match


def _projection_fields() -> dict[str, int]:
    """Only fields needed for export — omit Analysis / subQuestionAnalysis blobs."""
    projection: dict[str, int] = {
        "pk": 1,
        "sk": 1,
        "CustomAttributes.vendorName": 1,
        "CustomAttributes.projectName": 1,
        "CustomAttributes.channel": 1,
        "CustomAttributes.clientName": 1,
    }
    for field in DATE_FIELDS + TEXT_FIELDS + TITLE_FIELDS + RATING_FIELDS + SOURCE_FIELDS:
        projection[field] = 1
    return projection


def _month_windows(since: datetime, until: datetime):
    """Yield (window_start, window_end, YYYY-MM) calendar months in [since, until)."""
    current = datetime(since.year, since.month, 1, tzinfo=timezone.utc)
    while current < until:
        if current.month == 12:
            next_month = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(current.year, current.month + 1, 1, tzinfo=timezone.utc)
        window_start = max(current, since)
        window_end = min(next_month, until)
        if window_start < window_end:
            yield window_start, window_end, current.strftime("%Y-%m")
        current = next_month


def _build_pipeline(date_start: datetime, date_end: datetime) -> list[dict[str, Any]]:
    projection = _projection_fields()
    match_stage = _base_match()
    if EXTRA_FILTER_JSON.strip():
        extra = json.loads(EXTRA_FILTER_JSON)
        match_stage = {"$and": [match_stage, extra]}

    pipeline: list[dict[str, Any]] = [
        {"$match": match_stage},
        {
            "$addFields": {
                "_parsedDate": {
                    "$dateFromString": {
                        "dateString": _coalesce_date_field_expr(),
                        "format": "%d-%m-%Y %H:%M:%S",
                        "onError": None,
                        "onNull": None,
                    }
                }
            }
        },
        {"$match": {"_parsedDate": {"$gte": date_start, "$lt": date_end}}},
        {"$sort": {"_parsedDate": -1}},
        {"$project": projection},
    ]
    return pipeline


def _iter_month_documents(collection, since: datetime, until: datetime):
    """Stream reviews month-by-month to limit memory (client + server)."""
    for window_start, window_end, month_key in _month_windows(since, until):
        month_dir = OUTPUT_DIR / month_key
        if SKIP_EXISTING and month_dir.is_dir() and any(month_dir.glob("*.md")):
            _log(logging.INFO, "Skip month %s (folder already has .md files)", month_key)
            continue

        pipeline = _build_pipeline(window_start, window_end)
        _log(
            logging.INFO,
            "Query month %s (%s .. %s)",
            month_key,
            window_start.date(),
            window_end.date(),
        )
        cursor = collection.aggregate(
            pipeline,
            allowDiskUse=True,
            batchSize=CURSOR_BATCH_SIZE,
        )
        for doc in cursor:
            yield month_key, doc


class _MonthFileWriter:
    """Keep one append handle per month; rotate part files; no in-RAM batching."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._part: dict[str, int] = defaultdict(lambda: 1)
        self._count: dict[str, int] = defaultdict(int)
        self._handles: dict[str, Any] = {}
        self.files_written = 0

    def _close_month(self, month_key: str) -> None:
        fh = self._handles.pop(month_key, None)
        if fh is not None:
            fh.close()

    def _open_part(self, month_key: str) -> Any:
        self._close_month(month_key)
        month_dir = self.out_dir / month_key
        month_dir.mkdir(parents=True, exist_ok=True)
        path = month_dir / f"etsreviews_part_{self._part[month_key]:03d}.md"
        new_file = not path.exists()
        fh = path.open("a", encoding="utf-8")
        self._handles[month_key] = fh
        if new_file:
            fh.write(_month_header(month_key))
            self.files_written += 1
            _log(logging.INFO, "Opened %s (append)", path)
        return fh

    def _ensure_handle(self, month_key: str) -> Any:
        if self._count[month_key] >= REVIEWS_PER_FILE and month_key in self._handles:
            self._part[month_key] += 1
            self._count[month_key] = 0
            return self._open_part(month_key)
        if month_key not in self._handles:
            return self._open_part(month_key)
        return self._handles[month_key]

    def append_doc(self, month_key: str, doc: dict[str, Any], index: int) -> bool:
        fh = self._ensure_handle(month_key)
        if self._count[month_key] > 0:
            fh.write("\n\n")
        if not _write_review_lines(fh, doc, index):
            return False
        fh.flush()
        self._count[month_key] += 1
        return True

    def close(self) -> None:
        for month_key in list(self._handles):
            self._close_month(month_key)


def _month_header(month_key: str) -> str:
    return (
        f"# ETS Reviews — {month_key}\n\n"
        "Guest review corpus for hospitality advisor (exported from MongoDB).\n\n"
    )


def _diagnose_missing_mongo_env() -> None:
    env_file = os.path.join(BASE_DIR, ".env")
    _log(logging.ERROR, "PRODUCTION_MONGODB_URI is empty.")
    _log(logging.ERROR, "Expected .env at: %s (exists=%s)", env_file, os.path.isfile(env_file))
    try:
        import dotenv  # noqa: F401

        _log(logging.INFO, "python-dotenv: installed")
    except ImportError:
        _log(logging.INFO, "python-dotenv: not installed (using built-in .env parser)")
    if os.path.isfile(env_file):
        keys = []
        with open(env_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                keys.append(line.split("=", 1)[0].strip())
        _log(logging.INFO, "Keys in .env: %s", ", ".join(keys) or "(none)")
        if "PRODUCTION_MONGODB_URI" not in keys:
            _log(logging.ERROR, "Add PRODUCTION_MONGODB_URI=... to .env")
    else:
        _log(logging.ERROR, "Run: cp .env.example .env && nano .env")
    _log(logging.INFO, "See docs/HOSPITALITY_ETSREVIEWS.md")


def main() -> None:
    if not MONGODB_URI:
        _diagnose_missing_mongo_env()
        sys.exit(1)

    try:
        from pymongo import MongoClient
    except ImportError:
        _log(logging.ERROR, "pip install pymongo")
        sys.exit(1)

    logger = _setup_export_logger()
    started = time.monotonic()
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=DAYS_BACK)
    logger.info("Log file: %s", EXPORT_LOG_PATH)
    logger.info("Connecting to MongoDB db=%s collection=%s", MONGODB_DB, MONGODB_COLLECTION)
    logger.info(
        "Export range %s .. %s | date_fields=%s | batch=%s | part_size=%s | max=%s",
        since.date(),
        until.date(),
        DATE_FIELDS,
        CURSOR_BATCH_SIZE,
        REVIEWS_PER_FILE,
        MAX_REVIEWS or "unlimited",
    )

    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    collection = client[MONGODB_DB][MONGODB_COLLECTION]

    writer = _MonthFileWriter(OUTPUT_DIR)
    exported = 0
    skipped = 0
    idx = 0
    current_month: str | None = None
    month_exported = 0

    try:
        for month_key, doc in _iter_month_documents(collection, since, until):
            if month_key != current_month:
                if current_month is not None:
                    logger.info(
                        "Month %s done: %s reviews exported",
                        current_month,
                        month_exported,
                    )
                current_month = month_key
                month_exported = 0
                logger.info("Month %s started", month_key)

            if MAX_REVIEWS > 0 and exported >= MAX_REVIEWS:
                logger.info("Reached ETS_MAX_REVIEWS=%s, stopping.", MAX_REVIEWS)
                break
            idx += 1
            if writer.append_doc(month_key, doc, idx):
                exported += 1
                month_exported += 1
            else:
                skipped += 1
            del doc
            if exported % 1000 == 0 and exported > 0:
                elapsed = time.monotonic() - started
                logger.info(
                    "Progress: %s exported, %s skipped, %.1fs elapsed",
                    exported,
                    skipped,
                    elapsed,
                )
    finally:
        writer.close()
        if current_month is not None:
            logger.info(
                "Month %s done: %s reviews exported",
                current_month,
                month_exported,
            )

    elapsed = time.monotonic() - started
    if exported == 0:
        logger.warning(
            "No documents matched. Check ETS_DATE_FIELD / ETS_EXTRA_FILTER_JSON."
        )
        sample = collection.find_one(_base_match())
        if sample:
            logger.info("Sample document keys: %s", sorted(sample.keys()))
        sys.exit(0)

    logger.info(
        "Finished: exported=%s skipped=%s part_files=%s elapsed=%.1fs output=%s",
        exported,
        skipped,
        writer.files_written,
        elapsed,
        OUTPUT_DIR,
    )
    logger.info("Next: gsutil -m rsync -r %s gs://pivony-advisor/hospitality", OUTPUT_DIR)
    logger.info("Next: RECREATE_COLLECTIONS=false python src/data/ingest.py")


if __name__ == "__main__":
    main()
