#!/usr/bin/env bash
# Start uvicorn for prod or dev. Port comes from ADVISOR_PORT (required in systemd).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ADVISOR_PORT:?ADVISOR_PORT is not set}"
VENV_DIR="${ADVISOR_VENV:-${ROOT}/venv}"
UVICORN="${VENV_DIR}/bin/uvicorn"

if [[ ! -x "${UVICORN}" ]]; then
  echo "uvicorn not found at ${UVICORN}" >&2
  echo "Run: bash ${ROOT}/scripts/bootstrap-dev-venv.sh" >&2
  exit 127
fi

cd "${ROOT}"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${UVICORN}" api.main:app --host 0.0.0.0 --port "${PORT}"
