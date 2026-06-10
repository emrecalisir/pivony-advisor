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

### Production (`master`, port **8011**)

```bash
cd ~/pivony-advisor
git pull origin master
source venv/bin/activate
sudo cp deploy/pivony-advisor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart pivony-advisor.service
```

### Development (`development`, port **8012**)

Runs from a separate clone so it can restart without touching prod. Point the **dev API**
`PIVONY_MODELS_BASE_URL` at `http://127.0.0.1:8012` (not 8011).

```bash
cd ~/pivony-advisor-dev
git pull origin development
source venv/bin/activate
chmod +x scripts/start_advisor.sh
sudo bash scripts/install-advisor-dev-service.sh
```

Or manually:

```bash
sudo cp deploy/pivony-advisor-dev.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart pivony-advisor-dev.service
```

**If it still tries port 8011**, the old unit is still installed — check:

```bash
grep -E 'ADVISOR_PORT|ExecStart|8011' /etc/systemd/system/pivony-advisor-dev.service
# Must show ADVISOR_PORT=8012 and start_advisor.sh (not --port 8011)
```

Check:

```bash
curl -s http://127.0.0.1:8011/v1/models | head
curl -s http://127.0.0.1:8012/v1/models | head
sudo ss -tlnp | grep -E '8011|8012'
```
