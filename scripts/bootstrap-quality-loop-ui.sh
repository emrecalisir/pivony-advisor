#!/usr/bin/env bash
# Lightweight UI venv (FastAPI only — no CrewAI / Python 3.14 constraint).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

VENV_DIR="${ROOT}/.venv-quality-loop-ui"
PYTHON_VERSION="${QUALITY_LOOP_UI_PYTHON_VERSION:-3.12}"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Creating UI venv with Python ${PYTHON_VERSION} ..."
  uv venv "${VENV_DIR}" --python "${PYTHON_VERSION}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
uv pip install fastapi uvicorn python-dotenv

python - <<'PY'
import fastapi, uvicorn
print("Quality Loop UI deps OK")
PY

echo "UI venv ready: ${VENV_DIR}"
