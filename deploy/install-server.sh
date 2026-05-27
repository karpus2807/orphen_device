#!/usr/bin/env bash
# One-time setup on a Linux server: clone repo, install systemd services, enable auto-deploy.
set -euo pipefail

APP_DIR="${1:-/opt/device-safety-manager}"
REPO_URL="${2:-https://github.com/karpus2807/orphen_device.git}"
SERVER_PORT="${3:-9030}"
DEPLOY_USER="${SUDO_USER:-$(whoami)}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash deploy/install-server.sh [app-dir] [repo-url] [port]"
  exit 1
fi

echo "Installing Device Safety backend to ${APP_DIR} (port ${SERVER_PORT})"

if [[ ! -d "${APP_DIR}/.git" ]]; then
  mkdir -p "$(dirname "${APP_DIR}")"
  sudo -u "${DEPLOY_USER}" git clone "${REPO_URL}" "${APP_DIR}"
else
  echo "Repo already exists at ${APP_DIR}"
fi

mkdir -p "${APP_DIR}/backend/data"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}"

install_unit() {
  local src="$1"
  local name="$2"
  sed \
    -e "s|__APP_DIR__|${APP_DIR}|g" \
    -e "s|__DEPLOY_USER__|${DEPLOY_USER}|g" \
    -e "s|__DEVICE_SAFETY_PORT__|${SERVER_PORT}|g" \
    "${src}" > "/etc/systemd/system/${name}"
}

install_unit "${APP_DIR}/deploy/device-safety-backend.service" "device-safety-backend.service"
install_unit "${APP_DIR}/deploy/device-safety-webhook.service" "device-safety-webhook.service"

chmod +x "${APP_DIR}/deploy/deploy.sh" "${APP_DIR}/deploy/webhook-server.py"

if [[ ! -f "${APP_DIR}/deploy/server.env" ]]; then
  cp "${APP_DIR}/deploy/server.env.example" "${APP_DIR}/deploy/server.env"
  sed -i "s|9030|${SERVER_PORT}|g" "${APP_DIR}/deploy/server.env"
  chown "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}/deploy/server.env"
fi

if [[ ! -f "${APP_DIR}/deploy/webhook.env" ]]; then
  cp "${APP_DIR}/deploy/webhook.env.example" "${APP_DIR}/deploy/webhook.env"
  SECRET="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 64)"
  sed -i "s|change-me-to-a-long-random-string|${SECRET}|" "${APP_DIR}/deploy/webhook.env"
  sed -i "s|/opt/device-safety-manager|${APP_DIR}|g" "${APP_DIR}/deploy/webhook.env"
  chown "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}/deploy/webhook.env"
  echo
  echo "Generated webhook secret in ${APP_DIR}/deploy/webhook.env"
  echo "Use the same secret in GitHub repo webhook settings."
fi

systemctl daemon-reload
systemctl enable device-safety-backend.service
systemctl restart device-safety-backend.service

echo
echo "Backend service:"
systemctl status device-safety-backend.service --no-pager || true
echo
echo "Optional auto-deploy webhook:"
echo "  sudo systemctl enable --now device-safety-webhook.service"
echo "  Then add GitHub webhook: http://YOUR_SERVER_IP:9001/webhook"
echo "  Secret: see ${APP_DIR}/deploy/webhook.env"
echo
echo "Dashboard: http://YOUR_SERVER_IP:${SERVER_PORT}"
