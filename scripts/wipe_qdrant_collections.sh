#!/usr/bin/env bash
# Delete Pivony Qdrant collections (hospitality sector + platform KC).
#
# Usage:
#   ./scripts/wipe_qdrant_collections.sh              # hospitality + platform only
#   ./scripts/wipe_qdrant_collections.sh --all-pivony # any collection named pivony_*
#
# Requires: curl, jq (optional)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QDRANT_URL="${QDRANT_URL:-http://${QDRANT_HOST:-127.0.0.1}:6333}"

delete_collection() {
  local name="$1"
  echo "Deleting collection: $name"
  curl -sf -X DELETE "${QDRANT_URL}/collections/${name}" >/dev/null \
    || echo "  (missing or already deleted)"
}

if [[ "${1:-}" == "--all-pivony" ]]; then
  if command -v jq >/dev/null 2>&1; then
    mapfile -t names < <(curl -sf "${QDRANT_URL}/collections" | jq -r '.result.collections[].name')
    for name in "${names[@]}"; do
      [[ "$name" == pivony_* ]] && delete_collection "$name"
    done
  else
    echo "Install jq or delete collections manually via Qdrant UI"
    exit 1
  fi
else
  delete_collection "pivony_sector_hospitality"
  delete_collection "pivony_platform_knowledge"
fi

echo "Done. Re-export with hotel/date filters, then ingest with RECREATE_COLLECTIONS=true"
