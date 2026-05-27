# Hospitality RAG from MongoDB `etsreviews`

This is **not** model fine-tuning. You export the last year of reviews as text, upload to GCS `hospitality/`, then run `ingest.py` → Qdrant collection `pivony_sector_hospitality`.

## 1. Install

```bash
pip install pymongo
```

## 2. Schema (from pivony-external-api / pivony-scripts)

| Field | Typical name |
|--------|----------------|
| Collection | `ETSReviews` (not `etsreviews`) |
| DB | `production` (prod) or `staging` |
| Review text | `ReviewContent` |
| Date | `ReviewSubmissionDate` (`dd-mm-yyyy HH:mm:ss`) |
| Rating | `Rating` |
| Title | `ReviewTitle` (optional) |

Partition rows (`pk` = `s#0` … `s#4`) are **excluded** by default; export uses documents with real `ReviewContent`.

Verify once:

```bash
mongosh "$MONGODB_URI" --eval 'db.getSiblingDB("production").ETSReviews.findOne({ReviewContent:{$exists:true}})'
```

## 3. Export (last 365 days)

```bash
export MONGODB_URI="mongodb://..."
export MONGODB_DB="production"
export MONGODB_COLLECTION="ETSReviews"

# Defaults already match ETS schema; override only if needed:
export ETS_DATE_FIELD="ReviewSubmissionDate"
export ETS_TEXT_FIELDS="ReviewContent,ReviewText"
export ETS_TITLE_FIELDS="ReviewTitle"
export ETS_RATING_FIELDS="Rating"
export ETS_DAYS_BACK=365

# Test with 1000 reviews first:
export ETS_MAX_REVIEWS=1000
export ETS_EXPORT_MODE=monthly   # or raw_files

python src/data/export_etsreviews.py
```

Output layout (ay klasörleri — GCS ile aynı):

```text
output/hospitality/
  2025-05/etsreviews.md
  2025-06/etsreviews_part_001.md
  ...
```

Zaten yüklü ayları atlamak için: `export ETS_SKIP_EXISTING=true`

## 4. Upload to GCS

```bash
export GOOGLE_APPLICATION_CREDENTIALS=config/google_creds.json
gsutil -m rsync -r output/hospitality gs://pivony-advisor/hospitality
```

## 5. Ingest into Qdrant

On Qdrant VM:

```bash
export QDRANT_HOST=127.0.0.1
export RECREATE_COLLECTIONS=false
python src/data/ingest.py
```

Verify:

```bash
curl -s http://127.0.0.1:6333/collections/pivony_sector_hospitality
```

## 6. Test advisor

```bash
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "pivony-local-llm",
    "pivony_sector": "hospitality",
    "messages": [{"role": "user", "content": "Son dönemde misafirler housekeeping hakkında ne diyor?"}]
  }'
```

## Optional filters

Only published reviews:

```bash
export ETS_EXTRA_FILTER_JSON='{"status":"published"}'
```

## Volume tips

- Full year may be millions of rows — start with `ETS_MAX_REVIEWS=50000` and increase.
- `monthly` mode keeps fewer, larger files (better for ingest).
- Platform KC stays in `master/`; reviews only in `hospitality/`.
