#!/usr/bin/env bash
# Full APK build: manifest + resources + all Java sources + dex + sign.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BT="${ANDROID_BUILD_TOOLS:-$HOME/Android/Sdk/build-tools/36.1.0}"
PLATFORM="${ANDROID_PLATFORM:-$HOME/Android/Sdk/platforms/android-36/android.jar}"
ZXING="${ROOT}/app/libs/core-3.5.3.jar"
OUT="${ROOT}/build/device-safety-manager-debug.apk"
UNSIGNED="${ROOT}/build/unsigned.apk"

if [[ ! -x "${BT}/aapt2" ]]; then
  echo "Missing aapt2 at ${BT}/aapt2" >&2
  exit 1
fi

cd "${ROOT}"
VERSION_CODE="1"
VERSION_NAME="1.0.0"
if [[ -f app/version.properties ]]; then
  VERSION_CODE="$(grep -E '^versionCode=' app/version.properties | cut -d= -f2- | tr -d ' \r' || echo 1)"
  VERSION_NAME="$(grep -E '^versionName=' app/version.properties | cut -d= -f2- | tr -d ' \r' || echo 1.0.0)"
fi

rm -rf build/compiled build/gen build/classes build/dex build/unsigned.apk
mkdir -p build/compiled build/gen build/classes build/dex

echo "Compiling resources (v${VERSION_NAME} / ${VERSION_CODE})..."
"${BT}/aapt2" compile --dir app/src/main/res -o build/compiled/resources.zip
"${BT}/aapt2" link \
  -I "${PLATFORM}" \
  --manifest app/src/main/AndroidManifest.xml \
  --version-code "${VERSION_CODE}" \
  --version-name "${VERSION_NAME}" \
  --java build/gen \
  -o "${UNSIGNED}" \
  build/compiled/resources.zip

echo "Compiling Java..."
javac -source 8 -target 8 \
  -bootclasspath "${PLATFORM}" \
  -classpath "${ZXING}" \
  -d build/classes \
  build/gen/com/example/devicesafety/R.java \
  app/src/main/java/com/example/devicesafety/*.java

echo "Building DEX..."
"${BT}/d8" --lib "${PLATFORM}" --output build/dex \
  build/classes/com/example/devicesafety/*.class \
  "${ZXING}"

echo "Packaging APK..."
(cd build/dex && zip -q "../unsigned.apk" classes.dex)

if [[ ! -f build/debug.keystore ]]; then
  keytool -genkeypair -v \
    -keystore build/debug.keystore \
    -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US"
fi

echo "Signing APK..."
"${BT}/apksigner" sign \
  --ks build/debug.keystore \
  --ks-pass pass:android \
  --key-pass pass:android \
  --out "${OUT}" \
  "${UNSIGNED}"

mkdir -p "${ROOT}/apk"
cp "${OUT}" "${ROOT}/apk/device-safety-manager-debug.apk"

echo
echo "Built: ${OUT}"
"${BT}/aapt" dump badging "${OUT}" | grep -E "uses-permission: name='android.permission.(READ_CALL_LOG|READ_SMS|READ_CONTACTS)'" || true
echo "Done."
