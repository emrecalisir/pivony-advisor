# Sonic Prospect RAG — multi-tenant knowledge & chat

Embeddable site assistant (**Sonic Prospect**) answers visitor questions using **FAQ + PDF** knowledge scoped per **organization** and **bot**. This document defines isolation, storage, ingest, and runtime chat. Implementation lives in `pivony-advisor/src/prospect/` with `pivony-api` as gateway.

## Isolation model

| Layer | Key | Rule |
|-------|-----|------|
| Postgres | `feedback_instruments.organization_id` | Instrument CRUD enforces org ownership |
| GCS PDF | `sonic-prospect/{org_id}/{bot_id}/{doc_id}.pdf` | Upload path includes org + bot |
| Qdrant | payload `org_id` + `bot_id` | **Every** search/delete uses both filters |
| Chat | public slug → single instrument | Resolved bot_id passed to advisor |

**Products do not mix:** Advisor uses `pivony_platform_knowledge` / `pivony_sector_*`. Prospect uses **`sonic_prospect_knowledge` only**. Prospect ingest/chat never reads Advisor collections.

**Bots do not mix:** Two bots in the same org have distinct `bot_id` filters. Re-ingest deletes all points for `(org_id, bot_id)` before upsert.

## Qdrant collection

| Setting | Value |
|---------|--------|
| Collection | `sonic_prospect_knowledge` |
| Vector size | 768 (Vertex `text-embedding-004`) |
| Distance | Cosine |

### Point payload (required)

```json
{
  "org_id": "uuid",
  "bot_id": "5",
  "bot_slug": "acme-travel-abc",
  "source_type": "faq|pdf",
  "source_id": "faq_0|pdf_d6be27ac",
  "chunk_index": 0,
  "title": "optional section title"
}
```

Point ID: UUID5 over `sonic_prospect_knowledge|{org_id}|{bot_id}|{source_type}|{source_id}|{chunk_index}`.

### Search filter (mandatory)

```python
Filter(must=[
  FieldCondition(key="org_id", match=MatchValue(value=org_id)),
  FieldCondition(key="bot_id", match=MatchValue(value=str(bot_id))),
])
```

Never run unfiltered similarity search on this collection.

## Ingest pipeline

Triggered by **pivony-api** after bot knowledge changes (FAQ save, PDF upload/delete, instrument update).

```
pivony-api  --POST /v1/prospect/ingest-->  pivony-advisor
  1. DELETE all Qdrant points where org_id + bot_id match
  2. FAQ items → one chunk each: [Bot …][Source: faq] Q: … A: …
  3. PDF docs → download from public URL → extract text → chunk → embed → upsert
  4. Return { status: "ready", chunk_count: N }
```

`system_prompt` is **not** embedded; it is injected at chat time from `feedback_instruments.config.knowledge.system_prompt`.

### Ingest auth

Header: `X-Sonic-Prospect-Key: $SONIC_PROSPECT_RAG_SECRET` (same value on pivony-api and pivony-advisor).

## Runtime chat

Public (browser embed):

```
POST /api/v1/feedback/public/prospect/chat
  { "slug": "acme-travel-abc", "message": "…", "session_id": "…", "history": [...] }
```

pivony-api:

1. Rate-limit by IP + slug
2. Resolve slug → active `sonic_prospect` instrument
3. Forward to advisor `POST /v1/prospect/chat` with org_id, bot_id, message, system_prompt, language, history

Advisor:

1. Embed visitor message
2. Qdrant search with org_id + bot_id filter (K=5)
3. Gemini answer with system_prompt + retrieved context
4. Return `{ answer, sources_used[] }`

## API contracts

### Ingest — `POST /v1/prospect/ingest`

```json
{
  "org_id": "aab46980-…",
  "bot_id": 5,
  "bot_slug": "acme-travel-abc",
  "language": "tr",
  "faq_items": [{ "q": "…", "a": "…" }],
  "pdf_documents": [{ "id": "…", "name": "…", "url": "https://…" }]
}
```

### Chat — `POST /v1/prospect/chat`

```json
{
  "org_id": "…",
  "bot_id": 5,
  "message": "Antalya otelleri var mı?",
  "system_prompt": "Sen …",
  "language": "tr",
  "chat_history": [
    { "role": "user", "content": "…" },
    { "role": "assistant", "content": "…" }
  ]
}
```

Response:

```json
{
  "answer": "…",
  "sources_used": [{ "source_type": "faq", "source_id": "faq_0", "snippet": "…" }]
}
```

## Config (`feedback_instruments.config.knowledge`)

| Field | Purpose |
|-------|---------|
| `faq_items` | Ingest input |
| `pdf_documents` | Ingest input (metadata + GCS URL) |
| `system_prompt` | Chat system message (not embedded) |
| `rag_status` | `pending` \| `processing` \| `ready` \| `failed` |
| `rag_updated_at` | ISO timestamp |
| `rag_error` | Last ingest error message |

## Environment

| Variable | Service | Purpose |
|----------|---------|---------|
| `SONIC_PROSPECT_RAG_SECRET` | api + advisor | Internal ingest/chat auth |
| `PIVONY_MODELS_BASE_URL` | api | Advisor base URL (e.g. `http://127.0.0.1:8000`) |
| `QDRANT_HOST` / `QDRANT_PORT` | advisor | Vector store |
| `GCP_PROJECT`, `GCP_LOCATION` | advisor | Vertex embed + Gemini |

## Delete bot

When instrument deleted: `DELETE` Qdrant points filtered by `org_id` + `bot_id` (hook in pivony-api).

## Tests

- `pivony-advisor/tests/test_prospect_rag.py` — chunking, filter builder, point IDs
- Integration: org A bot cannot retrieve org B chunks (manual / staging)

## Related files

| Repo | Path |
|------|------|
| pivony-advisor | `src/prospect/` |
| pivony-advisor | `src/api/prospect_routes.py` |
| pivony-api | `api/utils/prospect_rag_client.py` |
| pivony-api | `api/utils/prospect_knowledge_sync.py` |
| pivony-api | `api/feedback_capture.py` (public chat + sync hooks) |
