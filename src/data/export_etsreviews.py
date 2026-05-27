"""
Export MongoDB `etsreviews` (last N days) into hospitality knowledge files for RAG ingest.

Does NOT train an LLM — builds text corpora under output/hospitality/ then you run:
  gsutil -m cp -r output/hospitality gs://pivony-advisor/hospitality/
  python src/data/ingest.py

Configure field names via env (see docs/HOSPITALITY_ETSREVIEWS.md).
"""

from __future__ import annotations

import json
import os
import sys
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

# Export layout: output/hospitality/YYYY-MM/etsreviews[_part_N].md
EXPORT_MODE = os.environ.get("ETS_EXPORT_MODE", "monthly")  # monthly | raw_files
REVIEWS_PER_FILE = int(os.environ.get("ETS_REVIEWS_PER_FILE", "500"))
MAX_REVIEWS = int(os.environ.get("ETS_MAX_REVIEWS", "0"))  # 0 = no limit
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


def _review_to_markdown(doc: dict[str, Any], index: int) -> str | None:
    text = _first_value(doc, TEXT_FIELDS)
    if not text:
        return None
    text = str(text).strip()
    if not text:
        return None

    title = _property_name(doc)
    rating = _first_value(doc, RATING_FIELDS)
    source = _review_source(doc)
    when = _doc_review_date(doc)
    survey_id = doc.get("pk") or doc.get("sk")

    lines = [f"### Review {index}"]
    if survey_id:
        lines.append(f"- Survey: {survey_id}")
    if title:
        lines.append(f"- Property: {title}")
    if rating is not None:
        lines.append(f"- Rating: {rating}")
    if source:
        lines.append(f"- Source: {source}")
    if when:
        lines.append(f"- Date: {when.date().isoformat()}")
    lines.append("")
    lines.append(text)
    return "\n".join(lines)


def _base_match() -> dict[str, Any]:
    """Full review rows only (not s#0..s#4 partition pointers)."""
    text_clause = [{f: {"$exists": True, "$ne": ""}} for f in TEXT_FIELDS[:3]]
    match: dict[str, Any] = {"pk": {"$not": {"$regex": r"^s#\d+$"}}}
    if text_clause:
        match["$or"] = text_clause
    return match


def _fetch_reviews(collection, since: datetime) -> list[dict[str, Any]]:
    projection: dict[str, int] = {"pk": 1, "sk": 1, "CustomAttributes": 1}
    for field in DATE_FIELDS + TEXT_FIELDS + TITLE_FIELDS + RATING_FIELDS + SOURCE_FIELDS:
        projection[field] = 1

    # ETS dates are "dd-mm-yyyy HH:mm:ss" on sk (not comparable as plain strings)
    pipeline: list[dict[str, Any]] = [
        {"$match": _base_match()},
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
        {"$match": {"_parsedDate": {"$gte": since}}},
        {"$sort": {"_parsedDate": -1}},
        {"$project": {**projection, "_parsedDate": 0}},
    ]
    if EXTRA_FILTER_JSON.strip():
        extra = json.loads(EXTRA_FILTER_JSON)
        pipeline[0]["$match"] = {"$and": [pipeline[0]["$match"], extra]}
    if MAX_REVIEWS > 0:
        pipeline.append({"$limit": MAX_REVIEWS})
    return list(collection.aggregate(pipeline, allowDiskUse=True))


def _month_header(month_key: str) -> str:
    return (
        f"# ETS Reviews — {month_key}\n\n"
        "Guest review corpus for hospitality advisor (exported from MongoDB).\n\n"
    )


