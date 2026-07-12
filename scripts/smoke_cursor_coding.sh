#!/usr/bin/env bash
# Dry-run or live smoke test for Cursor coding backend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

VENV_DIR="${ROOT}/.venv-quality-loop"
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"
fi

exec python -m quality_loop.smoke_cursor_coding "$@"
