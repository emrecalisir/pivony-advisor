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

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

# ---------------------------------------------------------------------------
# Configuration (override via environment)
# ---------------------------------------------------------------------------
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DB = os.environ.get("MONGODB_DB", "")
# Pivony prod collection name is ETSReviews (see pivony-external-api / pivony-scripts)
MONGODB_COLLECTION = os.environ.get("MONGODB_COLLECTION", "ETSReviews")

# Date filter — ETS uses ReviewSubmissionDate (string "dd-mm-yyyy HH:mm:ss")
DATE_FIELD = os.environ.get("ETS_DATE_FIELD", "ReviewSubmissionDate")
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
    os.environ.get(
        "ETS_OUTPUT_DIR",
        os.path.join(os.path.dirname(os.path.dirname(_BASE)), "output", "hospitality"),
    )
)

# Optional Mongo filter JSON, e.g. {"status":"published"}
EXTRA_FILTER_JSON = os.environ.get("ETS_EXTRA_FILTER_JSON", "")


def _first_value(doc: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in doc and doc[key] not in (None, ""):
            return doc[key]
    return None


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

    title = _first_value(doc, TITLE_FIELDS)
    rating = _first_value(doc, RATING_FIELDS)
    source = _first_value(doc, SOURCE_FIELDS)
    when = _parse_date(_first_value(doc, [DATE_FIELD]) or doc.get(DATE_FIELD))

    lines = [f"### Review {index}"]
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


def _build_find_query(since: datetime) -> dict[str, Any]:
    query: dict[str, Any] = {**_base_match(), DATE_FIELD: {"$gte": since}}
    if EXTRA_FILTER_JSON.strip():
        extra = json.loads(EXTRA_FILTER_JSON)
        if not isinstance(extra, dict):
            raise ValueError("ETS_EXTRA_FILTER_JSON must be a JSON object")
        query = {"$and": [query, extra]}
    return query


def _fetch_reviews(collection, since: datetime) -> list[dict[str, Any]]:
    projection = {DATE_FIELD: 1, "pk": 1, "sk": 1}
    for field in TEXT_FIELDS + TITLE_FIELDS + RATING_FIELDS + SOURCE_FIELDS:
        projection[field] = 1

    # ETS ReviewSubmissionDate is "dd-mm-yyyy HH:mm:ss" — string $gte is wrong; use $dateFromString
    if DATE_FIELD == "ReviewSubmissionDate":
        pipeline: list[dict[str, Any]] = [
            {"$match": _base_match()},
            {
                "$addFields": {
                    "_parsedDate": {
                        "$dateFromString": {
                            "dateString": f"${DATE_FIELD}",
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

    query = _build_find_query(since)
    cursor = collection.find(query, projection=projection).sort(DATE_FIELD, -1)
    if MAX_REVIEWS > 0:
        cursor = cursor.limit(MAX_REVIEWS)
    return list(cursor)


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


def main() -> None:
    if not MONGODB_URI or not MONGODB_DB:
        print("ERROR: Set MONGODB_URI and MONGODB_DB environment variables.")
        print("See docs/HOSPITALITY_ETSREVIEWS.md")
        sys.exit(1)

    try:
        from pymongo import MongoClient
    except ImportError:
        print("ERROR: pip install pymongo")
        sys.exit(1)

    since = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    print(f"Connecting to MongoDB db={MONGODB_DB} collection={MONGODB_COLLECTION}")
    print(f"Exporting reviews with {DATE_FIELD} >= {since.isoformat()}")

    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    collection = client[MONGODB_DB][MONGODB_COLLECTION]

    docs = _fetch_reviews(collection, since)
    print(f"Fetched {len(docs)} documents")

    if not docs:
        print("WARNING: No documents matched. Check DATE_FIELD / ETS_EXTRA_FILTER_JSON.")
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
        when = _parse_date(doc.get(DATE_FIELD))
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
