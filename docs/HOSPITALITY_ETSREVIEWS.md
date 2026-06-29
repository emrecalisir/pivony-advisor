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
| Date/time | `sk` + `SubmittedAt` (full `YYYY-MM-DD HH:MM:SS UTC` in export) |
| Hotel / pivot | All `CustomAttributes` keys (`vendorName`, `projectName`, channel, …) |
| Text | `ReviewContent` |
| Sub-questions | `SubQuestionAnswers` (flattened as `- SubQ[...]:` lines) |
| Rating | `Rating` |
| Title | `ReviewTitle` (optional) |

Each review block exports **all** `CustomAttributes` fields so pivot dimensions reach Qdrant. Ingest copies the metadata header onto **every chunk** (hotel + time stay searchable after follow-ups like “hangi otelde?”).

**After changing export format:** re-export and re-ingest hospitality (or `RECREATE_COLLECTIONS=true` once).

Partition rows (`pk` = `s#0` … `s#4`) are **excluded** by default; export uses documents with real `ReviewContent`.

Verify once:

```bash
mongosh "$MONGODB_URI" --eval 'db.getSiblingDB("production").ETSReviews.findOne({ReviewContent:{$exists:true}})'
```

## 3. `.env` setup

```bash
cp .env.example .env
# Edit .env — set PRODUCTION_MONGODB_URI and MONGO_COLLECTION
```

Example `.env`:

```env
PRODUCTION_MONGODB_URI=mongodb+srv://USER:PASS@cluster.mongodb.net/?appName=production
MONGO_COLLECTION=ETSReviews
MONGODB_DB=production
ETS_DAYS_BACK=365
ETS_MAX_REVIEWS=5000
```

## 4. Export (last 365 days)

```bash
pip install -r requirements.txt
python src/data/export_etsreviews.py
tail -f logs/ets_export.log
```

Progress is written to `logs/ets_export.log` (override with `ETS_EXPORT_LOG_PATH`).

Optional overrides (shell or `.env`): `ETS_DATE_FIELD`, `ETS_TEXT_FIELDS`, `ETS_SKIP_EXISTING`, `ETS_EXPORT_MODE`.

Output layout (ay klasörleri — GCS ile aynı):

```text
output/hospitality/
  2025-05/etsreviews.md
  2025-06/etsreviews_part_001.md
  ...
```

Zaten yüklü ayları atlamak için: `export ETS_SKIP_EXISTING=true`

## 5. Upload to GCS (optional)

```bash
export GOOGLE_APPLICATION_CREDENTIALS=config/google_creds.json
gcloud auth activate-service-account --key-file=config/google_creds.json
gcloud config set project pivony-ab6d2
gsutil ls gs://pivony-advisor/
gsutil -m rsync -r output/hospitality gs://pivony-advisor/hospitality
```

If you see `403 Provided scope(s) are not authorized`, the service account in `google_creds.json` needs **Storage Object Admin** on bucket `pivony-advisor` (GCP Console → IAM or bucket permissions). You can skip GCS and ingest locally (step 6).

## 6. Ingest into Qdrant

On Qdrant VM — **local files** (no GCS upload). Put settings in `.env` (see `.env.example`), then run in the **background** so SSH disconnect does not kill the job.

```bash
cd ~/pivony-advisor
cp .env.example .env   # if needed; edit INGEST_* and RECREATE_COLLECTIONS
chmod +x scripts/run_ingest_background.sh
git pull               # includes file-stream ingest + background script

./scripts/run_ingest_background.sh start
./scripts/run_ingest_background.sh status
./scripts/run_ingest_background.sh logs    # tail -f logs/ingest.log
```

**Logs**

| File | Content |
|------|---------|
| `logs/ingest.log` | Progress: months, files, Qdrant batches |
| `logs/ingest_stdout.log` | Python stdout/stderr, tracebacks |
| `run/ingest.pid` | PID while running |

**Stop / restart**

```bash
./scripts/run_ingest_background.sh stop
./scripts/run_ingest_background.sh restart
```

**Optional: systemd** (survives reboot only if you enable the unit; still one-shot ingest)

```bash
sudo cp deploy/pivony-ingest.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start pivony-ingest
sudo journalctl -u pivony-ingest -f   # or tail logs/ingest.log
```

Foreground (same as before, dies when SSH drops unless using `nohup` yourself):

```bash
export GOOGLE_APPLICATION_CREDENTIALS=config/google_creds.json
export QDRANT_HOST=127.0.0.1
export RECREATE_COLLECTIONS=false
export INGEST_LOCAL_DIR=output/hospitality
export INGEST_LOCAL_PREFIX=hospitality
export INGEST_BY_MONTH=true

python src/data/ingest.py
tail -f logs/ingest.log
```

**See where you stopped:**

```bash
./scripts/run_ingest_background.sh progress
grep "DONE \|=== Month \|COMPLETE\|ERROR" logs/ingest.log | tail -20
```

Log line format: `DONE 2025-11 file 50/266 etsreviews_part_050.md | ...`

**Resume after error** (do not restart from zero):

Each successfully indexed part file is saved in `run/ingest_checkpoint.json`. After a crash, fix the issue (e.g. `INGEST_BATCH_SIZE=16`) and:

```bash
export RECREATE_COLLECTIONS=false
export INGEST_RESUME=true
export INGEST_BATCH_SIZE=16
./scripts/run_ingest_background.sh restart
```

**One-time** (if checkpoint file is empty but `logs/ingest.log` has hours of progress):

```bash
export INGEST_BOOTSTRAP_CHECKPOINT=true   # only for the first restart
./scripts/run_ingest_background.sh restart
# then set INGEST_BOOTSTRAP_CHECKPOINT=false
```

Optional month filters (checkpoint still skips individual files already done):

```bash
export INGEST_FROM_MONTH=2025-08
# export INGEST_ONLY_MONTH=2025-09
```

Progress in `logs/ingest.log`. Large exports auto-use **month-by-month** ingest (`INGEST_BY_MONTH=true`) to avoid OOM on 1M+ chunks.

`INGEST_BATCH_SIZE` (default **16**). Re-indexing the same file **replaces** vectors (stable point ids), it does not duplicate.

`INGEST_PROGRESS_EVERY` only affects optional extra logs; each file always logs one `DONE <month> file X/Y` line.

Or from GCS after a successful `gsutil rsync`:

```bash
unset INGEST_LOCAL_DIR
python src/data/ingest.py
```

Verify:

```bash
curl -s http://127.0.0.1:6333/collections/pivony_sector_hospitality
```

## 7. Test advisor

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

- Full year may be millions of rows — export streams **month-by-month** to avoid OOM (`Killed`).
- Test first: `ETS_MAX_REVIEWS=5000` in `.env`
- Tune memory: `ETS_CURSOR_BATCH_SIZE=50`, `ETS_REVIEWS_PER_FILE=200` (append part files, no single blob)
- If the VM is small, run export on a machine with more RAM, then `rsync output/hospitality` to Qdrant VM.
- Platform KC stays in `master/`; reviews only in `hospitality/`.
