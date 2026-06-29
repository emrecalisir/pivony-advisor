# Pivony Advisor — Agentic RAG devam paketi

Bu dosya, model/chat değişince context kaybını önlemek için hazırlanmış özet handoff’tur.  
Yeni bir Cursor sohbetinde veya Opus’a geçerken **tüm bloğu** ilk mesaja yapıştırın.

---

## Proje bağlamı

| Katman | Repo / servis | Not |
|--------|----------------|-----|
| UI | `pivony-web-platform` (React) | **Dokunulmaz** — Advisor UI bitti |
| API proxy | `pivony-api` | CX-GPT → `PIVONY_MODELS_BASE_URL` |
| RAG backend | **`pivony-advisor`** | FastAPI `:8000`, `POST /v1/chat/completions` |
| Vector DB | Qdrant | `pivony_platform_knowledge`, `pivony_sector_hospitality` |
| LLM | Gemini (Vertex) | `langchain_google_genai`, model `gemini-2.5-flash` |
| Veri kaynağı | Mongo `ETSReviews` | export → `output/hospitality/` → ingest |

**Yanlış varsayım (Gemini prompt):** Next.js App Router API / Vercel AI SDK — **yok**. Tüm backend değişikliği `pivony-advisor/src/`.

---

## Akış

```
pivony-web-platform → pivony-api → pivony-advisor:8000/v1/chat/completions
                                              → Qdrant similarity_search (her istekte, tool yok)
```

Body: OpenAI-style `messages[]`, `pivony_sector` (ör. `hospitality`).  
System prompt: pivony-api industry prompt + advisor `MASTER_PROMPT` / sector prompt.

---

## Sorun: “Bu hangi otelde?”

Kullanıcı önce bir şikayet/özet görür, sonra “Bu hangi otelde?” der → model “bağlamda yok” diyebilir.

**Kök nedenler:**

1. Sabit RAG — her turda kör retrieval; Gemini orchestrator / tool calling yok.
2. `format_docs()` sadece `page_content` birleştiriyor; structured metadata formatı yok.
3. Follow-up retrieval (`conversation.build_retrieval_query`) kısa sorularda yeterince zengin olmayabilir.
4. `SECTOR_RETRIEVER_K=5` dar context.
5. Eski Qdrant indeksi — metadata prefix ingest sonrası re-index gerekebilir.

**Zaten yapılmış (kod):**

- `conversation.prepare_conversational_input` — `chat_history`, `retrieval_query`
- `ingest_utils.enrich_chunk_content` — otel/tarih her chunk `page_content` prefix’inde
- Export: `.env` filtreleri `ETS_HOTEL_NAMES`, `ETS_PIVOT_FILTERS_JSON`, tarih aralığı, full Mongo
- Git: `pivony-advisor` `master` commit `004eed4` (push edildi)

**Ops (VM):** `docs/HOSPITALITY_FILTERED_REINDEX.md` — wipe → export → ingest.

---

## Onay bekleyen implementasyon planı

### Faz 0 — Ops (kod değil)

```bash
cd ~/pivony-advisor && git pull
./scripts/wipe_qdrant_collections.sh
# .env: ETS_DATE_FROM/TO, ETS_HOTEL_NAMES, ETS_EXPORT_FULL_MONGO=true, ETS_SKIP_EXISTING=false
python src/data/export_etsreviews.py
./scripts/run_ingest_background.sh start
```

### Faz 1 — Düz RAG güçlendirme (düşük risk)

| Dosya | Değişiklik |
|-------|------------|
| `src/core/rag.py` | `format_docs` → `[Metadata → Otel: …, Tarih: …] Yorum: …` |
| `src/core/prompts.py` | Hospitality: otel/tarih varsa yanıtta zorunlu belirt |
| `src/core/conversation.py` | “hangi otel” follow-up → son assistant mesajı retrieval’a |
| `src/core/config.py` | `SECTOR_RETRIEVER_K` default artırılabilir (env) |

API sözleşmesi değişmez.

### Faz 2 — Agentic tool calling

| Tool | Amaç |
|------|------|
| `search_qdrant_reviews` | Şikayet/kanıt/detay → Qdrant + Faz 1 metadata formatı |
| `get_pivony_metrics` | Trend/skor → şimdilik **mock**, sonra pivony-api |

Yeni modül örn. `src/core/agent.py`; `main.py` `chat_completions` → agent loop; `messages[]` LangChain history.

### Faz 3 — Gerçek metrics API (sonra)

---

## Dokunulmayacaklar

- `pivony-web-platform`
- `pivony-api` (mesaj proxy yeterliyse)

---

## Ana dosyalar

- `src/api/main.py` — endpoint
- `src/core/rag.py` — retrieval + chain
- `src/core/conversation.py` — history / retrieval query
- `src/core/prompts.py` — system prompts
- `src/core/ingest_utils.py` — chunk metadata prefix
- `src/data/export_etsreviews.py` — Mongo export + env filtreleri
- `docs/HOSPITALITY_FILTERED_REINDEX.md`

---

## Test

1. Hospitality curl: genel soru → anlamlı cevap + otel adı (context’te varsa).
2. Çok tur: özet → “Bu hangi otelde?” → otel adı.
3. Metrik sorusu → `get_pivony_metrics` (Faz 2).
4. Platform sorusu → `pivony_platform_knowledge` regression.

---

## Cursor transcript (tam geçmiş)

UUID: `96e81baa-00f8-4974-beb3-91ef5ff94d66`  
Path: `~/.cursor/projects/Users-emrecalisir-devvv/agent-transcripts/96e81baa-00f8-4974-beb3-91ef5ff94d66.jsonl`

---

## İlk mesaj şablonu (Opus / yeni chat)

```
@docs/ADVISOR_AGENTIC_HANDOFF.md dosyasını oku.
Faz 1 + Faz 2 uygula. Frontend ve pivony-api'ye dokunma.
Mock metrics: vendorName, avg_rating, review_count, period yeterli.
```
