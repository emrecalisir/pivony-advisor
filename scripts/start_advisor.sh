#!/usr/bin/env bash
# Start uvicorn for prod or dev. Port comes from ADVISOR_PORT (required in systemd).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ADVISOR_PORT:?ADVISOR_PORT is not set}"

exec "${ROOT}/venv/bin/uvicorn" api.main:app --host 0.0.0.0 --port "${PORT}"
