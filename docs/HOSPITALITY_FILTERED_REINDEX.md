# Filtered re-index (wipe → export → ingest)

Use when you want **only selected hotels**, a **fixed date range**, and **full Mongo metadata** in Qdrant.

## 1. Wipe Qdrant collections

```bash
cd ~/pivony-advisor
chmod +x scripts/wipe_qdrant_collections.sh
./scripts/wipe_qdrant_collections.sh
```

Optional: delete all `pivony_*` collections:

```bash
./scripts/wipe_qdrant_collections.sh --all-pivony
```

## 2. Clean local export + checkpoint (recommended)

```bash
rm -rf output/hospitality
rm -f run/ingest_checkpoint.json
```

## 3. Configure `.env`

```env
# Mongo
PRODUCTION_MONGODB_URI=...
MONGO_COLLECTION=ETSReviews
MONGODB_DB=production

# Date range (inclusive days, UTC)
ETS_DATE_FROM=2025-06-01
ETS_DATE_TO=2026-05-31
ETS_DAYS_BACK=365

# Hotels / pivots (.env only)
ETS_HOTEL_FIELD=vendorName
ETS_HOTEL_NAMES=Grand Hotel Example,Another Resort Name
# Or multi-pivot (merged with HOTEL_NAMES):
# ETS_PIVOT_FILTERS_JSON={"vendorName":["Grand Hotel Example"],"channel":["Booking"]}
ETS_PIVOT_MATCH=all

# Full review payload from Mongo
ETS_EXPORT_FULL_MONGO=true
ETS_EXPORT_INCLUDE_ANALYSIS=false
ETS_SKIP_EXISTING=false

# Ingest
INGEST_LOCAL_DIR=output/hospitality
INGEST_LOCAL_PREFIX=hospitality
INGEST_BY_MONTH=true
RECREATE_COLLECTIONS=true
INGEST_BATCH_SIZE=16
INGEST_BOOTSTRAP_CHECKPOINT=false
```

List exact `vendorName` values for `.env` (mongosh):

```javascript
db.ETSReviews.aggregate([
  { $match: { "CustomAttributes.vendorName": { $exists: true, $ne: "" } } },
  { $group: { _id: "$CustomAttributes.vendorName", n: { $sum: 1 } } },
  { $sort: { n: -1 } }
])
```

Names in `ETS_HOTEL_NAMES` / JSON must match Mongo **exactly** (case-sensitive).

## 4. Export

```bash
python src/data/export_etsreviews.py
tail -f logs/ets_export.log
```

Check one part file:

```bash
head -60 output/hospitality/2025-06/etsreviews_part_001.md
```

Expect: `- SubmittedAt`, all `CustomAttributes` keys, `#### Mongo JSON` block, then review text.

## 5. Ingest

```bash
./scripts/run_ingest_background.sh start
./scripts/run_ingest_background.sh progress
```

After success set `RECREATE_COLLECTIONS=false` for future incremental runs.

## 6. Verify

```bash
curl -s http://127.0.0.1:6333/collections/pivony_sector_hospitality | jq '.result.points_count'
```

Test advisor with a hotel-specific question.
