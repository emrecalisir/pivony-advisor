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

### Production (`master`)

Prod host only — `~/pivony-advisor`, port **8011**. Do not run alongside
`pivony-advisor-dev` on the same machine (same port).

```bash
cd ~/pivony-advisor
git pull origin master
bash scripts/bootstrap-dev-venv.sh   # or existing venv
sudo cp deploy/pivony-advisor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart pivony-advisor.service
```

### Development (`development`)

Dev clone — `~/pivony-advisor-dev`, port **8011**. Point dev API at
`PIVONY_MODELS_BASE_URL=http://127.0.0.1:8011`.

First time:

```bash
cd ~/pivony-advisor-dev
git pull origin development
bash scripts/bootstrap-dev-venv.sh
sudo bash scripts/install-advisor-dev-service.sh
```

Check:

```bash
curl -s http://127.0.0.1:8011/v1/models | head
sudo ss -tlnp | grep 8011
```
