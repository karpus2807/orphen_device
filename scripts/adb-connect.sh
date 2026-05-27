#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-8080}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb not found. Install Android platform-tools first."
  exit 1
fi

restart_adb() {
  echo "Restarting ADB server..."
  echo "(Note: kill-server clears ALL adb reverse tunnels — this is normal.)"
  adb kill-server >/dev/null 2>&1 || true
  sleep 1
  adb start-server
  sleep 1
}

count_devices() {
  adb devices | awk 'NR>1 && $2=="device" {print $1}' | wc -l
}

if [ "$(count_devices)" -eq 0 ]; then
  restart_adb
fi

if [ "$(count_devices)" -eq 0 ]; then
  echo "No Android device connected."
  echo
  echo "Checklist:"
  echo "  1. USB cable lagao (data cable, sirf charging wala nahi)"
  echo "  2. Phone par USB debugging ON karo"
  echo "  3. 'Allow USB debugging' popup par Allow dabao"
  echo "  4. USB mode: File transfer / MTP select karo"
  echo "  5. Phir dubara chalao: bash scripts/adb-connect.sh"
  adb devices -l || true
  exit 1
fi

adb reverse --remove-all >/dev/null 2>&1 || true
adb reverse "tcp:${PORT}" "tcp:${PORT}"

echo "Connected device(s):"
adb devices -l | awk 'NR>1 && NF {print "  " $0}'
echo
echo "ADB reverse active:"
adb reverse --list
echo
echo "Phone app URL (ADB mode): http://127.0.0.1:${PORT}"

if ! pgrep -f "python3 backend/server.py" >/dev/null 2>&1; then
  echo
  echo "Backend not running. Starting server..."
  (cd "$ROOT" && python3 backend/server.py > /tmp/rat-server.log 2>&1 &)
  sleep 2
fi

if command -v python3 >/dev/null 2>&1; then
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/health', timeout=3)" >/dev/null 2>&1; then
    echo "PC backend health: OK (http://127.0.0.1:${PORT}/health)"
  else
    echo "PC backend health: FAILED — run: python3 backend/server.py"
  fi
fi

echo
echo "Done. App me ADB mode + http://127.0.0.1:${PORT} use karo."
