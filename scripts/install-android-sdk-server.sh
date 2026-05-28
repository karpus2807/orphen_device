#!/usr/bin/env bash
# Install Android SDK on the server for Web UI APK builds (no Android Studio).
set -euo pipefail

SDK_ROOT="${1:-/opt/android-sdk}"
ENV_FILE="${2:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/install-android-sdk-server.sh [/opt/android-sdk] [server.env path]"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq openjdk-17-jdk-headless unzip zip curl ca-certificates

if [[ ! -d "${SDK_ROOT}/cmdline-tools/latest/bin" ]]; then
  mkdir -p "${SDK_ROOT}/cmdline-tools"
  TMP_ZIP="$(mktemp).zip"
  curl -fsSL -o "${TMP_ZIP}" https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  unzip -q "${TMP_ZIP}" -d "${SDK_ROOT}/cmdline-tools"
  mv "${SDK_ROOT}/cmdline-tools/cmdline-tools" "${SDK_ROOT}/cmdline-tools/latest"
  rm -f "${TMP_ZIP}"
fi

export ANDROID_HOME="${SDK_ROOT}"
yes | "${SDK_ROOT}/cmdline-tools/latest/bin/sdkmanager" --sdk_root="${SDK_ROOT}" \
  "platform-tools" "platforms;android-36" "build-tools;36.0.0" "build-tools;36.1.0" || true

if [[ -n "${ENV_FILE}" && -f "${ENV_FILE}" ]]; then
  grep -q '^ANDROID_SDK_ROOT=' "${ENV_FILE}" 2>/dev/null && \
    sed -i "s|^ANDROID_SDK_ROOT=.*|ANDROID_SDK_ROOT=${SDK_ROOT}|" "${ENV_FILE}" || \
    echo "ANDROID_SDK_ROOT=${SDK_ROOT}" >> "${ENV_FILE}"
fi

echo "Android SDK ready at ${SDK_ROOT}"
echo "Restart backend: systemctl restart device-safety-backend.service"
