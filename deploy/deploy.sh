#!/usr/bin/env bash
# Pull latest code from git, replace tracked files, refresh systemd, restart services.
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BRANCH="${DEPLOY_BRANCH:-main}"
SERVICE_NAME="${DEPLOY_SERVICE:-device-safety-backend.service}"
WEBHOOK_SERVICE="${DEPLOY_WEBHOOK_SERVICE:-device-safety-webhook.service}"
LOG_FILE="${DEPLOY_LOG:-/var/log/device-safety-deploy.log}"

log() {
  echo "[$(date -Iseconds)] $*" | tee -a "${LOG_FILE}"
}

mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null || LOG_FILE="/tmp/device-safety-deploy.log"

cd "${APP_DIR}"

if [[ ! -d .git ]]; then
  log "ERROR: ${APP_DIR} is not a git repository"
  exit 1
fi

DEPLOY_USER="$(stat -c '%U' "${APP_DIR}" 2>/dev/null || echo "${USER}")"
SERVER_PORT="9030"
if [[ -f deploy/server.env ]]; then
  SERVER_PORT="$(grep -E '^DEVICE_SAFETY_PORT=' deploy/server.env | cut -d= -f2- | tr -d ' \r' || true)"
  SERVER_PORT="${SERVER_PORT:-9030}"
fi

refresh_systemd_units() {
  if [[ ! -f deploy/device-safety-backend.service ]]; then
    return 0
  fi
  install_unit() {
    local src="$1"
    local name="$2"
    sed \
      -e "s|__APP_DIR__|${APP_DIR}|g" \
      -e "s|__DEPLOY_USER__|${DEPLOY_USER}|g" \
      -e "s|__DEVICE_SAFETY_PORT__|${SERVER_PORT}|g" \
      "${src}" > "/tmp/${name}"
    if ! sudo cmp -s "/tmp/${name}" "/etc/systemd/system/${name}" 2>/dev/null; then
      sudo cp "/tmp/${name}" "/etc/systemd/system/${name}"
      log "Updated systemd unit ${name}"
      return 0
    fi
    return 1
  }
  local changed=0
  install_unit "${APP_DIR}/deploy/device-safety-backend.service" "device-safety-backend.service" && changed=1 || true
  install_unit "${APP_DIR}/deploy/device-safety-webhook.service" "device-safety-webhook.service" && changed=1 || true
  if [[ "${changed}" -eq 1 ]]; then
    sudo systemctl daemon-reload
  fi
}

log "Fetching origin/${BRANCH}..."
git fetch origin "${BRANCH}"

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/${BRANCH}")"

if [[ "${LOCAL}" == "${REMOTE}" ]]; then
  log "Already up to date (${LOCAL:0:8})"
  exit 0
fi

log "Replacing code ${LOCAL:0:8} -> ${REMOTE:0:8} (hard reset to origin/${BRANCH})"
git reset --hard "origin/${BRANCH}"
# Remove untracked files/dirs except server data (gitignored under backend/data).
git clean -fd

chmod +x deploy/*.sh deploy/webhook-server.py 2>/dev/null || true
chmod +x scripts/*.sh 2>/dev/null || true

refresh_systemd_units || true

if command -v systemctl >/dev/null 2>&1; then
  log "Restarting ${SERVICE_NAME}"
  sudo systemctl restart "${SERVICE_NAME}"
  sudo systemctl is-active --quiet "${SERVICE_NAME}"
  log "Backend is active."

  if sudo systemctl is-enabled --quiet "${WEBHOOK_SERVICE}" 2>/dev/null; then
    log "Restarting ${WEBHOOK_SERVICE}"
    sudo systemctl restart "${WEBHOOK_SERVICE}" || true
  fi

  if [[ -f deploy/docker-compose.yml ]] && command -v docker >/dev/null 2>&1; then
    if docker compose -f deploy/docker-compose.yml ps -q 2>/dev/null | grep -q .; then
      log "Refreshing Docker stack (MariaDB/phpMyAdmin)"
      (cd deploy && docker compose --env-file .env.docker -f docker-compose.yml up -d) || true
    fi
  fi

  log "Deploy complete."
else
  log "systemctl not found. Run manually: python3 backend/server.py"
fi
