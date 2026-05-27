# Multi-tenant knowledge layout

## GCS bucket (`pivony-advisor`)

```
gs://pivony-advisor/
├── master/              # Platform KC — all sectors
├── general/             # Alias for platform KC
├── hospitality/         # Sector-specific docs
└── network-infrastructure/
```

Root-level `.txt` / `.md` files are ingested into `pivony_platform_knowledge` (legacy only).

**Do not use bucket-root test files** (e.g. `pivony_sss.txt`) in production. Place real content under `master/` (platform KC) and `{sector}/` (e.g. `hospitality/`). Remove obsolete test objects from GCS and re-run ingest with `RECREATE_COLLECTIONS=true` so Qdrant is not polluted.

## Qdrant collections

| Collection | Source folders |
|------------|----------------|
| `pivony_platform_knowledge` | `master/`, `general/`, root files |
| `pivony_sector_hospitality` | `hospitality/` |
| `pivony_sector_{slug}` | `{slug}/` |

## Ingest

```bash
export GOOGLE_APPLICATION_CREDENTIALS=config/google_creds.json
export QDRANT_HOST=127.0.0.1
# Optional: drop and recreate all collections
export RECREATE_COLLECTIONS=true

python src/data/ingest.py
```

## Prompt layers

1. **Master** — `pivony-advisor` (`src/core/prompts.py`), always applied in the advisor service.
2. **Industry** — `pivony-api` DB (`cx_gpt_industry_prompts`) or org override (`cx_gpt_custom_prompt_override`), sent as system message.
3. **RAG** — platform collection + sector collection (via `pivony_sector` on `/v1/chat/completions`).

## API contract

`POST /v1/chat/completions` body:

```json
{
  "model": "pivony-local-llm",
  "pivony_sector": "hospitality",
  "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "stream": false
}
```

## Database migration (pivony-api)

```bash
psql "$DATABASE_URL" -f migrations/cx_gpt_industry_prompts.sql
```

Set `EnterpriseCustomers.category_id` to the correct `Industries.ID`, optionally set `cx_gpt_custom_prompt_override`.
