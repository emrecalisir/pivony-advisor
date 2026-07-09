#!/usr/bin/env bash
# Pull quality-loop outputs from gcp-pivony-advisor to local machine (no SSH tunnel).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${QUALITY_LOOP_SYNC_HOST:-gcp-pivony-advisor}"
REMOTE_DIR="${QUALITY_LOOP_SYNC_DIR:-~/pivony-advisor-dev/quality_loop/outputs}"
LOCAL_DIR="${ROOT}/quality_loop/outputs"

mkdir -p "${LOCAL_DIR}/sessions" "${LOCAL_DIR}/runs"

echo "Syncing ${REMOTE_HOST}:${REMOTE_DIR} → ${LOCAL_DIR}"

scp -r "${REMOTE_HOST}:${REMOTE_DIR}/." "${LOCAL_DIR}/"

echo "Done."
echo "  sessions: $(find "${LOCAL_DIR}/sessions" -name '*.json' 2>/dev/null | wc -l | tr -d ' ') files"
echo "  runs:     $(find "${LOCAL_DIR}/runs" -name '*.json' 2>/dev/null | wc -l | tr -d ' ') files"
echo ""
echo "Open UI locally:"
echo "  bash scripts/run_quality_loop_ui.sh"
echo "  open http://127.0.0.1:8020"