def _write_month_folder(
    month_key: str,
    blocks: list[str],
    out_dir: Path,
    *,
    split_parts: bool,
) -> int:
    """Write under out_dir/YYYY-MM/ (matches GCS hospitality/2025-05/)."""
    if not blocks:
        return 0

    month_dir = out_dir / month_key
    if SKIP_EXISTING and month_dir.is_dir() and any(month_dir.glob("*.md")):
        print(f"Skip month {month_key} (folder already has .md files)")
        return 0

    month_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    if split_parts and len(blocks) > REVIEWS_PER_FILE:
        batches = [
            blocks[i : i + REVIEWS_PER_FILE]
            for i in range(0, len(blocks), REVIEWS_PER_FILE)
        ]
        for part_idx, batch in enumerate(batches, start=1):
            path = month_dir / f"etsreviews_part_{part_idx:03d}.md"
            if SKIP_EXISTING and path.exists():
                print(f"Skip (exists): {path}")
                continue
            path.write_text(_month_header(month_key) + "\n\n".join(batch), encoding="utf-8")
            written += 1
            print(f"Wrote {path} ({len(batch)} reviews)")
        return written

    path = month_dir / "etsreviews.md"
    if SKIP_EXISTING and path.exists():
        print(f"Skip (exists): {path}")
        return 0
    path.write_text(_month_header(month_key) + "\n\n".join(blocks), encoding="utf-8")
    print(f"Wrote {path} ({len(blocks)} reviews)")
    return 1


def _write_monthly_files(by_month: dict[str, list[str]], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = 0
    for month_key in sorted(by_month.keys()):
        files += _write_month_folder(
            month_key, by_month[month_key], out_dir, split_parts=True
        )
    return files


def _write_raw_batches(by_month: dict[str, list[str]], out_dir: Path) -> int:
    """Same folder layout as monthly; always splits large months into parts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = 0
    for month_key in sorted(by_month.keys()):
        files += _write_month_folder(
            month_key, by_month[month_key], out_dir, split_parts=True
        )
    return files


def _diagnose_missing_mongo_env() -> None:
    env_file = os.path.join(BASE_DIR, ".env")
    print("ERROR: PRODUCTION_MONGODB_URI is empty.")
    print(f"  Expected .env at: {env_file}")
    print(f"  .env exists: {os.path.isfile(env_file)}")
    try:
        import dotenv  # noqa: F401

        print("  python-dotenv: installed")
    except ImportError:
        print("  python-dotenv: not installed (using built-in .env parser)")
    if os.path.isfile(env_file):
        keys = []
        with open(env_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                keys.append(line.split("=", 1)[0].strip())
        print(f"  Keys in .env: {', '.join(keys) or '(none)'}")
        if "PRODUCTION_MONGODB_URI" not in keys:
            print("  → Add: PRODUCTION_MONGODB_URI=mongodb+srv://...")
    else:
        print("  → Run: cp .env.example .env && nano .env")
    print("See docs/HOSPITALITY_ETSREVIEWS.md")


def main() -> None:
    if not MONGODB_URI:
        _diagnose_missing_mongo_env()
        sys.exit(1)

    try:
        from pymongo import MongoClient
    except ImportError:
        print("ERROR: pip install pymongo")
        sys.exit(1)

    since = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    print(f"Connecting to MongoDB db={MONGODB_DB} collection={MONGODB_COLLECTION}")
    print(f"Exporting reviews with date field(s) {DATE_FIELDS} >= {since.isoformat()}")

    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    collection = client[MONGODB_DB][MONGODB_COLLECTION]

    docs = _fetch_reviews(collection, since)
    print(f"Fetched {len(docs)} documents")

    if not docs:
        print("WARNING: No documents matched. Check ETS_DATE_FIELD / ETS_EXTRA_FILTER_JSON.")
        sample = collection.find_one()
        if sample:
            print("Sample document keys:", sorted(sample.keys()))
        sys.exit(0)

    blocks: list[str] = []
    by_month: dict[str, list[str]] = defaultdict(list)
    skipped = 0

    for idx, doc in enumerate(docs, start=1):
        block = _review_to_markdown(doc, idx)
        if not block:
            skipped += 1
            continue
        blocks.append(block)
        when = _doc_review_date(doc)
        month_key = (when or since).strftime("%Y-%m")
        by_month[month_key].append(block)

    print(f"Usable reviews: {len(blocks)} (skipped {skipped} without text)")

    if EXPORT_MODE == "raw_files":
        file_count = _write_raw_batches(by_month, OUTPUT_DIR)
    else:
        file_count = _write_monthly_files(by_month, OUTPUT_DIR)

    print(f"Done. {file_count} file(s) under {OUTPUT_DIR}/YYYY-MM/")
    print("Next:")
    print(f"  gsutil -m rsync -r {OUTPUT_DIR} gs://pivony-advisor/hospitality")
    print("  export RECREATE_COLLECTIONS=false && python src/data/ingest.py")


if __name__ == "__main__":
    main()
