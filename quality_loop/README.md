# Pivony Advisor — CrewAI Quality Loop

Automated CX Director ↔ Advisor conversation, QA evaluation, and optional code-fix cycle.

## Architecture (adapted to this repo)

| Layer | Role |
|-------|------|
| **pivony-advisor** | Stateless `POST /v1/chat/completions` — tools, prompts, agent loop |
| **quality_loop/** | Local session JSON + CrewAI orchestration |
| **pivony-api** (optional) | Postgres `cx_gpt_chat_messages` when `QUALITY_LOOP_DATABASE_URL` is set |
| **logs/history.log** | Advisor audit trail (one JSON line per completion) |

There is **no** `/chat` or `/session/create` on advisor — the loop uses:

- `POST {PIVONY_ADVISOR_URL}/v1/chat/completions`
- Local `quality_loop/outputs/sessions/*.json` for multi-turn state
- `pivony_page_context` for dashboard scope (mirrors web → API mapping)

## Install

CrewAI requires **Python >=3.10 and <3.14**. Advisor venv may use 3.14+ — keep quality loop in its own venv:

```bash
cd pivony-advisor
bash scripts/bootstrap-quality-loop-venv.sh
cp .env.example .env   # fill QUALITY_LOOP_* and LLM keys
```

This creates `.venv-quality-loop` with uv-managed Python 3.12 and installs `requirements-quality-loop.txt`.

Manual install (only if you already have a compatible Python):

```bash
pip install -r requirements-quality-loop.txt
```

Advisor must be running (e.g. `curl http://127.0.0.1:8000/health`).

For real metrics/tools, set `PIVONY_API_METRICS_URL` and `PIVONY_API_WORKER_SECRET` in advisor `.env`.

## Run

```bash
# Full loop: CX Director → QA → Coding
bash scripts/run_quality_loop.sh

# 5 iterations
bash scripts/run_quality_loop.sh --iterations 5

# Analyze existing session (local sess_* or Postgres session id)
bash scripts/run_quality_loop.sh --mode analyze --session sess_abc123
```

## Environment

```bash
# Advisor target
PIVONY_ADVISOR_URL=http://127.0.0.1:8000
PIVONY_ADVISOR_API_TOKEN=          # optional
QUALITY_LOOP_USER_ID=              # forwarded as pivony_user_id
QUALITY_LOOP_USER_EMAIL=

# LLMs (LiteLLM-style strings for CrewAI)
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
QUALITY_LOOP_CX_LLM=gemini/gemini-2.0-flash
QUALITY_LOOP_QA_LLM=anthropic/claude-sonnet-4-20250514
QUALITY_LOOP_CODING_LLM=anthropic/claude-sonnet-4-20250514

# Optional: read prod UI sessions from pivony-api Postgres
QUALITY_LOOP_DATABASE_URL=postgresql://...

# Coding agent safety (default: file write only, no git/deploy)
PIVONY_REPO_ROOT=/path/to/pivony-advisor
QUALITY_LOOP_ALLOW_GIT_PUSH=false
QUALITY_LOOP_AUTO_DEPLOY=false
DEPLOY_CMD=systemctl restart pivony-advisor
```

## Agents

1. **CX Director** — drives 6–10 turn conversation via `pivony_advisor_chat`
2. **QA Agent** — `fetch_conversation` + rubric JSON report
3. **Coding Agent** — reads/fixes code; git/deploy gated by env flags

## Outputs

- `quality_loop/outputs/iteration_*.json` — crew results
- `quality_loop/outputs/sessions/*.json` — per-conversation message history

## Inspection UI (SSH tüneli gerekmez)

### Yerel mod (önerilen)

Sunucudan veriyi bir kez çek, Mac'inde UI aç:

```bash
# 1) Sunucudan outputs sync et (scp, tunnel yok)
bash scripts/sync_quality_loop_outputs.sh

# 2) Yerel UI
bash scripts/bootstrap-quality-loop-ui.sh   # ilk sefer
bash scripts/run_quality_loop_ui.sh
open http://127.0.0.1:8020
```

UI şunları şeffaf gösterir:
- **Feedback Loop** — CX konuşma → QA → coding pipeline
- **Konuşmalar** — tur tur tool/reasoning/QA issue overlay
- **QA Raporları** — skorlar, severity, kanıt, fix_hint
- **İyileştirmeler** — fixes_applied / fixes_skipped

### Uzak erişim (dış IP — firewall değişikliği gerekmez)

Advisor dev API (8011) zaten dışarıdan açık. UI'ı ona mount et:

```bash
# .env
QUALITY_LOOP_UI_MOUNT=true
QUALITY_LOOP_UI_TOKEN=your-secret   # önerilir — UI giriş şifresi (cookie oturumu)
```

```bash
sudo systemctl restart pivony-advisor-dev.service
```

Tarayıcı: **http://104.198.55.230:8011/quality-loop/**

Token set ise ilk ziyarette **giriş ekranı** çıkar; şifre doğruysa tarayıcı cookie ile hatırlar (7 gün). Uzak API adresi kullanıyorsanız Ayarlar'dan header token girebilirsiniz.

### Alternatif: ayrı port 8020

GCP firewall'da tcp:8020 açman gerekir:

```bash
QUALITY_LOOP_UI_HOST=0.0.0.0
QUALITY_LOOP_UI_PORT=8020
bash scripts/run_quality_loop_ui.sh
```

## Key source files (for QA / coding hints)

| Concern | Path |
|---------|------|
| API entry | `src/api/main.py` |
| Tools | `src/core/agent.py` |
| Scope lock | `src/core/agent_state.py`, `src/core/tool_routing.py` |
| Prompts | `src/core/prompts.py` |
| Streaming | `src/core/agent_stream.py` |
| Platform worker | `src/core/pivony_platform.py` |

## Deploy (production)

```bash
cd ~/pivony-advisor && git pull origin master
sudo systemctl restart pivony-advisor.service
```

Git remote: `git@github-pivony-advisor:emrecalisir/pivony-advisor.git`
