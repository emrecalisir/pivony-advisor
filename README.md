# pivony-advisor

Pivony Advisor — multi-tenant RAG service for the Pivony platform.

- OpenAI-compatible API (`POST /v1/chat/completions`)
- Dual Qdrant collections: platform knowledge + sector knowledge
- GCS ingest for master guide and playbooks
- Contextual follow-ups and multi-turn conversation support

## Remote

```bash
git remote -v
# origin  git@github-pivony-advisor:emrecalisir/pivony-advisor.git
```

## Logs

| File | Content |
|------|---------|
| `logs/history.log` | JSON lines: user id, email, messages, LLM response, follow-ups |
| `logs/advisor.log` | Startup, errors, RAG, uvicorn — everything except history |

Log files are gitignored; the `logs/` directory is created automatically on startup.

## VM deploy

| | Clone | Port | systemd unit |
|---|--------|------|----------------|
| **Production** | `~/pivony-advisor` | **8000** | `pivony-advisor.service` |
| **Development** | `~/pivony-advisor-dev` | **8011** | `pivony-advisor-dev.service` |

Both can run on the same VM (different ports).

### Production (`master`, port **8000**)

```bash
cd ~/pivony-advisor
git pull origin master
sudo cp deploy/pivony-advisor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart pivony-advisor.service
curl -s http://127.0.0.1:8000/v1/models | head
```

Prod API: `PIVONY_MODELS_BASE_URL=http://127.0.0.1:8000`

### Development (`development`, port **8011**)

```bash
cd ~/pivony-advisor-dev
git pull origin development
bash scripts/bootstrap-dev-venv.sh
sudo bash scripts/install-advisor-dev-service.sh
curl -s http://127.0.0.1:8011/v1/models | head
```

Dev API: `PIVONY_MODELS_BASE_URL=http://127.0.0.1:8011`

Check both:

```bash
sudo ss -tlnp | grep -E '8000|8011'
```
