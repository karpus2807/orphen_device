#!/usr/bin/env bash
# Full APK build: manifest + resources + all Java sources + dex + sign.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZXING="${ROOT}/app/libs/core-3.5.3.jar"
OUT="${ROOT}/build/device-safety-manager-debug.apk"
UNSIGNED="${ROOT}/build/unsigned.apk"

resolve_sdk() {
  local sdk_root=""
  if [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
    sdk_root="${ANDROID_SDK_ROOT}"
  elif [[ -f "${ROOT}/deploy/server.env" ]]; then
    sdk_root="$(grep -E '^ANDROID_SDK_ROOT=' "${ROOT}/deploy/server.env" | cut -d= -f2- | tr -d ' \r' || true)"
  fi
  if [[ -z "${sdk_root}" && -d /opt/android-sdk ]]; then
    sdk_root="/opt/android-sdk"
  fi
  if [[ -z "${sdk_root}" && -d "${HOME}/Android/Sdk" ]]; then
    sdk_root="${HOME}/Android/Sdk"
  fi
  if [[ -z "${sdk_root}" ]]; then
    echo "Android SDK not found. Set ANDROID_SDK_ROOT or run: sudo bash scripts/install-android-sdk-server.sh" >&2
    exit 1
  fi
  BT=""
  if [[ -d "${sdk_root}/build-tools" ]]; then
    BT="$(find "${sdk_root}/build-tools" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort -V | tail -1)"
  fi
  PLATFORM=""
  for api in 36 34; do
    if [[ -f "${sdk_root}/platforms/android-${api}/android.jar" ]]; then
      PLATFORM="${sdk_root}/platforms/android-${api}/android.jar"
      break
    fi
  done
  export ANDROID_SDK_ROOT="${sdk_root}"
  export ANDROID_BUILD_TOOLS="${BT}"
  export ANDROID_PLATFORM="${PLATFORM}"
}

resolve_sdk

if [[ ! -x "${BT}/aapt2" ]]; then
  echo "Missing aapt2 at ${BT}/aapt2 (SDK: ${ANDROID_SDK_ROOT})" >&2
  exit 1
fi
if [[ ! -f "${PLATFORM}" ]]; then
  echo "Missing platform jar at ${PLATFORM}" >&2
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
"${BT}/aapt2" dump badging "${OUT}" 2>/dev/null | grep -E "package:|versionCode|versionName" || \
  "${BT}/aapt" dump badging "${OUT}" 2>/dev/null | grep -E "package:|versionCode|versionName" || true
echo "Done."
