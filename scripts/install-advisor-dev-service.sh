#!/usr/bin/env bash
# Install/reinstall the development systemd unit (port 8011).
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/install-advisor-dev-service.sh" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="${ROOT}/deploy/pivony-advisor-dev.service"
UNIT_DST="/etc/systemd/system/pivony-advisor-dev.service"
SVC_USER="${SVC_USER:-ubuntu}"

if [[ ! -f "${UNIT_SRC}" ]]; then
  echo "Missing ${UNIT_SRC}" >&2
  exit 1
fi

chmod +x "${ROOT}/scripts/start_advisor.sh" "${ROOT}/scripts/bootstrap-dev-venv.sh"
sudo -u "${SVC_USER}" bash "${ROOT}/scripts/bootstrap-dev-venv.sh"

cp "${UNIT_SRC}" "${UNIT_DST}"
systemctl daemon-reload
systemctl enable pivony-advisor-dev.service
systemctl restart pivony-advisor-dev.service

echo "Installed ${UNIT_DST}"
echo "ExecStart:"
grep -E '^ExecStart=|^Environment=ADVISOR_PORT' "${UNIT_DST}" || true
echo ""
systemctl status pivony-advisor-dev.service --no-pager -l | head -20
echo ""
ss -tlnp | grep ':8011' || true
