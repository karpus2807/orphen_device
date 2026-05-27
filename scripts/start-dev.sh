#!/usr/bin/env bash
# One command for USB dev: backend + auto adb reverse watcher.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8080}"
LOG_DIR="${ROOT}/build"
mkdir -p "${LOG_DIR}"

bash "${ROOT}/scripts/adb-connect.sh" "${PORT}" || true

if ! pgrep -f "python3 backend/server.py" >/dev/null 2>&1; then
  echo "Starting backend on port ${PORT}..."
  (cd "${ROOT}" && python3 backend/server.py > /tmp/rat-server.log 2>&1 &)
  sleep 2
else
  echo "Backend already running."
fi

if pgrep -f "scripts/adb-watch.sh ${PORT}" >/dev/null 2>&1; then
  echo "ADB watch already running."
else
  echo "Starting ADB watch (auto restore reverse)..."
  nohup bash "${ROOT}/scripts/adb-watch.sh" "${PORT}" > "${LOG_DIR}/adb-watch.log" 2>&1 &
fi

echo
echo "Dev stack ready:"
echo "  Dashboard: http://127.0.0.1:${PORT}"
echo "  Phone app: ADB mode + http://127.0.0.1:${PORT}"
echo "  ADB watch log: ${LOG_DIR}/adb-watch.log"
echo
echo "Stop watcher later: pkill -f 'scripts/adb-watch.sh'"
