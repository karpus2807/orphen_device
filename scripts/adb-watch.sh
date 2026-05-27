#!/usr/bin/env bash
# Keeps `adb reverse` alive while a USB device stays connected.
# Run in background during dev: bash scripts/adb-watch.sh
set -euo pipefail

PORT="${1:-8080}"
INTERVAL="${2:-5}"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb not found."
  exit 1
fi

has_device() {
  adb devices 2>/dev/null | awk 'NR>1 && $2=="device" { found=1 } END { exit !found }'
}

has_reverse() {
  adb reverse --list 2>/dev/null | grep -Fq "tcp:${PORT} tcp:${PORT}"
}

echo "ADB watch started (port ${PORT}, check every ${INTERVAL}s). Ctrl+C to stop."

while true; do
  if has_device; then
    if ! has_reverse; then
      if adb reverse "tcp:${PORT}" "tcp:${PORT}" >/dev/null 2>&1; then
        echo "[$(date '+%H:%M:%S')] Restored adb reverse tcp:${PORT}"
      fi
    fi
  fi
  sleep "${INTERVAL}"
done
