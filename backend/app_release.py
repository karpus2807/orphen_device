"""APK build, release registry, and OTA push helpers for the admin Web UI."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APK_DIR = ROOT / "apk"
BUILD_DIR = ROOT / "build"
VERSION_FILE = ROOT / "app" / "version.properties"
BUILD_SCRIPT = ROOT / "scripts" / "build-apk.sh"
BUILD_LOG = ROOT / "backend" / "data" / "build.log"
BUILD_LOCK = threading.Lock()
BUILD_STATE = {"running": False, "last_ok": False, "message": "", "finished_at": 0}


def ensure_app_releases_table(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS app_releases ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "package_name TEXT NOT NULL, "
        "app_label TEXT NOT NULL DEFAULT '', "
        "version_name TEXT NOT NULL, "
        "version_code INTEGER NOT NULL, "
        "apk_filename TEXT NOT NULL, "
        "release_notes TEXT NOT NULL DEFAULT '', "
        "created_at INTEGER NOT NULL, "
        "active INTEGER NOT NULL DEFAULT 1"
        ")"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_app_releases_pkg ON app_releases (package_name, version_code)"
    )


def ensure_update_manager_targets(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS update_manager_targets ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "package_name TEXT NOT NULL UNIQUE, "
        "app_label TEXT NOT NULL DEFAULT '', "
        "enabled INTEGER NOT NULL DEFAULT 1"
        ")"
    )
    connection.execute(
        "INSERT OR IGNORE INTO update_manager_targets (package_name, app_label, enabled) "
        "VALUES ('com.example.devicesafety', 'Device Safety Manager', 1)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO update_manager_targets (package_name, app_label, enabled) "
        "VALUES ('com.orphen.updatemanager', 'Orphen Update Manager', 1)"
    )


def read_version_properties():
    props = {"versionCode": "1", "versionName": "1.0.0"}
    if not VERSION_FILE.exists():
        return props
    for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


def write_version_properties(version_code, version_name):
    VERSION_FILE.write_text(
        f"# Bumped from App Release Center\n"
        f"versionCode={version_code}\n"
        f"versionName={version_name}\n",
        encoding="utf-8",
    )


def get_build_status():
    log_tail = ""
    if BUILD_LOG.exists():
        lines = BUILD_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = "\n".join(lines[-40:])
    return {
        "running": BUILD_STATE["running"],
        "lastOk": BUILD_STATE["last_ok"],
        "message": BUILD_STATE["message"],
        "finishedAt": BUILD_STATE["finished_at"],
        "logTail": log_tail,
        "version": read_version_properties(),
    }


def _run_build_thread(version_code, version_name):
    global BUILD_STATE
    BUILD_STATE = {"running": True, "last_ok": False, "message": "Building...", "finished_at": 0}
    BUILD_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_version_properties(version_code, version_name)
        env = os.environ.copy()
        sdk = env.get("ANDROID_SDK_ROOT", "").strip()
        if sdk:
            env["ANDROID_BUILD_TOOLS"] = f"{sdk}/build-tools/36.0.0"
            env["ANDROID_PLATFORM"] = f"{sdk}/platforms/android-36/android.jar"
        with open(BUILD_LOG, "w", encoding="utf-8") as log_file:
            result = subprocess.run(
                ["bash", str(BUILD_SCRIPT)],
                cwd=str(ROOT),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
        if result.returncode != 0:
            BUILD_STATE["message"] = f"Build failed (exit {result.returncode}). See build log."
            return
        apk = APK_DIR / "device-safety-manager-debug.apk"
        if not apk.is_file() or apk.stat().st_size < 100_000:
            BUILD_STATE["message"] = "Build finished but APK missing in apk/"
            return
        BUILD_STATE["last_ok"] = True
        BUILD_STATE["message"] = f"Built {version_name} ({version_code}) — {apk.stat().st_size} bytes"
    except subprocess.TimeoutExpired:
        BUILD_STATE["message"] = "Build timed out after 10 minutes"
    except Exception as exc:
        BUILD_STATE["message"] = str(exc)
    finally:
        BUILD_STATE["running"] = False
        BUILD_STATE["finished_at"] = int(time.time())


def start_build(version_code, version_name):
    with BUILD_LOCK:
        if BUILD_STATE["running"]:
            return False, "A build is already running"
        thread = threading.Thread(
            target=_run_build_thread,
            args=(str(version_code), str(version_name)),
            daemon=True,
        )
        thread.start()
        return True, "Build started"


def register_release(connection, package_name, app_label, version_name, version_code, release_notes, apk_filename):
    now = int(time.time())
    connection.execute(
        "UPDATE app_releases SET active = 0 WHERE package_name = ?",
        (package_name,),
    )
    connection.execute(
        "INSERT INTO app_releases (package_name, app_label, version_name, version_code, apk_filename, release_notes, created_at, active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        (package_name, app_label, version_name, int(version_code), apk_filename, release_notes, now),
    )


def list_releases(connection, package_name=""):
    query = "SELECT * FROM app_releases WHERE 1=1"
    params = []
    if package_name:
        query += " AND package_name = ?"
        params.append(package_name)
    query += " ORDER BY created_at DESC LIMIT 50"
    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def build_ota_payload_for_release(server_host, server_port, version_name, version_code, release_notes, apk_filename):
    host = str(server_host or "127.0.0.1").strip()
    port = str(server_port or "9030").strip()
    apk_url = f"http://{host}:{port}/apk/{apk_filename}"
    return {
        "version": version_name,
        "versionCode": int(version_code),
        "apkUrl": apk_url,
        "releaseNotes": release_notes or "",
        "autoInstall": True,
    }


def queue_push_to_devices(create_command_fn, read_devices_fn, package_name, payload_dict, device_ids=None):
    payload = json.dumps(payload_dict)
    queued = []
    for device in read_devices_fn():
        if not device.get("registered"):
            continue
        if device_ids and device.get("deviceId") not in device_ids:
            continue
        command_id = create_command_fn(device["deviceId"], "push_app_update", payload)
        queued.append({"deviceId": device["deviceId"], "commandId": command_id})
    return queued


def list_update_targets(connection):
    rows = connection.execute(
        "SELECT package_name, app_label, enabled FROM update_manager_targets ORDER BY app_label"
    ).fetchall()
    return [dict(row) for row in rows]


def get_active_release_for_package(connection, package_name, server_host, server_port):
    row = connection.execute(
        "SELECT * FROM app_releases WHERE package_name = ? AND active = 1 ORDER BY version_code DESC LIMIT 1",
        (package_name,),
    ).fetchone()
    if not row:
        return None
    return build_ota_payload_for_release(
        server_host,
        server_port,
        row["version_name"],
        row["version_code"],
        row["release_notes"],
        row["apk_filename"],
    )
