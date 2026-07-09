#!/usr/bin/env bash
# Bootstrap an isolated Python 3.12 venv for the CrewAI quality loop.
#
# CrewAI requires Python >=3.10 and <3.14. Advisor venv may use 3.14+, so this
# keeps quality_loop on a compatible interpreter (uv-managed CPython 3.12).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

VENV_DIR="${ROOT}/.venv-quality-loop"
PYTHON_VERSION="${QUALITY_LOOP_PYTHON_VERSION:-3.12}"
REQ_FILE="${ROOT}/requirements-quality-loop.txt"

if [[ ! -f "${REQ_FILE}" ]]; then
  echo "Missing ${REQ_FILE}" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (required by CrewAI)..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Creating quality-loop venv with Python ${PYTHON_VERSION} ..."
  uv venv "${VENV_DIR}" --python "${PYTHON_VERSION}"
else
  echo "Using existing venv: ${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

PY_VER="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$(python -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$(python -c 'import sys; print(sys.version_info.minor)')"

if (( PY_MAJOR < 3 || PY_MAJOR > 3 || PY_MINOR < 10 || PY_MINOR >= 14 )); then
  echo "CrewAI requires Python >=3.10 and <3.14; found ${PY_VER}" >&2
  exit 1
fi

echo "Installing quality-loop dependencies with uv ..."
uv pip install -r "${REQ_FILE}"

python - <<'PY'
import sys
from crewai import Agent, Crew, Process
from crewai.tools import BaseTool

print(f"CrewAI OK on Python {sys.version.split()[0]}")
PY

echo ""
echo "Quality loop venv ready:"
echo "  ${VENV_DIR}/bin/python"
echo "Run:"
echo "  bash scripts/run_quality_loop.sh"
echo "  bash scripts/run_quality_loop_ui.sh"
