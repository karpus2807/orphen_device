#!/usr/bin/env bash
# One-command fresh server setup: deps, Docker (MariaDB+phpMyAdmin), clone, systemd, optional Android SDK.
#
# Usage (on a new Ubuntu/Debian server as root or with sudo):
#   curl -fsSL https://raw.githubusercontent.com/karpus2807/orphen_device/feature/server-update-manager/deploy/setup-all.sh | sudo bash -s -- \
#     --branch feature/server-update-manager \
#     --app-dir /opt/device-safety-manager \
#     --port 9030
#
# Or from a cloned repo:
#   sudo bash deploy/setup-all.sh --branch feature/server-update-manager
set -euo pipefail

APP_DIR="/opt/device-safety-manager"
REPO_URL="https://github.com/karpus2807/orphen_device.git"
BRANCH="feature/server-update-manager"
SERVER_PORT="9030"
INSTALL_ANDROID_SDK="0"
DEPLOY_USER="${SUDO_USER:-root}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) APP_DIR="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --port) SERVER_PORT="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --with-android-sdk) INSTALL_ANDROID_SDK="1"; shift ;;
    --user) DEPLOY_USER="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: sudo bash deploy/setup-all.sh [--app-dir DIR] [--branch BRANCH] [--port PORT] [--with-android-sdk]"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

echo "=== Device Safety — full server setup ==="
echo "App dir: ${APP_DIR}  Branch: ${BRANCH}  Port: ${SERVER_PORT}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  git curl ca-certificates python3 python3-pip python3-venv \
  openjdk-17-jdk-headless unzip zip \
  docker.io docker-compose-v2 2>/dev/null || apt-get install -y -qq docker-compose-plugin

systemctl enable docker 2>/dev/null || true
systemctl start docker 2>/dev/null || true

if [[ ! -d "${APP_DIR}/.git" ]]; then
  mkdir -p "$(dirname "${APP_DIR}")"
  sudo -u "${DEPLOY_USER}" git clone --branch "${BRANCH}" --single-branch "${REPO_URL}" "${APP_DIR}"
else
  cd "${APP_DIR}"
  sudo -u "${DEPLOY_USER}" git fetch origin "${BRANCH}"
  sudo -u "${DEPLOY_USER}" git checkout "${BRANCH}"
  sudo -u "${DEPLOY_USER}" git pull origin "${BRANCH}" || true
fi

cd "${APP_DIR}"
chmod +x deploy/*.sh scripts/*.sh deploy/webhook-server.py 2>/dev/null || true

mkdir -p backend/data apk build
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}"

if [[ ! -f deploy/server.env ]]; then
  cp deploy/server.env.example deploy/server.env
  chown "${DEPLOY_USER}:${DEPLOY_USER}" deploy/server.env
fi

# Unlimited history + release center
grep -q DEVICE_SAFETY_UNLIMITED deploy/server.env 2>/dev/null || \
  echo "DEVICE_SAFETY_UNLIMITED=1" >> deploy/server.env
grep -q DEVICE_SAFETY_PORT deploy/server.env 2>/dev/null && \
  sed -i "s/^DEVICE_SAFETY_PORT=.*/DEVICE_SAFETY_PORT=${SERVER_PORT}/" deploy/server.env || \
  echo "DEVICE_SAFETY_PORT=${SERVER_PORT}" >> deploy/server.env

# MariaDB + phpMyAdmin (localhost only)
if command -v docker >/dev/null 2>&1; then
  cd "${APP_DIR}/deploy"
  MYSQL_PASSWORD="$(openssl rand -hex 16 2>/dev/null || head -c 16 /dev/urandom | xxd -p)"
  MYSQL_ROOT_PASSWORD="$(openssl rand -hex 16 2>/dev/null || head -c 16 /dev/urandom | xxd -p)"
  cat > .env.docker <<EOF
MYSQL_PASSWORD=${MYSQL_PASSWORD}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
EOF
  docker compose -f docker-compose.yml --env-file .env.docker up -d
  echo "phpMyAdmin: http://127.0.0.1:8081  (user: device_safety  pass: see ${APP_DIR}/deploy/.env.docker)"
fi

if [[ "${INSTALL_ANDROID_SDK}" == "1" ]]; then
  echo "Installing Android SDK (for Web UI APK builds on server)..."
  SDK_ROOT="/opt/android-sdk"
  if [[ ! -d "${SDK_ROOT}/cmdline-tools" ]]; then
    mkdir -p "${SDK_ROOT}"
    TMP_ZIP="$(mktemp).zip"
    curl -fsSL -o "${TMP_ZIP}" https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
    unzip -q "${TMP_ZIP}" -d "${SDK_ROOT}/cmdline-tools"
    mv "${SDK_ROOT}/cmdline-tools/cmdline-tools" "${SDK_ROOT}/cmdline-tools/latest"
    rm -f "${TMP_ZIP}"
    yes | "${SDK_ROOT}/cmdline-tools/latest/bin/sdkmanager" --sdk_root="${SDK_ROOT}" \
      "platform-tools" "platforms;android-36" "build-tools;36.0.0" || true
  fi
  chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${SDK_ROOT}"
  grep -q ANDROID_SDK_ROOT deploy/server.env 2>/dev/null || \
    echo "ANDROID_SDK_ROOT=${SDK_ROOT}" >> deploy/server.env
fi

bash deploy/install-server.sh "${APP_DIR}" "${REPO_URL}" "${SERVER_PORT}"

echo
echo "=== Setup complete ==="
echo "Dashboard:  http://$(hostname -I | awk '{print $1}'):${SERVER_PORT}"
echo "App Release Center: http://...:${SERVER_PORT}/app-release-center"
echo "phpMyAdmin (local): http://127.0.0.1:8081"
echo "Enable webhook: sudo systemctl enable --now device-safety-webhook.service"
echo "Build APK on server: install with --with-android-sdk or build locally and upload via Web UI"
