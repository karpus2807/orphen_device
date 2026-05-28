#!/usr/bin/env bash
# Build Orphen APK Installer (update-manager) — same toolchain as device-safety build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/update-manager/src/main"
BT="${ANDROID_BUILD_TOOLS:-$HOME/Android/Sdk/build-tools/36.1.0}"
PLATFORM="${ANDROID_PLATFORM:-$HOME/Android/Sdk/platforms/android-34/android.jar}"
OUT="${ROOT}/apk/orphen-update-manager.apk"
UNSIGNED="${ROOT}/build/update-manager-unsigned.apk"

if [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
  BT_CAND="${ANDROID_SDK_ROOT}/build-tools"
  if [[ -d "${BT_CAND}" ]]; then
    BT="$(find "${BT_CAND}" -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)"
  fi
  if [[ -f "${ANDROID_SDK_ROOT}/platforms/android-36/android.jar" ]]; then
    PLATFORM="${ANDROID_SDK_ROOT}/platforms/android-36/android.jar"
  fi
fi

if [[ ! -x "${BT}/aapt2" ]]; then
  echo "Missing aapt2 at ${BT}/aapt2 — set ANDROID_SDK_ROOT or install SDK." >&2
  exit 1
fi

cd "${ROOT}"
rm -rf build/um-compiled build/um-classes build/um-dex
mkdir -p build/um-compiled build/um-classes build/um-dex apk

echo "Compiling update-manager resources..."
if [[ -d "${SRC}/res" ]]; then
  "${BT}/aapt2" compile --dir "${SRC}/res" -o build/um-compiled/resources.zip
  "${BT}/aapt2" link \
    -I "${PLATFORM}" \
    --manifest "${SRC}/AndroidManifest.xml" \
    --version-code 3 \
    --version-name "1.0.2" \
    -o "${UNSIGNED}" \
    build/um-compiled/resources.zip
else
  "${BT}/aapt2" link \
    -I "${PLATFORM}" \
    --manifest "${SRC}/AndroidManifest.xml" \
    --version-code 3 \
    --version-name "1.0.2" \
    -o "${UNSIGNED}"
fi

echo "Compiling Java..."
javac -source 8 -target 8 -bootclasspath "${PLATFORM}" -d build/um-classes \
  "${SRC}/java/com/orphen/updatemanager/"*.java

echo "DEX..."
"${BT}/d8" --lib "${PLATFORM}" --output build/um-dex \
  build/um-classes/com/orphen/updatemanager/*.class

echo "Packaging..."
(cd build/um-dex && zip -q "../update-manager-unsigned.apk" classes.dex)
mv -f build/update-manager-unsigned.apk "${UNSIGNED}"

if [[ ! -f build/debug.keystore ]]; then
  keytool -genkeypair -v \
    -keystore build/debug.keystore \
    -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US"
fi

echo "Signing..."
"${BT}/apksigner" sign \
  --ks build/debug.keystore \
  --ks-pass pass:android \
  --key-pass pass:android \
  --out "${OUT}" \
  "${UNSIGNED}"

echo "Built ${OUT}"
