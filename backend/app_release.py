"""APK build, release registry, and OTA push helpers for the admin Web UI."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
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
DATABASE_FILE = ROOT / "backend" / "data" / "device_safety.db"
BUILD_LOCK = threading.Lock()
BUILD_STATE = {
    "running": False,
    "last_ok": False,
    "message": "",
    "finished_at": 0,
    "phase": "idle",
    "pushed_count": 0,
}


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
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(
        f"# Bumped from App Release Center\n"
        f"versionCode={version_code}\n"
        f"versionName={version_name}\n",
        encoding="utf-8",
    )


def bump_version():
    """Return next (version_code, version_name) from current properties."""
    props = read_version_properties()
    code = int(props.get("versionCode", "1") or "1")
    name = str(props.get("versionName", "1.0.0") or "1.0.0")
    new_code = code + 1
    parts = name.split(".")
    if len(parts) >= 3 and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        new_name = ".".join(parts)
    elif len(parts) == 2 and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        new_name = ".".join(parts)
    else:
        new_name = f"{name}.{new_code}"
    return str(new_code), new_name


def apk_filename_for_version(version_name, version_code):
    safe = re.sub(r"[^\w.\-]+", "_", str(version_name).strip()) or "release"
    return f"device-safety-manager-{safe}-{version_code}.apk"


def resolve_android_sdk_env(env):
    """Fill ANDROID_BUILD_TOOLS / ANDROID_PLATFORM from ANDROID_SDK_ROOT or common paths."""
    env = dict(env)
    candidates = [
        env.get("ANDROID_SDK_ROOT", "").strip(),
        "/opt/android-sdk",
        os.path.expanduser("~/Android/Sdk"),
    ]
    sdk_root = ""
    for path in candidates:
        if path and Path(path).is_dir():
            sdk_root = path
            break
    if not sdk_root:
        return env, "Android SDK not found. Run: sudo bash scripts/install-android-sdk-server.sh"
    env["ANDROID_SDK_ROOT"] = sdk_root
    bt_dir = Path(sdk_root) / "build-tools"
    if bt_dir.is_dir():
        versions = sorted((p.name for p in bt_dir.iterdir() if p.is_dir()), reverse=True)
        for ver in versions:
            aapt2 = bt_dir / ver / "aapt2"
            if aapt2.is_file():
                env["ANDROID_BUILD_TOOLS"] = str(bt_dir / ver)
                break
    platform = Path(sdk_root) / "platforms" / "android-36" / "android.jar"
    if platform.is_file():
        env["ANDROID_PLATFORM"] = str(platform)
    if not env.get("ANDROID_BUILD_TOOLS") or not env.get("ANDROID_PLATFORM"):
        return env, f"SDK incomplete under {sdk_root}. Install build-tools;36 and platforms;android-36."
    return env, ""


def publish_built_apk(version_name, version_code):
    """Copy build output to versioned APK name + canonical debug name for /apk/ URL."""
    APK_DIR.mkdir(parents=True, exist_ok=True)
    built = BUILD_DIR / "device-safety-manager-debug.apk"
    canonical = APK_DIR / "device-safety-manager-debug.apk"
    if not built.is_file():
        built = APK_DIR / "device-safety-manager-debug.apk"
    if not built.is_file() or built.stat().st_size < 100_000:
        raise FileNotFoundError("APK missing after build")
    versioned_name = apk_filename_for_version(version_name, version_code)
    versioned_path = APK_DIR / versioned_name
    shutil.copy2(built, versioned_path)
    shutil.copy2(built, canonical)
    return versioned_name


def db_connect():
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def read_server_config_from_db():
    defaults = {"host": "127.0.0.1", "port": "9030"}
    with db_connect() as connection:
        rows = connection.execute("SELECT key, value FROM server_config").fetchall()
    for row in rows:
        key = row["key"] if isinstance(row, sqlite3.Row) else row[0]
        value = row["value"] if isinstance(row, sqlite3.Row) else row[1]
        if key in defaults:
            defaults[key] = value
    return defaults


def write_ota_config_db(version_name, apk_url, release_notes):
    with db_connect() as connection:
        for key, value in (
            ("version", version_name),
            ("apkUrl", apk_url),
            ("releaseNotes", release_notes or ""),
        ):
            connection.execute(
                "INSERT INTO ota_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        connection.commit()


def get_build_status():
    log_tail = ""
    if BUILD_LOG.exists():
        lines = BUILD_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = "\n".join(lines[-40:])
    next_code, next_name = bump_version()
    env, sdk_err = resolve_android_sdk_env(os.environ.copy())
    return {
        "running": BUILD_STATE["running"],
        "lastOk": BUILD_STATE["last_ok"],
        "message": BUILD_STATE["message"],
        "finishedAt": BUILD_STATE["finished_at"],
        "phase": BUILD_STATE.get("phase", "idle"),
        "pushedCount": BUILD_STATE.get("pushed_count", 0),
        "logTail": log_tail,
        "version": read_version_properties(),
        "nextVersionCode": next_code,
        "nextVersionName": next_name,
        "sdkReady": not bool(sdk_err),
        "sdkError": sdk_err,
        "androidSdkRoot": env.get("ANDROID_SDK_ROOT", ""),
    }


def _run_build_thread(
    version_code,
    version_name,
    *,
    auto_register=True,
    auto_push=True,
    release_notes="",
    package_name="com.example.devicesafety",
    app_label="Device Safety Manager",
    create_command_fn=None,
    read_devices_fn=None,
):
    global BUILD_STATE
    BUILD_STATE = {
        "running": True,
        "last_ok": False,
        "message": "Building APK...",
        "finished_at": 0,
        "phase": "building",
        "pushed_count": 0,
    }
    BUILD_LOG.parent.mkdir(parents=True, exist_ok=True)
    APK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        write_version_properties(version_code, version_name)
        env, sdk_err = resolve_android_sdk_env(os.environ.copy())
        if sdk_err:
            BUILD_STATE["message"] = sdk_err
            return
        with open(BUILD_LOG, "w", encoding="utf-8") as log_file:
            result = subprocess.run(
                ["bash", str(BUILD_SCRIPT)],
                cwd=str(ROOT),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=900,
                check=False,
            )
        if result.returncode != 0:
            BUILD_STATE["message"] = f"Build failed (exit {result.returncode}). See build log below."
            return

        BUILD_STATE["phase"] = "publishing"
        BUILD_STATE["message"] = "Publishing APK..."
        apk_filename = publish_built_apk(version_name, version_code)

        if auto_register:
            BUILD_STATE["phase"] = "registering"
            BUILD_STATE["message"] = f"Registered {apk_filename}..."
            with db_connect() as connection:
                ensure_app_releases_table(connection)
                register_release(
                    connection,
                    package_name,
                    app_label,
                    version_name,
                    version_code,
                    release_notes,
                    apk_filename,
                )
                connection.commit()

        server = read_server_config_from_db()
        payload = build_ota_payload_for_release(
            server["host"],
            server["port"],
            version_name,
            version_code,
            release_notes,
            apk_filename,
        )
        write_ota_config_db(version_name, payload["apkUrl"], release_notes)

        pushed = 0
        if auto_push and create_command_fn and read_devices_fn:
            BUILD_STATE["phase"] = "pushing"
            BUILD_STATE["message"] = "Pushing update to all devices..."
            queued = queue_push_to_devices(
                create_command_fn,
                read_devices_fn,
                package_name,
                payload,
            )
            pushed = len(queued)
            BUILD_STATE["pushed_count"] = pushed

        BUILD_STATE["last_ok"] = True
        BUILD_STATE["message"] = (
            f"Done: v{version_name} ({version_code}) → {apk_filename}. "
            f"Pushed to {pushed} device(s)."
        )
    except subprocess.TimeoutExpired:
        BUILD_STATE["message"] = "Build timed out after 15 minutes"
    except Exception as exc:
        BUILD_STATE["message"] = str(exc)
    finally:
        BUILD_STATE["running"] = False
        BUILD_STATE["finished_at"] = int(time.time())
        BUILD_STATE["phase"] = "idle" if BUILD_STATE["last_ok"] else "failed"


def start_build(version_code, version_name, **kwargs):
    with BUILD_LOCK:
        if BUILD_STATE["running"]:
            return False, "A build is already running"
        thread = threading.Thread(
            target=_run_build_thread,
            args=(str(version_code), str(version_name)),
            kwargs=kwargs,
            daemon=True,
        )
        thread.start()
        return True, "Build started"


def start_build_and_push(
    create_command_fn,
    read_devices_fn,
    *,
    auto_bump=True,
    version_code="",
    version_name="",
    release_notes="",
    package_name="com.example.devicesafety",
    app_label="Device Safety Manager",
):
    if auto_bump or not version_code or not version_name:
        version_code, version_name = bump_version()
    with BUILD_LOCK:
        if BUILD_STATE["running"]:
            return False, "A build is already running", version_code, version_name
    ok, msg = start_build(
        version_code,
        version_name,
        auto_register=True,
        auto_push=True,
        release_notes=release_notes,
        package_name=package_name,
        app_label=app_label,
        create_command_fn=create_command_fn,
        read_devices_fn=read_devices_fn,
    )
    return ok, msg, version_code, version_name


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
