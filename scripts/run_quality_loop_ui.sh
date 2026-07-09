#!/usr/bin/env bash
# Local quality loop inspection UI (no SSH tunnel required when using sync script).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export PATH="${HOME}/.local/bin:${PATH}"

UI_VENV="${ROOT}/.venv-quality-loop-ui"
QL_VENV="${ROOT}/.venv-quality-loop"

pick_venv() {
  if [[ -x "${UI_VENV}/bin/python" ]]; then
    echo "${UI_VENV}"
  elif [[ -x "${QL_VENV}/bin/python" ]]; then
    echo "${QL_VENV}"
  else
    bash "${ROOT}/scripts/bootstrap-quality-loop-ui.sh" >/dev/null
    echo "${UI_VENV}"
  fi
}

VENV_DIR="$(pick_venv)"
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

HOST="${QUALITY_LOOP_UI_HOST:-127.0.0.1}"
PORT="${QUALITY_LOOP_UI_PORT:-8020}"

mkdir -p "${ROOT}/quality_loop/outputs/sessions" "${ROOT}/quality_loop/outputs/runs" "${ROOT}/logs"

echo "Quality Loop UI → http://${HOST}:${PORT}"
echo "Sync from server: bash scripts/sync_quality_loop_outputs.sh"
echo "Remote API mode: UI → Ayarlar → API adresi (ör. http://SERVER:8020)"

exec python -m quality_loop.ui.app
