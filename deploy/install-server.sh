#!/usr/bin/env bash
# One-time setup on a Linux server: clone repo, install systemd, enable GitHub auto-deploy.
set -euo pipefail

APP_DIR="${1:-/opt/device-safety-manager}"
REPO_URL="${2:-https://github.com/karpus2807/orphen_device.git}"
SERVER_PORT="${3:-9030}"
GIT_BRANCH="${4:-main}"
ENABLE_WEBHOOK="${5:-1}"
DEPLOY_USER="${SUDO_USER:-$(whoami)}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash deploy/install-server.sh [app-dir] [repo-url] [port] [branch] [enable-webhook:0|1]"
  exit 1
fi

echo "Installing Device Safety backend to ${APP_DIR} (port ${SERVER_PORT}, branch ${GIT_BRANCH})"

if [[ ! -d "${APP_DIR}/.git" ]]; then
  mkdir -p "$(dirname "${APP_DIR}")"
  sudo -u "${DEPLOY_USER}" git clone --branch "${GIT_BRANCH}" --single-branch "${REPO_URL}" "${APP_DIR}"
else
  echo "Repo already exists at ${APP_DIR}"
  cd "${APP_DIR}"
  sudo -u "${DEPLOY_USER}" git fetch origin "${GIT_BRANCH}"
  sudo -u "${DEPLOY_USER}" git checkout "${GIT_BRANCH}"
  sudo -u "${DEPLOY_USER}" git reset --hard "origin/${GIT_BRANCH}"
fi

mkdir -p "${APP_DIR}/backend/data" "${APP_DIR}/apk" "${APP_DIR}/build"
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
chmod +x "${APP_DIR}/deploy/"*.sh "${APP_DIR}/scripts/"*.sh 2>/dev/null || true

if [[ -f "${APP_DIR}/deploy/device-safety-deploy.sudoers" ]]; then
  sed -e "s|__DEPLOY_USER__|${DEPLOY_USER}|g" \
    "${APP_DIR}/deploy/device-safety-deploy.sudoers" > "/etc/sudoers.d/device-safety-deploy"
  chmod 440 "/etc/sudoers.d/device-safety-deploy"
fi

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
fi

sed -i "s|^WEBHOOK_BRANCH=.*|WEBHOOK_BRANCH=${GIT_BRANCH}|" "${APP_DIR}/deploy/webhook.env"
sed -i "s|^APP_DIR=.*|APP_DIR=${APP_DIR}|" "${APP_DIR}/deploy/webhook.env"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}/deploy/webhook.env"

systemctl daemon-reload
systemctl enable device-safety-backend.service
systemctl restart device-safety-backend.service

if [[ "${ENABLE_WEBHOOK}" == "1" ]]; then
  systemctl enable device-safety-webhook.service
  systemctl restart device-safety-webhook.service
fi

echo
echo "Backend service:"
systemctl status device-safety-backend.service --no-pager || true

if [[ "${ENABLE_WEBHOOK}" == "1" ]]; then
  echo
  echo "Auto-deploy webhook (branch: ${GIT_BRANCH}):"
  systemctl status device-safety-webhook.service --no-pager || true
  echo
  echo "Add GitHub webhook: http://$(hostname -I | awk '{print $1}'):9001/webhook"
  echo "Secret (WEBHOOK_SECRET):"
  grep WEBHOOK_SECRET "${APP_DIR}/deploy/webhook.env" || true
fi

echo
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):${SERVER_PORT}"
echo "Manual deploy: sudo -u ${DEPLOY_USER} APP_DIR=${APP_DIR} DEPLOY_BRANCH=${GIT_BRANCH} bash ${APP_DIR}/deploy/deploy.sh"
