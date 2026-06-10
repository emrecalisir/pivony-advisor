#!/usr/bin/env bash
# Create dev venv + install deps on first run. Safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -x "${ROOT}/venv/bin/uvicorn" ]]; then
  echo "venv ready: ${ROOT}/venv"
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found" >&2
  exit 1
fi

echo "Creating venv at ${ROOT}/venv ..."
python3 -m venv "${ROOT}/venv"
"${ROOT}/venv/bin/pip" install --upgrade pip
"${ROOT}/venv/bin/pip" install -r "${ROOT}/requirements.txt"

if [[ ! -f "${ROOT}/.env" && -f "${ROOT}/../pivony-advisor/.env" ]]; then
  cp "${ROOT}/../pivony-advisor/.env" "${ROOT}/.env"
  echo "Copied .env from ../pivony-advisor/.env (review ADVISOR_PORT / API URLs if needed)"
fi

echo "Done. uvicorn: ${ROOT}/venv/bin/uvicorn"
