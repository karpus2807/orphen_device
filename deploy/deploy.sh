#!/usr/bin/env bash
# Pull latest code from git and restart the backend service.
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BRANCH="${DEPLOY_BRANCH:-main}"
SERVICE_NAME="${DEPLOY_SERVICE:-device-safety-backend.service}"
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

log "Fetching origin/${BRANCH}..."
git fetch origin "${BRANCH}"

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/${BRANCH}")"

if [[ "${LOCAL}" == "${REMOTE}" ]]; then
  log "Already up to date (${LOCAL:0:8})"
  exit 0
fi

log "Updating ${LOCAL:0:8} -> ${REMOTE:0:8}"
git reset --hard "origin/${BRANCH}"

if command -v systemctl >/dev/null 2>&1; then
  log "Restarting ${SERVICE_NAME}"
  sudo systemctl restart "${SERVICE_NAME}"
  sudo systemctl is-active --quiet "${SERVICE_NAME}"
  log "Deploy complete. Service is active."
else
  log "systemctl not found. Run manually: python3 backend/server.py"
fi
