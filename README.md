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

```bash
cd ~/pivony-advisor
git pull origin master
source venv/bin/activate
sudo systemctl restart pivony-advisor.service
```
