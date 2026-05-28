#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/update-manager/src/main"
BT="${ANDROID_BUILD_TOOLS:-$HOME/Android/Sdk/build-tools/36.1.0}"
PLATFORM="${ANDROID_PLATFORM:-$HOME/Android/Sdk/platforms/android-34/android.jar}"
OUT="${ROOT}/apk/orphen-update-manager.apk"
UNSIGNED="${ROOT}/build/update-manager-unsigned.apk"
KS="${ROOT}/signing/release.keystore"
ALIAS="${SIGNING_ALIAS:-orphenrelease}"
STORE_PASS="${SIGNING_STORE_PASS:-orphen2026}"

if [[ ! -f "${KS}" ]]; then
  KS="${ROOT}/signing/debug.keystore"
  ALIAS="androiddebugkey"
  STORE_PASS="android"
fi

cd "${ROOT}"
rm -rf build/um-compiled build/um-classes build/um-dex
mkdir -p build/um-compiled build/um-classes build/um-dex apk

"${BT}/aapt2" compile --dir "${SRC}/res" -o build/um-compiled/resources.zip
"${BT}/aapt2" link \
  -I "${PLATFORM}" \
  --manifest "${SRC}/AndroidManifest.xml" \
  --version-code 1 \
  --version-name "1.0.0" \
  -o "${UNSIGNED}" \
  build/um-compiled/resources.zip

javac -source 8 -target 8 -bootclasspath "${PLATFORM}" -d build/um-classes \
  "${SRC}/java/com/orphen/updatemanager/"*.java

"${BT}/d8" --lib "${PLATFORM}" --output build/um-dex \
  build/um-classes/com/orphen/updatemanager/*.class

(cd build/um-dex && zip -q "../update-manager-unsigned.apk" classes.dex)
mv build/update-manager-unsigned.apk "${UNSIGNED}"

"${BT}/apksigner" sign \
  --ks "${KS}" \
  --ks-key-alias "${ALIAS}" \
  --ks-pass "pass:${STORE_PASS}" \
  --key-pass "pass:${STORE_PASS}" \
  --out "${OUT}" \
  "${UNSIGNED}"

echo "Built ${OUT}"
