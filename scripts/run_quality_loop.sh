#!/usr/bin/env bash
# Run CrewAI quality loop (uses .venv-quality-loop, Python 3.10–3.13).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export PATH="${HOME}/.local/bin:${PATH}"

VENV_DIR="${ROOT}/.venv-quality-loop"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Quality-loop venv missing — bootstrapping ..." >&2
  bash "${ROOT}/scripts/bootstrap-quality-loop-venv.sh"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

PY_MINOR="$(python -c 'import sys; print(sys.version_info.minor)')"
if (( PY_MINOR >= 14 )); then
  echo "CrewAI requires Python <3.14. Recreate venv:" >&2
  echo "  rm -rf .venv-quality-loop && bash scripts/bootstrap-quality-loop-venv.sh" >&2
  exit 1
fi

mkdir -p "${ROOT}/quality_loop/outputs/sessions" "${ROOT}/logs"

exec python -m quality_loop.crew "$@"
