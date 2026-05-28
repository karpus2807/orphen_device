#!/usr/bin/env python3
import base64
import hashlib
import html
import hmac
import json
import os
import secrets
import smtplib
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import app_release
import audio_stream
import geocode
import geofence_page as gf_page
import geofence_zones as gf
import remote_ops
import security_control

WIFI_SAVED_PROFILES_KEY = "wifi_saved_profiles_json"
WIFI_SCAN_AT_KEY = "wifi_scan_at"
STATUS_EMAIL_STATE_KEY = "status_email_state_json"
STATUS_EMAIL_COOLDOWN_SECONDS = 30 * 60
DATA_FILE = ROOT / "data" / "devices.json"
CONFIG_FILE = ROOT / "data" / "server_config.json"
HEARTBEAT_FILE = ROOT / "data" / "heartbeats.json"
POLICY_FILE = ROOT / "data" / "policy.json"
ADMIN_FILE = ROOT / "data" / "admin.json"
SMTP_FILE = ROOT / "data" / "smtp_config.json"
RESET_TOKENS_FILE = ROOT / "data" / "password_resets.json"
DATABASE_FILE = ROOT / "data" / "device_safety.db"
SCHEMA_FILE = ROOT / "schema.sql"
ONLINE_TIMEOUT_SECONDS = 90
STATUS_POLL_SECONDS = 30
SYNC_HISTORY_LIMIT = (
    10_000_000
    if os.environ.get("DEVICE_SAFETY_UNLIMITED", "1").strip().lower() in ("1", "true", "yes")
    else int(os.environ.get("DEVICE_SAFETY_HISTORY_LIMIT", "2500") or 2500)
)
SESSIONS = set()
DEVICE_LAST_STATUS = {}


def db_connect():
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    with db_connect() as connection:
        connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        ensure_column(connection, "devices", "device_token_hash", "TEXT")
        ensure_column(connection, "devices", "pending_device_token", "TEXT")
        ensure_column(connection, "devices", "device_token_sealed", "TEXT")
        ensure_column(connection, "devices", "device_admin_active", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "devices", "device_group", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "devices", "last_wifi_ssid", "TEXT")
        ensure_column(connection, "devices", "geofence_ok", "INTEGER")
        ensure_column(connection, "devices", "usage_summary_json", "TEXT")
        ensure_column(connection, "devices", "last_latitude", "REAL")
        ensure_column(connection, "devices", "last_longitude", "REAL")
        ensure_column(connection, "devices", "last_location_accuracy", "REAL")
        ensure_column(connection, "devices", "last_location_at", "INTEGER")
        ensure_column(connection, "devices", "location_permission_granted", "INTEGER")
        ensure_column(connection, "devices", "last_location_provider", "TEXT")
        ensure_column(connection, "devices", "last_location_altitude", "REAL")
        ensure_column(connection, "devices", "last_location_speed", "REAL")
        ensure_column(connection, "devices", "usage_access_granted", "INTEGER")
        ensure_column(connection, "devices", "call_log_permission_granted", "INTEGER")
        ensure_column(connection, "devices", "sms_permission_granted", "INTEGER")
        ensure_column(connection, "devices", "contacts_permission_granted", "INTEGER")
        ensure_column(connection, "devices", "audio_permission_granted", "INTEGER")
        ensure_column(connection, "devices", "audio_stream_active", "INTEGER")
        ensure_column(connection, "devices", "storage_permission_granted", "INTEGER")
        ensure_column(connection, "devices", "app_locked", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "devices", "app_hidden", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "devices", "battery_summary_json", "TEXT")
        ensure_column(connection, "devices", "usage_summary_at", "INTEGER")
        ensure_column(connection, "devices", "battery_summary_at", "INTEGER")
        ensure_column(connection, "devices", "notification_access_granted", "INTEGER")
        ensure_security_otp_table(connection)
        ensure_notification_table(connection)
        ensure_contact_sync_indexes(connection)
        ensure_column(connection, "device_call_history", "source_id", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "device_call_history", "country_iso", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "device_call_history", "location_label", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "device_sms_history", "source_id", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "device_sms_history", "read_state", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "device_sms_history", "thread_id", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "device_sms_history", "subject", "TEXT NOT NULL DEFAULT ''")
        ensure_communication_history_indexes(connection)
        dedupe_communication_history(connection)
        app_release.ensure_app_releases_table(connection)
        app_release.ensure_update_manager_targets(connection)
    migrate_json_files_to_database()


def ensure_column(connection, table_name, column_name, column_type):
    columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()]
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def ensure_security_otp_table(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS security_otp_requests ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "device_id TEXT NOT NULL, "
        "action_type TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "otp_hash TEXT, "
        "device_otp_code TEXT, "
        "created_at INTEGER NOT NULL, "
        "approved_at INTEGER, "
        "expires_at INTEGER, "
        "used_at INTEGER, "
        "FOREIGN KEY (device_id) REFERENCES devices(device_id)"
        ")"
    )
    ensure_column(connection, "security_otp_requests", "device_otp_code", "TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_otp_requests_device_status "
        "ON security_otp_requests (device_id, status)"
    )


def ensure_notification_table(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS device_notifications ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "device_id TEXT NOT NULL, "
        "source_id TEXT NOT NULL DEFAULT '', "
        "package_name TEXT NOT NULL DEFAULT '', "
        "app_name TEXT NOT NULL DEFAULT '', "
        "title TEXT NOT NULL DEFAULT '', "
        "body TEXT NOT NULL DEFAULT '', "
        "category TEXT NOT NULL DEFAULT 'general', "
        "timestamp INTEGER NOT NULL, "
        "FOREIGN KEY (device_id) REFERENCES devices(device_id)"
        ")"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_notifications_device_time "
        "ON device_notifications (device_id, timestamp)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_notifications_unique "
        "ON device_notifications (device_id, source_id)"
    )


SECURITY_ACTION_LABELS = {
    "unlock": "Unlock App",
    "unhide": "Unhide App",
    "hide": "Hide App",
    "lock": "Lock App",
    "enable_device_admin": "Enable Device Admin",
    "disable_device_admin": "Disable Device Admin",
    "allow_uninstall": "Allow Uninstall",
}


def set_device_security_flags(device_id, app_locked=None, app_hidden=None):
    devices = read_devices()
    updated = False
    for device in devices:
        if device.get("deviceId") != device_id:
            continue
        if app_locked is not None:
            device["appLocked"] = bool(app_locked)
        if app_hidden is not None:
            device["appHidden"] = bool(app_hidden)
        updated = True
        break
    if updated:
        write_devices(devices)
    return updated


def get_device_security_state(device_id):
    device = get_device_by_id(device_id)
    if not device:
        return None
    with db_connect() as connection:
        pending = security_control.get_latest_pending_request(connection, device_id)
    return {
        "appLocked": bool(device.get("appLocked")),
        "appHidden": bool(device.get("appHidden")),
        "pendingRequest": pending,
    }


def apply_admin_security_command(device_id, command_type):
    if command_type == "lock_app":
        set_device_security_flags(device_id, app_locked=True)
    elif command_type == "unlock_app":
        set_device_security_flags(device_id, app_locked=False)
    elif command_type == "hide_app":
        set_device_security_flags(device_id, app_hidden=True)
    elif command_type == "show_app":
        set_device_security_flags(device_id, app_hidden=False)
    else:
        return False
    return True


def ensure_contact_sync_indexes(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS device_contacts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "device_id TEXT NOT NULL, "
        "source_id TEXT NOT NULL DEFAULT '', "
        "contact_id TEXT NOT NULL DEFAULT '', "
        "display_name TEXT NOT NULL DEFAULT '', "
        "phone_number TEXT NOT NULL DEFAULT '', "
        "phone_type TEXT NOT NULL DEFAULT '', "
        "phone_label TEXT NOT NULL DEFAULT '', "
        "email TEXT NOT NULL DEFAULT '', "
        "organization TEXT NOT NULL DEFAULT '', "
        "starred INTEGER NOT NULL DEFAULT 0, "
        "updated_at INTEGER NOT NULL DEFAULT 0, "
        "FOREIGN KEY (device_id) REFERENCES devices(device_id)"
        ")"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_contacts_device_name "
        "ON device_contacts (device_id, display_name)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_contacts_unique "
        "ON device_contacts (device_id, source_id)"
    )


def ensure_communication_history_indexes(connection):
    connection.execute("DROP INDEX IF EXISTS idx_device_call_history_unique")
    connection.execute("DROP INDEX IF EXISTS idx_device_sms_history_unique")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_call_history_unique "
        "ON device_call_history (device_id, source_id)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_sms_history_unique "
        "ON device_sms_history (device_id, source_id)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_call_history_fallback "
        "ON device_call_history (device_id, timestamp, phone_number, call_type, duration_seconds) "
        "WHERE source_id = ''"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_sms_history_fallback "
        "ON device_sms_history (device_id, timestamp, address, sms_type, body) "
        "WHERE source_id = ''"
    )


def dedupe_communication_history(connection=None):
    cleanup = """
        DELETE FROM {table} WHERE id NOT IN (
            SELECT MIN(id) FROM {table}
            GROUP BY device_id, {group_columns}
        )
    """
    if connection is None:
        with db_connect() as conn:
            dedupe_communication_history(conn)
        return
    connection.execute(
        cleanup.format(
            table="device_call_history",
            group_columns="timestamp, phone_number, call_type, duration_seconds",
        )
    )
    connection.execute(
        cleanup.format(
            table="device_sms_history",
            group_columns="timestamp, address, sms_type, body",
        )
    )


def normalize_phone_value(value):
    return str(value or "").strip()


def parse_date_filter(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        year, month, day = [int(part) for part in value.split("-")]
        return int(time.mktime((year, month, day, 0, 0, 0, 0, 0, -1)))
    except (ValueError, OverflowError, TypeError):
        return None


def parse_date_range_from_query(query):
    from_ts = parse_date_filter(str(query.get("from", [""])[0]).strip())
    to_ts = parse_date_filter(str(query.get("to", [""])[0]).strip())
    if to_ts is not None:
        to_ts += 86399
    if from_ts is not None and to_ts is not None and from_ts > to_ts:
        from_ts, to_ts = to_ts - 86399, to_ts
    return from_ts, to_ts


def parse_history_filters(query):
    search = str(query.get("q", [""])[0]).strip()
    from_ts, to_ts = parse_date_range_from_query(query)
    return search, from_ts, to_ts


def parse_time_filter(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parts = value.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour * 3600 + minute * 60
    except (ValueError, IndexError, TypeError):
        return None
    return None


def parse_location_history_filters(query):
    search = str(query.get("q", [""])[0]).strip()
    from_date = str(query.get("from", [""])[0]).strip()
    to_date = str(query.get("to", [""])[0]).strip()
    time_from = parse_time_filter(query.get("timeFrom", [""])[0]) or 0
    time_to = parse_time_filter(query.get("timeTo", [""])[0])

    from_ts = None
    to_ts = None
    if from_date:
        day_start = parse_date_filter(from_date)
        if day_start is not None:
            from_ts = day_start + time_from
    if to_date:
        day_start = parse_date_filter(to_date)
        if day_start is not None:
            to_ts = day_start + (time_to if time_to is not None else 86399)
    elif from_date and not to_date:
        day_start = parse_date_filter(from_date)
        if day_start is not None:
            to_ts = day_start + (time_to if time_to is not None else 86399)

    if from_ts is not None and to_ts is not None and from_ts > to_ts:
        from_ts, to_ts = to_ts, from_ts
    return search, from_ts, to_ts


def render_history_date_range_widget():
    return """
      <div class="row g-2 align-items-end mt-3 pt-3 border-top">
        <div class="col-md-3">
          <label class="form-label small mb-1" for="date-from">From date</label>
          <input id="date-from" class="form-control" type="date">
        </div>
        <div class="col-md-3">
          <label class="form-label small mb-1" for="date-to">To date</label>
          <input id="date-to" class="form-control" type="date">
        </div>
        <div class="col-md-6 d-flex flex-wrap gap-2 align-items-center">
          <button type="button" class="btn btn-sm btn-primary" id="date-apply">Apply range</button>
          <button type="button" class="btn btn-sm btn-outline-secondary" id="date-clear">Clear dates</button>
          <span class="small text-secondary" id="date-filter-note">All dates</span>
        </div>
      </div>
    """


def render_history_date_filter_js():
    return """
      function buildHistoryQueryParams(deviceId, searchValue) {
        const params = new URLSearchParams();
        params.set("deviceId", deviceId);
        if (searchValue) params.set("q", searchValue);
        const fromEl = document.getElementById("date-from");
        const toEl = document.getElementById("date-to");
        if (fromEl && fromEl.value) params.set("from", fromEl.value);
        if (toEl && toEl.value) params.set("to", toEl.value);
        return params;
      }

      function updateDateFilterNote() {
        const note = document.getElementById("date-filter-note");
        const fromEl = document.getElementById("date-from");
        const toEl = document.getElementById("date-to");
        if (!note || !fromEl || !toEl) return;
        if (fromEl.value && toEl.value) {
          note.textContent = `Showing ${fromEl.value} to ${toEl.value}`;
        } else if (fromEl.value) {
          note.textContent = `From ${fromEl.value}`;
        } else if (toEl.value) {
          note.textContent = `Until ${toEl.value}`;
        } else {
          note.textContent = "All dates";
        }
      }

      function initDateFilterControls(onChange) {
        document.getElementById("date-apply")?.addEventListener("click", () => {
          updateDateFilterNote();
          onChange();
        });
        document.getElementById("date-clear")?.addEventListener("click", () => {
          const fromEl = document.getElementById("date-from");
          const toEl = document.getElementById("date-to");
          if (fromEl) fromEl.value = "";
          if (toEl) toEl.value = "";
          updateDateFilterNote();
          onChange();
        });
        ["date-from", "date-to"].forEach((id) => {
          document.getElementById(id)?.addEventListener("change", () => {
            updateDateFilterNote();
            onChange();
          });
        });
        updateDateFilterNote();
      }
    """


def table_is_empty(table_name):
    with db_connect() as connection:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"]) == 0


def load_json_file(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def migrate_json_files_to_database():
    if table_is_empty("devices"):
        devices = load_json_file(DATA_FILE, [])
        if devices:
            write_devices(devices)

    if table_is_empty("heartbeats"):
        heartbeats = load_json_file(HEARTBEAT_FILE, [])
        if heartbeats:
            write_heartbeats(heartbeats)

    if table_is_empty("policy_settings"):
        write_policy(load_json_file(POLICY_FILE, default_policy()))

    if table_is_empty("server_config"):
        write_server_config(load_json_file(CONFIG_FILE, {"host": "127.0.0.1", "port": "8080"}))

    if table_is_empty("smtp_config"):
        write_smtp_config(load_json_file(SMTP_FILE, default_smtp_config()))

    if table_is_empty("admins"):
        write_admin(load_json_file(ADMIN_FILE, default_admin()))

    if table_is_empty("password_resets"):
        tokens = load_json_file(RESET_TOKENS_FILE, [])
        if tokens:
            write_reset_tokens(tokens)

    if table_is_empty("geofence_settings"):
        write_geofence_config(default_geofence_config())

    if table_is_empty("ota_settings"):
        write_ota_config(default_ota_config())

    if table_is_empty("wifi_profile_settings"):
        write_wifi_profile_config(default_wifi_profile_config())


def read_key_values(table_name, defaults):
    values = dict(defaults)
    with db_connect() as connection:
        rows = connection.execute(f"SELECT key, value FROM {table_name}").fetchall()
    for row in rows:
        values[row["key"]] = row["value"]
    return values


def write_key_values(table_name, values):
    with db_connect() as connection:
        for key, value in values.items():
            connection.execute(
                f"INSERT INTO {table_name} (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_enrollment_token(label, ttl_seconds=86400):
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    with db_connect() as connection:
        connection.execute(
            "INSERT INTO enrollment_tokens (token_hash, label, created_at, expires_at, active) VALUES (?, ?, ?, ?, 1)",
            (hash_token(token), label, now, now + ttl_seconds),
        )
    return token


def read_enrollment_tokens():
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT id, label, created_at, expires_at, used_at, used_by_device_id, active "
            "FROM enrollment_tokens ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def validate_enrollment_token(token, device_id):
    if not token:
        return False
    token_hash = hash_token(token)
    now = int(time.time())
    with db_connect() as connection:
        row = connection.execute(
            "SELECT id FROM enrollment_tokens WHERE token_hash = ? AND active = 1 AND used_at IS NULL AND expires_at > ?",
            (token_hash, now),
        ).fetchone()
        if not row:
            return False
        connection.execute(
            "UPDATE enrollment_tokens SET used_at = ?, used_by_device_id = ? WHERE id = ?",
            (now, device_id, row["id"]),
        )
    return True


def device_token_valid(device_id, token):
    if not device_id or not token:
        return False
    with db_connect() as connection:
        row = connection.execute("SELECT device_token_hash FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    if not row or not row["device_token_hash"]:
        return False
    return hmac.compare_digest(row["device_token_hash"], hash_token(token))


def get_device_token_from_headers(handler):
    return handler.headers.get("X-Device-Token", "").strip()


def resolve_device_token(existing_device):
    sealed = str((existing_device or {}).get("deviceTokenSealed") or "").strip()
    if sealed:
        return sealed
    return secrets.token_urlsafe(32)


def assign_device_token(device, device_token, queue_pending=False):
    device_token = str(device_token or "").strip() or secrets.token_urlsafe(32)
    device["deviceTokenHash"] = hash_token(device_token)
    device["deviceTokenSealed"] = device_token
    if queue_pending:
        device["pendingDeviceToken"] = device_token
    return device_token


def redeliver_sealed_device_token(device_id):
    device = get_device_by_id(device_id)
    if not device:
        return None
    token = str(device.get("deviceTokenSealed") or "").strip()
    if not token or not device.get("deviceTokenHash"):
        return None
    record_device_event(device_id, "token_redelivered", "Stored device token re-delivered to app")
    return token


def register_device_via_enrollment_token(device_id, body, enrollment_token):
    enrollment_token = str(enrollment_token or "").strip()
    if not enrollment_token:
        return None

    existing = get_device_by_id(device_id)
    if existing and existing.get("registered") and existing.get("deviceTokenHash"):
        return None
    if not validate_enrollment_token(enrollment_token, device_id):
        return None

    now = int(time.time())
    manufacturer = str(body.get("manufacturer", "")).strip()
    model = str(body.get("model", "")).strip()
    android_version = str(body.get("androidVersion", "")).strip()
    api_level = str(body.get("apiLevel", "")).strip()

    devices = read_devices()
    existing = next((device for device in devices if device["deviceId"] == device_id), None)
    device_token = resolve_device_token(existing)
    record = {
        "deviceId": device_id,
        "manufacturer": manufacturer,
        "model": model,
        "androidVersion": android_version,
        "apiLevel": api_level,
        "lastSeenAt": now,
        "registered": True,
        "deregisteredAt": None,
        "pendingDeviceToken": None,
    }
    assign_device_token(record, device_token)
    if existing:
        existing.update(record)
    else:
        record["createdAt"] = now
        devices.append(record)

    write_devices(devices)
    record_device_event(device_id, "registered", "Device registered via enrollment QR token")
    record_status_transition(device_id, record)
    return device_token


def upsert_device_checkin(body, incoming_device_token=""):
    device_id = str(body.get("deviceId", "")).strip()
    model = str(body.get("model", "")).strip()
    if not device_id or not model:
        return None

    enrolled_device_token = register_device_via_enrollment_token(
        device_id,
        body,
        body.get("enrollmentToken", ""),
    )
    if enrolled_device_token:
        return {
            "deviceId": device_id,
            "registered": True,
            "deviceToken": enrolled_device_token,
        }

    incoming_device_token = str(incoming_device_token or "").strip()
    if incoming_device_token and device_token_valid(device_id, incoming_device_token):
        now = int(time.time())
        manufacturer = str(body.get("manufacturer", "")).strip()
        android_version = str(body.get("androidVersion", "")).strip()
        api_level = str(body.get("apiLevel", "")).strip()
        with db_connect() as connection:
            connection.execute(
                "UPDATE devices SET manufacturer = ?, model = ?, android_version = ?, api_level = ?, "
                "registered = 1, deregistered_at = NULL, pending_device_token = NULL, last_seen_at = ? "
                "WHERE device_id = ?",
                (manufacturer, model, android_version, api_level, now, device_id),
            )
        record_device_event(device_id, "heartbeat", "Device checked in with stored token")
        device = get_device_by_id(device_id)
        if device:
            record_status_transition(device_id, device)
        return {"deviceId": device_id, "registered": True}

    now = int(time.time())
    manufacturer = str(body.get("manufacturer", "")).strip()
    android_version = str(body.get("androidVersion", "")).strip()
    api_level = str(body.get("apiLevel", "")).strip()

    is_new_device = False
    server_has_token = False
    with db_connect() as connection:
        row = connection.execute(
            "SELECT registered, device_token_hash FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if row:
            server_has_token = bool(row["device_token_hash"])
            connection.execute(
                "UPDATE devices SET manufacturer = ?, model = ?, android_version = ?, api_level = ?, "
                "last_seen_at = ?, deregistered_at = NULL WHERE device_id = ?",
                (manufacturer, model, android_version, api_level, now, device_id),
            )
        else:
            connection.execute(
                "INSERT INTO devices (device_id, manufacturer, model, android_version, api_level, "
                "registered, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                (device_id, manufacturer, model, android_version, api_level, now, now),
            )
            is_new_device = True

    if is_new_device:
        record_device_event(device_id, "checkin", "Device checked in and is waiting for admin registration")
        notify_device_checkin(device_id, body)

    response = {"deviceId": device_id, "registered": False, "awaitingToken": True}
    if server_has_token:
        response["serverRegistered"] = True
    return response


def consume_pending_device_token(device_id):
    with db_connect() as connection:
        row = connection.execute(
            "SELECT pending_device_token, registered FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if not row or not row["pending_device_token"]:
            return None
        token = row["pending_device_token"]
        connection.execute(
            "UPDATE devices SET pending_device_token = NULL WHERE device_id = ?",
            (device_id,),
        )
    record_device_event(device_id, "token_delivered", "Device token delivered to app")
    return token


def admin_register_and_push_token(device_id):
    device_id = str(device_id or "").strip()
    if not device_id:
        return None, "device_id_required"

    devices = read_devices()
    existing = next((device for device in devices if device["deviceId"] == device_id), None)
    if not existing:
        return None, "device_not_found"

    device_token = resolve_device_token(existing)
    now = int(time.time())
    was_registered = bool(existing.get("registered")) and bool(existing.get("deviceTokenHash"))
    assign_device_token(existing, device_token, queue_pending=True)
    existing["deregisteredAt"] = None
    if was_registered:
        existing["registered"] = True
    write_devices(devices)
    event = "Admin re-pushed existing device token" if was_registered else "Admin pushed device token for registration"
    record_device_event(device_id, "token_pushed", event)
    return device_token, None


def read_pending_devices():
    return [
        device for device in read_devices()
        if decorate_device(device).get("status") == "unregistered"
    ]


def clear_device_credentials(device_id):
    devices = read_devices()
    updated = False
    for device in devices:
        if device.get("deviceId") == device_id:
            device["registered"] = False
            device["deviceTokenHash"] = None
            device["pendingDeviceToken"] = None
            device["deviceTokenSealed"] = None
            updated = True
    if updated:
        write_devices(devices)
        device = get_device_by_id(device_id)
        if device:
            record_status_transition(device_id, device)


def delete_device_by_id(device_id):
    device_id = str(device_id or "").strip()
    if not device_id:
        return False
    with db_connect() as connection:
        row = connection.execute("SELECT device_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if not row:
            return False
        connection.execute("DELETE FROM device_commands WHERE device_id = ?", (device_id,))
        connection.execute("DELETE FROM heartbeats WHERE device_id = ?", (device_id,))
        connection.execute("DELETE FROM device_location_history WHERE device_id = ?", (device_id,))
        connection.execute("DELETE FROM device_call_history WHERE device_id = ?", (device_id,))
        connection.execute("DELETE FROM device_sms_history WHERE device_id = ?", (device_id,))
        connection.execute("DELETE FROM device_contacts WHERE device_id = ?", (device_id,))
        connection.execute("DELETE FROM device_notifications WHERE device_id = ?", (device_id,))
        connection.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
    return True


def read_devices():
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT device_id, manufacturer, model, android_version, api_level, "
            "device_token_hash, pending_device_token, device_token_sealed, device_admin_active, app_locked, app_hidden, registered, device_group, "
            "last_wifi_ssid, geofence_ok, usage_summary_json, battery_summary_json, usage_summary_at, battery_summary_at, "
            "last_latitude, last_longitude, last_location_accuracy, last_location_at, location_permission_granted, "
            "last_location_provider, last_location_altitude, last_location_speed, usage_access_granted, "
            "call_log_permission_granted, sms_permission_granted, contacts_permission_granted, "
            "audio_permission_granted, audio_stream_active, storage_permission_granted, notification_access_granted, "
            "created_at, last_seen_at, deregistered_at FROM devices"
        ).fetchall()
    return [
        {
            "deviceId": row["device_id"],
            "manufacturer": row["manufacturer"],
            "model": row["model"],
            "androidVersion": row["android_version"],
            "apiLevel": row["api_level"],
            "deviceTokenHash": row["device_token_hash"],
            "pendingDeviceToken": row["pending_device_token"],
            "deviceTokenSealed": row["device_token_sealed"],
            "deviceAdminActive": bool(row["device_admin_active"]),
            "appLocked": bool(row["app_locked"]),
            "appHidden": bool(row["app_hidden"]),
            "registered": bool(row["registered"]),
            "deviceGroup": row["device_group"] or "",
            "lastWifiSsid": row["last_wifi_ssid"] or "",
            "geofenceOk": None if row["geofence_ok"] is None else bool(row["geofence_ok"]),
            "usageSummaryJson": row["usage_summary_json"] or "",
            "batterySummaryJson": row["battery_summary_json"] or "",
            "usageSummaryAt": row["usage_summary_at"],
            "batterySummaryAt": row["battery_summary_at"],
            "lastLatitude": row["last_latitude"],
            "lastLongitude": row["last_longitude"],
            "lastLocationAccuracy": row["last_location_accuracy"],
            "lastLocationAt": row["last_location_at"],
            "locationPermissionGranted": None if row["location_permission_granted"] is None else bool(row["location_permission_granted"]),
            "lastLocationProvider": row["last_location_provider"] or "",
            "lastLocationAltitude": row["last_location_altitude"],
            "lastLocationSpeed": row["last_location_speed"],
            "usageAccessGranted": None if row["usage_access_granted"] is None else bool(row["usage_access_granted"]),
            "callLogPermissionGranted": None if row["call_log_permission_granted"] is None else bool(row["call_log_permission_granted"]),
            "smsPermissionGranted": None if row["sms_permission_granted"] is None else bool(row["sms_permission_granted"]),
            "contactsPermissionGranted": None if row["contacts_permission_granted"] is None else bool(row["contacts_permission_granted"]),
            "audioPermissionGranted": None if row["audio_permission_granted"] is None else bool(row["audio_permission_granted"]),
            "audioStreamActive": None if row["audio_stream_active"] is None else bool(row["audio_stream_active"]),
            "storagePermissionGranted": None if row["storage_permission_granted"] is None else bool(row["storage_permission_granted"]),
            "notificationAccessGranted": None if row["notification_access_granted"] is None else bool(row["notification_access_granted"]),
            "createdAt": row["created_at"],
            "lastSeenAt": row["last_seen_at"],
            "deregisteredAt": row["deregistered_at"],
        }
        for row in rows
    ]


def write_devices(devices):
    with db_connect() as connection:
        connection.execute("DELETE FROM devices")
        for device in devices:
            now = int(time.time())
            connection.execute(
                "INSERT INTO devices (device_id, manufacturer, model, android_version, api_level, "
                "device_token_hash, pending_device_token, device_token_sealed, device_admin_active, app_locked, app_hidden, registered, device_group, "
                "last_wifi_ssid, geofence_ok, usage_summary_json, battery_summary_json, usage_summary_at, battery_summary_at, "
                "last_latitude, last_longitude, last_location_accuracy, last_location_at, location_permission_granted, "
                "last_location_provider, last_location_altitude, last_location_speed, usage_access_granted, "
                "call_log_permission_granted, sms_permission_granted, contacts_permission_granted, "
                "audio_permission_granted, audio_stream_active, storage_permission_granted, notification_access_granted, "
                "created_at, last_seen_at, deregistered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(device.get("deviceId", "")),
                    str(device.get("manufacturer", "")),
                    str(device.get("model", "")),
                    str(device.get("androidVersion", "")),
                    str(device.get("apiLevel", "")),
                    device.get("deviceTokenHash"),
                    device.get("pendingDeviceToken"),
                    device.get("deviceTokenSealed"),
                    1 if device.get("deviceAdminActive") else 0,
                    1 if device.get("appLocked") else 0,
                    1 if device.get("appHidden") else 0,
                    1 if device.get("registered", True) else 0,
                    str(device.get("deviceGroup") or ""),
                    str(device.get("lastWifiSsid") or ""),
                    None if device.get("geofenceOk") is None else (1 if device.get("geofenceOk") else 0),
                    str(device.get("usageSummaryJson") or ""),
                    str(device.get("batterySummaryJson") or ""),
                    device.get("usageSummaryAt"),
                    device.get("batterySummaryAt"),
                    device.get("lastLatitude"),
                    device.get("lastLongitude"),
                    device.get("lastLocationAccuracy"),
                    device.get("lastLocationAt"),
                    None if device.get("locationPermissionGranted") is None else (1 if device.get("locationPermissionGranted") else 0),
                    str(device.get("lastLocationProvider") or ""),
                    device.get("lastLocationAltitude"),
                    device.get("lastLocationSpeed"),
                    None if device.get("usageAccessGranted") is None else (1 if device.get("usageAccessGranted") else 0),
                    None if device.get("callLogPermissionGranted") is None else (1 if device.get("callLogPermissionGranted") else 0),
                    None if device.get("smsPermissionGranted") is None else (1 if device.get("smsPermissionGranted") else 0),
                    None if device.get("contactsPermissionGranted") is None else (1 if device.get("contactsPermissionGranted") else 0),
                    None if device.get("audioPermissionGranted") is None else (1 if device.get("audioPermissionGranted") else 0),
                    None if device.get("audioStreamActive") is None else (1 if device.get("audioStreamActive") else 0),
                    None if device.get("storagePermissionGranted") is None else (1 if device.get("storagePermissionGranted") else 0),
                    None if device.get("notificationAccessGranted") is None else (1 if device.get("notificationAccessGranted") else 0),
                    int(device.get("createdAt") or now),
                    int(device.get("lastSeenAt") or now),
                    device.get("deregisteredAt"),
                ),
            )


def update_device_admin_status(device_id, active):
    update_device_telemetry_from_body(device_id, {"deviceAdminActive": active})


def update_device_telemetry_from_body(device_id, body):
    devices = read_devices()
    wifi_ssid = str(body.get("wifiSsid", "")).strip()
    usage_summary = body.get("usageSummary")
    updated = False

    for device in devices:
        if device.get("deviceId") != device_id:
            continue
        if "deviceAdminActive" in body:
            device["deviceAdminActive"] = bool(body.get("deviceAdminActive"))
        if wifi_ssid or "wifiSsid" in body:
            device["lastWifiSsid"] = wifi_ssid
        if usage_summary is not None:
            if isinstance(usage_summary, (list, dict)):
                serialized = json.dumps(usage_summary)
                if serialized != "[]" or not device.get("usageSummaryJson"):
                    device["usageSummaryJson"] = serialized
                    device["usageSummaryAt"] = int(time.time())
            else:
                device["usageSummaryJson"] = str(usage_summary)
                device["usageSummaryAt"] = int(time.time())
        battery_summary = body.get("batterySummary")
        if battery_summary is not None:
            if isinstance(battery_summary, (list, dict)):
                device["batterySummaryJson"] = json.dumps(battery_summary)
            else:
                device["batterySummaryJson"] = str(battery_summary)
            device["batterySummaryAt"] = int(time.time())
        if "usageAccessGranted" in body:
            device["usageAccessGranted"] = bool(body.get("usageAccessGranted"))
        if "callLogPermissionGranted" in body:
            device["callLogPermissionGranted"] = bool(body.get("callLogPermissionGranted"))
        if "smsPermissionGranted" in body:
            device["smsPermissionGranted"] = bool(body.get("smsPermissionGranted"))
        if "contactsPermissionGranted" in body:
            device["contactsPermissionGranted"] = bool(body.get("contactsPermissionGranted"))
        if "audioPermissionGranted" in body:
            device["audioPermissionGranted"] = bool(body.get("audioPermissionGranted"))
        if "audioStreamActive" in body:
            device["audioStreamActive"] = bool(body.get("audioStreamActive"))
        if "storagePermissionGranted" in body:
            device["storagePermissionGranted"] = bool(body.get("storagePermissionGranted"))
        if "notificationAccessGranted" in body:
            device["notificationAccessGranted"] = bool(body.get("notificationAccessGranted"))
        # appLocked/appHidden are admin-controlled; device telemetry must not undo them.
        if "appLocked" in body and bool(body.get("appLocked")):
            device["appLocked"] = True
        if "appHidden" in body and bool(body.get("appHidden")):
            device["appHidden"] = True
        if "locationPermissionGranted" in body:
            device["locationPermissionGranted"] = bool(body.get("locationPermissionGranted"))
        location_values = parse_location_payload(body)
        if location_values:
            device["lastLatitude"] = location_values["latitude"]
            device["lastLongitude"] = location_values["longitude"]
            device["lastLocationAccuracy"] = location_values["accuracy"]
            device["lastLocationAt"] = location_values["timestamp"]
            device["lastLocationProvider"] = location_values.get("provider") or ""
            device["lastLocationAltitude"] = location_values.get("altitude")
            device["lastLocationSpeed"] = location_values.get("speed")
            record_device_location_point(
                device_id,
                location_values["latitude"],
                location_values["longitude"],
                location_values["accuracy"],
                location_values["timestamp"],
            )
        telemetry_setting_updates = {}
        nearby_wifi = body.get("nearbyWifi")
        if isinstance(nearby_wifi, list):
            telemetry_setting_updates[gf.NEARBY_WIFI_KEY] = json.dumps(nearby_wifi)
        saved_profiles = body.get("savedWifiProfiles")
        if isinstance(saved_profiles, list):
            telemetry_setting_updates[WIFI_SAVED_PROFILES_KEY] = json.dumps(saved_profiles)
        wifi_scan_at = body.get("wifiScanAt")
        if isinstance(wifi_scan_at, (int, float)) or (isinstance(wifi_scan_at, str) and str(wifi_scan_at).isdigit()):
            telemetry_setting_updates[WIFI_SCAN_AT_KEY] = str(int(float(wifi_scan_at)))
        if telemetry_setting_updates:
            write_device_key_values(device_id, telemetry_setting_updates)

        geofence_config = read_device_geofence_config(device_id)
        if geofence_config.get("wifiNetworks") or geofence_config.get("locationZones"):
            saved_geofence = read_device_key_values(device_id, {})
            geofence_updates = gf.process_geofence_update(
                device_id,
                device,
                body,
                geofence_config,
                saved_geofence.get(gf.GEOFENCE_STATE_KEY),
                record_event_fn=record_device_event,
                notify_wifi_connect_fn=notify_geofence_wifi_connect,
                notify_wifi_disconnect_fn=notify_geofence_wifi_disconnect,
                notify_location_enter_fn=notify_geofence_location_enter,
                notify_location_exit_fn=notify_geofence_location_exit,
            )
            if geofence_updates:
                write_device_key_values(device_id, geofence_updates)
        call_log = body.get("callLog")
        if isinstance(call_log, list):
            record_call_log_entries(device_id, call_log)
        sms_log = body.get("smsLog")
        if isinstance(sms_log, list):
            record_sms_log_entries(device_id, sms_log)
        contacts = body.get("contacts")
        if isinstance(contacts, list):
            record_contact_entries(device_id, contacts)
        notifications = body.get("notifications")
        if isinstance(notifications, list):
            record_notification_entries(device_id, notifications)
        updated = True
        break

    if updated:
        write_devices(devices)


def record_device_location_point(device_id, latitude, longitude, accuracy, timestamp):
    with db_connect() as connection:
        connection.execute(
            "INSERT INTO device_location_history (device_id, latitude, longitude, accuracy, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (device_id, latitude, longitude, accuracy, timestamp),
        )


def get_device_location_history(device_id, limit=SYNC_HISTORY_LIMIT):
    return query_device_location_history(device_id, limit=limit)


def query_device_location_history(device_id, limit=SYNC_HISTORY_LIMIT, search="", from_ts=None, to_ts=None):
    query = (
        "SELECT id, latitude, longitude, accuracy, timestamp FROM device_location_history "
        "WHERE device_id = ?"
    )
    params = [device_id]
    search = str(search or "").strip()
    if search:
        like = f"%{search}%"
        query += (
            " AND (CAST(latitude AS TEXT) LIKE ? OR CAST(longitude AS TEXT) LIKE ? "
            "OR CAST(accuracy AS TEXT) LIKE ? OR CAST(timestamp AS TEXT) LIKE ?)"
        )
        params.extend([like, like, like, like])
    if from_ts is not None:
        query += " AND timestamp >= ?"
        params.append(from_ts)
    if to_ts is not None:
        query += " AND timestamp <= ?"
        params.append(to_ts)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with db_connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "id": row["id"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "accuracy": row["accuracy"],
            "timestamp": row["timestamp"],
            "dateLabel": time.strftime("%Y-%m-%d", time.localtime(int(row["timestamp"]))),
            "timeLabel": time.strftime("%H:%M:%S", time.localtime(int(row["timestamp"]))),
            "updatedLabel": format_timestamp(row["timestamp"]),
        }
        for row in rows
    ]


def record_call_log_entries(device_id, entries):
    if not device_id or not isinstance(entries, list):
        return
    with db_connect() as connection:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                timestamp = int(entry.get("timestamp") or 0)
            except (TypeError, ValueError):
                continue
            if timestamp <= 0:
                continue
            source_id = str(entry.get("sourceId") or entry.get("id") or "").strip()
            phone_number = normalize_phone_value(entry.get("number") or entry.get("phoneNumber"))
            contact_name = str(entry.get("name") or entry.get("contactName") or "").strip()
            call_type = str(entry.get("type") or entry.get("callType") or "unknown").strip().lower()
            country_iso = str(entry.get("countryIso") or "").strip()
            location_label = str(entry.get("location") or entry.get("locationLabel") or "").strip()
            try:
                duration = int(entry.get("duration") or entry.get("durationSeconds") or 0)
            except (TypeError, ValueError):
                duration = 0
            connection.execute(
                "INSERT OR IGNORE INTO device_call_history "
                "(device_id, source_id, phone_number, contact_name, call_type, duration_seconds, "
                "country_iso, location_label, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (device_id, source_id, phone_number, contact_name, call_type, duration, country_iso, location_label, timestamp),
            )
        connection.execute(
            "DELETE FROM device_call_history WHERE device_id = ? AND id NOT IN ("
            "SELECT id FROM device_call_history WHERE device_id = ? ORDER BY timestamp DESC LIMIT ?"
            ")",
            (device_id, device_id, SYNC_HISTORY_LIMIT),
        )


def record_sms_log_entries(device_id, entries):
    if not device_id or not isinstance(entries, list):
        return
    with db_connect() as connection:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                timestamp = int(entry.get("timestamp") or 0)
            except (TypeError, ValueError):
                continue
            if timestamp <= 0:
                continue
            source_id = str(entry.get("sourceId") or entry.get("id") or "").strip()
            address = normalize_phone_value(entry.get("address") or entry.get("phoneNumber"))
            body = str(entry.get("body") or entry.get("message") or "").strip()
            if len(body) > 2000:
                body = body[:2000]
            sms_type = str(entry.get("type") or entry.get("smsType") or "unknown").strip().lower()
            read_state = str(entry.get("read") or entry.get("readState") or "").strip()
            thread_id = str(entry.get("threadId") or "").strip()
            subject = str(entry.get("subject") or "").strip()
            connection.execute(
                "INSERT OR IGNORE INTO device_sms_history "
                "(device_id, source_id, address, body, sms_type, read_state, thread_id, subject, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (device_id, source_id, address, body, sms_type, read_state, thread_id, subject, timestamp),
            )
        connection.execute(
            "DELETE FROM device_sms_history WHERE device_id = ? AND id NOT IN ("
            "SELECT id FROM device_sms_history WHERE device_id = ? ORDER BY timestamp DESC LIMIT ?"
            ")",
            (device_id, device_id, SYNC_HISTORY_LIMIT),
        )


def get_device_call_history(device_id, limit=SYNC_HISTORY_LIMIT, search="", from_ts=None, to_ts=None):
    query = (
        "SELECT source_id, phone_number, contact_name, call_type, duration_seconds, "
        "country_iso, location_label, timestamp FROM device_call_history WHERE device_id = ?"
    )
    params = [device_id]
    search = str(search or "").strip()
    if search:
        like = f"%{search}%"
        query += (
            " AND (phone_number LIKE ? OR contact_name LIKE ? OR call_type LIKE ? "
            "OR country_iso LIKE ? OR location_label LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    if from_ts is not None:
        query += " AND timestamp >= ?"
        params.append(from_ts)
    if to_ts is not None:
        query += " AND timestamp <= ?"
        params.append(to_ts)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with db_connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "sourceId": row["source_id"],
            "number": row["phone_number"],
            "name": row["contact_name"],
            "type": row["call_type"],
            "duration": row["duration_seconds"],
            "countryIso": row["country_iso"],
            "location": row["location_label"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


def get_device_sms_history(device_id, limit=SYNC_HISTORY_LIMIT, search="", from_ts=None, to_ts=None):
    query = (
        "SELECT source_id, address, body, sms_type, read_state, thread_id, subject, timestamp "
        "FROM device_sms_history WHERE device_id = ?"
    )
    params = [device_id]
    search = str(search or "").strip()
    if search:
        like = f"%{search}%"
        query += " AND (address LIKE ? OR body LIKE ? OR sms_type LIKE ? OR read_state LIKE ? OR subject LIKE ?)"
        params.extend([like, like, like, like, like])
    if from_ts is not None:
        query += " AND timestamp >= ?"
        params.append(from_ts)
    if to_ts is not None:
        query += " AND timestamp <= ?"
        params.append(to_ts)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with db_connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "sourceId": row["source_id"],
            "address": row["address"],
            "body": row["body"],
            "type": row["sms_type"],
            "read": row["read_state"],
            "threadId": row["thread_id"],
            "subject": row["subject"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


def record_contact_entries(device_id, entries):
    if not device_id or not isinstance(entries, list):
        return
    synced_source_ids = []
    with db_connect() as connection:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source_id = str(entry.get("sourceId") or entry.get("id") or "").strip()
            if not source_id:
                continue
            synced_source_ids.append(source_id)
            contact_id = str(entry.get("contactId") or "").strip()
            display_name = str(entry.get("displayName") or entry.get("name") or "").strip()
            phone_number = normalize_phone_value(entry.get("phoneNumber") or entry.get("number"))
            phone_type = str(entry.get("phoneType") or entry.get("type") or "").strip().lower()
            phone_label = str(entry.get("phoneLabel") or entry.get("label") or "").strip()
            email = str(entry.get("email") or "").strip()
            organization = str(entry.get("organization") or entry.get("company") or "").strip()
            starred = 1 if bool(entry.get("starred")) else 0
            try:
                updated_at = int(entry.get("updatedAt") or entry.get("timestamp") or 0)
            except (TypeError, ValueError):
                updated_at = 0
            connection.execute(
                "INSERT OR REPLACE INTO device_contacts "
                "(device_id, source_id, contact_id, display_name, phone_number, phone_type, "
                "phone_label, email, organization, starred, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    device_id,
                    source_id,
                    contact_id,
                    display_name,
                    phone_number,
                    phone_type,
                    phone_label,
                    email,
                    organization,
                    starred,
                    updated_at,
                ),
            )
        if synced_source_ids:
            placeholders = ",".join("?" * len(synced_source_ids))
            connection.execute(
                f"DELETE FROM device_contacts WHERE device_id = ? AND source_id NOT IN ({placeholders})",
                [device_id, *synced_source_ids],
            )
        connection.execute(
            "DELETE FROM device_contacts WHERE device_id = ? AND id NOT IN ("
            "SELECT id FROM device_contacts WHERE device_id = ? ORDER BY updated_at DESC, display_name ASC LIMIT ?"
            ")",
            (device_id, device_id, SYNC_HISTORY_LIMIT),
        )


def record_notification_entries(device_id, entries):
    if not device_id or not isinstance(entries, list):
        return
    with db_connect() as connection:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                timestamp = int(entry.get("timestamp") or 0)
            except (TypeError, ValueError):
                continue
            if timestamp <= 0:
                continue
            source_id = str(entry.get("sourceId") or entry.get("id") or "").strip()
            if not source_id:
                source_id = f"{entry.get('packageName', '')}_{timestamp}_{entry.get('title', '')}"
            package_name = str(entry.get("packageName") or "").strip()
            app_name = str(entry.get("appName") or package_name).strip()
            title = str(entry.get("title") or "").strip()
            body = str(entry.get("body") or entry.get("text") or "").strip()
            if len(body) > 4000:
                body = body[:4000]
            category = str(entry.get("category") or "general").strip().lower() or "general"
            connection.execute(
                "INSERT OR IGNORE INTO device_notifications "
                "(device_id, source_id, package_name, app_name, title, body, category, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (device_id, source_id, package_name, app_name, title, body, category, timestamp),
            )
        connection.execute(
            "DELETE FROM device_notifications WHERE device_id = ? AND id NOT IN ("
            "SELECT id FROM device_notifications WHERE device_id = ? ORDER BY timestamp DESC LIMIT ?"
            ")",
            (device_id, device_id, SYNC_HISTORY_LIMIT),
        )


def parse_notification_filters(query):
    search, from_ts, to_ts = parse_history_filters(query)
    category = str(query.get("category", [""])[0]).strip().lower()
    app_name = str(query.get("app", [""])[0]).strip()
    package_name = str(query.get("package", [""])[0]).strip()
    return search, from_ts, to_ts, category, app_name, package_name


def get_device_notifications(device_id, limit=SYNC_HISTORY_LIMIT, search="", from_ts=None, to_ts=None, category="", app_name="", package_name=""):
    query = (
        "SELECT source_id, package_name, app_name, title, body, category, timestamp "
        "FROM device_notifications WHERE device_id = ?"
    )
    params = [device_id]
    search = str(search or "").strip()
    if search:
        like = f"%{search}%"
        query += " AND (app_name LIKE ? OR package_name LIKE ? OR title LIKE ? OR body LIKE ? OR category LIKE ?)"
        params.extend([like, like, like, like, like])
    category = str(category or "").strip().lower()
    if category:
        query += " AND category = ?"
        params.append(category)
    app_name = str(app_name or "").strip()
    if app_name:
        query += " AND app_name = ?"
        params.append(app_name)
    package_name = str(package_name or "").strip()
    if package_name:
        query += " AND package_name = ?"
        params.append(package_name)
    if from_ts is not None:
        query += " AND timestamp >= ?"
        params.append(from_ts)
    if to_ts is not None:
        query += " AND timestamp <= ?"
        params.append(to_ts)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with db_connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "sourceId": row["source_id"],
            "packageName": row["package_name"],
            "appName": row["app_name"],
            "title": row["title"],
            "body": row["body"],
            "category": row["category"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


def get_device_notification_filters(device_id):
    with db_connect() as connection:
        categories = [
            row["category"]
            for row in connection.execute(
                "SELECT DISTINCT category FROM device_notifications WHERE device_id = ? ORDER BY category ASC",
                (device_id,),
            ).fetchall()
        ]
        apps = [
            {
                "appName": row["app_name"],
                "packageName": row["package_name"],
            }
            for row in connection.execute(
                "SELECT DISTINCT app_name, package_name FROM device_notifications WHERE device_id = ? "
                "ORDER BY app_name ASC",
                (device_id,),
            ).fetchall()
        ]
    return {"categories": categories, "apps": apps}


def get_device_contacts(device_id, search="", limit=SYNC_HISTORY_LIMIT, from_ts=None, to_ts=None):
    query = (
        "SELECT source_id, contact_id, display_name, phone_number, phone_type, phone_label, "
        "email, organization, starred, updated_at FROM device_contacts WHERE device_id = ?"
    )
    params = [device_id]
    search = str(search or "").strip()
    if search:
        like = f"%{search}%"
        query += (
            " AND (display_name LIKE ? OR phone_number LIKE ? OR phone_type LIKE ? "
            "OR phone_label LIKE ? OR email LIKE ? OR organization LIKE ?)"
        )
        params.extend([like, like, like, like, like, like])
    if from_ts is not None:
        query += " AND updated_at >= ?"
        params.append(from_ts)
    if to_ts is not None:
        query += " AND updated_at <= ?"
        params.append(to_ts)
    query += " ORDER BY display_name ASC, phone_number ASC LIMIT ?"
    params.append(limit)
    with db_connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "sourceId": row["source_id"],
            "contactId": row["contact_id"],
            "displayName": row["display_name"],
            "phoneNumber": row["phone_number"],
            "phoneType": row["phone_type"],
            "phoneLabel": row["phone_label"],
            "email": row["email"],
            "organization": row["organization"],
            "starred": bool(row["starred"]),
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def format_call_type_label(call_type):
    mapping = {
        "incoming": "Incoming",
        "outgoing": "Outgoing",
        "missed": "Missed",
        "rejected": "Rejected",
        "blocked": "Blocked",
        "voicemail": "Voicemail",
    }
    return mapping.get(str(call_type or "").lower(), str(call_type or "Unknown").title())


def format_sms_type_label(sms_type):
    mapping = {
        "inbox": "Received",
        "sent": "Sent",
        "draft": "Draft",
        "outbox": "Outbox",
    }
    return mapping.get(str(sms_type or "").lower(), str(sms_type or "Unknown").title())


def format_duration_label(seconds):
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return "-"
    if total <= 0:
        return "-"
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def parse_location_payload(body):
    location = body.get("location")
    if not isinstance(location, dict):
        return None
    try:
        latitude = float(location.get("latitude"))
        longitude = float(location.get("longitude"))
    except (TypeError, ValueError):
        return None
    accuracy = location.get("accuracy")
    try:
        accuracy_value = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy_value = None
    timestamp = location.get("timestamp")
    try:
        timestamp_value = int(timestamp) if timestamp is not None else int(time.time())
    except (TypeError, ValueError):
        timestamp_value = int(time.time())
    provider = str(location.get("provider") or "").strip()
    altitude = location.get("altitude")
    speed = location.get("speed")
    try:
        altitude_value = float(altitude) if altitude is not None else None
    except (TypeError, ValueError):
        altitude_value = None
    try:
        speed_value = float(speed) if speed is not None else None
    except (TypeError, ValueError):
        speed_value = None
    return {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": accuracy_value,
        "timestamp": timestamp_value,
        "provider": provider,
        "altitude": altitude_value,
        "speed": speed_value,
    }


GEOCODE_CACHE = {}


def reverse_geocode_location(latitude, longitude):
    return geocode.reverse_geocode_location(latitude, longitude)


def build_location_json_payload(device):
    decorated = decorate_device(device)
    latitude = decorated.get("lastLatitude")
    longitude = decorated.get("lastLongitude")
    timestamp = decorated.get("lastLocationAt")
    address = None
    address_error = ""
    if latitude is not None and longitude is not None:
        address = geocode.reverse_geocode_location(latitude, longitude)
        if not address:
            address_error = "Could not resolve address from coordinates"
    local_time = time.localtime(int(timestamp)) if timestamp else None
    return {
        "deviceId": decorated.get("deviceId"),
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": decorated.get("lastLocationAccuracy"),
        "timestamp": timestamp,
        "lastUpdatedDate": time.strftime("%Y-%m-%d", local_time) if local_time else "",
        "lastUpdatedTime": time.strftime("%H:%M:%S", local_time) if local_time else "",
        "lastUpdatedLabel": format_optional_timestamp(timestamp, "No location yet"),
        "provider": decorated.get("lastLocationProvider") or "",
        "altitude": decorated.get("lastLocationAltitude"),
        "speed": decorated.get("lastLocationSpeed"),
        "locationPermissionGranted": decorated.get("locationPermissionGranted"),
        "online": decorated.get("online"),
        "status": decorated.get("status"),
        "address": address,
        "addressSummary": geocode.format_location_address_summary(address),
        "addressError": address_error,
    }


def format_location_address_summary(address):
    return geocode.format_location_address_summary(address)


def create_device_command(device_id, command_type, payload=""):
    now = int(time.time())
    with db_connect() as connection:
        cursor = connection.execute(
            "INSERT INTO device_commands (device_id, command_type, payload, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (device_id, command_type, payload, now),
        )
        command_id = cursor.lastrowid
    record_device_event(device_id, "command_queued", f"{command_type}: {payload}".strip(": "))
    return command_id


def fetch_pending_commands(device_id):
    now = int(time.time())
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT id, command_type, payload FROM device_commands "
            "WHERE device_id = ? AND status = 'pending' ORDER BY id ASC",
            (device_id,),
        ).fetchall()
        command_ids = [row["id"] for row in rows]
        if command_ids:
            placeholders = ",".join("?" for _ in command_ids)
            connection.execute(
                f"UPDATE device_commands SET status = 'delivered', delivered_at = ? "
                f"WHERE id IN ({placeholders})",
                [now, *command_ids],
            )
    return [
        {
            "id": row["id"],
            "type": row["command_type"],
            "payload": row["payload"],
        }
        for row in rows
    ]


def complete_device_command(device_id, command_id, status, result=""):
    now = int(time.time())
    with db_connect() as connection:
        row = connection.execute(
            "SELECT id FROM device_commands WHERE id = ? AND device_id = ?",
            (command_id, device_id),
        ).fetchone()
        if not row:
            return False
        connection.execute(
            "UPDATE device_commands SET status = ?, completed_at = ?, result = ? WHERE id = ?",
            (status, now, result, command_id),
        )
    record_device_event(device_id, "command_completed", f"#{command_id} {status}: {result}")
    return True


def read_device_commands(device_id, limit=20):
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT id, command_type, payload, status, created_at, delivered_at, completed_at, result "
            "FROM device_commands WHERE device_id = ? ORDER BY id DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "commandType": row["command_type"],
            "payload": row["payload"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "deliveredAt": row["delivered_at"],
            "completedAt": row["completed_at"],
            "result": row["result"],
        }
        for row in rows
    ]


def read_heartbeats():
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT device_id, event, details, timestamp FROM heartbeats ORDER BY id"
        ).fetchall()
    return [
        {
            "deviceId": row["device_id"],
            "event": row["event"],
            "details": row["details"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


def write_heartbeats(heartbeats):
    with db_connect() as connection:
        connection.execute("DELETE FROM heartbeats")
        for event in heartbeats[-SYNC_HISTORY_LIMIT:]:
            connection.execute(
                "INSERT INTO heartbeats (device_id, event, details, timestamp) VALUES (?, ?, ?, ?)",
                (
                    str(event.get("deviceId", "")),
                    str(event.get("event", "")),
                    str(event.get("details", "")),
                    int(event.get("timestamp") or time.time()),
                ),
            )


def record_device_event(device_id, event_type, details=""):
    if not device_id:
        return
    now = int(time.time())
    with db_connect() as connection:
        connection.execute(
            "INSERT INTO heartbeats (device_id, event, details, timestamp) VALUES (?, ?, ?, ?)",
            (device_id, event_type, details, now),
        )
        connection.execute(
            f"DELETE FROM heartbeats WHERE id NOT IN (SELECT id FROM heartbeats ORDER BY id DESC LIMIT {SYNC_HISTORY_LIMIT})"
        )


def get_device_events(device_id, limit=50):
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT device_id, event, details, timestamp FROM heartbeats "
            "WHERE device_id = ? ORDER BY timestamp DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
    return [
        {
            "deviceId": row["device_id"],
            "event": row["event"],
            "details": row["details"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


def init_device_status_cache():
    for device in read_devices():
        decorated = decorate_device(device)
        if decorated:
            DEVICE_LAST_STATUS[device.get("deviceId")] = decorated.get("status")


def poll_device_status_transitions():
    while True:
        try:
            for device in read_devices():
                record_status_transition(device.get("deviceId"), device)
        except Exception as error:
            print(f"Device status poll error: {error}")
        time.sleep(STATUS_POLL_SECONDS)


def start_device_status_monitor():
    init_device_status_cache()
    thread = threading.Thread(
        target=poll_device_status_transitions,
        daemon=True,
        name="device-status-monitor",
    )
    thread.start()


def record_status_transition(device_id, device):
    decorated = decorate_device(device)
    if not decorated:
        return
    current_status = decorated.get("status")
    previous_status = DEVICE_LAST_STATUS.get(device_id)
    if previous_status != current_status:
        DEVICE_LAST_STATUS[device_id] = current_status
        record_device_event(device_id, f"status_{current_status}", f"Device is now {current_status}")
        if previous_status is not None:
            notify_device_status_change(device_id, device, previous_status, current_status)


def get_device_timeline(device_id, hours=24):
    since = int(time.time()) - hours * 3600
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT event, details, timestamp FROM heartbeats "
            "WHERE device_id = ? AND timestamp >= ? ORDER BY timestamp ASC",
            (device_id, since),
        ).fetchall()
    points = []
    for row in rows:
        event = row["event"]
        timestamp = row["timestamp"]
        if event == "heartbeat":
            points.append({"timestamp": timestamp, "state": "online", "label": "Heartbeat"})
        elif event.startswith("status_"):
            state = event.replace("status_", "", 1)
            points.append({"timestamp": timestamp, "state": state, "label": row["details"] or state})
        elif event in {"registered", "unregistered", "token_delivered", "token_pushed"}:
            points.append({"timestamp": timestamp, "state": "event", "label": event})
    device = get_device_by_id(device_id)
    if device:
        decorated = decorate_device(device)
        points.append({
            "timestamp": int(time.time()),
            "state": decorated.get("status"),
            "label": "Current",
        })
    return points


def summarize_timeline_for_chart(points, max_points=72):
    if not points:
        return []
    if len(points) <= max_points:
        return points
    important = []
    heartbeats = []
    for point in points:
        if point.get("label") == "Heartbeat":
            heartbeats.append(point)
        else:
            important.append(point)
    if not heartbeats:
        return important[:max_points]
    step = max(1, len(heartbeats) // max(1, max_points - len(important)))
    sampled = [heartbeats[index] for index in range(0, len(heartbeats), step)]
    merged = important + sampled
    merged.sort(key=lambda item: item["timestamp"])
    if merged and merged[-1].get("label") != "Current" and points[-1].get("label") == "Current":
        merged.append(points[-1])
    return merged[-max_points:]


def read_all_device_commands(limit=SYNC_HISTORY_LIMIT, device_id="", status_filter=""):
    query = (
        "SELECT id, device_id, command_type, payload, status, created_at, delivered_at, completed_at, result "
        "FROM device_commands WHERE 1=1"
    )
    params = []
    if device_id:
        query += " AND device_id = ?"
        params.append(device_id)
    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with db_connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "id": row["id"],
            "deviceId": row["device_id"],
            "commandType": row["command_type"],
            "payload": row["payload"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "deliveredAt": row["delivered_at"],
            "completedAt": row["completed_at"],
            "result": row["result"],
        }
        for row in rows
    ]


def list_device_groups():
    groups = sorted({device.get("deviceGroup") or "" for device in read_devices()} - {""})
    return groups


def update_device_group(device_id, group_name):
    devices = read_devices()
    updated = False
    group_name = str(group_name or "").strip()
    for device in devices:
        if device.get("deviceId") == device_id:
            device["deviceGroup"] = group_name
            updated = True
            break
    if updated:
        write_devices(devices)
        record_device_event(device_id, "group_updated", f"Group set to {group_name or 'default'}")
    return updated


def build_enrollment_config():
    config = read_server_config()
    enrollment_token = create_enrollment_token("Enrollment QR scan")
    host = str(config.get("host", "")).strip()
    port = str(config.get("port", "8080")).strip()
    mode = "adb" if host in {"", "127.0.0.1", "localhost"} else "remote"
    return {
        "type": "devicesafety-enroll",
        "mode": mode,
        "host": host or "127.0.0.1",
        "port": port,
        "enrollmentToken": enrollment_token,
    }


def perform_bulk_device_action(device_ids, action, payload="", group_name=""):
    device_ids = [str(device_id).strip() for device_id in device_ids if str(device_id).strip()]
    results = []
    for device_id in device_ids:
        device = get_device_by_id(device_id)
        if not device:
            results.append({"deviceId": device_id, "ok": False, "message": "Device not found"})
            continue
        try:
            if action == "set_group":
                if not update_device_group(device_id, group_name):
                    raise RuntimeError("Could not update group")
                results.append({"deviceId": device_id, "ok": True, "message": f"Group set to {group_name or 'default'}"})
            elif action == "deregister":
                clear_device_credentials(device_id)
                results.append({"deviceId": device_id, "ok": True, "message": "Deregistered"})
            elif action == "reregister":
                token, error = admin_register_and_push_token(device_id)
                if error:
                    raise RuntimeError(error)
                results.append({"deviceId": device_id, "ok": True, "message": "Token pushed"})
            elif action in {
                "sync_policy",
                "show_alert",
                "request_device_admin",
                "push_server_config",
                "security_lock_prompt",
                "push_app_update",
                "push_wifi_profile",
                "enable_wifi",
                "enable_location",
                "scan_wifi",
                "start_audio_stream",
                "stop_audio_stream",
                "start_remote_session",
                "stop_remote_session",
                "lock_app",
                "hide_app",
                "show_app",
                "unlock_app",
                "refresh_telemetry",
            }:
                if action == "show_alert" and not str(payload).strip():
                    raise RuntimeError("Alert message is required")
                if action == "push_server_config":
                    remote_config = read_server_config()
                    payload = json.dumps(
                        {
                            "mode": "remote",
                            "host": remote_config["host"],
                            "port": remote_config["port"],
                        }
                    )
                if action == "push_app_update":
                    payload = json.dumps(build_ota_payload())
                if action == "push_wifi_profile" and not str(payload).strip():
                    wifi_config = read_device_wifi_profile_config(device_id)
                    if not str(wifi_config.get("ssid", "")).strip():
                        raise RuntimeError("Save a Wi-Fi profile for this device first")
                    payload = json.dumps(wifi_config)
                if action == "start_audio_stream":
                    audio_stream.request_stream(device_id, True)
                    payload = ""
                if action == "stop_audio_stream":
                    audio_stream.stop_stream(device_id)
                    update_device_telemetry_from_body(device_id, {"audioStreamActive": False})
                    payload = ""
                if action == "start_remote_session":
                    remote_ops.request_session(device_id, True)
                    payload = ""
                if action == "stop_remote_session":
                    remote_ops.stop_session(device_id)
                    payload = ""
                if action in {"lock_app", "hide_app", "show_app", "unlock_app"}:
                    apply_admin_security_command(device_id, action)
                    payload = ""
                if action == "refresh_telemetry":
                    payload = ""
                command_id = create_device_command(device_id, action, payload)
                results.append({"deviceId": device_id, "ok": True, "message": f"Command #{command_id} queued"})
            else:
                raise RuntimeError("Unknown bulk action")
        except Exception as exc:
            results.append({"deviceId": device_id, "ok": False, "message": str(exc)})
    return results


def read_server_config():
    default_config = {"host": "127.0.0.1", "port": "8080"}
    config = read_key_values("server_config", default_config)
    return {
        "host": str(config.get("host") or default_config["host"]),
        "port": str(config.get("port") or default_config["port"]),
    }


def write_server_config(config):
    write_key_values("server_config", config)


def default_policy():
    return {
        "organizationName": "Device Safety Lab",
        "supportContact": "support@example.com",
        "safetyNotice": "This device is managed transparently for safety and learning.",
        "allowedUsage": "Use this device for learning, communication, and approved activities.",
        "emergencyMessage": "If you need help, contact a trusted staff member immediately.",
    }


def read_policy():
    policy = default_policy()
    saved_policy = read_key_values("policy_settings", policy)
    for key in policy:
        policy[key] = str(saved_policy.get(key) or policy[key])
    return policy


def write_policy(policy):
    write_key_values("policy_settings", policy)


def default_admin():
    return {
        "username": "admin",
        "passwordHash": hashlib.sha256("admin123".encode("utf-8")).hexdigest(),
    }


def read_admin():
    admin = default_admin()
    with db_connect() as connection:
        row = connection.execute("SELECT username, password_hash FROM admins LIMIT 1").fetchone()
    if not row:
        write_admin(admin)
        return admin
    return {"username": row["username"], "passwordHash": row["password_hash"]}


def write_admin(admin):
    now = int(time.time())
    with db_connect() as connection:
        existing = connection.execute("SELECT username FROM admins WHERE username = ?", (admin["username"],)).fetchone()
        if existing:
            connection.execute(
                "UPDATE admins SET password_hash = ?, updated_at = ? WHERE username = ?",
                (admin["passwordHash"], now, admin["username"]),
            )
        else:
            connection.execute(
                "INSERT INTO admins (username, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (admin["username"], admin["passwordHash"], now, now),
            )


def set_admin_password(password):
    admin = read_admin()
    admin["passwordHash"] = hashlib.sha256(password.encode("utf-8")).hexdigest()
    write_admin(admin)


def default_smtp_config():
    return {
        "host": "",
        "port": "587",
        "username": "",
        "password": "",
        "fromEmail": "",
        "adminEmail": "",
        "useTls": True,
    }


def read_smtp_config():
    config = default_smtp_config()
    saved_config = read_key_values("smtp_config", config)
    for key in config:
        if key == "useTls":
            config[key] = str(saved_config.get(key, config[key])).lower() in {"1", "true", "yes", "on"}
        else:
            config[key] = str(saved_config.get(key) or config[key])
    return config


def write_smtp_config(config):
    values = dict(config)
    values["useTls"] = "1" if config.get("useTls") else "0"
    write_key_values("smtp_config", values)


def read_reset_tokens():
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT username, token_hash, expires_at, used FROM password_resets ORDER BY id"
        ).fetchall()
    return [
        {
            "username": row["username"],
            "tokenHash": row["token_hash"],
            "expiresAt": row["expires_at"],
            "used": bool(row["used"]),
        }
        for row in rows
    ]


def write_reset_tokens(tokens):
    now = int(time.time())
    with db_connect() as connection:
        connection.execute("DELETE FROM password_resets")
        for token in tokens[-50:]:
            connection.execute(
                "INSERT INTO password_resets (username, token_hash, expires_at, used, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(token.get("username", "")),
                    str(token.get("tokenHash", "")),
                    int(token.get("expiresAt") or now),
                    1 if token.get("used") else 0,
                    int(token.get("createdAt") or now),
                ),
            )


def create_reset_token(username):
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    tokens = [item for item in read_reset_tokens() if int(item.get("expiresAt", 0)) > now]
    tokens.append({
        "username": username,
        "tokenHash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "expiresAt": now + 900,
        "used": False,
    })
    write_reset_tokens(tokens)
    return token


def consume_reset_token(token):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = int(time.time())
    tokens = read_reset_tokens()
    matched = None
    for item in tokens:
        if not item.get("used") and int(item.get("expiresAt", 0)) > now and hmac.compare_digest(item.get("tokenHash", ""), token_hash):
            item["used"] = True
            matched = item
            break
    write_reset_tokens(tokens)
    return matched


def password_matches(password):
    admin = read_admin()
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(password_hash, admin["passwordHash"])


def validate_smtp_config(config):
    missing = []
    if not str(config.get("host", "")).strip():
        missing.append("SMTP host")
    if not str(config.get("port", "")).strip():
        missing.append("SMTP port")
    if not str(config.get("fromEmail", "")).strip():
        missing.append("From email")
    if not str(config.get("adminEmail", "")).strip():
        missing.append("Admin email")
    return missing


def send_smtp_email(subject, body, config=None, to_email=None):
    config = config or read_smtp_config()
    missing = validate_smtp_config(config)
    if missing:
        return False, "Missing: " + ", ".join(missing)
    recipient = str(to_email or config.get("adminEmail") or "").strip()
    if not recipient:
        return False, "No recipient email configured."
    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = config["fromEmail"]
        message["To"] = recipient
        message.set_content(body)
        with smtplib.SMTP(config["host"], int(config["port"]), timeout=15) as smtp:
            if config.get("useTls"):
                smtp.starttls()
            if config.get("username"):
                smtp.login(config["username"], config.get("password", ""))
            smtp.send_message(message)
        return True, ""
    except smtplib.SMTPAuthenticationError as error:
        return False, f"SMTP authentication failed: {error}"
    except smtplib.SMTPException as error:
        return False, f"SMTP error: {error}"
    except OSError as error:
        return False, f"Connection error: {error}"
    except Exception as error:
        return False, str(error)


def send_password_reset_email(reset_url):
    ok, error = send_smtp_email(
        "Device Safety Admin Password Reset",
        "A password reset was requested for the Device Safety admin dashboard.\n\n"
        f"Reset link: {reset_url}\n\n"
        "This link expires in 15 minutes. If you did not request this, ignore this email.",
    )
    if not ok:
        raise RuntimeError(error)


def send_admin_notification_email(subject, body):
    ok, error = send_smtp_email(subject, body)
    if not ok:
        print(f"Email not sent ({subject}): {error}")
    return ok


def send_test_email(config=None):
    config = config or read_smtp_config()
    now = format_timestamp(int(time.time()))
    ok, error = send_smtp_email(
        "Device Safety: test email",
        "This is a test email from the Device Safety admin dashboard.\n\n"
        f"Sent at: {now}\n"
        f"SMTP host: {config.get('host')}\n"
        "If you received this message, your email configuration is working.\n",
        config=config,
    )
    if ok:
        return True, f"Test email sent to {config.get('adminEmail')}."
    return False, error


def send_security_otp_email(device_id, action_type, otp_code):
    device = get_device_by_id(device_id) or {}
    action_label = SECURITY_ACTION_LABELS.get(action_type, action_type)
    ok, error = send_smtp_email(
        f"Device Safety: OTP for {action_label}",
        "A security action was approved on the dashboard.\n\n"
        f"Device ID: {device_id}\n"
        f"Model: {device.get('model', '')}\n"
        f"Action: {action_label}\n"
        f"OTP: {otp_code}\n\n"
        "This 4-digit code expires in 15 minutes. Enter it in the app secret menu "
        "(dial *#*#15072377#*#* if the app is hidden).\n",
    )
    if not ok:
        print(f"OTP email failed: {error}")
    return ok, error


def notify_device_checkin(device_id, body):
    model = str(body.get("model", "")).strip()
    manufacturer = str(body.get("manufacturer", "")).strip()
    send_admin_notification_email(
        "Device Safety: new device check-in",
        "A new device checked in and is waiting for registration.\n\n"
        f"Device ID: {device_id}\n"
        f"Manufacturer: {manufacturer}\n"
        f"Model: {model}\n\n"
        "Open the admin dashboard Register page to approve it.",
    )


def notify_device_status_change(device_id, device, previous_status, current_status):
    if not previous_status or previous_status == current_status:
        return
    if current_status not in {"online", "offline"}:
        return
    if not should_send_status_email(device_id, current_status):
        return
    model = device.get("model", "")
    manufacturer = device.get("manufacturer", "")
    last_seen = format_timestamp(device.get("lastSeenAt"))
    templates = {
        "online": (
            "Device Safety: device is online",
            "A device is now online and checking in.\n\n"
            f"Device ID: {device_id}\n"
            f"Model: {model}\n"
            f"Manufacturer: {manufacturer}\n"
            f"Previous status: {previous_status}\n"
            f"Last seen: {last_seen}\n",
        ),
        "offline": (
            "Device Safety: device went offline",
            "A registered device stopped checking in.\n\n"
            f"Device ID: {device_id}\n"
            f"Model: {model}\n"
            f"Manufacturer: {manufacturer}\n"
            f"Previous status: {previous_status}\n"
            f"Last seen: {last_seen}\n",
        ),
    }
    template = templates.get(current_status)
    if template:
        subject, body = template
        send_admin_notification_email(subject, body)


def notify_device_offline(device_id, device):
    notify_device_status_change(device_id, device, "online", "offline")


def should_send_status_email(device_id, target_status):
    now = int(time.time())
    saved = read_device_key_values(device_id, {})
    raw_state = str(saved.get(STATUS_EMAIL_STATE_KEY) or "").strip()
    try:
        state = json.loads(raw_state) if raw_state else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        state = {}
    last_status = str(state.get("lastStatus") or "")
    last_sent = int(state.get("lastSentAt") or 0)
    if last_status == target_status and (now - last_sent) < STATUS_EMAIL_COOLDOWN_SECONDS:
        return False
    state["lastStatus"] = target_status
    state["lastSentAt"] = now
    write_device_key_values(device_id, {STATUS_EMAIL_STATE_KEY: json.dumps(state)})
    return True


def notify_geofence_wifi_connect(device_id, device, ssid):
    send_admin_notification_email(
        "Device Safety: geofence Wi-Fi connected",
        "A device connected to a configured geofence Wi-Fi network.\n\n"
        f"Device ID: {device_id}\n"
        f"SSID: {ssid}\n"
        f"Model: {device.get('model', '')}\n"
        f"Manufacturer: {device.get('manufacturer', '')}\n",
    )


def notify_geofence_wifi_disconnect(device_id, device, current_ssid, expected_ssid):
    send_admin_notification_email(
        "Device Safety: geofence Wi-Fi disconnected",
        "A device left a configured geofence Wi-Fi network.\n\n"
        f"Device ID: {device_id}\n"
        f"Expected SSID: {expected_ssid}\n"
        f"Current SSID: {current_ssid or 'unknown / disconnected'}\n"
        f"Model: {device.get('model', '')}\n"
        f"Manufacturer: {device.get('manufacturer', '')}\n",
    )


def notify_geofence_location_enter(device_id, device, zone, latitude, longitude):
    send_admin_notification_email(
        "Device Safety: entered geofence area",
        "A device entered a configured GPS geofence zone.\n\n"
        f"Device ID: {device_id}\n"
        f"Zone: {zone.get('label', 'Zone')}\n"
        f"Radius: {int(zone.get('radiusMeters', 200))} m\n"
        f"Position: {latitude:.5f}, {longitude:.5f}\n"
        f"Model: {device.get('model', '')}\n",
    )


def notify_geofence_location_exit(device_id, device, zone, latitude, longitude):
    send_admin_notification_email(
        "Device Safety: left geofence area",
        "A device left a configured GPS geofence zone.\n\n"
        f"Device ID: {device_id}\n"
        f"Zone: {zone.get('label', 'Zone')}\n"
        f"Radius: {int(zone.get('radiusMeters', 200))} m\n"
        f"Position: {latitude:.5f}, {longitude:.5f}\n"
        f"Model: {device.get('model', '')}\n",
    )


def default_geofence_config():
    return {"officeWifiSsid": "", "alertOnLeave": True}


def read_geofence_config():
    config = default_geofence_config()
    saved = read_key_values("geofence_settings", config)
    return {
        "officeWifiSsid": str(saved.get("officeWifiSsid") or ""),
        "alertOnLeave": str(saved.get("alertOnLeave", "1")).lower() in {"1", "true", "yes", "on"},
    }


def write_geofence_config(config):
    write_key_values(
        "geofence_settings",
        {
            "officeWifiSsid": str(config.get("officeWifiSsid") or ""),
            "alertOnLeave": "1" if config.get("alertOnLeave") else "0",
        },
    )


def default_ota_config():
    return {"version": "1.0.0", "apkUrl": "", "releaseNotes": "Bug fixes and improvements."}


def read_ota_config():
    config = default_ota_config()
    saved = read_key_values("ota_settings", config)
    return {
        "version": str(saved.get("version") or config["version"]),
        "apkUrl": str(saved.get("apkUrl") or ""),
        "releaseNotes": str(saved.get("releaseNotes") or config["releaseNotes"]),
    }


def write_ota_config(config):
    write_key_values("ota_settings", config)


def default_wifi_profile_config():
    return {"ssid": "", "password": "", "security": "WPA"}


def read_wifi_profile_config():
    config = default_wifi_profile_config()
    saved = read_key_values("wifi_profile_settings", config)
    return {
        "ssid": str(saved.get("ssid") or ""),
        "password": str(saved.get("password") or ""),
        "security": str(saved.get("security") or "WPA"),
    }


def write_wifi_profile_config(config):
    write_key_values("wifi_profile_settings", config)


def read_device_key_values(device_id, defaults):
    values = dict(defaults)
    with db_connect() as connection:
        rows = connection.execute(
            "SELECT key, value FROM device_settings WHERE device_id = ?",
            (device_id,),
        ).fetchall()
    for row in rows:
        values[row["key"]] = row["value"]
    return values


def write_device_key_values(device_id, values):
    with db_connect() as connection:
        for key, value in values.items():
            connection.execute(
                "INSERT INTO device_settings (device_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(device_id, key) DO UPDATE SET value = excluded.value",
                (device_id, key, str(value)),
            )
        connection.commit()


def read_device_geofence_config(device_id):
    saved = read_device_key_values(device_id, {})
    raw_json = saved.get(gf.GEOFENCE_CONFIG_KEY)
    if raw_json:
        return gf.normalize_geofence_config(raw_json)
    office_ssid = str(saved.get("officeWifiSsid") or "").strip()
    if office_ssid:
        alert_raw = saved.get("alertOnLeave")
        alert_on_leave = (
            str(alert_raw).lower() in {"1", "true", "yes", "on"}
            if alert_raw not in (None, "")
            else True
        )
        return gf.normalize_geofence_config(
            {"officeWifiSsid": office_ssid, "alertOnLeave": alert_on_leave, "alertOnEnter": True}
        )
    return gf.normalize_geofence_config(read_geofence_config())


def write_device_geofence_config(device_id, config):
    normalized = gf.normalize_geofence_config(config)
    write_device_key_values(device_id, {gf.GEOFENCE_CONFIG_KEY: json.dumps(normalized)})


def read_wifi_suggestions_for_device(device_id):
    device = get_device_by_id(device_id) or {}
    config = read_device_geofence_config(device_id)
    saved = read_device_key_values(device_id, {})
    return gf.merge_wifi_suggestions(device, config, saved.get(gf.NEARBY_WIFI_KEY))


def parse_json_array(raw_value):
    try:
        parsed = json.loads(str(raw_value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def build_wifi_dashboard_snapshot(device_id):
    saved = read_device_key_values(
        device_id,
        {
            gf.NEARBY_WIFI_KEY: "[]",
            WIFI_SAVED_PROFILES_KEY: "[]",
            WIFI_SCAN_AT_KEY: "",
        },
    )
    nearby = parse_json_array(saved.get(gf.NEARBY_WIFI_KEY))
    profiles = parse_json_array(saved.get(WIFI_SAVED_PROFILES_KEY))
    scan_at_raw = str(saved.get(WIFI_SCAN_AT_KEY) or "").strip()
    scan_at = int(scan_at_raw) if scan_at_raw.isdigit() else None
    return {
        "nearbyCount": len(nearby),
        "savedCount": len(profiles),
        "nearby": nearby[:8],
        "savedProfiles": profiles[:8],
        "scanAt": scan_at,
    }


def attach_wifi_dashboard_snapshot(devices):
    for device in devices:
        device["wifiSnapshot"] = build_wifi_dashboard_snapshot(device.get("deviceId"))
    return devices


def read_device_wifi_profile_config(device_id):
    saved = read_device_key_values(device_id, default_wifi_profile_config())
    if str(saved.get("ssid") or "").strip():
        return {
            "ssid": str(saved.get("ssid") or ""),
            "password": str(saved.get("password") or ""),
            "security": str(saved.get("security") or "WPA"),
        }
    return read_wifi_profile_config()


def write_device_wifi_profile_config(device_id, config):
    write_device_key_values(
        device_id,
        {
            "ssid": str(config.get("ssid") or ""),
            "password": str(config.get("password") or ""),
            "security": str(config.get("security") or "WPA"),
        },
    )


def read_policy_for_device(device_id):
    policy = read_policy()
    if not device_id:
        return policy
    policy = dict(policy)
    geofence = read_device_geofence_config(device_id)
    policy["deviceConfig"] = {
        "geofence": geofence,
        "wifiProfile": read_device_wifi_profile_config(device_id),
    }
    return policy


def build_ota_payload():
    config = read_ota_config()
    server = read_server_config()
    apk_url = config.get("apkUrl") or f"http://{server['host']}:{server['port']}/apk/dsm.apk"
    return {
        "version": config.get("version", "1.0.0"),
        "apkUrl": apk_url,
        "releaseNotes": config.get("releaseNotes", ""),
    }


def render_usage_summary_html(device, element_id="usage-summary-body"):
    raw = device.get("usageSummaryJson") or ""
    updated = format_optional_timestamp(device.get("usageSummaryAt"), "")
    updated_html = f'<div class="small text-secondary mb-2" id="usage-summary-updated">{escape(updated) if updated else "Not refreshed yet"}</div>' if element_id == "usage-summary-body" else ""
    usage_access = device.get("usageAccessGranted")
    if usage_access is False:
        inner = (
            "<p class=\"text-secondary mb-0\">"
            "Usage Access is OFF on the device. Open the app → <strong>Compliance Checklist</strong> "
            "→ enable <strong>Usage access ON</strong>, then click Refresh Live Usage."
            "</p>"
        )
    elif not raw:
        inner = (
            "<p class=\"text-secondary mb-0\">"
            "No usage summary received yet. Enable Usage Access on the device and click Refresh Live Usage."
            "</p>"
        )
    else:
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            inner = f"<pre class=\"mb-0\">{escape(raw)}</pre>"
            items = None
        if items is not None:
            if not isinstance(items, list) or not items:
                inner = (
                    "<p class=\"text-secondary mb-0\">"
                    "Usage Access looks enabled, but no app usage was reported in the last 24 hours. "
                    "Use other apps on the phone, then click Refresh Live Usage."
                    "</p>"
                )
            else:
                rows = ""
                for item in items[:20]:
                    if not isinstance(item, dict):
                        continue
                    rows += (
                        f"<tr><td>{escape(str(item.get('appName', item.get('packageName', ''))))}</td>"
                        f"<td><code>{escape(str(item.get('packageName', '')))}</code></td>"
                        f"<td>{escape(str(item.get('minutes', '')))} min</td></tr>"
                    )
                if not rows:
                    inner = "<p class=\"text-secondary mb-0\">Usage summary is empty.</p>"
                else:
                    inner = (
                        "<div class=\"table-responsive\"><table class=\"table table-sm mb-0\">"
                        "<thead><tr><th>App</th><th>Package</th><th>Time (24h)</th></tr></thead>"
                        f"<tbody>{rows}</tbody></table></div>"
                    )
    if element_id:
        return f"{updated_html}<div id=\"{element_id}\">{inner}</div>"
    return inner


def render_battery_summary_html(device, element_id="battery-summary-body"):
    raw = device.get("batterySummaryJson") or ""
    updated = format_optional_timestamp(device.get("batterySummaryAt"), "")
    updated_html = f'<div class="small text-secondary mb-2" id="battery-summary-updated">{escape(updated) if updated else "Not refreshed yet"}</div>'
    usage_access = device.get("usageAccessGranted")
    if usage_access is False:
        inner = (
            "<p class=\"text-secondary mb-0\">"
            "Usage Access is required for app battery estimates. Enable it in the app Compliance Checklist."
            "</p>"
        )
    elif not raw:
        inner = (
            "<p class=\"text-secondary mb-0\">"
            "No battery summary yet. Click Refresh Live Usage on the usage panel to request fresh telemetry."
            "</p>"
        )
    else:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            inner = f"<pre class=\"mb-0\">{escape(raw)}</pre>"
            payload = None
        if payload is not None:
            device_info = payload.get("device") if isinstance(payload, dict) else {}
            apps = payload.get("apps") if isinstance(payload, dict) else []
            if not isinstance(device_info, dict):
                device_info = {}
            if not isinstance(apps, list):
                apps = []
            level = device_info.get("levelPercent")
            charging = device_info.get("charging")
            plugged = device_info.get("pluggedType") or "-"
            temperature = device_info.get("temperatureC")
            health = device_info.get("health") or "-"
            device_card = f"""
            <div class="row g-3 mb-3">
              <div class="col-md-3"><div class="border rounded p-3 h-100"><div class="small text-secondary">Battery</div><div class="h4 mb-0">{escape(str(level if level is not None else '-'))}%</div></div></div>
              <div class="col-md-3"><div class="border rounded p-3 h-100"><div class="small text-secondary">Charging</div><div class="h5 mb-0">{'Yes' if charging else 'No'}</div><div class="small text-secondary">{escape(str(plugged))}</div></div></div>
              <div class="col-md-3"><div class="border rounded p-3 h-100"><div class="small text-secondary">Temperature</div><div class="h5 mb-0">{escape(str(temperature if temperature is not None else '-'))}{' °C' if temperature is not None else ''}</div></div></div>
              <div class="col-md-3"><div class="border rounded p-3 h-100"><div class="small text-secondary">Health</div><div class="h5 mb-0">{escape(str(health))}</div></div></div>
            </div>
            """
            rows = ""
            for item in apps[:20]:
                if not isinstance(item, dict):
                    continue
                rows += (
                    f"<tr><td>{escape(str(item.get('appName', item.get('packageName', ''))))}</td>"
                    f"<td><code>{escape(str(item.get('packageName', '')))}</code></td>"
                    f"<td>{escape(str(item.get('foregroundMinutes', item.get('minutes', ''))))} min</td>"
                    f"<td>{escape(str(item.get('batterySharePercent', '')))}%</td></tr>"
                )
            if not rows:
                apps_html = "<p class=\"text-secondary mb-0\">No app battery estimates in the last sync.</p>"
            else:
                apps_html = (
                    "<div class=\"table-responsive\"><table class=\"table table-sm mb-0\">"
                    "<thead><tr><th>App</th><th>Package</th><th>Screen time</th><th>Est. battery share</th></tr></thead>"
                    f"<tbody>{rows}</tbody></table></div>"
                    "<p class=\"small text-secondary mt-2 mb-0\">Per-app battery share is estimated from foreground usage time.</p>"
                )
            inner = device_card + apps_html
    return f"{updated_html}<div id=\"{element_id}\">{inner}</div>"


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "DeviceSafetyBackend/0.1"

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/login":
            self.send_html(render_login())
            return
        if path == "/forgot-password":
            self.send_html(render_forgot_password())
            return
        if path == "/reset-password":
            query = parse_qs(parsed_url.query)
            token = str(query.get("token", [""])[0]).strip()
            self.send_html(render_reset_password(token))
            return
        if path == "/logout":
            self.logout()
            return
        if path in ("/app-release-center/status.json", "/api/build-status.json"):
            self.send_json(app_release.get_build_status())
            return
        if self.is_admin_route(path) and not self.is_authenticated():
            self.require_login(path)
            return
        if path == "/":
            query = parse_qs(parsed_url.query)
            selected_filter = str(query.get("filter", ["online"])[0]).strip() or "online"
            selected_group = str(query.get("group", [""])[0]).strip()
            self.send_html(render_dashboard(read_devices(), selected_filter, selected_group))
            return
        if path == "/commands":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            status_filter = str(query.get("status", [""])[0]).strip()
            self.send_html(render_commands_history(read_all_device_commands(device_id=device_id, status_filter=status_filter)))
            return
        if path == "/commands.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            status_filter = str(query.get("status", [""])[0]).strip()
            self.send_json({"commands": read_all_device_commands(device_id=device_id, status_filter=status_filter)})
            return
        if path == "/enrollment-qr":
            self.send_html(render_enrollment_qr(build_enrollment_config()))
            return
        if path == "/enrollment/config.json":
            self.send_json(build_enrollment_config())
            return
        if path == "/server-config":
            self.send_html(render_server_config(read_server_config()))
            return
        if path == "/server-config.json":
            self.send_json(read_server_config())
            return
        if path == "/policy-config":
            self.send_html(render_policy_config(read_policy()))
            return
        if path == "/email-config":
            self.send_html(render_email_config(read_smtp_config()))
            return
        if path == "/geofence-config":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            target = f"/devices/geofence?deviceId={device_id}" if device_id else "/"
            self.send_redirect(target)
            return
        if path == "/ota-config":
            self.send_redirect("/app-release-center")
            return
        if path == "/app-release-center":
            self.send_html(render_app_release_center())
            return
        if path == "/wifi-profile-config":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            target = f"/devices/wifi-profile?deviceId={device_id}" if device_id else "/"
            self.send_redirect(target)
            return
        if path.startswith("/apk/"):
            self.serve_apk(path)
            return
        if path == "/api/update-manager/catalog":
            self.send_update_manager_catalog()
            return
        if path == "/enrollment-tokens":
            self.send_html(render_device_registration(read_pending_devices()))
            return
        if path == "/devices/provision":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            if not device_id:
                self.send_json({"error": "deviceId_required"}, status=400)
                return
            pending_token = consume_pending_device_token(device_id)
            if not pending_token:
                pending_token = redeliver_sealed_device_token(device_id)
            if pending_token:
                self.send_json({"ok": True, "deviceToken": pending_token, "registered": True})
                return
            device = get_device_by_id(device_id)
            self.send_json({
                "ok": True,
                "registered": bool(device and device.get("registered")),
                "pending": not bool(device and device.get("registered")),
            })
            return
        if path == "/policy":
            if not self.is_authenticated() and not self.request_has_valid_device_token():
                self.send_json({"error": "unauthorized_device"}, status=401)
                return
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            self.send_json(read_policy_for_device(device_id))
            return
        if path == "/health":
            self.send_json({"ok": True, "service": "device-safety-backend"})
            return
        if path == "/devices":
            devices = [decorate_device(device) for device in read_devices()]
            attach_wifi_dashboard_snapshot(devices)
            self.send_json({"devices": devices})
            return
        if path == "/devices/timeline.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            hours = str(query.get("hours", ["24"])[0]).strip()
            hours_value = int(hours) if hours.isdigit() else 24
            if not device_id:
                self.send_json({"error": "deviceId_required"}, status=400)
                return
            points = get_device_timeline(device_id, hours_value)
            self.send_json({
                "deviceId": device_id,
                "points": points,
                "chartPoints": summarize_timeline_for_chart(points),
            })
            return
        if path == "/devices/detail":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_detail(decorate_device(device), get_device_events(device_id), read_device_commands(device_id)))
            return
        if path == "/devices/detail.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            self.send_json({
                "device": decorate_device(device) if device else None,
                "events": get_device_events(device_id),
                "commands": read_device_commands(device_id),
                "usageSummaryAt": device.get("usageSummaryAt") if device else None,
                "batterySummaryAt": device.get("batterySummaryAt") if device else None,
            }, status=200 if device else 404)
            return
        if path == "/devices/notifications":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_notifications_page(decorate_device(device)))
            return
        if path == "/devices/notifications.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            search, from_ts, to_ts, category, app_name, package_name = parse_notification_filters(query)
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            decorated = decorate_device(device)
            items = get_device_notifications(
                device_id,
                search=search,
                from_ts=from_ts,
                to_ts=to_ts,
                category=category,
                app_name=app_name,
                package_name=package_name,
            )
            filters = get_device_notification_filters(device_id)
            self.send_json({
                "deviceId": device_id,
                "permissionGranted": decorated.get("notificationAccessGranted"),
                "status": decorated.get("status"),
                "from": str(query.get("from", [""])[0]).strip(),
                "to": str(query.get("to", [""])[0]).strip(),
                "category": category,
                "app": app_name,
                "package": package_name,
                "filters": filters,
                "items": items,
                "count": len(items),
            })
            return
        if path == "/devices/location":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_location_map(decorate_device(device)))
            return
        if path == "/devices/location.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            decorated = decorate_device(device)
            self.send_json(build_location_json_payload(device))
            return
        if path == "/devices/location/history.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            search, from_ts, to_ts = parse_location_history_filters(query)
            try:
                limit = int(str(query.get("limit", ["200"])[0]).strip() or 200)
            except (TypeError, ValueError):
                limit = 200
            limit = max(1, min(limit, 500))
            items = query_device_location_history(
                device_id,
                limit=limit,
                search=search,
                from_ts=from_ts,
                to_ts=to_ts,
            )
            items = geocode.enrich_location_items_with_addresses(items, cache_only=True)
            self.send_json({"ok": True, "items": items, "count": len(items)})
            return
        if path == "/devices/location/geocode.json":
            query = parse_qs(parsed_url.query)
            try:
                latitude = float(str(query.get("lat", [""])[0]).strip())
                longitude = float(str(query.get("lng", [""])[0]).strip())
            except (TypeError, ValueError):
                self.send_json({"error": "lat_lng_required"}, status=400)
                return
            address = geocode.reverse_geocode_location(latitude, longitude)
            if not address:
                self.send_json({"ok": False, "error": "Could not resolve address"}, status=502)
                return
            self.send_json({
                "ok": True,
                "latitude": latitude,
                "longitude": longitude,
                "address": address,
                "addressSummary": geocode.format_location_address_summary(address),
            })
            return
        if path == "/devices/communications":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            target = f"/devices/call-log?deviceId={device_id}" if device_id else "/"
            self.send_redirect(target)
            return
        if path == "/devices/call-log":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_call_log_page(decorate_device(device)))
            return
        if path == "/devices/call-log.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            search, from_ts, to_ts = parse_history_filters(query)
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            decorated = decorate_device(device)
            items = get_device_call_history(device_id, search=search, from_ts=from_ts, to_ts=to_ts)
            self.send_json({
                "deviceId": device_id,
                "permissionGranted": decorated.get("callLogPermissionGranted"),
                "status": decorated.get("status"),
                "from": str(query.get("from", [""])[0]).strip(),
                "to": str(query.get("to", [""])[0]).strip(),
                "items": items,
                "count": len(items),
            })
            return
        if path == "/devices/sms-history":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_sms_history_page(decorate_device(device)))
            return
        if path == "/devices/sms-history.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            search, from_ts, to_ts = parse_history_filters(query)
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            decorated = decorate_device(device)
            items = get_device_sms_history(device_id, search=search, from_ts=from_ts, to_ts=to_ts)
            self.send_json({
                "deviceId": device_id,
                "permissionGranted": decorated.get("smsPermissionGranted"),
                "status": decorated.get("status"),
                "from": str(query.get("from", [""])[0]).strip(),
                "to": str(query.get("to", [""])[0]).strip(),
                "items": items,
                "count": len(items),
            })
            return
        if path == "/devices/contacts":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_contacts_page(decorate_device(device)))
            return
        if path == "/devices/contacts.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            search, from_ts, to_ts = parse_history_filters(query)
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            decorated = decorate_device(device)
            items = get_device_contacts(device_id, search=search, from_ts=from_ts, to_ts=to_ts)
            self.send_json({
                "deviceId": device_id,
                "permissionGranted": decorated.get("contactsPermissionGranted"),
                "status": decorated.get("status"),
                "from": str(query.get("from", [""])[0]).strip(),
                "to": str(query.get("to", [""])[0]).strip(),
                "items": items,
                "count": len(items),
            })
            return
        if path == "/devices/audio":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_audio_page(decorate_device(device)))
            return
        if path == "/devices/audio/session.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            decorated = decorate_device(device)
            session = audio_stream.get_session(device_id)
            self.send_json({
                "deviceId": device_id,
                "status": decorated.get("status"),
                "permissionGranted": decorated.get("audioPermissionGranted"),
                "session": session,
                "recordings": audio_stream.list_recordings(device_id)[:10],
            })
            return
        if path == "/devices/audio/chunks.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            since = str(query.get("since", ["0"])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            since_seq = int(since) if since.isdigit() else 0
            session, items = audio_stream.get_chunks_since(device_id, since_seq)
            self.send_json({
                "deviceId": device_id,
                "session": session,
                "items": items,
                "count": len(items),
            })
            return
        if path == "/devices/audio/live.wav":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            if not device_id:
                self.send_json({"error": "deviceId_required"}, status=400)
                return
            wav_bytes = audio_stream.build_live_wav_snapshot(device_id)
            if not wav_bytes:
                self.send_json({"error": "no_audio"}, status=404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)
            return
        if path == "/devices/audio/recording":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            recording_id = str(query.get("id", [""])[0]).strip()
            file_path = audio_stream.get_recording_file(device_id, recording_id)
            if not file_path:
                self.send_json({"error": "not_found"}, status=404)
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{recording_id}.wav"')
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/devices/files":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_files_page(decorate_device(device)))
            return
        if path == "/devices/files/listing.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            path_value = str(query.get("path", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            listing = remote_ops.get_listing(device_id, path_value)
            session = remote_ops.get_session(device_id)
            decorated = decorate_device(device)
            if listing and listing.get("entries"):
                enriched_entries = []
                for entry in listing.get("entries") or []:
                    item = dict(entry)
                    if not item.get("thumbnail") and item.get("path"):
                        thumb = remote_ops.get_thumbnail(device_id, item.get("path"))
                        if thumb:
                            item["thumbnail"] = thumb.get("data")
                            item["thumbnailMime"] = thumb.get("mimeType") or "image/jpeg"
                    enriched_entries.append(item)
                listing = dict(listing)
                listing["entries"] = enriched_entries
            self.send_json({
                "deviceId": device_id,
                "status": decorated.get("status"),
                "permissionGranted": decorated.get("storagePermissionGranted"),
                "clipboard": remote_ops.get_clipboard(device_id),
                "path": remote_ops._normalize_path(path_value),
                "listing": listing,
                "session": session,
                "ready": bool(listing),
            })
            return
        if path == "/devices/files/action.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            job_id = str(query.get("jobId", [""])[0]).strip()
            if not get_device_by_id(device_id):
                self.send_json({"error": "device_not_found"}, status=404)
                return
            result = remote_ops.get_job_result(job_id)
            self.send_json({"ok": True, "jobId": job_id, "ready": bool(result), "result": result})
            return
        if path == "/devices/files/download.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            job_id = str(query.get("jobId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            download = remote_ops.get_download(job_id)
            self.send_json({
                "deviceId": device_id,
                "jobId": job_id,
                "download": download,
                "ready": bool(download and download.get("ready")),
            })
            return
        if path == "/devices/files/content":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            job_id = str(query.get("jobId", [""])[0]).strip()
            file_path = remote_ops.get_download_file(job_id)
            if not file_path:
                self.send_json({"error": "not_found"}, status=404)
                return
            meta = remote_ops.get_download(job_id) or {}
            data = file_path.read_bytes()
            filename = Path(str(meta.get("path") or file_path.name)).name or file_path.name
            self.send_response(200)
            self.send_header("Content-Type", str(meta.get("mimeType") or "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/devices/shell":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(render_device_shell_page(decorate_device(device)))
            return
        if path == "/devices/shell/history.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            since_id = str(query.get("since", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            session = remote_ops.get_session(device_id)
            items = remote_ops.get_shell_history(device_id, since_id)
            self.send_json({
                "deviceId": device_id,
                "status": decorate_device(device).get("status"),
                "session": session,
                "items": items,
                "count": len(items),
            })
            return
        if path == "/devices/remote/jobs.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            if not device_token_valid(device_id, get_device_token_from_headers(self)):
                self.send_json({"error": "unauthorized_device"}, status=401)
                return
            jobs = remote_ops.fetch_pending_jobs(device_id)
            session = remote_ops.get_session(device_id)
            self.send_json({
                "ok": True,
                "deviceId": device_id,
                "jobs": jobs,
                "sessionRequested": session.get("requested"),
                "sessionActive": session.get("active"),
            })
            return
        if path == "/devices/remote/upload.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            upload_id = str(query.get("uploadId", [""])[0]).strip()
            if not device_token_valid(device_id, get_device_token_from_headers(self)):
                self.send_json({"error": "unauthorized_device"}, status=401)
                return
            upload = remote_ops.consume_upload(upload_id)
            if not upload:
                self.send_json({"error": "upload_not_found"}, status=404)
                return
            if str(upload.get("destPath") or "").strip() and device_id:
                pass
            self.send_json({"ok": True, **upload})
            return
        if path == "/devices/commands":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            if not device_token_valid(device_id, get_device_token_from_headers(self)):
                self.send_json({"error": "unauthorized_device"}, status=401)
                return
            commands = fetch_pending_commands(device_id)
            self.send_json({"ok": True, "commands": commands})
            return
        if path == "/devices/status":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            if not device_token_valid(device_id, get_device_token_from_headers(self)):
                self.send_json({"error": "unauthorized_device"}, status=401)
                return
            devices = read_devices()
            device = next((item for item in devices if item.get("deviceId") == device_id), None)
            if device:
                was_registered = bool(device.get("registered"))
                device["registered"] = True
                device["deregisteredAt"] = None
                device["pendingDeviceToken"] = None
                device["lastSeenAt"] = int(time.time())
                write_devices(devices)
                record_device_event(device_id, "heartbeat", "Device checked in")
                if not was_registered:
                    record_device_event(device_id, "registered", "Device authenticated with token")
                record_status_transition(device_id, device)
            self.send_json({
                "registered": bool(device and device.get("registered")),
                "online": is_online(device) if device else False,
                "device": decorate_device(device) if device else None,
                "appLocked": bool(device and device.get("appLocked")),
                "appHidden": bool(device and device.get("appHidden")),
            })
            return
        if path == "/devices/security/state.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            if not device_token_valid(device_id, get_device_token_from_headers(self)):
                self.send_json({"error": "unauthorized_device"}, status=401)
                return
            state = get_device_security_state(device_id)
            if not state:
                self.send_json({"error": "device_not_found"}, status=404)
                return
            self.send_json({"ok": True, **state})
            return
        if path == "/devices/security/request.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            request_id = int(query.get("requestId", ["0"])[0] or 0)
            if not device_token_valid(device_id, get_device_token_from_headers(self)):
                self.send_json({"error": "unauthorized_device"}, status=401)
                return
            with db_connect() as connection:
                request = security_control.get_request_by_id(connection, request_id) if request_id else None
                if not request or request.get("deviceId") != device_id:
                    self.send_json({"error": "request_not_found"}, status=404)
                    return
                if request.get("status") == "approved":
                    otp_code = security_control.get_device_otp(connection, request_id, device_id)
                    if otp_code:
                        request = dict(request)
                        request["otpCode"] = otp_code
            self.send_json({"ok": True, "request": request})
            return
        if path == "/devices/security":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            with db_connect() as connection:
                requests = security_control.list_requests(connection, device_id)
            self.send_html(render_device_security_page(decorate_device(device), requests))
            return
        if path == "/devices/geofence":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(
                render_device_geofence_page(
                    decorate_device(device),
                    read_device_geofence_config(device_id),
                )
            )
            return
        if path == "/devices/wifi-profile":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            if not device:
                self.send_html(render_not_found("Device not found"), status=404)
                return
            self.send_html(
                render_device_wifi_profile_page(
                    decorate_device(device),
                    read_device_wifi_profile_config(device_id),
                )
            )
            return
        if path == "/devices/wifi-suggestions.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            self.send_json({"ok": True, "suggestions": read_wifi_suggestions_for_device(device_id)})
            return
        if path == "/devices/security/requests.json":
            query = parse_qs(parsed_url.query)
            device_id = str(query.get("deviceId", [""])[0]).strip()
            device = get_device_by_id(device_id)
            with db_connect() as connection:
                requests = security_control.list_requests(connection, device_id)
            self.send_json({
                "ok": True,
                "requests": requests,
                "device": decorate_device(device) if device else None,
            })
            return
        self.send_json({"error": "not_found"}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/login":
            self.login()
            return
        if path == "/forgot-password":
            self.request_password_reset()
            return
        if path == "/reset-password":
            self.reset_password()
            return
        if self.is_admin_route(path) and not self.is_authenticated():
            self.require_login(path)
            return
        if path == "/devices/register":
            self.send_json({"error": "registration_from_app_disabled"}, status=403)
            return
        if path == "/devices/checkin":
            self.device_checkin()
            return
        if path == "/devices/deregister":
            self.deregister_device()
            return
        if path == "/devices/delete":
            self.delete_device()
            return
        if path == "/devices/commands/complete":
            self.complete_device_command_handler()
            return
        if path == "/devices/telemetry":
            self.device_telemetry()
            return
        if path == "/devices/security/request":
            self.device_security_request()
            return
        if path == "/devices/security/verify":
            self.device_security_verify()
            return
        if path == "/devices/security/approve":
            self.admin_security_approve()
            return
        if path == "/devices/security/reject":
            self.admin_security_reject()
            return
        if path == "/devices/audio/chunk":
            self.device_audio_chunk()
            return
        if path == "/devices/bulk-action":
            self.admin_bulk_action()
            return
        if path == "/devices/usage/refresh":
            self.admin_refresh_usage()
            return
        if path == "/devices/set-group":
            self.admin_set_device_group()
            return
        if path == "/devices/send-command":
            self.admin_send_command()
            return
        if path == "/devices/audio/control":
            self.admin_audio_control()
            return
        if path == "/devices/files/control":
            self.admin_files_control()
            return
        if path == "/devices/files/upload":
            self.admin_files_upload()
            return
        if path == "/devices/shell/exec":
            self.admin_shell_exec()
            return
        if path == "/devices/remote/jobs/complete":
            self.device_remote_job_complete()
            return
        if path == "/server-config":
            self.save_server_config()
            return
        if path == "/policy-config":
            self.save_policy_config()
            return
        if path == "/email-config":
            self.save_email_config()
            return
        if path == "/email-config/test":
            self.send_test_email_config()
            return
        if path == "/geofence-config":
            self.send_redirect("/")
            return
        if path == "/ota-config":
            self.send_redirect("/app-release-center")
            return
        if path == "/devices/geofence":
            self.save_device_geofence_config()
            return
        if path == "/devices/wifi-profile":
            self.save_device_wifi_profile_config()
            return
        if path == "/app-release-center/build":
            self.app_release_build()
            return
        if path == "/app-release-center/build-push":
            self.app_release_build_push()
            return
        if path == "/app-release-center/build-installer":
            self.app_release_build_installer()
            return
        if path == "/app-release-center/push":
            self.app_release_push()
            return
        if path == "/app-release-center/register":
            self.app_release_register()
            return
        if path == "/app-release-center/push-release":
            self.app_release_push_release()
            return
        if path == "/app-release-center/delete-releases":
            self.app_release_delete_releases()
            return
        if path == "/wifi-profile-config":
            self.send_redirect("/")
            return
        if path == "/enrollment-tokens":
            self.admin_register_device()
            return
        self.send_json({"error": "not_found"}, status=404)

    def is_admin_route(self, path):
        return path in {
            "/",
            "/devices",
            "/devices/detail",
            "/devices/detail.json",
            "/devices/location",
            "/devices/location.json",
            "/devices/location/history.json",
            "/devices/location/geocode.json",
            "/devices/call-log",
            "/devices/call-log.json",
            "/devices/sms-history",
            "/devices/sms-history.json",
            "/devices/contacts",
            "/devices/contacts.json",
            "/devices/audio",
            "/devices/audio/session.json",
            "/devices/audio/chunks.json",
            "/devices/audio/live.wav",
            "/devices/audio/recording",
            "/devices/audio/control",
            "/devices/files",
            "/devices/files/listing.json",
            "/devices/files/download.json",
            "/devices/files/content",
            "/devices/files/control",
            "/devices/files/upload",
            "/devices/files/action.json",
            "/devices/shell",
            "/devices/shell/history.json",
            "/devices/shell/exec",
            "/devices/communications",
            "/devices/timeline.json",
            "/commands",
            "/commands.json",
            "/enrollment-qr",
            "/server-config",
            "/server-config.json",
            "/policy-config",
            "/email-config",
            "/email-config/test",
            "/app-release-center",
            "/app-release-center/build",
            "/app-release-center/build-push",
            "/app-release-center/build-installer",
            "/app-release-center/push",
            "/app-release-center/push-release",
            "/app-release-center/delete-releases",
            "/app-release-center/register",
            "/devices/geofence",
            "/devices/wifi-profile",
            "/devices/wifi-suggestions.json",
            "/enrollment-tokens",
            "/devices/send-command",
            "/devices/bulk-action",
            "/devices/set-group",
            "/devices/security",
            "/devices/security/requests.json",
            "/devices/security/approve",
            "/devices/security/reject",
            "/devices/notifications",
            "/devices/notifications.json",
            "/devices/usage/refresh",
        }

    def login(self):
        body = self.read_form_body()
        username = str(body.get("username", [""])[0]).strip()
        password = str(body.get("password", [""])[0])
        admin = read_admin()
        if username == admin["username"] and password_matches(password):
            session_id = secrets.token_urlsafe(32)
            SESSIONS.add(session_id)
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"admin_session={session_id}; HttpOnly; SameSite=Lax; Path=/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_html(render_login("Invalid username or password."), status=401)

    def request_password_reset(self):
        body = self.read_form_body()
        username = str(body.get("username", [""])[0]).strip()
        admin = read_admin()
        # Return a generic response so username discovery is not possible.
        generic_message = "If email settings are configured and the username is valid, a reset link has been sent."
        if username == admin["username"]:
            token = create_reset_token(username)
            host = self.headers.get("Host", "127.0.0.1:8080")
            reset_url = f"http://{host}/reset-password?token={token}"
            try:
                send_password_reset_email(reset_url)
            except Exception as exc:
                self.send_html(render_forgot_password(f"Could not send reset email: {exc}"), status=500)
                return
        self.send_html(render_forgot_password(generic_message))

    def reset_password(self):
        body = self.read_form_body()
        token = str(body.get("token", [""])[0]).strip()
        password = str(body.get("password", [""])[0])
        confirm_password = str(body.get("confirmPassword", [""])[0])
        if not token:
            self.send_html(render_reset_password("", "Reset token is required."), status=400)
            return
        if len(password) < 8:
            self.send_html(render_reset_password(token, "Password must be at least 8 characters."), status=400)
            return
        if password != confirm_password:
            self.send_html(render_reset_password(token, "Passwords do not match."), status=400)
            return
        token_record = consume_reset_token(token)
        if not token_record:
            self.send_html(render_reset_password("", "Reset token is invalid or expired."), status=400)
            return
        set_admin_password(password)
        SESSIONS.clear()
        self.send_html(render_login("Password reset successful. Please login with the new password."))

    def logout(self):
        session_id = self.get_session_id()
        if session_id in SESSIONS:
            SESSIONS.remove(session_id)
        self.send_response(303)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", "admin_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def is_authenticated(self):
        return self.get_session_id() in SESSIONS

    def request_has_valid_device_token(self):
        parsed_url = urlparse(self.path)
        query = parse_qs(parsed_url.query)
        device_id = str(query.get("deviceId", [""])[0]).strip()
        return device_token_valid(device_id, get_device_token_from_headers(self))

    def get_session_id(self):
        cookie_header = self.headers.get("Cookie", "")
        for cookie in cookie_header.split(";"):
            name, _, value = cookie.strip().partition("=")
            if name == "admin_session":
                return value
        return ""

    def require_login(self, path):
        accept = self.headers.get("Accept", "")
        if path.endswith(".json") or "application/json" in accept:
            self.send_json({"error": "unauthorized"}, status=401)
            return
        self.send_redirect("/login")

    def device_checkin(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        result = upsert_device_checkin(body, get_device_token_from_headers(self))
        if not result:
            self.send_json({"error": "deviceId_and_model_required"}, status=400)
            return
        self.send_json({"ok": True, **result})

    def admin_register_device(self):
        body = self.read_form_body()
        device_id = str(body.get("deviceId", [""])[0]).strip()
        token, error = admin_register_and_push_token(device_id)
        if error == "device_not_found":
            self.send_html(
                render_device_registration(read_pending_devices(), f"Device ID {device_id} was not found. Ask the app to check in first."),
                status=404,
            )
            return
        if error:
            self.send_html(render_device_registration(read_pending_devices(), "Device ID is required."), status=400)
            return
        message = f"Token pushed to device {device_id}. The same stored token is reused when available."
        self.send_html(render_device_registration(read_pending_devices(), message))

    def admin_send_command(self):
        body = self.read_form_body()
        device_id = str(body.get("deviceId", [""])[0]).strip()
        command_type = str(body.get("commandType", [""])[0]).strip()
        payload = str(body.get("payload", [""])[0]).strip()
        return_to = str(body.get("returnTo", [""])[0]).strip()
        allowed = {
            "sync_policy",
            "show_alert",
            "request_device_admin",
            "push_server_config",
            "security_lock_prompt",
            "push_app_update",
            "push_wifi_profile",
            "enable_wifi",
            "enable_location",
            "scan_wifi",
            "start_audio_stream",
            "stop_audio_stream",
            "start_remote_session",
            "stop_remote_session",
            "lock_app",
            "hide_app",
            "show_app",
            "unlock_app",
            "refresh_telemetry",
        }
        if not device_id or command_type not in allowed:
            device = get_device_by_id(device_id) if device_id else None
            if device:
                self.send_html(
                    self.render_command_result_page(
                        device_id,
                        return_to,
                        decorate_device(device),
                        "Invalid command type.",
                        is_error=True,
                    ),
                    status=400,
                )
            else:
                self.send_html(render_not_found("Device not found"), status=404)
            return
        if command_type == "show_alert" and not payload:
            device = get_device_by_id(device_id)
            self.send_html(
                self.render_command_result_page(
                    device_id,
                    return_to,
                    decorate_device(device),
                    "Alert message is required.",
                    is_error=True,
                ),
                status=400,
            )
            return
        if command_type == "push_server_config":
            remote_config = read_server_config()
            payload = json.dumps(
                {
                    "mode": "remote",
                    "host": remote_config["host"],
                    "port": remote_config["port"],
                }
            )
        if command_type == "push_app_update":
            payload = json.dumps(build_ota_payload())
        if command_type == "push_wifi_profile" and not payload:
            wifi_config = read_device_wifi_profile_config(device_id)
            if not str(wifi_config.get("ssid", "")).strip():
                self.send_html(
                    render_not_found("Save a Wi-Fi profile for this device before pushing."),
                    status=400,
                )
                return
            payload = json.dumps(wifi_config)
        if not get_device_by_id(device_id):
            self.send_html(render_not_found("Device not found"), status=404)
            return
        if command_type in {"lock_app", "hide_app", "show_app", "unlock_app"}:
            apply_admin_security_command(device_id, command_type)
        create_device_command(device_id, command_type, payload)
        device = get_device_by_id(device_id)
        self.send_html(
            self.render_command_result_page(
                device_id,
                return_to,
                decorate_device(device),
                f"Command '{command_type}' queued.",
            )
        )

    def render_command_result_page(self, device_id, return_to, device, message, is_error=False):
        if return_to.startswith("/devices/security") and device:
            with db_connect() as connection:
                requests = security_control.list_requests(connection, device_id)
            return render_device_security_page(device, requests, message)
        if return_to.startswith("/devices/geofence") and device:
            return render_device_geofence_page(device, read_device_geofence_config(device_id), message)
        if return_to.startswith("/devices/wifi-profile") and device:
            alert = "alert-warning" if is_error or "failed" in message.lower() else "alert-success"
            return render_device_wifi_profile_page(
                device,
                read_device_wifi_profile_config(device_id),
                message,
                alert_class=alert,
            )
        return render_device_detail(device, get_device_events(device_id), read_device_commands(device_id), message)

    def admin_bulk_action(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_ids = body.get("deviceIds") or []
        if isinstance(device_ids, str):
            device_ids = [device_ids]
        action = str(body.get("action", "")).strip()
        payload = str(body.get("payload", "")).strip()
        group_name = str(body.get("group", "")).strip()
        if not device_ids or not action:
            self.send_json({"error": "deviceIds_and_action_required"}, status=400)
            return
        results = perform_bulk_device_action(device_ids, action, payload, group_name)
        self.send_json({"ok": True, "results": results})

    def admin_refresh_usage(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        if not device_id:
            self.send_json({"error": "deviceId_required"}, status=400)
            return
        if not get_device_by_id(device_id):
            self.send_json({"error": "device_not_found"}, status=404)
            return
        command_id = create_device_command(device_id, "refresh_telemetry", "")
        self.send_json({"ok": True, "commandId": command_id, "message": "Live usage refresh queued"})

    def admin_set_device_group(self):
        body = self.read_form_body()
        device_id = str(body.get("deviceId", [""])[0]).strip()
        group_name = str(body.get("group", [""])[0]).strip()
        if not device_id:
            self.send_json({"error": "deviceId_required"}, status=400)
            return
        if not update_device_group(device_id, group_name):
            self.send_json({"error": "device_not_found"}, status=404)
            return
        self.send_redirect(f"/devices/detail?deviceId={device_id}")

    def complete_device_command_handler(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        command_id = int(body.get("commandId") or 0)
        status = str(body.get("status", "completed")).strip() or "completed"
        result = str(body.get("result", "")).strip()
        if not device_id or not command_id:
            self.send_json({"error": "deviceId_and_commandId_required"}, status=400)
            return
        if not device_token_valid(device_id, get_device_token_from_headers(self)):
            self.send_json({"error": "unauthorized_device"}, status=401)
            return
        if not complete_device_command(device_id, command_id, status, result):
            self.send_json({"error": "command_not_found"}, status=404)
            return
        self.send_json({"ok": True})

    def device_telemetry(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        if not device_id:
            self.send_json({"error": "deviceId_required"}, status=400)
            return
        if not device_token_valid(device_id, get_device_token_from_headers(self)):
            self.send_json({"error": "unauthorized_device"}, status=401)
            return
        update_device_telemetry_from_body(device_id, body)
        self.send_json({"ok": True})

    def device_security_request(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        action_type = str(body.get("actionType", "")).strip()
        if not device_id or not action_type:
            self.send_json({"error": "deviceId_and_actionType_required"}, status=400)
            return
        if not device_token_valid(device_id, get_device_token_from_headers(self)):
            self.send_json({"error": "unauthorized_device"}, status=401)
            return
        if not get_device_by_id(device_id):
            self.send_json({"error": "device_not_found"}, status=404)
            return
        with db_connect() as connection:
            request, error = security_control.create_otp_request(connection, device_id, action_type)
        if error:
            self.send_json({"error": error}, status=400)
            return
        send_admin_notification_email(
            "Device Safety: security action approval needed",
            "A device requested a protected security action.\n\n"
            f"Device ID: {device_id}\n"
            f"Action: {SECURITY_ACTION_LABELS.get(action_type, action_type)}\n"
            f"Request ID: {request['id']}\n\n"
            "Open the device Security page on the dashboard to approve or reject.",
        )
        self.send_json({"ok": True, "request": request})

    def device_security_verify(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        request_id = int(body.get("requestId") or 0)
        otp_code = str(body.get("otp", "")).strip()
        if not device_id or not request_id:
            self.send_json({"error": "deviceId_and_requestId_required"}, status=400)
            return
        if not device_token_valid(device_id, get_device_token_from_headers(self)):
            self.send_json({"error": "unauthorized_device"}, status=401)
            return
        with db_connect() as connection:
            verified, error = security_control.verify_request_otp(connection, device_id, request_id, otp_code)
        if error:
            self.send_json({"error": error}, status=400)
            return
        action_type = verified.get("actionType")
        if action_type == "unlock":
            set_device_security_flags(device_id, app_locked=False)
        elif action_type == "unhide":
            set_device_security_flags(device_id, app_hidden=False)
        elif action_type == "hide":
            set_device_security_flags(device_id, app_hidden=True)
        elif action_type == "lock":
            set_device_security_flags(device_id, app_locked=True)
        self.send_json({"ok": True, "verified": verified})

    def admin_security_approve(self):
        body = self.read_form_body()
        request_id = int(str(body.get("requestId", ["0"])[0]).strip() or 0)
        device_id = str(body.get("deviceId", [""])[0]).strip()
        with db_connect() as connection:
            approved, error = security_control.approve_request(connection, request_id)
        if error:
            device = get_device_by_id(device_id)
            if device:
                with db_connect() as connection:
                    requests = security_control.list_requests(connection, device_id)
                self.send_html(
                    render_device_security_page(decorate_device(device), requests, "Could not approve request."),
                    status=400,
                )
            else:
                self.send_json({"error": error}, status=400)
            return
        emailed, email_error = send_security_otp_email(approved["deviceId"], approved["actionType"], approved["otpCode"])
        if emailed:
            message = "Request approved. OTP sent to the device and emailed to admin."
        elif email_error:
            message = f"Request approved. OTP sent to the device, but email failed: {email_error}"
        else:
            message = "Request approved. OTP sent to the device."
        device = get_device_by_id(device_id or approved["deviceId"])
        with db_connect() as connection:
            requests = security_control.list_requests(connection, device_id or approved["deviceId"])
        self.send_html(render_device_security_page(decorate_device(device), requests, message))

    def admin_security_reject(self):
        body = self.read_form_body()
        request_id = int(str(body.get("requestId", ["0"])[0]).strip() or 0)
        device_id = str(body.get("deviceId", [""])[0]).strip()
        with db_connect() as connection:
            rejected = security_control.reject_request(connection, request_id)
        device = get_device_by_id(device_id)
        with db_connect() as connection:
            requests = security_control.list_requests(connection, device_id)
        message = "Request rejected." if rejected else "Request could not be rejected."
        self.send_html(render_device_security_page(decorate_device(device), requests, message))

    def device_audio_chunk(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        if not device_id:
            self.send_json({"error": "deviceId_required"}, status=400)
            return
        if not device_token_valid(device_id, get_device_token_from_headers(self)):
            self.send_json({"error": "unauthorized_device"}, status=401)
            return
        try:
            pcm = base64.b64decode(str(body.get("data", "")))
        except (ValueError, TypeError):
            self.send_json({"error": "invalid_audio_data"}, status=400)
            return
        seq = int(body.get("seq") or 0)
        audio_stream.append_chunk(
            device_id,
            seq,
            pcm,
            sample_rate=int(body.get("sampleRate") or audio_stream.SAMPLE_RATE),
            channels=int(body.get("channels") or audio_stream.CHANNELS),
            fmt=str(body.get("format") or "pcm16le"),
        )
        update_device_telemetry_from_body(
            device_id,
            {
                "audioStreamActive": True,
                "audioPermissionGranted": True,
            },
        )
        self.send_json({"ok": True, "seq": seq})

    def admin_audio_control(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        action = str(body.get("action", "")).strip().lower()
        device = get_device_by_id(device_id)
        if not device:
            self.send_json({"error": "device_not_found"}, status=404)
            return
        if action == "start":
            audio_stream.request_stream(device_id, True)
            create_device_command(device_id, "start_audio_stream", "")
            self.send_json({"ok": True, "message": "Live audio stream requested. Device will start on next sync."})
            return
        if action == "stop":
            audio_stream.stop_stream(device_id)
            create_device_command(device_id, "stop_audio_stream", "")
            update_device_telemetry_from_body(device_id, {"audioStreamActive": False})
            self.send_json({"ok": True, "message": "Live audio stream stop requested."})
            return
        if action == "record_start":
            meta = audio_stream.start_server_recording(device_id)
            self.send_json({"ok": True, "recording": meta})
            return
        if action == "record_stop":
            finished = audio_stream.stop_server_recording(device_id)
            if not finished:
                self.send_json({"error": "no_active_recording"}, status=400)
                return
            self.send_json({"ok": True, "recording": finished})
            return
        self.send_json({"error": "invalid_action"}, status=400)

    def ensure_remote_session(self, device_id):
        remote_ops.request_session(device_id, True)
        create_device_command(device_id, "start_remote_session", "")

    def admin_files_control(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        action = str(body.get("action", "")).strip().lower()
        device = get_device_by_id(device_id)
        if not device:
            self.send_json({"error": "device_not_found"}, status=404)
            return
        if action == "start_session":
            self.ensure_remote_session(device_id)
            self.send_json({"ok": True, "message": "Remote session requested on device."})
            return
        if action == "stop_session":
            remote_ops.stop_session(device_id)
            create_device_command(device_id, "stop_remote_session", "")
            self.send_json({"ok": True, "message": "Remote session stop requested."})
            return
        if action == "list":
            path_value = str(body.get("path", "/storage/emulated/0")).strip()
            job_id, normalized = remote_ops.queue_list_dir(device_id, path_value)
            self.ensure_remote_session(device_id)
            self.send_json({"ok": True, "jobId": job_id, "path": normalized})
            return
        if action == "download":
            path_value = str(body.get("path", "")).strip()
            if not path_value:
                self.send_json({"error": "path_required"}, status=400)
                return
            job_id, normalized = remote_ops.queue_read_file(device_id, path_value)
            self.ensure_remote_session(device_id)
            self.send_json({"ok": True, "jobId": job_id, "path": normalized})
            return
        if action == "copy":
            paths = body.get("paths") or []
            clip = remote_ops.set_clipboard(device_id, "copy", paths)
            if not clip:
                self.send_json({"error": "paths_required"}, status=400)
                return
            self.send_json({"ok": True, "clipboard": clip})
            return
        if action == "cut":
            paths = body.get("paths") or []
            clip = remote_ops.set_clipboard(device_id, "cut", paths)
            if not clip:
                self.send_json({"error": "paths_required"}, status=400)
                return
            self.send_json({"ok": True, "clipboard": clip})
            return
        if action == "paste":
            dest_path = str(body.get("path", "")).strip()
            if not dest_path:
                self.send_json({"error": "path_required"}, status=400)
                return
            clip = remote_ops.get_clipboard(device_id)
            paths = clip.get("paths") or []
            if not paths:
                self.send_json({"error": "clipboard_empty"}, status=400)
                return
            mode = str(clip.get("mode") or "copy").strip().lower()
            file_action = "move" if mode == "cut" else "copy"
            job_id = remote_ops.queue_file_action(device_id, file_action, paths, dest_path)
            self.ensure_remote_session(device_id)
            if mode == "cut":
                remote_ops.clear_clipboard(device_id)
            self.send_json({"ok": True, "jobId": job_id, "action": file_action, "count": len(paths)})
            return
        if action == "delete":
            paths = body.get("paths") or []
            job_id = remote_ops.queue_file_action(device_id, "delete", paths)
            if not job_id:
                self.send_json({"error": "paths_required"}, status=400)
                return
            self.ensure_remote_session(device_id)
            self.send_json({"ok": True, "jobId": job_id, "count": len(paths)})
            return
        if action == "move":
            paths = body.get("paths") or []
            dest_path = str(body.get("destPath", body.get("path", ""))).strip()
            if not dest_path:
                self.send_json({"error": "destPath_required"}, status=400)
                return
            job_id = remote_ops.queue_file_action(device_id, "move", paths, dest_path)
            if not job_id:
                self.send_json({"error": "paths_required"}, status=400)
                return
            self.ensure_remote_session(device_id)
            self.send_json({"ok": True, "jobId": job_id, "count": len(paths), "destPath": dest_path})
            return
        self.send_json({"error": "invalid_action"}, status=400)

    def admin_files_upload(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        dest_path = str(body.get("path", "")).strip()
        filename = str(body.get("filename", "")).strip()
        data_b64 = str(body.get("data", "")).strip()
        if not device_id or not dest_path or not data_b64:
            self.send_json({"error": "deviceId_path_and_data_required"}, status=400)
            return
        if not get_device_by_id(device_id):
            self.send_json({"error": "device_not_found"}, status=404)
            return
        try:
            file_bytes = base64.b64decode(data_b64)
        except (ValueError, TypeError):
            self.send_json({"error": "invalid_base64_data"}, status=400)
            return
        upload_id, error = remote_ops.stage_upload(device_id, dest_path, file_bytes, filename)
        if error:
            self.send_json({"error": error}, status=400)
            return
        job_id, normalized = remote_ops.queue_write_file(device_id, dest_path, upload_id)
        self.ensure_remote_session(device_id)
        self.send_json({"ok": True, "uploadId": upload_id, "jobId": job_id, "path": normalized})

    def admin_shell_exec(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        command = str(body.get("command", "")).strip()
        if not device_id or not command:
            self.send_json({"error": "deviceId_and_command_required"}, status=400)
            return
        if not get_device_by_id(device_id):
            self.send_json({"error": "device_not_found"}, status=404)
            return
        job_id = remote_ops.queue_shell_exec(device_id, command)
        self.ensure_remote_session(device_id)
        self.send_json({"ok": True, "jobId": job_id})

    def device_remote_job_complete(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return
        device_id = str(body.get("deviceId", "")).strip()
        job_id = str(body.get("jobId", "")).strip()
        if not device_id or not job_id:
            self.send_json({"error": "deviceId_and_jobId_required"}, status=400)
            return
        if not device_token_valid(device_id, get_device_token_from_headers(self)):
            self.send_json({"error": "unauthorized_device"}, status=401)
            return
        success = bool(body.get("ok"))
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        error = str(body.get("error", "")).strip()
        if not remote_ops.complete_job(device_id, job_id, success, result, error):
            self.send_json({"error": "job_not_found"}, status=404)
            return
        self.send_json({"ok": True})

    def serve_apk(self, path):
        filename = Path(path).name
        if not filename.endswith(".apk") or ".." in filename or "/" in filename.strip("/"):
            self.send_json({"error": "not_found"}, status=404)
            return
        file_path = ROOT.parent / "apk" / filename
        if not file_path.exists():
            self.send_json({"error": "not_found"}, status=404)
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.android.package-archive")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def save_device_geofence_config(self):
        body = self.read_form_body()
        device_id = str(body.get("deviceId", [""])[0]).strip()
        device = get_device_by_id(device_id)
        if not device:
            self.send_html(render_not_found("Device not found"), status=404)
            return
        raw_json = str(body.get("geofenceJson", [""])[0]).strip()
        try:
            parsed = json.loads(raw_json) if raw_json else {}
        except json.JSONDecodeError:
            parsed = {}
        write_device_geofence_config(device_id, parsed)
        self.send_html(
            render_device_geofence_page(
                decorate_device(device),
                read_device_geofence_config(device_id),
                "Geofence settings saved for this device.",
            )
        )

    def save_device_wifi_profile_config(self):
        body = self.read_form_body()
        device_id = str(body.get("deviceId", [""])[0]).strip()
        device = get_device_by_id(device_id)
        if not device:
            self.send_html(render_not_found("Device not found"), status=404)
            return
        existing = read_device_wifi_profile_config(device_id)
        password = str(body.get("password", [""])[0])
        config = {
            "ssid": str(body.get("ssid", [""])[0]).strip(),
            "password": password if password else existing.get("password", ""),
            "security": str(body.get("security", ["WPA"])[0]).strip() or "WPA",
        }
        write_device_wifi_profile_config(device_id, config)
        message = "Wi-Fi profile saved for this device."
        if str(body.get("pushNow", [""])[0]) == "on":
            if not config.get("ssid"):
                message = "SSID is required before pushing to the device."
            else:
                create_device_command(device_id, "push_wifi_profile", json.dumps(config))
                message = "Wi-Fi profile saved and push command queued."
        self.send_html(
            render_device_wifi_profile_page(
                decorate_device(device),
                read_device_wifi_profile_config(device_id),
                message,
            )
        )

    def app_release_build(self):
        body = self.read_form_body()
        version_name = str(body.get("versionName", [""])[0]).strip()
        version_code = str(body.get("versionCode", [""])[0]).strip()
        if not version_name or not version_code.isdigit():
            self.send_html(render_app_release_center("Version name and numeric version code are required."))
            return
        ok, message = app_release.start_build(
            version_code,
            version_name,
            auto_register=False,
            auto_push=False,
        )
        self.send_html(render_app_release_center(message))

    def app_release_build_installer(self):
        body = self.read_form_body()
        auto_bump = str(body.get("autoBump", ["on"])[0]).strip().lower() in ("on", "1", "true", "yes")
        release_notes = str(body.get("releaseNotes", [""])[0]).strip()
        ok, message = app_release.start_installer_build(
            auto_bump=auto_bump,
            release_notes=release_notes or "Orphen APK Installer — built from server UI",
        )
        self.send_html(render_app_release_center(message, building=ok, detail=message if ok else ""))

    def app_release_build_push(self):
        body = self.read_form_body()
        release_notes = str(body.get("releaseNotes", [""])[0]).strip()
        package_name = str(body.get("packageName", ["com.orphen.devicesafety"])[0]).strip()
        app_label = str(body.get("appLabel", ["Orphen Device Safety"])[0]).strip()
        auto_bump = str(body.get("autoBump", ["on"])[0]).strip().lower() in ("on", "1", "true", "yes")
        version_name = str(body.get("versionName", [""])[0]).strip()
        version_code = str(body.get("versionCode", [""])[0]).strip()
        ok, message, vc, vn = app_release.start_build_and_push(
            create_device_command,
            read_devices,
            auto_bump=auto_bump,
            version_code=version_code,
            version_name=version_name,
            release_notes=release_notes,
            package_name=package_name,
            app_label=app_label,
        )
        detail = f"Building v{vn} ({vc}). Refresh this page — status updates automatically."
        self.send_html(render_app_release_center(message if ok else message, building=ok, detail=detail))

    def app_release_register(self):
        body = self.read_form_body()
        package_name = str(body.get("packageName", ["com.orphen.devicesafety"])[0]).strip()
        app_label = str(body.get("appLabel", ["Orphen Device Safety"])[0]).strip()
        version_name = str(body.get("versionName", [""])[0]).strip()
        version_code = str(body.get("versionCode", [""])[0]).strip()
        release_notes = str(body.get("releaseNotes", [""])[0]).strip()
        apk_filename = "dsm.apk"
        apk_path = ROOT.parent / "apk" / apk_filename
        if not apk_path.is_file():
            for legacy in ("device-safety-manager-debug.apk",):
                legacy_path = ROOT.parent / "apk" / legacy
                if legacy_path.is_file():
                    apk_path = legacy_path
                    break
        if not version_name or not version_code.isdigit():
            self.send_html(render_app_release_center("Version name and version code required."))
            return
        if not apk_path.is_file():
            self.send_html(render_app_release_center("APK not found. Run Build APK first."))
            return
        with db_connect() as connection:
            app_release.register_release(
                connection,
                package_name,
                app_label,
                version_name,
                version_code,
                release_notes,
                apk_filename,
            )
            connection.commit()
        config = {
            "version": version_name,
            "apkUrl": "",
            "releaseNotes": release_notes,
        }
        write_ota_config(config)
        self.send_html(render_app_release_center(f"Registered release {version_name} and updated OTA settings."))

    def app_release_push(self):
        body = self.read_form_body()
        package_name = str(body.get("packageName", ["com.orphen.devicesafety"])[0]).strip()
        server = read_server_config()
        with db_connect() as connection:
            row = connection.execute(
                "SELECT * FROM app_releases WHERE package_name = ? AND active = 1 ORDER BY version_code DESC LIMIT 1",
                (package_name,),
            ).fetchone()
        if not row:
            self.send_html(render_app_release_center("No active release. Build and register first."))
            return
        payload = app_release.build_ota_payload_for_release(
            server["host"],
            server["port"],
            row["version_name"],
            row["version_code"],
            row["release_notes"],
            row["apk_filename"],
        )
        write_ota_config(
            {
                "version": row["version_name"],
                "apkUrl": payload["apkUrl"],
                "releaseNotes": row["release_notes"],
            }
        )
        queued = app_release.queue_push_to_devices(
            create_device_command,
            read_devices,
            package_name,
            payload,
        )
        self.send_html(
            render_app_release_center(f"Queued push_app_update for {len(queued)} device(s).")
        )

    def app_release_push_release(self):
        body = self.read_form_body()
        release_id = str(body.get("releaseId", [""])[0]).strip()
        if not release_id.isdigit():
            self.send_html(render_app_release_center("Invalid release selected."))
            return
        server = read_server_config()
        with db_connect() as connection:
            queued, error = app_release.push_release_to_devices(
                connection,
                release_id,
                server["host"],
                server["port"],
                create_device_command,
                read_devices,
            )
            connection.commit()
        if error:
            self.send_html(render_app_release_center(error))
            return
        row = None
        with db_connect() as connection:
            row = app_release.get_release_by_id(connection, release_id)
        if row:
            payload = app_release.build_ota_payload_for_release(
                server["host"],
                server["port"],
                row["version_name"],
                row["version_code"],
                row["release_notes"],
                row["apk_filename"],
            )
            write_ota_config(
                {
                    "version": row["version_name"],
                    "apkUrl": payload["apkUrl"],
                    "releaseNotes": row["release_notes"],
                }
            )
        self.send_html(
            render_app_release_center(
                f"Pushed v{row['version_name']} ({row['version_code']}) to {len(queued)} device(s)."
                if row
                else f"Queued push_app_update for {len(queued)} device(s)."
            )
        )

    def app_release_delete_releases(self):
        body = self.read_form_body()
        release_ids = body.get("releaseIds") or []
        if isinstance(release_ids, str):
            release_ids = [release_ids]
        release_ids = [str(value).strip() for value in release_ids if str(value).strip()]
        if not release_ids:
            self.send_html(render_app_release_center("Select at least one release to remove."))
            return
        with db_connect() as connection:
            deleted, errors = app_release.delete_releases(connection, release_ids)
            connection.commit()
        parts = []
        if deleted:
            labels = ", ".join(item["version"] for item in deleted)
            apk_removed = sum(1 for item in deleted if item.get("apkRemoved"))
            parts.append(f"Removed {len(deleted)} release(s): {labels}.")
            if apk_removed:
                parts.append(f"Deleted {apk_removed} APK file(s) from server disk.")
        if errors:
            parts.append("Errors: " + "; ".join(errors))
        self.send_html(render_app_release_center(" ".join(parts) or "Nothing removed."))

    def send_update_manager_catalog(self):
        server = read_server_config()
        catalog = []
        with db_connect() as connection:
            targets = app_release.list_update_targets(connection)
            for target in targets:
                if not target.get("enabled"):
                    continue
                payload = app_release.get_catalog_release_for_package(
                    connection,
                    target["package_name"],
                    server["host"],
                    server["port"],
                )
                if payload:
                    catalog.append(
                        {
                            "packageName": target["package_name"],
                            "appLabel": target["app_label"],
                            **payload,
                        }
                    )
        self.send_json({"ok": True, "releases": catalog, "serverTime": int(time.time())})

    def register_device(self):
        body = self.read_json_body()
        if body is None:
            self.send_json({"error": "invalid_json"}, status=400)
            return

        device_id = str(body.get("deviceId", "")).strip()
        model = str(body.get("model", "")).strip()
        if not device_id or not model:
            self.send_json({"error": "deviceId_and_model_required"}, status=400)
            return

        devices = read_devices()
        existing = next((device for device in devices if device["deviceId"] == device_id), None)
        incoming_device_token = get_device_token_from_headers(self)
        enrollment_token = str(body.get("enrollmentToken", "")).strip()
        issued_device_token = ""
        authorized = False

        if existing and device_token_valid(device_id, incoming_device_token):
            authorized = True
        elif validate_enrollment_token(enrollment_token, device_id):
            issued_device_token = secrets.token_urlsafe(32)
            authorized = True

        if not authorized:
            self.send_json({"error": "valid_enrollment_or_device_token_required"}, status=401)
            return

        record = {
            "deviceId": device_id,
            "manufacturer": str(body.get("manufacturer", "")).strip(),
            "model": model,
            "androidVersion": str(body.get("androidVersion", "")).strip(),
            "apiLevel": str(body.get("apiLevel", "")).strip(),
            "lastSeenAt": int(time.time()),
            "registered": True,
            "deregisteredAt": None,
        }
        if issued_device_token:
            assign_device_token(record, issued_device_token)

        if existing:
            existing.update(record)
        else:
            record["createdAt"] = record["lastSeenAt"]
            devices.append(record)

        write_devices(devices)
        record_device_event(device_id, "registered", "Device registered or refreshed")
        response = {"ok": True, "device": decorate_device(record)}
        if issued_device_token:
            response["deviceToken"] = issued_device_token
        self.send_json(response, status=201)

    def deregister_device(self):
        body = self.read_form_body()
        device_id = str(body.get("deviceId", [""])[0]).strip()
        if not device_id:
            self.send_json({"error": "deviceId_required"}, status=400)
            return
        if not self.is_authenticated() and not device_token_valid(device_id, get_device_token_from_headers(self)):
            self.send_json({"error": "unauthorized_device"}, status=401)
            return

        devices = read_devices()
        now = int(time.time())
        updated = 0
        for device in devices:
            if device.get("deviceId") == device_id:
                device["registered"] = False
                device["deregisteredAt"] = now
                device["deviceTokenHash"] = None
                device["pendingDeviceToken"] = None
                device["deviceTokenSealed"] = None
                updated += 1
        write_devices(devices)
        if updated:
            record_device_event(device_id, "deregistered", "Device deregistered")
            device = get_device_by_id(device_id)
            if device:
                record_status_transition(device_id, device)

        accept = self.headers.get("Accept", "")
        if "text/html" in accept:
            self.send_redirect("/")
            return
        self.send_json({"ok": True, "deregistered": updated})

    def delete_device(self):
        if not self.is_authenticated():
            self.send_json({"error": "unauthorized"}, status=401)
            return

        body = self.read_form_body()
        device_id = str(body.get("deviceId", [""])[0]).strip()
        if not device_id:
            self.send_json({"error": "deviceId_required"}, status=400)
            return
        if not delete_device_by_id(device_id):
            self.send_json({"error": "device_not_found"}, status=404)
            return

        accept = self.headers.get("Accept", "")
        if "text/html" in accept:
            self.send_redirect("/")
            return
        self.send_json({"ok": True, "deleted": 1})

    def save_server_config(self):
        body = self.read_form_body()
        host = str(body.get("host", [""])[0]).strip()
        port = str(body.get("port", [""])[0]).strip()
        if not host or not port:
            self.send_html(render_server_config({"host": host, "port": port}, "Host and port are required."), status=400)
            return

        write_server_config({"host": host, "port": port})
        self.send_html(render_server_config(
            read_server_config(),
            "Server config saved. Restart the backend if you changed the port so it listens on the new port.",
        ))

    def save_policy_config(self):
        body = self.read_form_body()
        policy = {}
        for key in default_policy():
            policy[key] = str(body.get(key, [""])[0]).strip()
        write_policy(policy)
        self.send_html(render_policy_config(read_policy(), "Policy saved. Devices will sync it on their next heartbeat."))

    def save_email_config(self):
        body = self.read_form_body()
        config = {
            "host": str(body.get("host", [""])[0]).strip(),
            "port": str(body.get("port", ["587"])[0]).strip(),
            "username": str(body.get("username", [""])[0]).strip(),
            "password": str(body.get("password", [""])[0]),
            "fromEmail": str(body.get("fromEmail", [""])[0]).strip(),
            "adminEmail": str(body.get("adminEmail", [""])[0]).strip(),
            "useTls": str(body.get("useTls", [""])[0]) == "on",
        }
        if not config["password"]:
            config["password"] = read_smtp_config().get("password", "")
        write_smtp_config(config)
        self.send_html(render_email_config(read_smtp_config(), "Email settings saved."))

    def send_test_email_config(self):
        ok, message = send_test_email()
        alert_class = "alert-success" if ok else "alert-danger"
        self.send_html(render_email_config(read_smtp_config(), message, alert_class=alert_class))

    def generate_enrollment_token(self):
        body = self.read_form_body()
        label = str(body.get("label", [""])[0]).strip()
        token = create_enrollment_token(label or "Android device enrollment")
        self.send_html(render_enrollment_tokens(read_enrollment_tokens(), token))

    def read_form_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return parse_qs(raw)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return None
        try:
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def send_json(self, payload, status=200):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def send_redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_html(self, html_body, status=200):
        encoded = html_body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))


ADMIN_LAYOUT_STYLES = """
<style>
  :root {
    --admin-shell-max: 1320px;
    --admin-shell-narrow-max: 960px;
    --admin-page-gutter: clamp(14px, 2.8vw, 32px);
  }
  html {
    box-sizing: border-box;
  }
  *, *::before, *::after {
    box-sizing: inherit;
  }
  body {
    margin: 0;
    background: #eef3f9;
    color: #172033;
    font-family: 'Segoe UI', system-ui, Arial, sans-serif;
    overflow-x: hidden;
  }
  .admin-shell {
    width: 100%;
    max-width: var(--admin-shell-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--admin-page-gutter);
    padding-right: var(--admin-page-gutter);
  }
  .admin-shell-narrow {
    max-width: var(--admin-shell-narrow-max);
  }
  .admin-navbar {
    background: linear-gradient(135deg, #0f172a 0%, #1565c0 60%, #2f80ed 100%);
    box-shadow: 0 4px 20px rgba(15, 23, 42, 0.25);
    padding: 0.45rem 0;
  }
  .admin-navbar .navbar-brand {
    color: #fff !important;
    font-weight: 700;
  }
  .admin-navbar .nav-link {
    color: rgba(255, 255, 255, 0.95) !important;
    font-weight: 600;
    padding: 0.5rem 0.85rem !important;
  }
  .admin-navbar .nav-link:hover,
  .admin-navbar .nav-link:focus,
  .admin-navbar .nav-link.active {
    color: #fff !important;
  }
  .admin-navbar .dropdown-menu {
    border: 0;
    border-radius: 12px;
    box-shadow: 0 12px 32px rgba(20, 36, 64, 0.18);
    padding: 0.45rem;
    min-width: 12rem;
  }
  .admin-navbar .dropdown-item {
    border-radius: 8px;
    font-weight: 500;
    color: #172033;
    padding: 0.45rem 0.85rem;
  }
  .admin-navbar .dropdown-item.active,
  .admin-navbar .dropdown-item:active {
    background: #1565c0;
    color: #fff;
  }
  .admin-navbar .btn-logout {
    border-color: rgba(255, 255, 255, 0.6);
    color: #fff;
    font-weight: 600;
  }
  .admin-navbar .btn-logout:hover {
    background: rgba(255, 255, 255, 0.15);
    color: #fff;
    border-color: #fff;
  }
  .page-header {
    background: #fff;
    border-bottom: 1px solid #dbe4ef;
    padding: 1rem 0;
    margin-bottom: 1rem;
  }
  .page-header h1 {
    font-size: clamp(1.35rem, 2.4vw, 1.65rem);
    font-weight: 700;
    color: #0f172a;
    margin: 0;
    overflow-wrap: anywhere;
  }
  .page-header .subtitle {
    color: #64748b;
    margin: 0.35rem 0 0;
    font-size: 0.95rem;
    overflow-wrap: anywhere;
    line-height: 1.45;
  }
  main.admin-main {
    padding-top: 0.25rem;
    padding-bottom: 2.5rem;
  }
  .admin-card {
    border: 0;
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(20, 36, 64, 0.1);
    background: #fff;
    overflow: visible;
  }
  .admin-card.clip-content {
    overflow: hidden;
  }
  .admin-card p,
  .admin-card .text-secondary,
  .admin-card dd,
  .admin-card td,
  .admin-card th {
    overflow-wrap: anywhere;
    word-break: break-word;
  }
  .admin-card dl.row dt,
  .admin-card dl.row dd {
    overflow-wrap: anywhere;
    word-break: break-word;
  }
  @media (max-width: 575.98px) {
    .admin-card dl.row dt,
    .admin-card dl.row dd {
      flex: 0 0 100%;
      max-width: 100%;
    }
    .admin-card dl.row dt {
      margin-bottom: 0.15rem;
      font-weight: 600;
    }
    .admin-card dl.row dd {
      margin-bottom: 0.75rem;
    }
  }
  .dashboard-toolbar {
    padding: 0.85rem 1.25rem 0.35rem;
  }
  .dashboard-bulk {
    padding: 0.35rem 1.25rem 0.75rem;
  }
  .device-table-viewport {
    --device-row-height: 3rem;
    --device-head-height: 2.85rem;
    max-height: calc(var(--device-head-height) + (var(--device-row-height) * 5));
    overflow: auto;
    border-top: 1px solid #dee2e6;
    -webkit-overflow-scrolling: touch;
  }
  .device-table-viewport table {
    margin-bottom: 0;
    min-width: 980px;
  }
  .device-table-viewport thead th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: #fff;
    box-shadow: inset 0 -1px 0 #dee2e6;
    white-space: nowrap;
  }
  .device-table-viewport .table > :not(caption) > * > * {
    padding-top: 0.55rem;
    padding-bottom: 0.55rem;
  }
  .table-responsive {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .device-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    align-items: center;
    min-width: 140px;
  }
  .device-table-viewport .dropdown-menu {
    z-index: 1080;
  }
  .device-id {
    font-family: ui-monospace, monospace;
    word-break: break-all;
  }
  .status {
    border-radius: 999px;
    color: white;
    display: inline-block;
    font-size: 12px;
    font-weight: 700;
    padding: 5px 9px;
    white-space: nowrap;
  }
  .online { background: #2e7d32; }
  .offline { background: #ef6c00; }
  .pending { background: #5e35b1; }
  .unregistered { background: #607d8b; }
  .deregistered { background: #607d8b; }
  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    padding: 0 1.25rem 0.65rem;
  }
  .empty {
    color: #657085;
    padding: 28px;
    text-align: center;
  }
  code {
    background: #eef2f7;
    border-radius: 6px;
    padding: 2px 6px;
    color: #b42318;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
  pre {
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }
  #qrcode { min-height: 280px; }
  .timeline-chart-wrap {
    position: relative;
    height: 220px;
  }
  .timeline-chart-wrap canvas {
    width: 100% !important;
    height: 100% !important;
  }
  .form-control,
  .form-select,
  .btn {
    max-width: 100%;
  }
</style>
"""

ADMIN_NAV_GROUPS = (
    {
        "label": "Devices",
        "paths": ("/", "/commands", "/enrollment-tokens", "/enrollment-qr"),
        "items": (
            ("/", "Device List"),
            ("/commands", "Command History"),
            ("/enrollment-tokens", "Register Device"),
            ("/enrollment-qr", "Enrollment QR"),
        ),
    },
    {
        "label": "Device Config",
        "paths": ("/policy-config", "/app-release-center"),
        "items": (
            ("/policy-config", "Policy"),
            ("/app-release-center", "App Build & OTA"),
        ),
    },
    {
        "label": "Server",
        "paths": ("/server-config", "/email-config"),
        "items": (
            ("/server-config", "Server Config"),
            ("/email-config", "Email & Alerts"),
        ),
    },
)


def resolve_admin_active_path(path):
    if path.startswith("/devices/detail") or path.startswith("/devices/location") or path.startswith("/devices/call-log") or path.startswith("/devices/sms-history") or path.startswith("/devices/contacts") or path.startswith("/devices/notifications") or path.startswith("/devices/audio") or path.startswith("/devices/files") or path.startswith("/devices/shell") or path.startswith("/devices/communications") or path.startswith("/devices/security") or path.startswith("/devices/geofence") or path.startswith("/devices/wifi-profile"):
        return "/"
    return path


def render_admin_navbar(active_path="/"):
    active_path = resolve_admin_active_path(active_path)
    dropdowns = []
    for group in ADMIN_NAV_GROUPS:
        group_active = "active" if active_path in group["paths"] else ""
        items = []
        for href, label in group["items"]:
            item_active = " active" if active_path == href else ""
            items.append(f'<li><a class="dropdown-item{item_active}" href="{href}">{label}</a></li>')
        dropdowns.append(
            f'<li class="nav-item dropdown">'
            f'<a class="nav-link dropdown-toggle {group_active}" href="#" role="button" '
            f'data-bs-toggle="dropdown" aria-expanded="false">{group["label"]}</a>'
            f'<ul class="dropdown-menu">{"".join(items)}</ul>'
            f"</li>"
        )
    return (
        '<nav class="navbar navbar-expand-lg navbar-dark admin-navbar">'
        '<div class="admin-shell">'
        '<a class="navbar-brand" href="/">Device Safety</a>'
        '<button class="navbar-toggler" type="button" data-bs-toggle="collapse" '
        'data-bs-target="#adminNav" aria-controls="adminNav" aria-expanded="false" '
        'aria-label="Toggle navigation">'
        '<span class="navbar-toggler-icon"></span>'
        "</button>"
        '<div class="collapse navbar-collapse" id="adminNav">'
        f'<ul class="navbar-nav me-auto mb-2 mb-lg-0">{"".join(dropdowns)}</ul>'
        '<div class="d-flex ms-lg-3">'
        '<a class="btn btn-sm btn-outline-light btn-logout" href="/logout">Logout</a>'
        "</div>"
        "</div></div></nav>"
    )


def render_admin_page(title, subtitle, content, active_path="/", page_title=None, extra_head="", extra_scripts="", fluid=True):
    if page_title is None:
        page_title = title
    shell_class = "admin-shell" if fluid else "admin-shell admin-shell-narrow"
    return (
        "<!doctype html><html lang=\"en\"><head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(page_title)} — Device Safety</title>"
        "<link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\" rel=\"stylesheet\">"
        + ADMIN_LAYOUT_STYLES
        + extra_head
        + "</head><body>"
        + render_admin_navbar(active_path)
        + f"<div class=\"page-header\"><div class=\"{shell_class}\">"
        f"<h1>{escape(title)}</h1>"
        + (f'<p class="subtitle">{escape(subtitle)}</p>' if subtitle else "")
        + "</div></div>"
        + f"<main class=\"admin-main {shell_class}\">"
        + content
        + "</main>"
        "<script src=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js\"></script>"
        + extra_scripts
        + "</body></html>"
    )


def render_admin_nav():
    return render_admin_navbar("/")


def render_dashboard(devices, selected_filter="online", selected_group=""):
    attach_wifi_dashboard_snapshot(devices)
    decorated_devices = [decorate_device(device) for device in devices]
    visible_devices = filter_devices(devices, selected_filter, selected_group)
    groups = list_device_groups()
    group_options = "".join(
        f'<option value="{escape(group)}"{" selected" if group == selected_group else ""}>{escape(group)}</option>'
        for group in groups
    )
    rows = "\n".join(render_device_row(device) for device in visible_devices)
    if not rows:
        rows = "<tr><td colspan=\"11\" class=\"empty\">No devices match this filter.</td></tr>"

    filter_links = render_filter_links(selected_filter, selected_group)

    content = f"""<section class="admin-card">
      <div class="d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-2 dashboard-toolbar">
        <div>
          <h2 class="h5 mb-1">Registered Devices</h2>
          <div id="device-summary" class="text-secondary small">Showing {len(visible_devices)} of {len(decorated_devices)} devices</div>
          <div id="live-status" class="small text-secondary">Live sync active</div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="loadDevices()">Sync Now</button>
      </div>
      <div class="filters">{filter_links}</div>
      <div class="px-4 pb-2 d-flex flex-wrap gap-2 align-items-center">
        <label class="fw-bold small" for="group-filter">Group</label>
        <select id="group-filter" class="form-select form-select-sm" style="width:auto" onchange="applyGroupFilter()">
          <option value="">All groups</option>
          {group_options}
        </select>
      </div>
      <div class="dashboard-bulk border-bottom">
        <div class="d-flex flex-wrap gap-2 align-items-center">
          <span class="fw-bold small">Bulk actions:</span>
          <select id="bulk-action" class="form-select form-select-sm" style="width:auto">
            <option value="sync_policy">Force Sync Policy</option>
            <option value="push_server_config">Push Server URL</option>
            <option value="security_lock_prompt">Security Lock Prompt</option>
            <option value="push_app_update">Push App Update</option>
            <option value="push_wifi_profile">Push Wi-Fi Profile</option>
            <option value="enable_wifi">Enable Wi-Fi</option>
            <option value="enable_location">Enable Location (GPS)</option>
            <option value="scan_wifi">Scan Wi-Fi & Refresh</option>
            <option value="show_alert">Show Alert</option>
            <option value="request_device_admin">Request Device Admin</option>
            <option value="reregister">Re-register & Push Token</option>
            <option value="deregister">Deregister</option>
            <option value="set_group">Set Group</option>
          </select>
          <input id="bulk-payload" class="form-control form-control-sm" style="max-width:240px" placeholder="Alert message or group name">
          <button class="btn btn-sm btn-primary" onclick="runBulkAction()">Apply To Selected</button>
          <button class="btn btn-sm btn-outline-secondary" onclick="toggleSelectAll(true)">Select All Visible</button>
          <button class="btn btn-sm btn-outline-secondary" onclick="toggleSelectAll(false)">Clear Selection</button>
        </div>
      </div>
      <div class="device-table-viewport">
        <table class="table table-hover align-middle mb-0">
          <thead>
            <tr>
              <th><input type="checkbox" id="select-all" onchange="toggleSelectAll(this.checked)"></th>
              <th>Device ID</th>
              <th>Status</th>
              <th>Group</th>
              <th>Manufacturer</th>
              <th>Model</th>
              <th>Android</th>
              <th>API</th>
              <th>Created</th>
              <th>Last Seen</th>
              <th>Wi-Fi</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="devices-body">
            {rows}
          </tbody>
        </table>
      </div>
    </section>"""

    scripts = f"""<script>
    const currentFilter = "{selected_filter}";
    const currentGroup = "{escape(selected_group)}";
    const emptyRow = '<tr><td colspan="12" class="empty">No devices match this filter.</td></tr>';
    const DEVICE_MENU_ITEMS = {render_device_menu_js_items()};

    function escapeHtml(value) {{
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }}

    function formatTimestamp(value) {{
      if (!value) {{
        return '';
      }}
      return new Date(value * 1000).toLocaleString();
    }}

    function summarizeWifi(device) {{
      const snap = device.wifiSnapshot || {{}};
      const scanAt = snap.scanAt ? ` · scan ${{
        new Date(Number(snap.scanAt) * 1000).toLocaleTimeString()
      }}` : '';
      const nearbyCount = Number(snap.nearbyCount || 0);
      const savedCount = Number(snap.savedCount || 0);
      const current = device.lastWifiSsid ? `Now: ${{escapeHtml(device.lastWifiSsid)}}<br>` : '';
      const nearby = nearbyCount > 0 ? `Near: ${{nearbyCount}}` : 'Near: 0';
      const saved = savedCount > 0 ? `Saved: ${{savedCount}}` : 'Saved: 0';
      return `${{current}}<span class="small text-secondary">${{nearby}} · ${{saved}}${{scanAt}}</span>`;
    }}

    function deviceVisible(device) {{
      if (currentGroup && (device.deviceGroup || '') !== currentGroup) {{
        return false;
      }}
      if (currentFilter === 'unregistered' || currentFilter === 'deregistered' || currentFilter === 'pending') {{
        return device.status === 'unregistered';
      }}
      if (currentFilter === 'offline') {{
        return device.status === 'offline';
      }}
      if (currentFilter === 'all') {{
        return true;
      }}
      return device.status === 'online';
    }}

    function renderReregisterButton(deviceId) {{
      return `<form class="d-inline ms-1" method="post" action="/enrollment-tokens" onsubmit="return confirm('Push a new device token to the app for registration?');">
  <input type="hidden" name="deviceId" value="${{escapeHtml(deviceId)}}">
  <button class="btn btn-sm btn-primary" type="submit">Re-register</button>
</form>`;
    }}

    function renderDeleteButton(deviceId) {{
      return `<button class="btn btn-sm btn-danger ms-1" onclick="deleteDevice('${{escapeHtml(deviceId)}}')">Delete</button>`;
    }}

    function renderDeviceMenu(deviceId) {{
      const menuItems = DEVICE_MENU_ITEMS.map((item) =>
        `<li><a class="dropdown-item" href="${{item.path}}?deviceId=${{encodeURIComponent(deviceId)}}">${{escapeHtml(item.label)}}</a></li>`
      ).join('');
      return `<div class="dropup device-row-menu d-inline-block">
  <button class="btn btn-sm btn-primary dropdown-toggle" type="button" data-bs-toggle="dropdown" data-bs-popper-config='{{"strategy":"fixed"}}'>Device Menu</button>
  <ul class="dropdown-menu dropdown-menu-end shadow">${{menuItems}}</ul>
</div>`;
    }}

    function configureDeviceMenuDropdowns(root) {{
      const scope = root || document;
      scope.querySelectorAll('.device-row-menu [data-bs-toggle="dropdown"]').forEach((toggle) => {{
        const existing = bootstrap.Dropdown.getInstance(toggle);
        if (existing) {{
          existing.dispose();
        }}
        new bootstrap.Dropdown(toggle, {{
          popperConfig(defaultConfig) {{
            return {{
              ...defaultConfig,
              strategy: 'fixed',
              modifiers: [
                ...(defaultConfig.modifiers || []),
                {{ name: 'preventOverflow', options: {{ boundary: 'viewport', padding: 8 }} }},
                {{ name: 'flip', options: {{ fallbackPlacements: ['top', 'bottom'] }} }}
              ]
            }};
          }}
        }});
      }});
    }}

    function renderAction(device) {{
      const menu = renderDeviceMenu(device.deviceId);
      const deleteButton = renderDeleteButton(device.deviceId);
      if (device.status === 'online' || device.status === 'offline') {{
        return `<div class="device-actions">${{menu}}<button class="btn btn-sm btn-outline-danger" onclick="deregisterDevice('${{escapeHtml(device.deviceId)}}')">Deregister</button>${{deleteButton}}</div>`;
      }}
      return `<div class="device-actions">${{menu}}${{renderReregisterButton(device.deviceId)}}${{deleteButton}}</div>`;
    }}

    function renderDeviceRow(device) {{
      const status = escapeHtml(device.status);
      const group = escapeHtml(device.deviceGroup || '-');
      return `<tr>
        <td><input type="checkbox" class="device-select" value="${{escapeHtml(device.deviceId)}}"></td>
        <td class="device-id">${{escapeHtml(device.deviceId)}}</td>
        <td><span class="status ${{status}}">${{status.charAt(0).toUpperCase() + status.slice(1)}}</span></td>
        <td>${{group}}</td>
        <td>${{escapeHtml(device.manufacturer)}}</td>
        <td>${{escapeHtml(device.model)}}</td>
        <td>${{escapeHtml(device.androidVersion)}}</td>
        <td>${{escapeHtml(device.apiLevel)}}</td>
        <td>${{formatTimestamp(device.createdAt)}}</td>
        <td>${{formatTimestamp(device.lastSeenAt)}}</td>
        <td>${{summarizeWifi(device)}}</td>
        <td>${{renderAction(device)}}</td>
      </tr>`;
    }}

    function selectedDeviceIds() {{
      return Array.from(document.querySelectorAll('.device-select:checked')).map((input) => input.value);
    }}

    function toggleSelectAll(checked) {{
      document.querySelectorAll('.device-select').forEach((input) => {{ input.checked = checked; }});
      const selectAll = document.getElementById('select-all');
      if (selectAll) {{
        selectAll.checked = checked;
      }}
    }}

    function applyGroupFilter() {{
      const group = document.getElementById('group-filter').value;
      const params = new URLSearchParams(window.location.search);
      if (group) {{
        params.set('group', group);
      }} else {{
        params.delete('group');
      }}
      window.location.search = params.toString();
    }}

    async function runBulkAction() {{
      const deviceIds = selectedDeviceIds();
      if (!deviceIds.length) {{
        alert('Select at least one device.');
        return;
      }}
      const action = document.getElementById('bulk-action').value;
      const payload = document.getElementById('bulk-payload').value.trim();
      if (action === 'show_alert' && !payload) {{
        alert('Enter an alert message in the bulk text field.');
        return;
      }}
      if (action === 'set_group' && !payload) {{
        alert('Enter a group name in the bulk text field.');
        return;
      }}
      if (!confirm(`Apply '${{action}}' to ${{deviceIds.length}} device(s)?`)) {{
        return;
      }}
      const response = await fetch('/devices/bulk-action', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          deviceIds,
          action,
          payload,
          group: action === 'set_group' ? payload : ''
        }})
      }});
      const result = await response.json();
      alert((result.results || []).map((item) => `${{item.deviceId}}: ${{item.message}}`).join('\\n'));
      loadDevices();
    }}

    async function loadDevices() {{
      const liveStatus = document.getElementById('live-status');
      try {{
        const response = await fetch('/devices', {{ cache: 'no-store' }});
        const payload = await response.json();
        const devices = payload.devices || [];
        const visibleDevices = devices.filter(deviceVisible);
        document.getElementById('devices-body').innerHTML = visibleDevices.length
          ? visibleDevices.map(renderDeviceRow).join('')
          : emptyRow;
        configureDeviceMenuDropdowns(document.getElementById('devices-body'));
        document.getElementById('device-summary').textContent = `Showing ${{visibleDevices.length}} of ${{devices.length}} devices`;
        liveStatus.textContent = `Live synced at ${{new Date().toLocaleTimeString()}}`;
        liveStatus.className = 'small text-success mt-1';
      }} catch (error) {{
        liveStatus.textContent = `Live sync failed: ${{error.message}}`;
        liveStatus.className = 'small text-danger mt-1';
      }}
    }}

    async function deregisterDevice(deviceId) {{
      if (!confirm('Deregister this device?')) {{
        return;
      }}
      const body = new URLSearchParams();
      body.set('deviceId', deviceId);
      await fetch('/devices/deregister', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
        body
      }});
      loadDevices();
    }}

    async function deleteDevice(deviceId) {{
      if (!confirm('Permanently delete this device and all its history?')) {{
        return;
      }}
      const body = new URLSearchParams();
      body.set('deviceId', deviceId);
      await fetch('/devices/delete', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
        body
      }});
      loadDevices();
    }}

    loadDevices();
    configureDeviceMenuDropdowns(document.getElementById('devices-body'));
    setInterval(loadDevices, 5000);
  </script>"""

    return render_admin_page(
        "Device Dashboard",
        "Transparent registered-device list for the learning MDM project.",
        content,
        active_path="/",
        page_title="Dashboard",
        extra_scripts=scripts,
    )


def render_login(error_message=""):
    error_html = f"<div class=\"alert alert-danger\">{escape(error_message)}</div>" if error_message else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin Login</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body {{
      background: linear-gradient(135deg, #0f172a 0%, #1565c0 70%, #2f80ed 100%);
      min-height: 100vh;
    }}
    .login-card {{
      border: 0;
      border-radius: 18px;
      box-shadow: 0 18px 46px rgba(15, 23, 42, 0.25);
      max-width: 430px;
      width: 100%;
    }}
  </style>
</head>
<body class="d-flex align-items-center justify-content-center p-4">
  <main class="card login-card p-4">
    <h1 class="h4 mb-2">Admin Login</h1>
    <p class="text-secondary">Sign in to manage devices, server config, and policies.</p>
    {error_html}
    <form method="post" action="/login">
      <label class="form-label fw-bold" for="username">Username</label>
      <input class="form-control mb-3" id="username" name="username" autocomplete="username" required>

      <label class="form-label fw-bold" for="password">Password</label>
      <input class="form-control mb-3" id="password" name="password" type="password" autocomplete="current-password" required>

      <button class="btn btn-primary w-100" type="submit">Login</button>
    </form>
    <a class="d-block mt-3" href="/forgot-password">Forgot password?</a>
    <p class="small text-secondary mt-3 mb-0">Lab default: admin / admin123</p>
  </main>
</body>
</html>"""


def render_forgot_password(message=""):
    message_html = f"<div class=\"alert alert-info\">{escape(message)}</div>" if message else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Forgot Password</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
  <main class="container py-5" style="max-width: 520px;">
    <section class="card border-0 shadow-sm p-4">
      <h1 class="h4">Forgot Password</h1>
      <p class="text-secondary">Enter the admin username. A reset link will be sent to the configured admin email.</p>
      {message_html}
      <form method="post" action="/forgot-password">
        <label class="form-label fw-bold" for="username">Username</label>
        <input class="form-control mb-3" id="username" name="username" autocomplete="username" required>
        <button class="btn btn-primary w-100" type="submit">Send Reset Link</button>
      </form>
      <a class="d-block mt-3" href="/login">Back to login</a>
    </section>
  </main>
</body>
</html>"""


def render_reset_password(token, error_message=""):
    error_html = f"<div class=\"alert alert-danger\">{escape(error_message)}</div>" if error_message else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reset Password</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
  <main class="container py-5" style="max-width: 520px;">
    <section class="card border-0 shadow-sm p-4">
      <h1 class="h4">Reset Password</h1>
      <p class="text-secondary">Choose a new admin password. The reset link expires in 15 minutes.</p>
      {error_html}
      <form method="post" action="/reset-password">
        <input type="hidden" name="token" value="{escape(token)}">
        <label class="form-label fw-bold" for="password">New Password</label>
        <input class="form-control mb-3" id="password" name="password" type="password" minlength="8" required>
        <label class="form-label fw-bold" for="confirmPassword">Confirm Password</label>
        <input class="form-control mb-3" id="confirmPassword" name="confirmPassword" type="password" minlength="8" required>
        <button class="btn btn-primary w-100" type="submit">Reset Password</button>
      </form>
    </section>
  </main>
</body>
</html>"""


def render_server_config(config, message=""):
    host = escape(config.get("host"))
    port = escape(config.get("port"))
    message_html = f'<div class="alert alert-info">{escape(message)}</div>' if message else ""
    content = f"""<section class="admin-card p-4">
      {message_html}
      <p class="text-secondary">Use ADB mode for USB testing. Use a reachable LAN IP, hostname, or domain for remote mode.</p>
      <form method="post" action="/server-config">
        <label class="form-label fw-bold" for="host">Host/IP or hostname</label>
        <input class="form-control mb-3" id="host" name="host" value="{host}" placeholder="10.105.162.117 or example.com" required>
        <label class="form-label fw-bold" for="port">Port</label>
        <input class="form-control mb-3" id="port" name="port" value="{port}" placeholder="8080" required>
        <button class="btn btn-primary" type="submit">Save Server Config</button>
      </form>
      <div class="mt-4">
        <p class="text-secondary mb-2">Client URL preview: <code>http://{host}:{port}</code></p>
        <p class="text-secondary mb-2">The backend listens on <code>0.0.0.0:{port}</code> after restart. Use a LAN IP or hostname that phones can reach, not <code>127.0.0.1</code>.</p>
        <p class="text-secondary mb-0">For USB live testing, keep using ADB mode with <code>http://127.0.0.1:8080</code> and <code>adb reverse tcp:8080 tcp:8080</code>.</p>
        <p class="text-secondary mt-3 mb-0">Use the <strong>Push Server URL</strong> remote command on a device detail page to update enrolled phones automatically after you change this config.</p>
      </div>
    </section>"""
    return render_admin_page(
        "Server Config",
        "Set the host/IP and port that Android clients use for remote communication.",
        content,
        active_path="/server-config",
        fluid=False,
    )


def render_policy_config(policy, message=""):
    message_html = f'<div class="alert alert-info">{escape(message)}</div>' if message else ""
    content = f"""<section class="admin-card p-4">
      {message_html}
      <form method="post" action="/policy-config">
        <label class="form-label fw-bold" for="organizationName">Organization Name</label>
        <input class="form-control mb-3" id="organizationName" name="organizationName" value="{escape(policy.get("organizationName"))}" required>
        <label class="form-label fw-bold" for="supportContact">Support Contact</label>
        <input class="form-control mb-3" id="supportContact" name="supportContact" value="{escape(policy.get("supportContact"))}" required>
        <label class="form-label fw-bold" for="safetyNotice">Safety Notice</label>
        <textarea class="form-control mb-3" id="safetyNotice" name="safetyNotice" rows="3" required>{escape(policy.get("safetyNotice"))}</textarea>
        <label class="form-label fw-bold" for="allowedUsage">Allowed Usage</label>
        <textarea class="form-control mb-3" id="allowedUsage" name="allowedUsage" rows="3" required>{escape(policy.get("allowedUsage"))}</textarea>
        <label class="form-label fw-bold" for="emergencyMessage">Emergency Message</label>
        <textarea class="form-control mb-3" id="emergencyMessage" name="emergencyMessage" rows="3" required>{escape(policy.get("emergencyMessage"))}</textarea>
        <button class="btn btn-primary" type="submit">Save Policy</button>
      </form>
    </section>"""
    return render_admin_page(
        "Policy Config",
        "Server-controlled messages and guidance that Android devices sync.",
        content,
        active_path="/policy-config",
        fluid=False,
    )


def render_email_config(config, message="", alert_class="alert-info"):
    message_html = f'<div class="alert {alert_class}">{escape(message)}</div>' if message else ""
    tls_checked = "checked" if config.get("useTls") else ""
    password_placeholder = "Leave blank to keep existing password" if config.get("password") else "SMTP password"
    content = f"""<section class="admin-card p-4">
      {message_html}
      <form method="post" action="/email-config">
        <div class="row">
          <div class="col-md-8">
            <label class="form-label fw-bold" for="host">SMTP Host</label>
            <input class="form-control mb-3" id="host" name="host" value="{escape(config.get("host"))}" placeholder="smtp.company.com">
          </div>
          <div class="col-md-4">
            <label class="form-label fw-bold" for="port">SMTP Port</label>
            <input class="form-control mb-3" id="port" name="port" value="{escape(config.get("port"))}" placeholder="587">
          </div>
        </div>
        <label class="form-label fw-bold" for="username">SMTP Username</label>
        <input class="form-control mb-3" id="username" name="username" value="{escape(config.get("username"))}">
        <label class="form-label fw-bold" for="password">SMTP Password</label>
        <input class="form-control mb-3" id="password" name="password" type="password" placeholder="{password_placeholder}">
        <label class="form-label fw-bold" for="fromEmail">From Email</label>
        <input class="form-control mb-3" id="fromEmail" name="fromEmail" value="{escape(config.get("fromEmail"))}" placeholder="mdm@company.com">
        <label class="form-label fw-bold" for="adminEmail">Admin Recovery Email</label>
        <input class="form-control mb-3" id="adminEmail" name="adminEmail" value="{escape(config.get("adminEmail"))}" placeholder="admin@company.com">
        <div class="form-check mb-3">
          <input class="form-check-input" id="useTls" name="useTls" type="checkbox" {tls_checked}>
          <label class="form-check-label" for="useTls">Use STARTTLS</label>
        </div>
        <button class="btn btn-primary" type="submit">Save Email Settings</button>
      </form>
      <form method="post" action="/email-config/test" class="mt-3">
        <button class="btn btn-outline-primary" type="submit">Send Test Email</button>
        <span class="text-muted ms-2">Uses saved settings and sends to Admin Recovery Email.</span>
      </form>
    </section>"""
    return render_admin_page(
        "Email Settings",
        "Configure SMTP for password resets, OTP emails, test messages, and device status alerts.",
        content,
        active_path="/email-config",
        fluid=False,
    )


def render_device_geofence_page(device, config, message=""):
    device_id = escape(device.get("deviceId"))
    raw_device_id = device.get("deviceId")
    message_html = f'<div class="alert alert-info">{escape(message)}</div>' if message else ""
    current_ssid = escape(device.get("lastWifiSsid") or "-")
    wifi_ok, matched_wifi = gf.evaluate_wifi_match(config, device.get("lastWifiSsid"))
    loc_ok, zone_id = gf.evaluate_location_zone(config, device.get("lastLatitude"), device.get("lastLongitude"))
    wifi_status = "Not configured"
    if config.get("wifiNetworks"):
        wifi_status = f"On monitored Wi-Fi ({matched_wifi})" if wifi_ok else "Not on monitored Wi-Fi"
    loc_status = "Not configured"
    if config.get("locationZones"):
        zone = next((z for z in config.get("locationZones", []) if z.get("id") == zone_id), None)
        label = zone.get("label") if zone else ""
        loc_status = f"Inside {label}" if loc_ok else "Outside monitored areas"
    suggestions = read_wifi_suggestions_for_device(raw_device_id)
    datalist = gf_page.wifi_ssid_datalist_html(suggestions)
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-3">
        <div>
          <h2 class="h5 mb-1">Geofence (this device)</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">{render_device_status_badge(device)}</div>
      </div>
      <p class="text-secondary small mb-2">
        Current Wi-Fi: <strong>{current_ssid}</strong> · Wi-Fi geofence: <strong>{escape(wifi_status)}</strong> · GPS geofence: <strong>{escape(loc_status)}</strong>
      </p>
      <p class="text-secondary small">SSID suggestions come from this device&apos;s last scan and connection. Enable Wi-Fi and Location on the device for fresh lists.</p>
      {message_html}
      {datalist}
      <form method="post" action="/devices/geofence" id="geofence-form">
        <input type="hidden" name="deviceId" value="{device_id}">
        <input type="hidden" name="geofenceJson" id="geofenceJson" value="">
        <h3 class="h6 mt-2">Wi-Fi networks</h3>
        <p class="text-secondary small">Add one or more SSIDs. Email alerts fire on connect and disconnect for each network.</p>
        <div id="wifi-networks"></div>
        <button type="button" class="btn btn-outline-secondary btn-sm mb-4" id="add-wifi-btn">+ Add Wi-Fi</button>
        <h3 class="h6">GPS areas</h3>
        <p class="text-secondary small">Add circular zones on the map. Email alerts fire when the device enters or leaves each area.</p>
        <div id="location-zones"></div>
        <button type="button" class="btn btn-outline-secondary btn-sm mb-3" id="add-zone-btn">+ Add location zone</button>
        <div class="d-flex gap-2">
          <button class="btn btn-primary" type="submit">Save Geofence</button>
        </div>
      </form>
    </section>
    <div class="modal fade" id="geofence-map-modal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-lg modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Place geofence zone</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <p class="text-secondary small">Click the map or drag the pin to set the center. Adjust the slider to change the circular area.</p>
            <div id="geofence-zone-map" class="mb-3"></div>
            <label class="form-label fw-bold" for="geofence-radius-slider">Radius: <span id="geofence-radius-label">200 m</span></label>
            <input type="range" class="form-range" id="geofence-radius-slider" min="25" max="5000" step="25" value="200">
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-primary" id="geofence-map-apply">Use this area</button>
          </div>
        </div>
      </div>
    </div>"""
    return render_admin_page(
        "Device Geofence",
        "Per-device Wi-Fi and GPS geofence rules with email alerts on connect, disconnect, enter, and exit.",
        content,
        active_path="/",
        fluid=False,
        extra_head=gf_page.geofence_leaflet_head(),
        extra_scripts=gf_page.geofence_page_scripts(config, device, suggestions),
    )


def render_device_wifi_profile_page(device, config, message="", alert_class="alert-info"):
    device_id = escape(device.get("deviceId"))
    raw_device_id = device.get("deviceId")
    message_html = f'<div class="alert {alert_class}">{escape(message)}</div>' if message else ""
    password_placeholder = "Leave blank to keep existing password" if config.get("password") else "Wi-Fi password"
    wpa_selected = "selected" if config.get("security", "WPA") == "WPA" else ""
    open_selected = "selected" if config.get("security") == "OPEN" else ""
    ssid = escape(config.get("ssid"))
    suggestions = read_wifi_suggestions_for_device(raw_device_id)
    datalist = gf_page.wifi_ssid_datalist_html(suggestions, list_id="wifi-profile-ssid-suggestions")
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-3">
        <div>
          <h2 class="h5 mb-1">Wi-Fi Profile (this device)</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">{render_device_status_badge(device)}</div>
      </div>
      {message_html}
      {datalist}
      <p class="text-secondary small">Pick an SSID from the device scan list or type your office router name manually.</p>
      <form method="post" action="/devices/wifi-profile">
        <input type="hidden" name="deviceId" value="{device_id}">
        <label class="form-label fw-bold" for="ssid">SSID</label>
        <input class="form-control mb-3" id="ssid" name="ssid" list="wifi-profile-ssid-suggestions" value="{ssid}" placeholder="Office-LAN">
        <label class="form-label fw-bold" for="password">Password</label>
        <input class="form-control mb-3" id="password" name="password" type="password" placeholder="{escape(password_placeholder)}">
        <label class="form-label fw-bold" for="security">Security</label>
        <select class="form-select mb-3" id="security" name="security">
          <option value="WPA" {wpa_selected}>WPA/WPA2</option>
          <option value="OPEN" {open_selected}>Open network</option>
        </select>
        <div class="form-check mb-3">
          <input class="form-check-input" id="pushNow" name="pushNow" type="checkbox" checked>
          <label class="form-check-label" for="pushNow">Push to device after save</label>
        </div>
        <button class="btn btn-primary" type="submit">Save Wi-Fi Profile</button>
      </form>
      <hr class="my-4">
      <h3 class="h6">Quick device actions</h3>
      <p class="text-secondary small">Android 10+ needs Wi-Fi and Location ON before Push Wi-Fi Profile. Use office router SSID (not phone hotspot name).</p>
      <div class="d-flex flex-wrap gap-2">
        <form method="post" action="/devices/send-command" class="d-inline">
          <input type="hidden" name="deviceId" value="{device_id}">
          <input type="hidden" name="commandType" value="enable_wifi">
          <input type="hidden" name="returnTo" value="/devices/wifi-profile?deviceId={device_id}">
          <button class="btn btn-outline-primary" type="submit">Enable Wi-Fi</button>
        </form>
        <form method="post" action="/devices/send-command" class="d-inline">
          <input type="hidden" name="deviceId" value="{device_id}">
          <input type="hidden" name="commandType" value="enable_location">
          <input type="hidden" name="returnTo" value="/devices/wifi-profile?deviceId={device_id}">
          <button class="btn btn-outline-primary" type="submit">Enable Location (GPS)</button>
        </form>
        <form method="post" action="/devices/send-command" class="d-inline">
          <input type="hidden" name="deviceId" value="{device_id}">
          <input type="hidden" name="commandType" value="scan_wifi">
          <input type="hidden" name="returnTo" value="/devices/wifi-profile?deviceId={device_id}">
          <button class="btn btn-outline-secondary" type="submit">Scan Wi-Fi & Refresh</button>
        </form>
        <form method="post" action="/devices/send-command" class="d-inline">
          <input type="hidden" name="deviceId" value="{device_id}">
          <input type="hidden" name="commandType" value="push_wifi_profile">
          <input type="hidden" name="returnTo" value="/devices/wifi-profile?deviceId={device_id}">
          <button class="btn btn-outline-success" type="submit">Push Wi-Fi Profile Now</button>
        </form>
      </div>
    </section>"""
    return render_admin_page(
        "Device Wi-Fi Profile",
        "SSID and password pushed to this device with Push Wi-Fi Profile.",
        content,
        active_path="/",
        fluid=False,
    )


def render_app_release_center(message="", building=False, detail=""):
    message_html = f'<div class="alert alert-info">{escape(message)}</div>' if message else ""
    if detail:
        message_html += f'<div class="alert alert-secondary">{escape(detail)}</div>'
    version = app_release.read_version_properties()
    server = read_server_config()
    build_status = app_release.get_build_status()
    status_line = escape(build_status.get("message") or "Ready")
    log_tail = escape(build_status.get("logTail") or "")
    next_code = escape(str(build_status.get("nextVersionCode") or ""))
    next_name = escape(str(build_status.get("nextVersionName") or ""))
    sdk_ready = build_status.get("sdkReady")
    sdk_err = escape(str(build_status.get("sdkError") or ""))
    sdk_root = escape(str(build_status.get("androidSdkRoot") or ""))
    sdk_alert = (
        '<div class="alert alert-warning">'
        "<strong>Android SDK required on server</strong> for one-click build. "
        "SSH: <code>sudo bash scripts/install-android-sdk-server.sh /opt/android-sdk "
        f"/opt/device-safety-manager/deploy/server.env</code> then "
        "<code>systemctl restart device-safety-backend</code>. "
        f"{sdk_err}</div>"
        if not sdk_ready
        else f'<p class="text-secondary small mb-0">SDK: <code>{sdk_root or "detected"}</code></p>'
    )
    poll_script = ""
    if building or build_status.get("running"):
        poll_script = (
            "<script>"
            "(function poll(){fetch('/app-release-center/status.json',{credentials:'same-origin'})"
            ".then(r=>r.json()).then(s=>{"
            "var el=document.getElementById('build-status-line');"
            "var iel=document.getElementById('installer-build-status-line');"
            "var msg=s.message||'Working...';"
            "if(el)el.textContent=msg;"
            "if(iel)iel.textContent=msg;"
            "if(s.running)setTimeout(poll,2500);else if(s.running===false)location.reload();"
            "}).catch(()=>setTimeout(poll,4000));})();"
            "</script>"
        )
    installer_props = build_status.get("installerVersion") or {}
    installer_current = escape(
        f"{installer_props.get('versionName', '—')} (code {installer_props.get('versionCode', '—')})"
    )
    installer_next_name = escape(str(build_status.get("installerNextVersionName") or ""))
    installer_next_code = escape(str(build_status.get("installerNextVersionCode") or ""))
    installer_apk_url = escape(str(build_status.get("installerApkUrl") or ""))
    installer_ready = "yes" if build_status.get("installerApkReady") else "no"
    with db_connect() as connection:
        releases = app_release.list_releases(connection)
    release_rows = ""
    for row in releases:
        release_id = int(row.get("id") or 0)
        active_badge = (
            '<span class="badge text-bg-success">Active</span>'
            if row.get("active")
            else '<span class="text-secondary">—</span>'
        )
        created = format_optional_timestamp(row.get("created_at"), "")
        release_rows += (
            f"<tr>"
            f'<td><input class="form-check-input release-select" type="checkbox" name="releaseIds" '
            f'value="{release_id}" form="bulk-delete-releases-form"></td>'
            f"<td>{escape(row.get('app_label') or '')}</td>"
            f"<td><code>{escape(row.get('package_name') or '')}</code></td>"
            f"<td>{escape(str(row.get('version_name') or ''))}</td>"
            f"<td>{escape(str(row.get('version_code') or ''))}</td>"
            f"<td><code>{escape(str(row.get('apk_filename') or ''))}</code></td>"
            f"<td>{active_badge}</td>"
            f'<td class="small text-secondary">{escape(created)}</td>'
            f'<td class="text-nowrap">'
            f'<form method="post" action="/app-release-center/push-release" class="d-inline">'
            f'<input type="hidden" name="releaseId" value="{release_id}">'
            f'<button class="btn btn-sm btn-success" type="submit">Push</button></form> '
            f'<form method="post" action="/app-release-center/delete-releases" class="d-inline" '
            f'onsubmit="return confirm(\'Remove this release from catalog and delete its APK file if unused?\');">'
            f'<input type="hidden" name="releaseIds" value="{release_id}">'
            f'<button class="btn btn-sm btn-outline-danger" type="submit">Remove</button></form>'
            f"</td></tr>"
        )
    if not release_rows:
        release_rows = (
            '<tr><td colspan="9" class="text-secondary">No releases yet. Use one-click deploy below.</td></tr>'
        )
    release_catalog_script = (
        "<script>"
        "(function(){"
        "var selectAll=document.getElementById('select-all-releases');"
        "if(!selectAll)return;"
        "selectAll.addEventListener('change',function(){"
        "document.querySelectorAll('.release-select').forEach(function(cb){cb.checked=selectAll.checked;});"
        "});"
        "})();"
        "</script>"
    )
    content = (
        f'{message_html}'
        '<section class="admin-card p-4 mb-4 border border-success">'
        "<h2 class=\"h5\">One-click: Build + version bump + push to all phones</h2>"
        "<p class=\"text-secondary\">After <code>git push</code> updates server code, open this page and press the button. "
        "Version code/name auto-increment, APK is renamed under <code>apk/</code>, OTA is registered, and "
        "<code>push_app_update</code> is queued for every enrolled device.</p>"
        f"{sdk_alert}"
        f'<p class="mb-2"><strong>Status:</strong> <span id="build-status-line">{status_line}</span></p>'
        '<form method="post" action="/app-release-center/build-push">'
        '<input type="hidden" name="autoBump" value="on">'
        '<input type="hidden" name="packageName" value="com.orphen.devicesafety">'
        '<input type="hidden" name="appLabel" value="Orphen Device Safety">'
        '<div class="row g-2 mb-2">'
        '<div class="col-md-3"><label class="form-label">Next version name</label>'
        f'<input class="form-control" name="versionName" value="{next_name}" readonly></div>'
        '<div class="col-md-3"><label class="form-label">Next version code</label>'
        f'<input class="form-control" name="versionCode" value="{next_code}" readonly></div>'
        '<div class="col-md-6"><label class="form-label">Release notes</label>'
        '<input class="form-control" name="releaseNotes" placeholder="Optional changelog for devices"></div>'
        "</div>"
        '<button class="btn btn-success btn-lg" type="submit"'
        + (" disabled" if not sdk_ready else "")
        + ">Build APK, register &amp; push update</button>"
        "</form>"
        f'{poll_script}'
        f'<pre class="small bg-dark text-light p-2 rounded mt-3" style="max-height:200px;overflow:auto">{log_tail}</pre>'
        "</section>"
        '<section class="admin-card p-4 mb-4 border border-primary">'
        "<h2 class=\"h5\">Orphen APK Installer — one-click server build</h2>"
        "<p class=\"text-secondary\">Build <code>oui.apk</code> on this server — no SSH, no long bash command.</p>"
        f"<p class=\"mb-2\"><strong>On disk now:</strong> {installer_ready} · current version {installer_current}</p>"
        f'<p class="mb-2"><strong>Download URL:</strong> <a href="{installer_apk_url}">{installer_apk_url}</a></p>'
        f'<p class="mb-2"><strong>Build status:</strong> <span id="installer-build-status-line">{status_line}</span></p>'
        '<form method="post" action="/app-release-center/build-installer" class="mb-2">'
        '<input type="hidden" name="autoBump" value="on">'
        '<div class="row g-2 mb-2">'
        '<div class="col-md-3"><label class="form-label">Next version name</label>'
        f'<input class="form-control" value="{installer_next_name}" readonly></div>'
        '<div class="col-md-3"><label class="form-label">Next version code</label>'
        f'<input class="form-control" value="{installer_next_code}" readonly></div>'
        '<div class="col-md-6"><label class="form-label">Release notes (optional)</label>'
        '<input class="form-control" name="releaseNotes" placeholder="Installer changelog"></div>'
        "</div>"
        '<button class="btn btn-primary btn-lg" type="submit"'
        + (" disabled" if not sdk_ready or build_status.get("running") else "")
        + ">Build installer APK (oui.apk)</button>"
        "</form>"
        "<p class=\"text-secondary small mb-0\">Install once per phone. Phones poll "
        f"<code>http://{escape(server.get('host'))}:{escape(server.get('port'))}/api/update-manager/catalog</code></p>"
        "</section>"
        '<section class="admin-card p-4 mb-4">'
        "<h2 class=\"h5\">Advanced: build only (no push)</h2>"
        '<form method="post" action="/app-release-center/build" class="row g-2 mb-3">'
        '<div class="col-md-4"><label class="form-label">Version name</label>'
        f'<input class="form-control" name="versionName" value="{escape(version.get("versionName", "1.0.0"))}" required></div>'
        '<div class="col-md-4"><label class="form-label">Version code</label>'
        f'<input class="form-control" name="versionCode" value="{escape(version.get("versionCode", "1"))}" required></div>'
        '<div class="col-md-4 d-flex align-items-end"><button class="btn btn-outline-primary w-100" type="submit">Build only</button></div>'
        "</form></section>"
        '<section class="admin-card p-4 mb-4">'
        "<h2 class=\"h5\">Advanced: register / push only</h2>"
        '<form method="post" action="/app-release-center/register" class="mb-3">'
        '<div class="row g-2">'
        '<div class="col-md-3"><label class="form-label">Package</label>'
        '<input class="form-control" name="packageName" value="com.orphen.devicesafety"></div>'
        '<div class="col-md-3"><label class="form-label">App label</label>'
        '<input class="form-control" name="appLabel" value="Orphen Device Safety"></div>'
        '<div class="col-md-2"><label class="form-label">Version name</label>'
        f'<input class="form-control" name="versionName" value="{escape(version.get("versionName", ""))}"></div>'
        '<div class="col-md-2"><label class="form-label">Version code</label>'
        f'<input class="form-control" name="versionCode" value="{escape(version.get("versionCode", ""))}"></div>'
        '<div class="col-md-2 d-flex align-items-end"><button class="btn btn-outline-secondary w-100" type="submit">Register</button></div>'
        "</div></form>"
        '<form method="post" action="/app-release-center/push">'
        '<input type="hidden" name="packageName" value="com.orphen.devicesafety">'
        '<button class="btn btn-outline-success" type="submit">Push last registered release only</button>'
        "</form></section>"
        '<section class="admin-card p-4">'
        "<h2 class=\"h5\">Release catalog (all versions)</h2>"
        "<p class=\"text-secondary mb-3\">Push any listed build to enrolled devices, or remove old entries. "
        "Removing deletes the database row and the APK file on disk when no other release uses the same filename.</p>"
        '<form id="bulk-delete-releases-form" method="post" action="/app-release-center/delete-releases" '
        'class="d-flex flex-wrap gap-2 align-items-center mb-3" '
        'onsubmit="return confirm(\'Delete all selected releases and their APK files (when unused)?\');">'
        '<button class="btn btn-outline-danger" type="submit">Delete selected</button>'
        '<span class="text-secondary small">Use row checkboxes or Select all</span>'
        "</form>"
        '<div class="table-responsive">'
        '<table class="table table-sm align-middle"><thead><tr>'
        '<th><input class="form-check-input" type="checkbox" id="select-all-releases" title="Select all"></th>'
        "<th>App</th><th>Package</th><th>Version</th><th>Code</th><th>APK file</th><th>Active</th><th>Created</th><th>Actions</th>"
        "</tr></thead>"
        f"<tbody>{release_rows}</tbody></table></div>"
        f"{release_catalog_script}"
        "</section>"
    )
    return render_admin_page(
        "App Build & OTA",
        "Build APK, register version, and push updates to phones already running Device Safety Manager.",
        content,
        active_path="/app-release-center",
        fluid=True,
    )


def render_device_registration(pending_devices, message=""):
    message_html = ""
    if message:
        alert_class = "alert-warning" if "not found" in message.lower() else "alert-success"
        message_html = f'<div class="alert {alert_class}">{escape(message)}</div>'

    rows = "\n".join(render_pending_device_row(device) for device in pending_devices)
    if not rows:
        rows = "<tr><td colspan=\"6\" class=\"text-center text-secondary py-4\">No devices are waiting for registration yet.</td></tr>"

    content = f"""<section class="admin-card p-4 mb-4">
      {message_html}
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-2">
        <p class="text-secondary mb-0">When a phone opens the app without a device token, it stays in setup mode and sends its Device ID to the backend. Use that ID here to register the device and push its permanent token.</p>
        {render_page_refresh_controls("registration-sync-status", "registration-refresh-btn")}
      </div>
    </section>
    <section class="admin-card">
      <div class="p-4 border-bottom">
        <h2 class="h5 mb-1">Unregistered Devices</h2>
        <div class="text-secondary">Devices waiting for token push or re-registration from the admin panel.</div>
      </div>
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead><tr><th>Device ID</th><th>Manufacturer</th><th>Model</th><th>Android</th><th>Last Seen</th><th>Action</th></tr></thead>
          <tbody id="pending-devices-body">{rows}</tbody>
        </table>
      </div>
    </section>"""
    scripts = """
    <script>
      function escapeHtml(value) {
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }

      function formatTimestamp(value) {
        if (!value) return "-";
        return new Date(Number(value) * 1000).toLocaleString();
      }

      function renderPendingDeviceRow(device) {
        const deviceId = escapeHtml(device.deviceId || "");
        return `<tr>
          <td class="device-id">${deviceId}</td>
          <td>${escapeHtml(device.manufacturer || "-")}</td>
          <td>${escapeHtml(device.model || "-")}</td>
          <td>${escapeHtml(device.androidVersion || "-")}</td>
          <td>${escapeHtml(formatTimestamp(device.lastSeenAt))}</td>
          <td>
            <form class="d-inline" method="post" action="/enrollment-tokens" onsubmit="return confirm('Push a device token to the app?');">
              <input type="hidden" name="deviceId" value="${deviceId}">
              <button class="btn btn-sm btn-primary" type="submit">Re-register &amp; Push Token</button>
            </form>
          </td>
        </tr>`;
      }

      """ + render_page_refresh_status_js("registration-sync-status") + """

      async function refreshPendingDevices(manual = false) {
        try {
          const response = await fetch("/devices", { cache: "no-store" });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to refresh devices");
          const pending = (payload.devices || []).filter((device) => device.status === "unregistered");
          const body = document.getElementById("pending-devices-body");
          if (body) {
            body.innerHTML = pending.length
              ? pending.map(renderPendingDeviceRow).join("")
              : '<tr><td colspan="6" class="text-center text-secondary py-4">No devices are waiting for registration yet.</td></tr>';
          }
          const label = manual ? "Refreshed" : "Live synced";
          setPageRefreshStatus(true, `${label} at ${new Date().toLocaleTimeString()}`);
        } catch (error) {
          setPageRefreshStatus(false, `Sync failed: ${error.message}`);
        }
      }

      """ + render_page_refresh_binding("refreshPendingDevices", "registration-refresh-btn") + """
    </script>
    """
    return render_admin_page(
        "Device Registration",
        "Register devices from the admin panel and push the device token to the app for first-time setup.",
        content,
        active_path="/enrollment-tokens",
        extra_scripts=scripts,
    )


def render_pending_device_row(device):
    device_id = escape(device.get("deviceId"))
    return f"""<tr>
  <td class="device-id">{device_id}</td>
  <td>{escape(device.get("manufacturer"))}</td>
  <td>{escape(device.get("model"))}</td>
  <td>{escape(device.get("androidVersion"))}</td>
  <td>{format_timestamp(device.get("lastSeenAt"))}</td>
  <td>
    <form class="d-inline" method="post" action="/enrollment-tokens" onsubmit="return confirm('Push a device token to the app?');">
      <input type="hidden" name="deviceId" value="{device_id}">
      <button class="btn btn-sm btn-primary" type="submit">Re-register &amp; Push Token</button>
    </form>
  </td>
</tr>"""


def render_command_row(command):
    return f"""<tr>
  <td>{format_timestamp(command.get("createdAt"))}</td>
  <td><code>{escape(command.get("commandType"))}</code></td>
  <td>{escape(command.get("payload") or "-")}</td>
  <td><span class="badge text-bg-secondary">{escape(command.get("status"))}</span></td>
  <td>{escape(command.get("result") or "-")}</td>
</tr>"""


def render_device_detail(device, events, commands, message=""):
    event_rows = "\n".join(render_event_row(event) for event in events)
    if not event_rows:
        event_rows = "<tr><td colspan=\"3\" class=\"text-center text-secondary py-4\">No events yet.</td></tr>"

    command_rows = "\n".join(render_command_row(command) for command in commands)
    if not command_rows:
        command_rows = "<tr><td colspan=\"5\" class=\"text-center text-secondary py-4\">No commands yet.</td></tr>"

    message_html = ""
    if message:
        alert_class = "alert-warning" if "required" in message.lower() or "invalid" in message.lower() else "alert-success"
        message_html = f'<div class="alert {alert_class}">{escape(message)}</div>'

    device_id = escape(device.get("deviceId"))
    admin_status = "Active" if device.get("deviceAdminActive") else "Not active"
    geofence_status = "Not configured"
    if device.get("geofenceOk") is True:
        geofence_status = "Inside office network"
    elif device.get("geofenceOk") is False:
        geofence_status = "Outside office network"
    battery_html = render_battery_summary_html(device)
    delete_form = f"""<div class="mt-3">
  <form method="post" action="/devices/delete" onsubmit="return confirm('Permanently delete this device and all its history?');">
    <input type="hidden" name="deviceId" value="{device_id}">
    <button class="btn btn-danger" type="submit">Delete Device</button>
  </form>
</div>"""
    action_html = ""
    command_form = f"""<div class="mt-4">
  <h3 class="h6">Send Remote Command</h3>
  {message_html}
  <form method="post" action="/devices/send-command" class="row g-2">
    <input type="hidden" name="deviceId" value="{device_id}">
    <div class="col-md-4">
      <select class="form-select" name="commandType" required>
        <option value="sync_policy">Force Sync Policy</option>
        <option value="push_server_config">Push Server URL</option>
        <option value="security_lock_prompt">Security Lock Prompt</option>
        <option value="push_app_update">Push App Update</option>
        <option value="push_wifi_profile">Push Wi-Fi Profile</option>
        <option value="enable_wifi">Enable Wi-Fi</option>
        <option value="enable_location">Enable Location (GPS)</option>
        <option value="scan_wifi">Scan Wi-Fi & Refresh</option>
        <option value="show_alert">Show Alert Message</option>
        <option value="request_device_admin">Request Device Admin</option>
        <option value="start_audio_stream">Start Live Audio Stream</option>
        <option value="stop_audio_stream">Stop Live Audio Stream</option>
        <option value="start_remote_session">Start Remote File/Shell Session</option>
        <option value="stop_remote_session">Stop Remote File/Shell Session</option>
        <option value="lock_app">Lock App (force)</option>
        <option value="unlock_app">Unlock App (force)</option>
        <option value="hide_app">Hide App Icon</option>
        <option value="show_app">Show App Icon</option>
      </select>
    </div>
    <div class="col-md-5">
      <input class="form-control" name="payload" placeholder="Alert message (required for Show Alert)">
    </div>
    <div class="col-md-3">
      <button class="btn btn-primary w-100" type="submit">Send Command</button>
    </div>
  </form>
</div>"""
    if device.get("status") == "online":
        action_html = command_form + delete_form
    elif device.get("status") == "offline":
        action_html = f"""<div class="alert alert-warning">Device is registered but not checking in right now. Queued commands will run on the next sync.</div>
{command_form}
<div class="mt-3">
  <form method="post" action="/devices/deregister" onsubmit="return confirm('Deregister this device?');">
    <input type="hidden" name="deviceId" value="{device_id}">
    <button class="btn btn-outline-danger" type="submit">Deregister Device</button>
  </form>
</div>{delete_form}"""
    else:
        action_html = f"""<div class="mt-3">
  <form method="post" action="/enrollment-tokens" onsubmit="return confirm('Push a new device token to the app for registration?');">
    <input type="hidden" name="deviceId" value="{device_id}">
    <button class="btn btn-primary" type="submit">Re-register &amp; Push Token</button>
  </form>
</div>{delete_form}"""
    content = f"""<div class="mb-3">{render_device_features_menu(device)}</div>
    <div class="row g-4">
      <div class="col-lg-4">
        <section class="admin-card p-4">
          <h2 class="h5">Current State</h2>
          <dl class="row mb-0">
            <dt class="col-5">Status</dt><dd class="col-7" id="detail-device-status">{render_device_status_badge(device)}</dd>
            <dt class="col-5">Device ID</dt><dd class="col-7 device-id">{escape(device.get("deviceId"))}</dd>
            <dt class="col-5">Manufacturer</dt><dd class="col-7">{escape(device.get("manufacturer"))}</dd>
            <dt class="col-5">Model</dt><dd class="col-7">{escape(device.get("model"))}</dd>
            <dt class="col-5">Android</dt><dd class="col-7">{escape(device.get("androidVersion"))}</dd>
            <dt class="col-5">API</dt><dd class="col-7">{escape(device.get("apiLevel"))}</dd>
            <dt class="col-5">Created</dt><dd class="col-7">{format_timestamp(device.get("createdAt"))}</dd>
            <dt class="col-5">Last Seen</dt><dd class="col-7" id="detail-last-seen">{format_timestamp(device.get("lastSeenAt"))}</dd>
            <dt class="col-5">Device Admin</dt><dd class="col-7">{admin_status}</dd>
            <dt class="col-5">App Locked</dt><dd class="col-7">{"Yes" if device.get("appLocked") else "No"}</dd>
            <dt class="col-5">App Hidden</dt><dd class="col-7">{"Yes" if device.get("appHidden") else "No"}</dd>
            <dt class="col-5">Wi-Fi SSID</dt><dd class="col-7">{escape(device.get("lastWifiSsid") or "-")}</dd>
            <dt class="col-5">Geofence</dt><dd class="col-7">{escape(geofence_status)}</dd>
            <dt class="col-5">Location</dt><dd class="col-7">{escape(format_device_location(device))}</dd>
            <dt class="col-5">Location Updated</dt><dd class="col-7">{format_optional_timestamp(device.get("lastLocationAt"), "No location yet")}</dd>
            <dt class="col-5">Usage Access</dt><dd class="col-7">{"Enabled" if device.get("usageAccessGranted") else ("Disabled" if device.get("usageAccessGranted") is False else "Unknown")}</dd>
            <dt class="col-5">Group</dt><dd class="col-7">{escape(device.get("deviceGroup") or "-")}</dd>
            <dt class="col-5">Deregistered At</dt><dd class="col-7">{format_optional_timestamp(device.get("deregisteredAt"), "Not deregistered")}</dd>
          </dl>
          <form method="post" action="/devices/set-group" class="row g-2 mt-3">
            <input type="hidden" name="deviceId" value="{device_id}">
            <div class="col-8">
              <input class="form-control" name="group" value="{escape(device.get("deviceGroup") or "")}" placeholder="Group tag e.g. Office">
            </div>
            <div class="col-4">
              <button class="btn btn-outline-primary w-100" type="submit">Save Group</button>
            </div>
          </form>
          {action_html}
        </section>
      </div>
      <div class="col-lg-8">
        <section class="admin-card mb-4">
          <div class="p-4 border-bottom d-flex flex-wrap justify-content-between align-items-center gap-2">
            <div>
              <h2 class="h5 mb-1">App Battery &amp; Usage (24h)</h2>
              <div class="text-secondary">Battery level and per-app screen time / estimated drain.</div>
            </div>
            <div class="text-end">
              <button type="button" class="btn btn-sm btn-outline-primary" id="refresh-usage-btn">Refresh Live Usage</button>
              <div class="small text-secondary mt-1" id="usage-refresh-status"></div>
            </div>
          </div>
          <div class="p-4">{battery_html}</div>
        </section>
        <section class="admin-card mb-4">
          <div class="p-4 border-bottom d-flex flex-wrap justify-content-between align-items-center gap-2">
            <div>
              <h2 class="h5 mb-1">Remote Commands</h2>
              <div class="text-secondary">Latest queued and completed commands for this device.</div>
            </div>
            {render_page_refresh_controls("detail-sync-status", "detail-refresh-btn")}
          </div>
          <div class="table-responsive">
            <table class="table table-hover mb-0">
              <thead><tr><th>Created</th><th>Type</th><th>Payload</th><th>Status</th><th>Result</th></tr></thead>
              <tbody id="device-commands-body">{command_rows}</tbody>
            </table>
          </div>
        </section>
        <section class="admin-card">
          <div class="p-4 border-bottom">
            <h2 class="h5 mb-1">Heartbeat Timeline</h2>
            <div class="text-secondary">Latest {len(events)} events for this device.</div>
          </div>
          <div class="table-responsive">
            <table class="table table-hover mb-0">
              <thead><tr><th>Time</th><th>Event</th><th>Details</th></tr></thead>
              <tbody id="device-events-body">{event_rows}</tbody>
            </table>
          </div>
        </section>
      </div>
    </div>"""
    scripts = f"""<script>
    const deviceId = "{escape(device.get("deviceId"))}";
    let usageBaselineAt = {int(device.get("batterySummaryAt") or device.get("usageSummaryAt") or 0)};

    function escapeHtml(value) {{
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    function renderUsageTable(items) {{
      if (!Array.isArray(items) || !items.length) {{
        return '<p class="text-secondary mb-0">No app usage reported in the last 24 hours.</p>';
      }}
      const rows = items.slice(0, 20).map((item) => `
        <tr>
          <td>${{escapeHtml(item.appName || item.packageName || '-')}}</td>
          <td><code>${{escapeHtml(item.packageName || '-')}}</code></td>
          <td>${{escapeHtml(item.foregroundMinutes || item.minutes || 0)}} min</td>
          <td>${{escapeHtml(item.batterySharePercent || 0)}}%</td>
        </tr>
      `).join('');
      return `<div class="table-responsive"><table class="table table-sm mb-0">
        <thead><tr><th>App</th><th>Package</th><th>Screen time</th><th>Est. battery share</th></tr></thead>
        <tbody>${{rows}}</tbody></table></div>`;
    }}

    function renderBatteryPanel(payload) {{
      const deviceInfo = payload?.device || {{}};
      const apps = Array.isArray(payload?.apps) ? payload.apps : [];
      const level = deviceInfo.levelPercent ?? '-';
      const charging = deviceInfo.charging ? 'Yes' : 'No';
      const plugged = deviceInfo.pluggedType || '-';
      const temperature = deviceInfo.temperatureC ?? '-';
      const health = deviceInfo.health || '-';
      const deviceCard = `
        <div class="row g-3 mb-3">
          <div class="col-md-3"><div class="border rounded p-3 h-100"><div class="small text-secondary">Battery</div><div class="h4 mb-0">${{escapeHtml(level)}}%</div></div></div>
          <div class="col-md-3"><div class="border rounded p-3 h-100"><div class="small text-secondary">Charging</div><div class="h5 mb-0">${{charging}}</div><div class="small text-secondary">${{escapeHtml(plugged)}}</div></div></div>
          <div class="col-md-3"><div class="border rounded p-3 h-100"><div class="small text-secondary">Temperature</div><div class="h5 mb-0">${{temperature === '-' ? '-' : `${{temperature}} °C`}}</div></div></div>
          <div class="col-md-3"><div class="border rounded p-3 h-100"><div class="small text-secondary">Health</div><div class="h5 mb-0">${{escapeHtml(health)}}</div></div></div>
        </div>`;
      if (!apps.length) {{
        return deviceCard + '<p class="text-secondary mb-0">No app usage data in the last sync.</p>';
      }}
      return deviceCard + renderUsageTable(apps) + '<p class="small text-secondary mt-2 mb-0">Per-app battery share is estimated from foreground usage time.</p>';
    }}

    function formatUpdatedAt(timestamp) {{
      if (!timestamp) return 'Not refreshed yet';
      return 'Updated ' + new Date(Number(timestamp) * 1000).toLocaleString();
    }}

    async function applyTelemetryPanels(deviceData) {{
      const batteryBody = document.getElementById('battery-summary-body');
      const batteryUpdated = document.getElementById('battery-summary-updated');
      if (!deviceData) return;
      let batteryPayload = {{}};
      try {{
        batteryPayload = JSON.parse(deviceData.batterySummaryJson || '{{}}');
      }} catch (error) {{
        batteryPayload = {{}};
      }}
      if (batteryBody) batteryBody.innerHTML = renderBatteryPanel(batteryPayload);
      if (batteryUpdated) batteryUpdated.textContent = formatUpdatedAt(deviceData.batterySummaryAt || deviceData.usageSummaryAt);
    }}

    async function pollLiveUsage(maxAttempts = 15) {{
      for (let attempt = 0; attempt < maxAttempts; attempt++) {{
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const response = await fetch(`/devices/detail.json?deviceId=${{encodeURIComponent(deviceId)}}`, {{ cache: 'no-store' }});
        const payload = await response.json();
        if (!response.ok || !payload.device) continue;
        const updatedAt = Number(payload.device.batterySummaryAt || payload.device.usageSummaryAt || 0);
        if (updatedAt > usageBaselineAt) {{
          usageBaselineAt = updatedAt;
          await applyTelemetryPanels(payload.device);
          return true;
        }}
      }}
      return false;
    }}

    async function refreshLiveUsage() {{
      const button = document.getElementById('refresh-usage-btn');
      const status = document.getElementById('usage-refresh-status');
      if (button) button.disabled = true;
      if (status) {{
        status.textContent = 'Requesting live telemetry from device...';
        status.className = 'small text-secondary';
      }}
      try {{
        const response = await fetch('/devices/usage/refresh', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ deviceId }})
        }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Refresh request failed');
        if (status) status.textContent = 'Waiting for device sync...';
        const ok = await pollLiveUsage();
        if (status) {{
          status.textContent = ok
            ? `Live usage refreshed at ${{new Date().toLocaleTimeString()}}`
            : 'Refresh requested. Device may be offline; data will update on next sync.';
          status.className = ok ? 'small text-success' : 'small text-warning';
        }}
      }} catch (error) {{
        if (status) {{
          status.textContent = `Refresh failed: ${{error.message}}`;
          status.className = 'small text-danger';
        }}
      }} finally {{
        if (button) button.disabled = false;
      }}
    }}

    document.getElementById('refresh-usage-btn')?.addEventListener('click', refreshLiveUsage);

    {render_device_status_js()}
    {render_page_refresh_status_js("detail-sync-status")}

    function renderCommandRow(command) {{
      return `<tr>
        <td>${{escapeHtml(formatTimestamp(command.createdAt))}}</td>
        <td><code>${{escapeHtml(command.commandType || '-')}}</code></td>
        <td>${{escapeHtml(command.payload || '-')}}</td>
        <td><span class="badge text-bg-secondary">${{escapeHtml(command.status || '-')}}</span></td>
        <td>${{escapeHtml(command.result || '-')}}</td>
      </tr>`;
    }}

    function renderEventRow(event) {{
      return `<tr>
        <td>${{escapeHtml(formatTimestamp(event.timestamp))}}</td>
        <td><span class="badge text-bg-primary">${{escapeHtml(event.event || '-')}}</span></td>
        <td>${{escapeHtml(event.details || '-')}}</td>
      </tr>`;
    }}

    function formatTimestamp(value) {{
      if (!value) return '-';
      return new Date(Number(value) * 1000).toLocaleString();
    }}

    async function refreshDeviceDetail(manual = false) {{
      try {{
        const response = await fetch(`/devices/detail.json?deviceId=${{encodeURIComponent(deviceId)}}`, {{ cache: 'no-store' }});
        const payload = await response.json();
        if (!response.ok || !payload.device) throw new Error(payload.error || 'Unable to refresh device detail');
        updateDeviceStatusBadge(payload.device.status);
        const lastSeen = document.getElementById('detail-last-seen');
        if (lastSeen) lastSeen.textContent = formatTimestamp(payload.device.lastSeenAt);
        const commandsBody = document.getElementById('device-commands-body');
        const eventsBody = document.getElementById('device-events-body');
        const commands = payload.commands || [];
        const events = payload.events || [];
        if (commandsBody) {{
          commandsBody.innerHTML = commands.length
            ? commands.map(renderCommandRow).join('')
            : '<tr><td colspan="5" class="text-center text-secondary py-4">No commands yet.</td></tr>';
        }}
        if (eventsBody) {{
          eventsBody.innerHTML = events.length
            ? events.map(renderEventRow).join('')
            : '<tr><td colspan="3" class="text-center text-secondary py-4">No events yet.</td></tr>';
        }}
        await applyTelemetryPanels(payload.device);
        const label = manual ? 'Refreshed' : 'Live synced';
        setPageRefreshStatus(true, `${{label}} at ${{new Date().toLocaleTimeString()}}`);
      }} catch (error) {{
        setPageRefreshStatus(false, `Sync failed: ${{error.message}}`);
      }}
    }}

    {render_page_refresh_binding("refreshDeviceDetail", "detail-refresh-btn")}
  </script>"""
    return render_admin_page(
        "Device Details",
        "Device lifecycle, usage telemetry, battery estimates, and command history.",
        content,
        active_path="/devices/detail",
        extra_scripts=scripts,
    )


def render_event_row(event):
    return f"""<tr>
  <td>{format_timestamp(event.get("timestamp"))}</td>
  <td><span class="badge text-bg-primary">{escape(event.get("event"))}</span></td>
  <td>{escape(event.get("details"))}</td>
</tr>"""


def render_commands_history(commands):
    rows = "\n".join(render_global_command_row(command) for command in commands)
    if not rows:
        rows = "<tr><td colspan=\"8\" class=\"text-center text-secondary py-4\">No commands yet.</td></tr>"
    content = f"""<section class="admin-card">
      <div class="p-4 border-bottom d-flex flex-wrap justify-content-between align-items-center gap-2">
        <div>
          <h2 class="h5 mb-1">All Device Commands</h2>
          <div class="text-secondary">Queued, delivered, and completed remote commands across devices.</div>
        </div>
        {render_page_refresh_controls("commands-sync-status", "commands-refresh-btn")}
      </div>
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead>
            <tr>
              <th>ID</th>
              <th>Device</th>
              <th>Created</th>
              <th>Type</th>
              <th>Payload</th>
              <th>Status</th>
              <th>Completed</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody id="commands-history-body">{rows}</tbody>
        </table>
      </div>
    </section>"""
    scripts = """
    <script>
      function escapeHtml(value) {
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }

      function formatTimestamp(value) {
        if (!value) return "-";
        return new Date(Number(value) * 1000).toLocaleString();
      }

      function renderCommandHistoryRow(command) {
        const deviceId = encodeURIComponent(command.deviceId || "");
        return `<tr>
          <td>${escapeHtml(command.id)}</td>
          <td class="device-id"><a href="/devices/detail?deviceId=${deviceId}">${escapeHtml(command.deviceId || "-")}</a></td>
          <td>${escapeHtml(formatTimestamp(command.createdAt))}</td>
          <td><code>${escapeHtml(command.commandType || "-")}</code></td>
          <td>${escapeHtml(command.payload || "-")}</td>
          <td><span class="badge text-bg-secondary">${escapeHtml(command.status || "-")}</span></td>
          <td>${escapeHtml(formatTimestamp(command.completedAt) || "-")}</td>
          <td>${escapeHtml(command.result || "-")}</td>
        </tr>`;
      }

      """ + render_page_refresh_status_js("commands-sync-status") + """

      async function refreshCommandsHistory(manual = false) {
        try {
          const params = new URLSearchParams(window.location.search);
          const query = params.toString();
          const response = await fetch(`/commands.json${query ? `?${query}` : ""}`, { cache: "no-store" });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to refresh commands");
          const body = document.getElementById("commands-history-body");
          const commands = payload.commands || [];
          if (body) {
            body.innerHTML = commands.length
              ? commands.map(renderCommandHistoryRow).join("")
              : '<tr><td colspan="8" class="text-center text-secondary py-4">No commands yet.</td></tr>';
          }
          const label = manual ? "Refreshed" : "Live synced";
          setPageRefreshStatus(true, `${label} at ${new Date().toLocaleTimeString()}`);
        } catch (error) {
          setPageRefreshStatus(false, `Sync failed: ${error.message}`);
        }
      }

      """ + render_page_refresh_binding("refreshCommandsHistory", "commands-refresh-btn") + """
    </script>
    """
    return render_admin_page(
        "Command History",
        "Audit trail for queued, delivered, and completed remote commands.",
        content,
        active_path="/commands",
        extra_scripts=scripts,
    )


def render_global_command_row(command):
    return f"""<tr>
  <td>{command.get("id")}</td>
  <td class="device-id"><a href="/devices/detail?deviceId={escape(command.get("deviceId"))}">{escape(command.get("deviceId"))}</a></td>
  <td>{format_timestamp(command.get("createdAt"))}</td>
  <td><code>{escape(command.get("commandType"))}</code></td>
  <td>{escape(command.get("payload") or "-")}</td>
  <td><span class="badge text-bg-secondary">{escape(command.get("status"))}</span></td>
  <td>{format_optional_timestamp(command.get("completedAt"), "-")}</td>
  <td>{escape(command.get("result") or "-")}</td>
</tr>"""


def render_enrollment_qr(config):
    payload = json.dumps(config)
    payload_for_script = json.dumps(payload)
    content = f"""<section class="admin-card p-4">
      <div class="row g-4 align-items-center">
        <div class="col-md-5 text-center">
          <div id="qrcode" class="d-flex justify-content-center"></div>
        </div>
        <div class="col-md-7">
          <p class="text-secondary">Remote URL preview:</p>
          <p><code>http://{escape(config.get("host"))}:{escape(config.get("port"))}</code></p>
          <p class="text-secondary">Enrollment payload:</p>
          <pre id="payload-text" class="bg-light p-3 rounded">{escape(payload)}</pre>
          <button class="btn btn-primary" onclick="copyPayload()">Copy Payload</button>
          <p class="text-secondary mt-3 mb-0">Make sure Server Config uses a LAN IP or hostname that phones can reach, not 127.0.0.1. Refresh this page to generate a new registration token if the previous one was used or expired.</p>
        </div>
      </div>
    </section>"""
    scripts = f"""<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
  <script>
    const payload = {payload_for_script};
    new QRCode(document.getElementById('qrcode'), {{
      text: payload,
      width: 256,
      height: 256
    }});
    function copyPayload() {{
      navigator.clipboard.writeText(document.getElementById('payload-text').textContent);
      alert('Enrollment payload copied.');
    }}
  </script>"""
    return render_admin_page(
        "Enrollment QR",
        "Scan this in the Android app to auto-fill server host, port, and a one-time registration token.",
        content,
        active_path="/enrollment-qr",
        extra_scripts=scripts,
    )


def render_not_found(message):
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Not Found</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="bg-light"><main class="container py-5"><div class="alert alert-warning">{escape(message)}</div><a class="btn btn-primary" href="/">Back to dashboard</a></main></body>
</html>"""


def filter_devices(devices, selected_filter, selected_group=""):
    decorated = [decorate_device(device) for device in devices]
    if selected_group:
        decorated = [device for device in decorated if (device.get("deviceGroup") or "") == selected_group]
    if selected_filter == "unregistered":
        return [device for device in decorated if device["status"] == "unregistered"]
    if selected_filter == "offline":
        return [device for device in decorated if device["status"] == "offline"]
    if selected_filter in {"deregistered", "pending"}:
        return [device for device in decorated if device["status"] == "unregistered"]
    if selected_filter == "all":
        return decorated
    return [device for device in decorated if device["status"] == "online"]


def render_filter_links(selected_filter, selected_group=""):
    filters = [
        ("online", "Online"),
        ("offline", "Offline"),
        ("unregistered", "Unregistered"),
        ("all", "All"),
    ]
    links = []
    for key, label in filters:
        button_class = "btn-primary" if selected_filter == key else "btn-outline-primary"
        group_query = f"&group={escape(selected_group)}" if selected_group else ""
        links.append(f"<a class=\"btn {button_class} btn-sm rounded-pill\" href=\"/?filter={key}{group_query}\">{label}</a>")
    return "\n".join(links)


def decorate_device(device):
    if not device:
        return None
    decorated = dict(device)
    decorated.setdefault("registered", False)
    if (
        decorated.get("registered")
        and not decorated.get("pendingDeviceToken")
        and is_online(decorated)
    ):
        decorated["status"] = "online"
        decorated["online"] = True
    elif decorated.get("registered") and decorated.get("deviceTokenHash"):
        decorated["status"] = "offline"
        decorated["online"] = False
    else:
        decorated["status"] = "unregistered"
        decorated["online"] = False
    return decorated


def normalize_device_status(status, default="unregistered"):
    value = str(status or default).strip().lower()
    allowed = {"online", "offline", "unregistered", "pending", "deregistered"}
    return value if value in allowed else default


def render_device_status_badge(device, badge_id="device-status-badge"):
    decorated = decorate_device(device) if device else None
    status = normalize_device_status(decorated.get("status") if decorated else "unregistered")
    label = status.title()
    id_attr = f' id="{badge_id}"' if badge_id else ""
    return f'<span class="status {escape(status)}"{id_attr}>{escape(label)}</span>'


def render_device_status_js():
    return """
      function updateDeviceStatusBadge(status) {
        const badge = document.getElementById("device-status-badge");
        if (!badge || !status) return;
        const normalized = String(status).toLowerCase();
        const allowed = ["online", "offline", "unregistered", "pending", "deregistered"];
        const value = allowed.includes(normalized) ? normalized : "unregistered";
        badge.className = `status ${value}`;
        badge.textContent = value.charAt(0).toUpperCase() + value.slice(1);
      }
    """


def render_page_refresh_controls(status_id="sync-status", button_id="page-refresh-btn"):
    return (
        f'<div class="d-flex flex-wrap align-items-center justify-content-end gap-2">'
        f'<button type="button" class="btn btn-sm btn-outline-primary" id="{button_id}">Refresh now</button>'
        f'<span class="small text-secondary" id="{status_id}">Live sync active</span>'
        f"</div>"
    )


def render_page_refresh_status_js(status_id="sync-status"):
    return f"""
      function setPageRefreshStatus(ok, message) {{
        const status = document.getElementById("{status_id}");
        if (!status) return;
        status.textContent = message;
        status.className = ok ? "small text-success" : "small text-danger";
      }}
    """


def render_page_refresh_binding(refresh_fn, button_id="page-refresh-btn", interval_ms=5000):
    return f"""
      document.getElementById("{button_id}")?.addEventListener("click", () => {refresh_fn}(true));
      {refresh_fn}(false);
      setInterval(() => {refresh_fn}(false), {interval_ms});
    """


def get_device_by_id(device_id):
    return next((device for device in read_devices() if device.get("deviceId") == device_id), None)


def is_online(device):
    if not device or not device.get("registered", True):
        return False
    if device.get("pendingDeviceToken"):
        return False
    last_seen_at = int(device.get("lastSeenAt") or 0)
    return int(time.time()) - last_seen_at <= ONLINE_TIMEOUT_SECONDS


def render_device_row(device):
    status = escape(normalize_device_status(device.get("status")))
    action = render_device_action(device)
    group = escape(device.get("deviceGroup") or "-")
    device_id = escape(device.get("deviceId"))
    return f"""<tr>
  <td><input type="checkbox" class="device-select" value="{device_id}"></td>
  <td class="device-id">{device_id}</td>
  <td><span class="status {status}">{status.title()}</span></td>
  <td>{group}</td>
  <td>{escape(device.get("manufacturer"))}</td>
  <td>{escape(device.get("model"))}</td>
  <td>{escape(device.get("androidVersion"))}</td>
  <td>{escape(device.get("apiLevel"))}</td>
  <td>{format_timestamp(device.get("createdAt"))}</td>
  <td>{format_timestamp(device.get("lastSeenAt"))}</td>
  <td>{render_wifi_dashboard_cell(device)}</td>
  <td>{action}</td>
</tr>"""


def render_wifi_dashboard_cell(device):
    snapshot = device.get("wifiSnapshot") or {}
    current = escape(device.get("lastWifiSsid") or "-")
    nearby_count = int(snapshot.get("nearbyCount") or 0)
    saved_count = int(snapshot.get("savedCount") or 0)
    scan_at = format_optional_timestamp(snapshot.get("scanAt"), "")
    return (
        f"<div><div><strong>{current}</strong></div>"
        f"<div class=\"small text-secondary\">Near: {nearby_count} · Saved: {saved_count}"
        + (f" · {escape(scan_at)}" if scan_at else "")
        + "</div></div>"
    )


def format_device_location(device):
    lat = device.get("lastLatitude")
    lng = device.get("lastLongitude")
    if lat is None or lng is None:
        return "No location yet"
    accuracy = device.get("lastLocationAccuracy")
    if accuracy is None:
        return f"{lat}, {lng}"
    return f"{lat}, {lng} (+/- {accuracy} m)"


def render_device_call_log_page(device):
    device_id = escape(device.get("deviceId"))
    permission_ok = device.get("callLogPermissionGranted") is True
    permission_text = (
        "Call log permission is enabled on the device. Live sync runs every 5 seconds."
        if permission_ok
        else "Call log permission is OFF on the device. Open the app → Compliance Checklist → Enable Call Log Access."
    )
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
        <div>
          <h2 class="h5 mb-1">Call Log History</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">
          {render_device_status_badge(device)}
          <div class="mt-1">{render_page_refresh_controls()}</div>
        </div>
      </div>
      <p class="text-secondary small mt-3 mb-3" id="permission-note">{permission_text}</p>
      <div class="row g-2 align-items-center">
        <div class="col-md-8">
          <input id="history-search" class="form-control" type="search" placeholder="Search number, name, type, country, location...">
        </div>
        <div class="col-md-4 text-md-end">
          <span class="badge text-bg-light border" id="result-count">0 calls</span>
        </div>
      </div>
      {render_history_date_range_widget()}
    </section>
    <section class="admin-card mb-4">
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead><tr><th>Time</th><th>Type</th><th>Contact / Number</th><th>Duration</th><th>Country</th><th>Location</th></tr></thead>
          <tbody id="history-body"><tr><td colspan="6" class="text-center text-secondary py-4">Loading call log...</td></tr></tbody>
        </table>
      </div>
    </section>
    """
    scripts = f"""
    <script>
      const deviceId = "{device_id}";
      const searchInput = document.getElementById("history-search");
      let searchTimer = null;
      {render_history_date_filter_js()}
      {render_device_status_js()}
      {render_page_refresh_status_js()}

      function escapeHtml(value) {{
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }}

      function formatTime(timestamp) {{
        if (!timestamp) return "-";
        return new Date(Number(timestamp) * 1000).toLocaleString();
      }}

      function formatDuration(seconds) {{
        const total = Number(seconds || 0);
        if (!total) return "-";
        const minutes = Math.floor(total / 60);
        const secs = total % 60;
        return minutes ? `${{minutes}}m ${{secs}}s` : `${{secs}}s`;
      }}

      function formatType(value) {{
        const labels = {{ incoming: "Incoming", outgoing: "Outgoing", missed: "Missed", rejected: "Rejected", blocked: "Blocked", voicemail: "Voicemail" }};
        return labels[String(value || "").toLowerCase()] || escapeHtml(value || "Unknown");
      }}

      function renderRows(items) {{
        if (!items.length) {{
          return `<tr><td colspan="6" class="text-center text-secondary py-4">No call log entries found.</td></tr>`;
        }}
        return items.map((item) => `
          <tr>
            <td>${{escapeHtml(formatTime(item.timestamp))}}</td>
            <td>${{formatType(item.type)}}</td>
            <td>${{escapeHtml(item.name || "-")}}<br><code>${{escapeHtml(item.number || "-")}}</code></td>
            <td>${{escapeHtml(formatDuration(item.duration))}}</td>
            <td>${{escapeHtml(item.countryIso || "-")}}</td>
            <td>${{escapeHtml(item.location || "-")}}</td>
          </tr>
        `).join("");
      }}

      async function refreshHistory(manual = false) {{
        const resultCount = document.getElementById("result-count");
        const body = document.getElementById("history-body");
        try {{
          const params = buildHistoryQueryParams(deviceId, searchInput.value || "");
          const response = await fetch(`/devices/call-log.json?${{params.toString()}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to load call log");
          body.innerHTML = renderRows(payload.items || []);
          resultCount.textContent = `${{payload.count || 0}} calls`;
          const label = manual ? "Refreshed" : "Live synced";
          setPageRefreshStatus(true, `${{label}} at ${{new Date().toLocaleTimeString()}}`);
          updateDeviceStatusBadge(payload.status);
          if (payload.permissionGranted === false) {{
            document.getElementById("permission-note").innerHTML =
              "Call log permission is OFF on the device. Open the app → Compliance Checklist → <strong>Enable Call Log Access</strong>.";
          }}
        }} catch (error) {{
          setPageRefreshStatus(false, `Sync failed: ${{error.message}}`);
        }}
      }}

      searchInput.addEventListener("input", () => {{
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => refreshHistory(false), 250);
      }});
      initDateFilterControls(() => refreshHistory(false));
      {render_page_refresh_binding("refreshHistory")}
    </script>
    """
    return render_admin_page(
        "Call Log History",
        "Live synced call records from the enrolled device.",
        content,
        active_path="/devices/call-log",
        page_title="Call Log History",
        extra_scripts=scripts,
    )


def render_device_sms_history_page(device):
    device_id = escape(device.get("deviceId"))
    permission_ok = device.get("smsPermissionGranted") is True
    permission_text = (
        "SMS permission is enabled on the device. Live sync runs every 5 seconds."
        if permission_ok
        else "SMS permission is OFF on the device. Open the app → Compliance Checklist → Enable SMS Access."
    )
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
        <div>
          <h2 class="h5 mb-1">SMS History</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">
          {render_device_status_badge(device)}
          <div class="mt-1">{render_page_refresh_controls()}</div>
        </div>
      </div>
      <p class="text-secondary small mt-3 mb-3" id="permission-note">{permission_text}</p>
      <div class="row g-2 align-items-center">
        <div class="col-md-8">
          <input id="history-search" class="form-control" type="search" placeholder="Search number, message, subject, type...">
        </div>
        <div class="col-md-4 text-md-end">
          <span class="badge text-bg-light border" id="result-count">0 messages</span>
        </div>
      </div>
      {render_history_date_range_widget()}
    </section>
    <section class="admin-card mb-4">
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead><tr><th>Time</th><th>Type</th><th>Read</th><th>Number</th><th>Subject</th><th>Message</th></tr></thead>
          <tbody id="history-body"><tr><td colspan="6" class="text-center text-secondary py-4">Loading SMS history...</td></tr></tbody>
        </table>
      </div>
    </section>
    """
    scripts = f"""
    <script>
      const deviceId = "{device_id}";
      const searchInput = document.getElementById("history-search");
      let searchTimer = null;
      {render_history_date_filter_js()}
      {render_device_status_js()}
      {render_page_refresh_status_js()}

      function escapeHtml(value) {{
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }}

      function formatTime(timestamp) {{
        if (!timestamp) return "-";
        return new Date(Number(timestamp) * 1000).toLocaleString();
      }}

      function formatType(value) {{
        const labels = {{ inbox: "Received", sent: "Sent", draft: "Draft", outbox: "Outbox" }};
        return labels[String(value || "").toLowerCase()] || escapeHtml(value || "Unknown");
      }}

      function renderRows(items) {{
        if (!items.length) {{
          return `<tr><td colspan="6" class="text-center text-secondary py-4">No SMS entries found.</td></tr>`;
        }}
        return items.map((item) => `
          <tr>
            <td>${{escapeHtml(formatTime(item.timestamp))}}</td>
            <td>${{formatType(item.type)}}</td>
            <td>${{escapeHtml(item.read || "-")}}</td>
            <td><code>${{escapeHtml(item.address || "-")}}</code></td>
            <td>${{escapeHtml(item.subject || "-")}}</td>
            <td style="white-space:pre-wrap">${{escapeHtml(item.body || "")}}</td>
          </tr>
        `).join("");
      }}

      async function refreshHistory(manual = false) {{
        const resultCount = document.getElementById("result-count");
        const body = document.getElementById("history-body");
        try {{
          const params = buildHistoryQueryParams(deviceId, searchInput.value || "");
          const response = await fetch(`/devices/sms-history.json?${{params.toString()}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to load SMS history");
          body.innerHTML = renderRows(payload.items || []);
          resultCount.textContent = `${{payload.count || 0}} messages`;
          const label = manual ? "Refreshed" : "Live synced";
          setPageRefreshStatus(true, `${{label}} at ${{new Date().toLocaleTimeString()}}`);
          updateDeviceStatusBadge(payload.status);
          if (payload.permissionGranted === false) {{
            document.getElementById("permission-note").innerHTML =
              "SMS permission is OFF on the device. Open the app → Compliance Checklist → <strong>Enable SMS Access</strong>.";
          }}
        }} catch (error) {{
          setPageRefreshStatus(false, `Sync failed: ${{error.message}}`);
        }}
      }}

      searchInput.addEventListener("input", () => {{
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => refreshHistory(false), 250);
      }});
      initDateFilterControls(() => refreshHistory(false));
      {render_page_refresh_binding("refreshHistory")}
    </script>
    """
    return render_admin_page(
        "SMS History",
        "Live synced SMS records from the enrolled device.",
        content,
        active_path="/devices/sms-history",
        page_title="SMS History",
        extra_scripts=scripts,
    )


def render_device_notifications_page(device):
    device_id = escape(device.get("deviceId"))
    permission_ok = device.get("notificationAccessGranted") is True
    permission_text = (
        "Notification listener is enabled on the device. New notifications sync automatically."
        if permission_ok
        else "Notification listener is OFF. Open the app → Compliance Checklist → Enable Notification Listener."
    )
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
        <div>
          <h2 class="h5 mb-1">Notification Feed</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">
          {render_device_status_badge(device)}
          <div class="mt-1">{render_page_refresh_controls()}</div>
        </div>
      </div>
      <p class="text-secondary small mt-3 mb-3" id="permission-note">{permission_text}</p>
      <div class="row g-2 align-items-center">
        <div class="col-lg-5">
          <input id="history-search" class="form-control" type="search" placeholder="Search app, title, message, category...">
        </div>
        <div class="col-md-3">
          <select id="category-filter" class="form-select">
            <option value="">All categories</option>
          </select>
        </div>
        <div class="col-md-3">
          <select id="app-filter" class="form-select">
            <option value="">All apps</option>
          </select>
        </div>
        <div class="col-md-1 text-md-end">
          <span class="badge text-bg-light border" id="result-count">0</span>
        </div>
      </div>
      {render_history_date_range_widget()}
    </section>
    <section class="admin-card mb-4">
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead><tr><th>Time</th><th>App</th><th>Category</th><th>Title</th><th>Message</th></tr></thead>
          <tbody id="history-body"><tr><td colspan="5" class="text-center text-secondary py-4">Loading notifications...</td></tr></tbody>
        </table>
      </div>
    </section>
    """
    scripts = f"""
    <script>
      const deviceId = "{device_id}";
      const searchInput = document.getElementById("history-search");
      const categoryFilter = document.getElementById("category-filter");
      const appFilter = document.getElementById("app-filter");
      let searchTimer = null;
      {render_history_date_filter_js()}
      {render_device_status_js()}
      {render_page_refresh_status_js()}

      function escapeHtml(value) {{
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }}

      function formatTime(timestamp) {{
        if (!timestamp) return "-";
        return new Date(Number(timestamp) * 1000).toLocaleString();
      }}

      function formatCategory(value) {{
        const label = String(value || "general");
        return label.charAt(0).toUpperCase() + label.slice(1);
      }}

      function populateFilters(filters) {{
        const categories = Array.isArray(filters?.categories) ? filters.categories : [];
        const apps = Array.isArray(filters?.apps) ? filters.apps : [];
        const selectedCategory = categoryFilter.value;
        const selectedApp = appFilter.value;
        categoryFilter.innerHTML = '<option value="">All categories</option>' + categories.map((item) =>
          `<option value="${{escapeHtml(item)}}">${{escapeHtml(formatCategory(item))}}</option>`
        ).join("");
        appFilter.innerHTML = '<option value="">All apps</option>' + apps.map((item) =>
          `<option value="${{escapeHtml(item.appName || item.packageName || "")}}">${{escapeHtml(item.appName || item.packageName || "-")}}</option>`
        ).join("");
        categoryFilter.value = selectedCategory;
        appFilter.value = selectedApp;
      }}

      function buildNotificationQueryParams() {{
        const params = buildHistoryQueryParams(deviceId, searchInput.value || "");
        if (categoryFilter.value) params.set("category", categoryFilter.value);
        if (appFilter.value) params.set("app", appFilter.value);
        return params;
      }}

      function renderRows(items) {{
        if (!items.length) {{
          return `<tr><td colspan="5" class="text-center text-secondary py-4">No notifications found.</td></tr>`;
        }}
        return items.map((item) => `
          <tr>
            <td>${{escapeHtml(formatTime(item.timestamp))}}</td>
            <td>${{escapeHtml(item.appName || item.packageName || "-")}}<br><code>${{escapeHtml(item.packageName || "-")}}</code></td>
            <td><span class="badge text-bg-light border">${{escapeHtml(formatCategory(item.category))}}</span></td>
            <td>${{escapeHtml(item.title || "-")}}</td>
            <td>${{escapeHtml(item.body || "-")}}</td>
          </tr>
        `).join("");
      }}

      async function refreshHistory(manual = false) {{
        const resultCount = document.getElementById("result-count");
        const body = document.getElementById("history-body");
        try {{
          const params = buildNotificationQueryParams();
          const response = await fetch(`/devices/notifications.json?${{params.toString()}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to load notifications");
          populateFilters(payload.filters || {{}});
          body.innerHTML = renderRows(payload.items || []);
          resultCount.textContent = `${{payload.count || 0}} notifications`;
          const label = manual ? "Refreshed" : "Live synced";
          setPageRefreshStatus(true, `${{label}} at ${{new Date().toLocaleTimeString()}}`);
          updateDeviceStatusBadge(payload.status);
          if (payload.permissionGranted === false) {{
            document.getElementById("permission-note").innerHTML =
              "Notification listener is OFF. Open the app → Compliance Checklist → <strong>Enable Notification Listener</strong>.";
          }}
        }} catch (error) {{
          setPageRefreshStatus(false, `Sync failed: ${{error.message}}`);
        }}
      }}

      searchInput.addEventListener("input", () => {{
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => refreshHistory(false), 250);
      }});
      categoryFilter.addEventListener("change", () => refreshHistory(false));
      appFilter.addEventListener("change", () => refreshHistory(false));
      initDateFilterControls(() => refreshHistory(false));
      {render_page_refresh_binding("refreshHistory")}
    </script>
    """
    return render_admin_page(
        "Notification Feed",
        "Live synced notifications from the enrolled device.",
        content,
        active_path="/devices/notifications",
        page_title="Notification Feed",
        extra_scripts=scripts,
    )


def render_device_contacts_page(device):
    device_id = escape(device.get("deviceId"))
    permission_ok = device.get("contactsPermissionGranted") is True
    permission_text = (
        "Contacts permission is enabled on the device. Live sync runs every 5 seconds."
        if permission_ok
        else "Contacts permission is OFF on the device. Open the app → Compliance Checklist → Enable Contacts Access."
    )
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
        <div>
          <h2 class="h5 mb-1">Contact List</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">
          {render_device_status_badge(device)}
          <div class="mt-1">{render_page_refresh_controls()}</div>
        </div>
      </div>
      <p class="text-secondary small mt-3 mb-3" id="permission-note">{permission_text}</p>
      <div class="row g-2 align-items-center">
        <div class="col-md-8">
          <input id="contacts-search" class="form-control" type="search" placeholder="Search name, number, email, company, type...">
        </div>
        <div class="col-md-4 text-md-end">
          <span class="badge text-bg-light border" id="result-count">0 contacts</span>
        </div>
      </div>
      {render_history_date_range_widget()}
    </section>
    <section class="admin-card mb-4">
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead><tr><th>Name</th><th>Phone</th><th>Type</th><th>Email</th><th>Organization</th><th>Starred</th></tr></thead>
          <tbody id="contacts-body"><tr><td colspan="6" class="text-center text-secondary py-4">Loading contacts...</td></tr></tbody>
        </table>
      </div>
    </section>
    """
    scripts = f"""
    <script>
      const deviceId = "{device_id}";
      const searchInput = document.getElementById("contacts-search");
      let searchTimer = null;
      {render_history_date_filter_js()}
      {render_device_status_js()}
      {render_page_refresh_status_js()}

      function escapeHtml(value) {{
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }}

      function formatPhoneType(value, label) {{
        const types = {{
          mobile: "Mobile",
          home: "Home",
          work: "Work",
          main: "Main",
          fax_home: "Home Fax",
          fax_work: "Work Fax",
          pager: "Pager",
          other: "Other",
          custom: label || "Custom"
        }};
        const key = String(value || "").toLowerCase();
        return escapeHtml(types[key] || value || "-");
      }}

      function renderRows(items) {{
        if (!items.length) {{
          return `<tr><td colspan="6" class="text-center text-secondary py-4">No contacts found.</td></tr>`;
        }}
        return items.map((item) => `
          <tr>
            <td>${{escapeHtml(item.displayName || "-")}}</td>
            <td><code>${{escapeHtml(item.phoneNumber || "-")}}</code></td>
            <td>${{formatPhoneType(item.phoneType, item.phoneLabel)}}</td>
            <td>${{escapeHtml(item.email || "-")}}</td>
            <td>${{escapeHtml(item.organization || "-")}}</td>
            <td>${{item.starred ? "Yes" : "No"}}</td>
          </tr>
        `).join("");
      }}

      async function refreshContacts(manual = false) {{
        const resultCount = document.getElementById("result-count");
        const body = document.getElementById("contacts-body");
        try {{
          const params = buildHistoryQueryParams(deviceId, searchInput.value || "");
          const response = await fetch(`/devices/contacts.json?${{params.toString()}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to load contacts");
          body.innerHTML = renderRows(payload.items || []);
          resultCount.textContent = `${{payload.count || 0}} contacts`;
          const label = manual ? "Refreshed" : "Live synced";
          setPageRefreshStatus(true, `${{label}} at ${{new Date().toLocaleTimeString()}}`);
          updateDeviceStatusBadge(payload.status);
          if (payload.permissionGranted === false) {{
            document.getElementById("permission-note").innerHTML =
              "Contacts permission is OFF on the device. Open the app → Compliance Checklist → <strong>Enable Contacts Access</strong>.";
          }}
        }} catch (error) {{
          setPageRefreshStatus(false, `Sync failed: ${{error.message}}`);
        }}
      }}

      searchInput.addEventListener("input", () => {{
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => refreshContacts(false), 250);
      }});
      initDateFilterControls(() => refreshContacts(false));
      {render_page_refresh_binding("refreshContacts")}
    </script>
    """
    return render_admin_page(
        "Contact List",
        "Live synced phone contacts from the enrolled device.",
        content,
        active_path="/devices/contacts",
        page_title="Contact List",
        extra_scripts=scripts,
    )


def render_device_audio_page(device):
    device_id = escape(device.get("deviceId"))
    permission_ok = device.get("audioPermissionGranted") is True
    permission_text = (
        "Microphone permission is enabled on the device. Admin can start a visible foreground audio broadcast."
        if permission_ok
        else "Microphone permission is OFF. Open the app → Compliance Checklist → Enable Microphone Access."
    )
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
        <div>
          <h2 class="h5 mb-1">Live Audio Broadcast</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">
          {render_device_status_badge(device)}
          <div class="small text-secondary mt-1" id="sync-status">Waiting for stream...</div>
        </div>
      </div>
      <p class="text-secondary small mt-3 mb-3" id="permission-note">{permission_text}</p>
      <div class="d-flex flex-wrap gap-2 mb-3">
        <button type="button" class="btn btn-sm btn-success" id="btn-start-stream">Start Stream on Device</button>
        <button type="button" class="btn btn-sm btn-outline-danger" id="btn-stop-stream">Stop Stream</button>
        <button type="button" class="btn btn-sm btn-primary" id="btn-server-record">Start Server Recording</button>
        <button type="button" class="btn btn-sm btn-outline-primary" id="btn-server-stop">Stop &amp; Save Recording</button>
        <button type="button" class="btn btn-sm btn-secondary" id="btn-browser-record">Record in Browser</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" id="btn-browser-stop" disabled>Stop Browser Recording</button>
      </div>
      <div class="row g-3">
        <div class="col-lg-6">
          <label class="form-label small mb-1">Playback format</label>
          <select id="playback-format" class="form-select form-select-sm">
            <option value="live">Live PCM (Web Audio)</option>
            <option value="wav">Latest WAV snapshot</option>
          </select>
          <div class="mt-3">
            <div class="small text-secondary mb-1">Live level</div>
            <div class="progress" style="height: 18px;">
              <div id="audio-level" class="progress-bar bg-success" style="width: 0%"></div>
            </div>
          </div>
          <audio id="wav-player" class="w-100 mt-3" controls style="display:none;"></audio>
        </div>
        <div class="col-lg-6">
          <div class="small text-secondary">Session</div>
          <dl class="row mb-0 mt-2">
            <dt class="col-5">Stream</dt><dd class="col-7" id="session-active">Inactive</dd>
            <dt class="col-5">Last chunk</dt><dd class="col-7" id="session-last-chunk">-</dd>
            <dt class="col-5">Sample rate</dt><dd class="col-7" id="session-rate">16000 Hz</dd>
            <dt class="col-5">Buffered chunks</dt><dd class="col-7" id="session-chunks">0</dd>
          </dl>
        </div>
      </div>
    </section>
    <section class="admin-card p-4 mb-4">
      <h3 class="h6 mb-3">Saved Recordings</h3>
      <div id="recordings-list" class="small text-secondary">No recordings yet.</div>
    </section>
    """
    scripts = f"""
    <script>
      const deviceId = "{device_id}";
      let lastSeq = 0;
      let audioContext = null;
      let nextPlayTime = 0;
      let browserRecorder = null;
      let browserChunks = [];
      let browserDestination = null;
      let pollTimer = null;
      {render_device_status_js()}

      function ensureAudioContext() {{
        if (!audioContext) {{
          audioContext = new (window.AudioContext || window.webkitAudioContext)({{ sampleRate: 16000 }});
          browserDestination = audioContext.createMediaStreamDestination();
        }}
        if (audioContext.state === "suspended") {{
          audioContext.resume();
        }}
      }}

      function decodePcmBase64(data) {{
        const binary = atob(data);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        return new Int16Array(bytes.buffer);
      }}

      function playPcmChunk(int16) {{
        ensureAudioContext();
        const float32 = new Float32Array(int16.length);
        let peak = 0;
        for (let i = 0; i < int16.length; i++) {{
          const value = int16[i] / 32768;
          float32[i] = value;
          peak = Math.max(peak, Math.abs(value));
        }}
        document.getElementById("audio-level").style.width = `${{Math.min(100, Math.round(peak * 100))}}%`;
        const buffer = audioContext.createBuffer(1, float32.length, 16000);
        buffer.copyToChannel(float32, 0);
        const source = audioContext.createBufferSource();
        source.buffer = buffer;
        source.connect(audioContext.destination);
        if (browserDestination) source.connect(browserDestination);
        if (nextPlayTime < audioContext.currentTime) nextPlayTime = audioContext.currentTime;
        source.start(nextPlayTime);
        nextPlayTime += buffer.duration;
      }}

      async function postControl(action) {{
        const response = await fetch("/devices/audio/control", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ deviceId, action }})
        }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || payload.message || "Request failed");
        return payload;
      }}

      function renderRecordings(items) {{
        const root = document.getElementById("recordings-list");
        if (!items || !items.length) {{
          root.textContent = "No recordings yet.";
          return;
        }}
        root.innerHTML = items.map((item) => `
          <div class="mb-2">
            <strong>${{new Date(item.finishedAt * 1000).toLocaleString()}}</strong>
            · ${{item.durationSeconds || 0}}s
            · <a href="/devices/audio/recording?deviceId=${{encodeURIComponent(deviceId)}}&id=${{encodeURIComponent(item.id)}}">Download WAV</a>
          </div>
        `).join("");
      }}

      async function refreshSession() {{
        const syncStatus = document.getElementById("sync-status");
        try {{
          const response = await fetch(`/devices/audio/session.json?deviceId=${{encodeURIComponent(deviceId)}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to load session");
          updateDeviceStatusBadge(payload.status);
          const session = payload.session || {{}};
          document.getElementById("session-active").textContent = session.active ? "Active" : (session.requested ? "Requested" : "Inactive");
          document.getElementById("session-last-chunk").textContent = session.lastChunkAt
            ? new Date(session.lastChunkAt * 1000).toLocaleTimeString()
            : "-";
          document.getElementById("session-rate").textContent = `${{session.sampleRate || 16000}} Hz`;
          document.getElementById("session-chunks").textContent = session.chunkCount || 0;
          renderRecordings(payload.recordings || []);
          if (payload.permissionGranted === false) {{
            document.getElementById("permission-note").innerHTML =
              "Microphone permission is OFF. Open the app → Compliance Checklist → <strong>Enable Microphone Access</strong>.";
          }}
          syncStatus.textContent = session.active
            ? `Live audio active · ${{new Date().toLocaleTimeString()}}`
            : (session.requested ? "Waiting for device to start stream..." : "Stream inactive");
          syncStatus.className = session.active ? "small text-success mt-1" : "small text-secondary mt-1";
        }} catch (error) {{
          syncStatus.textContent = `Sync failed: ${{error.message}}`;
          syncStatus.className = "small text-danger mt-1";
        }}
      }}

      async function pollChunks() {{
        const format = document.getElementById("playback-format").value;
        if (format === "wav") {{
          const player = document.getElementById("wav-player");
          player.style.display = "block";
          player.src = `/devices/audio/live.wav?deviceId=${{encodeURIComponent(deviceId)}}&t=${{Date.now()}}`;
          return;
        }}
        const response = await fetch(`/devices/audio/chunks.json?deviceId=${{encodeURIComponent(deviceId)}}&since=${{lastSeq}}`, {{ cache: "no-store" }});
        const payload = await response.json();
        if (!response.ok) return;
        for (const item of payload.items || []) {{
          lastSeq = Math.max(lastSeq, Number(item.seq || 0));
          playPcmChunk(decodePcmBase64(item.data));
        }}
      }}

      document.getElementById("btn-start-stream").addEventListener("click", async () => {{
        try {{
          await postControl("start");
          await refreshSession();
        }} catch (error) {{ alert(error.message); }}
      }});
      document.getElementById("btn-stop-stream").addEventListener("click", async () => {{
        try {{
          await postControl("stop");
          lastSeq = 0;
          nextPlayTime = 0;
          await refreshSession();
        }} catch (error) {{ alert(error.message); }}
      }});
      document.getElementById("btn-server-record").addEventListener("click", async () => {{
        try {{
          await postControl("record_start");
          await refreshSession();
        }} catch (error) {{ alert(error.message); }}
      }});
      document.getElementById("btn-server-stop").addEventListener("click", async () => {{
        try {{
          await postControl("record_stop");
          await refreshSession();
        }} catch (error) {{ alert(error.message); }}
      }});
      document.getElementById("btn-browser-record").addEventListener("click", async () => {{
        ensureAudioContext();
        browserChunks = [];
        browserRecorder = new MediaRecorder(browserDestination.stream);
        browserRecorder.ondataavailable = (event) => {{
          if (event.data.size > 0) browserChunks.push(event.data);
        }};
        browserRecorder.onstop = () => {{
          const blob = new Blob(browserChunks, {{ type: browserRecorder.mimeType || "audio/webm" }});
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = `live-audio-${{deviceId}}-${{Date.now()}}.webm`;
          link.click();
          URL.revokeObjectURL(url);
        }};
        browserRecorder.start(1000);
        document.getElementById("btn-browser-record").disabled = true;
        document.getElementById("btn-browser-stop").disabled = false;
      }});
      document.getElementById("btn-browser-stop").addEventListener("click", () => {{
        if (browserRecorder && browserRecorder.state !== "inactive") browserRecorder.stop();
        document.getElementById("btn-browser-record").disabled = false;
        document.getElementById("btn-browser-stop").disabled = true;
      }});
      document.getElementById("playback-format").addEventListener("change", () => {{
        const player = document.getElementById("wav-player");
        player.style.display = document.getElementById("playback-format").value === "wav" ? "block" : "none";
      }});

      refreshSession();
      pollChunks();
      pollTimer = setInterval(() => {{
        refreshSession();
        pollChunks();
      }}, 500);
    </script>
    """
    return render_admin_page(
        "Live Audio",
        "Admin-started microphone broadcast from the enrolled device.",
        content,
        active_path="/devices/audio",
        page_title="Live Audio",
        extra_scripts=scripts,
    )


def render_device_files_page(device):
    device_id = escape(device.get("deviceId"))
    permission_ok = device.get("storagePermissionGranted") is True
    permission_text = (
        "All files access is enabled on the device. The file manager can browse live folders and files."
        if permission_ok
        else "All files access is OFF. On the phone open the app → Compliance Checklist → <strong>Enable All Files Access</strong>, then allow “All files access” in Android settings."
    )
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-3">
        <div>
          <h2 class="h5 mb-1">Remote File Manager</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">
          {render_device_status_badge(device)}
          <div class="small text-secondary mt-1" id="sync-status">Ready</div>
        </div>
      </div>
      <p class="text-secondary small mb-3" id="permission-note">{permission_text}</p>
      <div class="d-flex flex-wrap gap-2 mb-2">
        <button type="button" class="btn btn-sm btn-success" id="btn-start-session">Start Remote Session</button>
        <button type="button" class="btn btn-sm btn-outline-danger" id="btn-stop-session">Stop Session</button>
        <button type="button" class="btn btn-sm btn-primary" id="btn-refresh">Refresh Listing</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" id="btn-up">Up</button>
      </div>
      <div class="d-flex flex-wrap gap-2 mb-2 border-top pt-3">
        <button type="button" class="btn btn-sm btn-outline-primary" id="btn-select-all">Select All</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" id="btn-clear-selection">Clear</button>
        <button type="button" class="btn btn-sm btn-outline-primary" id="btn-copy">Copy</button>
        <button type="button" class="btn btn-sm btn-outline-primary" id="btn-cut">Cut</button>
        <button type="button" class="btn btn-sm btn-outline-success" id="btn-paste">Paste</button>
        <button type="button" class="btn btn-sm btn-outline-warning" id="btn-move">Move</button>
        <button type="button" class="btn btn-sm btn-outline-danger" id="btn-delete">Delete</button>
        <button type="button" class="btn btn-sm btn-secondary" id="btn-download-selected">Download</button>
      </div>
      <div class="small text-secondary mb-2" id="clipboard-info">Clipboard empty</div>
      <div class="mb-2"><code id="current-path">/storage/emulated/0</code></div>
      <div id="files-grid" class="file-manager-grid">
        <div class="text-secondary text-center py-5 w-100">Start remote session, then refresh listing.</div>
      </div>
    </section>
    <section class="admin-card p-4 mb-4">
      <h3 class="h6 mb-3">Upload File To Device</h3>
      <div class="row g-2 align-items-end">
        <div class="col-md-5">
          <label class="form-label small">Destination path on device</label>
          <input class="form-control form-control-sm" id="upload-path" placeholder="/storage/emulated/0/Download/myfile.txt">
        </div>
        <div class="col-md-5">
          <label class="form-label small">Choose file</label>
          <input class="form-control form-control-sm" id="upload-file" type="file">
        </div>
        <div class="col-md-2">
          <button type="button" class="btn btn-sm btn-primary w-100" id="btn-upload">Upload</button>
        </div>
      </div>
      <div class="small text-secondary mt-2">Max 25 MB per transfer. Device shows a visible remote session notification.</div>
    </section>
    """
    styles = """
    <style>
      .file-manager-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
        gap: 12px;
      }
      .file-card {
        border: 1px solid #dee2e6;
        border-radius: 10px;
        padding: 10px;
        background: #fff;
        cursor: pointer;
        position: relative;
        min-height: 190px;
      }
      .file-card.selected {
        border-color: #0d6efd;
        box-shadow: 0 0 0 2px rgba(13,110,253,.15);
        background: #f3f8ff;
      }
      .file-card .file-select {
        position: absolute;
        top: 8px;
        left: 8px;
        z-index: 2;
      }
      .file-thumb-wrap {
        width: 100%;
        aspect-ratio: 1;
        border-radius: 8px;
        overflow: hidden;
        background: #f1f3f5;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 8px;
      }
      .file-thumb {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
      }
      .file-icon {
        font-size: 42px;
        line-height: 1;
      }
      .file-name {
        font-size: 12px;
        font-weight: 600;
        word-break: break-word;
        min-height: 32px;
      }
      .file-meta {
        font-size: 11px;
        color: #6c757d;
        margin-top: 4px;
      }
    </style>
    """
    scripts = f"""
    <script>
      {render_device_status_js()}
      const deviceId = "{device_id}";
      let currentPath = "/storage/emulated/0";
      let pendingListJob = "";
      let pendingActionJob = "";
      let currentEntries = [];
      const selectedPaths = new Set();

      function escapeHtml(value) {{
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }}

      function formatSize(bytes) {{
        const value = Number(bytes || 0);
        if (value < 1024) return `${{value}} B`;
        if (value < 1024 * 1024) return `${{(value / 1024).toFixed(1)}} KB`;
        return `${{(value / (1024 * 1024)).toFixed(1)}} MB`;
      }}

      function getSelectedPaths() {{
        return Array.from(selectedPaths);
      }}

      function updateClipboardInfo(clipboard) {{
        const info = document.getElementById("clipboard-info");
        const paths = clipboard && clipboard.paths ? clipboard.paths : [];
        if (!paths.length) {{
          info.textContent = "Clipboard empty";
          return;
        }}
        info.textContent = `${{clipboard.mode === "cut" ? "Cut" : "Copy"}}: ${{paths.length}} item(s) ready to paste`;
      }}

      function thumbHtml(entry) {{
        if (entry.thumbnail) {{
          const mime = entry.thumbnailMime || "image/jpeg";
          return `<img class="file-thumb" src="data:${{mime}};base64,${{entry.thumbnail}}" alt="">`;
        }}
        if (entry.isDir) {{
          return `<div class="file-icon">📁</div>`;
        }}
        if (entry.mediaType === "video") {{
          return `<div class="file-icon">🎬</div>`;
        }}
        if (entry.mediaType === "image") {{
          return `<div class="file-icon">🖼️</div>`;
        }}
        return `<div class="file-icon">📄</div>`;
      }}

      function renderGrid(entries) {{
        const grid = document.getElementById("files-grid");
        if (!entries || !entries.length) {{
          grid.innerHTML = `<div class="text-secondary text-center py-5 w-100">Empty folder</div>`;
          return;
        }}
        grid.innerHTML = entries.map((entry) => {{
          const selectable = !entry.isParent;
          const checked = selectedPaths.has(entry.path) ? "checked" : "";
          const selectedClass = selectedPaths.has(entry.path) ? "selected" : "";
          const checkbox = selectable
            ? `<input type="checkbox" class="form-check-input file-select" data-path="${{escapeHtml(entry.path)}}" ${{checked}}>`
            : "";
          return `<div class="file-card ${{selectedClass}}" data-path="${{escapeHtml(entry.path)}}" data-is-dir="${{entry.isDir ? "1" : "0"}}" data-is-parent="${{entry.isParent ? "1" : "0"}}">
            ${{checkbox}}
            <div class="file-thumb-wrap">${{thumbHtml(entry)}}</div>
            <div class="file-name">${{escapeHtml(entry.name)}}</div>
            <div class="file-meta">${{entry.isDir ? "Folder" : formatSize(entry.size)}}</div>
          </div>`;
        }}).join("");
      }}

      async function remoteControl(action, extra = {{}}) {{
        const response = await fetch("/devices/files/control", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ deviceId, action, ...extra }}),
        }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Request failed");
        return payload;
      }}

      async function pollActionJob(jobId, successMessage) {{
        const syncStatus = document.getElementById("sync-status");
        for (let attempt = 0; attempt < 60; attempt++) {{
          const response = await fetch(`/devices/files/action.json?deviceId=${{encodeURIComponent(deviceId)}}&jobId=${{encodeURIComponent(jobId)}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (payload.ready && payload.result) {{
            if (!payload.result.ok) {{
              throw new Error(payload.result.error || "File action failed");
            }}
            const inner = payload.result.result || {{}};
            if (inner.ok === false) {{
              throw new Error("Some selected items could not be processed");
            }}
            selectedPaths.clear();
            syncStatus.textContent = successMessage || "Action completed";
            pendingActionJob = "";
            await refreshListing(true);
            return;
          }}
          await new Promise((resolve) => setTimeout(resolve, 500));
        }}
        throw new Error("Action timed out");
      }}

      async function refreshListing(forceRequest = false) {{
        const syncStatus = document.getElementById("sync-status");
        try {{
          if (forceRequest) {{
            const queued = await remoteControl("list", {{ path: currentPath }});
            pendingListJob = queued.jobId || "";
            syncStatus.textContent = "Listing requested on device...";
          }}
          const response = await fetch(`/devices/files/listing.json?deviceId=${{encodeURIComponent(deviceId)}}&path=${{encodeURIComponent(currentPath)}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to load listing");
          document.getElementById("current-path").textContent = payload.path || currentPath;
          updateClipboardInfo(payload.clipboard || {{}});
          if (payload.listing && payload.listing.entries) {{
            currentEntries = payload.listing.entries;
            renderGrid(currentEntries);
            syncStatus.textContent = `Updated ${{new Date().toLocaleTimeString()}}`;
            pendingListJob = "";
            updateDeviceStatusBadge(payload.status);
            if (payload.permissionGranted === false) {{
              document.getElementById("permission-note").innerHTML =
                "All files access is OFF on the device. Open the app → Compliance Checklist → <strong>Enable All Files Access</strong>.";
            }}
            return true;
          }}
          if (payload.listing && payload.listing.error) {{
            syncStatus.textContent = payload.listing.error;
            document.getElementById("files-grid").innerHTML =
              `<div class="text-danger text-center py-5 w-100">${{escapeHtml(payload.listing.error)}}</div>`;
            pendingListJob = "";
            return true;
          }}
          syncStatus.textContent = payload.permissionGranted === false
            ? "Waiting for All files access on device..."
            : "Waiting for device response...";
          updateDeviceStatusBadge(payload.status);
          return false;
        }} catch (error) {{
          syncStatus.textContent = `Error: ${{error.message}}`;
          return false;
        }}
      }}

      async function pollDownload(jobId) {{
        const syncStatus = document.getElementById("sync-status");
        for (let attempt = 0; attempt < 60; attempt++) {{
          const response = await fetch(`/devices/files/download.json?deviceId=${{encodeURIComponent(deviceId)}}&jobId=${{encodeURIComponent(jobId)}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (payload.ready) {{
            window.location.href = `/devices/files/content?deviceId=${{encodeURIComponent(deviceId)}}&jobId=${{encodeURIComponent(jobId)}}`;
            syncStatus.textContent = "Download ready";
            return;
          }}
          if (payload.download && payload.download.error) {{
            throw new Error(payload.download.error);
          }}
          await new Promise((resolve) => setTimeout(resolve, 500));
        }}
        throw new Error("Download timed out");
      }}

      async function runOnSelection(action, extra = {{}}) {{
        const paths = getSelectedPaths();
        if (!paths.length) {{
          alert("Select one or more items first.");
          return;
        }}
        const syncStatus = document.getElementById("sync-status");
        try {{
          syncStatus.textContent = `${{action}} queued on device...`;
          const queued = await remoteControl(action, {{ paths, ...extra }});
          if (queued.jobId) {{
            pendingActionJob = queued.jobId;
            await pollActionJob(queued.jobId, `${{action}} completed`);
            if (queued.clipboard) updateClipboardInfo(queued.clipboard);
            return;
          }}
          if (queued.clipboard) updateClipboardInfo(queued.clipboard);
          syncStatus.textContent = `${{action}} ready`;
        }} catch (error) {{
          syncStatus.textContent = `${{action}} failed: ${{error.message}}`;
        }}
      }}

      document.getElementById("btn-start-session").addEventListener("click", async () => {{
        await remoteControl("start_session");
        document.getElementById("sync-status").textContent = "Remote session requested";
      }});
      document.getElementById("btn-stop-session").addEventListener("click", async () => {{
        await remoteControl("stop_session");
        document.getElementById("sync-status").textContent = "Remote session stop requested";
      }});
      document.getElementById("btn-refresh").addEventListener("click", () => refreshListing(true));
      document.getElementById("btn-up").addEventListener("click", () => {{
        selectedPaths.clear();
        const parts = currentPath.replace(/\\/+$/, "").split("/").filter(Boolean);
        if (parts.length <= 1) currentPath = "/storage/emulated/0";
        else {{ parts.pop(); currentPath = "/" + parts.join("/"); }}
        refreshListing(true);
      }});
      document.getElementById("btn-select-all").addEventListener("click", () => {{
        currentEntries.forEach((entry) => {{
          if (!entry.isParent) selectedPaths.add(entry.path);
        }});
        renderGrid(currentEntries);
      }});
      document.getElementById("btn-clear-selection").addEventListener("click", () => {{
        selectedPaths.clear();
        renderGrid(currentEntries);
      }});
      document.getElementById("btn-copy").addEventListener("click", () => runOnSelection("copy"));
      document.getElementById("btn-cut").addEventListener("click", () => runOnSelection("cut"));
      document.getElementById("btn-paste").addEventListener("click", async () => {{
        try {{
          document.getElementById("sync-status").textContent = "Pasting on device...";
          const queued = await remoteControl("paste", {{ path: currentPath }});
          pendingActionJob = queued.jobId;
          await pollActionJob(queued.jobId, "Paste completed");
          await refreshListing(false);
        }} catch (error) {{
          document.getElementById("sync-status").textContent = `Paste failed: ${{error.message}}`;
        }}
      }});
      document.getElementById("btn-delete").addEventListener("click", () => {{
        if (!confirm("Delete selected items from the device?")) return;
        runOnSelection("delete");
      }});
      document.getElementById("btn-move").addEventListener("click", () => {{
        const destPath = prompt("Move selected items to folder path:", currentPath);
        if (!destPath) return;
        runOnSelection("move", {{ destPath: destPath.trim() }});
      }});
      document.getElementById("btn-download-selected").addEventListener("click", async () => {{
        const paths = getSelectedPaths().filter((path) => {{
          const entry = currentEntries.find((item) => item.path === path);
          return entry && !entry.isDir;
        }});
        if (!paths.length) {{
          alert("Select one or more files to download.");
          return;
        }}
        for (const path of paths) {{
          try {{
            const queued = await remoteControl("download", {{ path }});
            await pollDownload(queued.jobId);
          }} catch (error) {{
            document.getElementById("sync-status").textContent = `Download failed: ${{error.message}}`;
            break;
          }}
        }}
      }});

      document.getElementById("files-grid").addEventListener("click", async (event) => {{
        const checkbox = event.target.closest(".file-select");
        if (checkbox) {{
          event.stopPropagation();
          const path = checkbox.getAttribute("data-path");
          if (checkbox.checked) selectedPaths.add(path);
          else selectedPaths.delete(path);
          const card = checkbox.closest(".file-card");
          if (card) card.classList.toggle("selected", checkbox.checked);
          return;
        }}
        const card = event.target.closest(".file-card");
        if (!card) return;
        const path = card.getAttribute("data-path");
        const isDir = card.getAttribute("data-is-dir") === "1";
        const isParent = card.getAttribute("data-is-parent") === "1";
        if (isDir || isParent) {{
          selectedPaths.clear();
          currentPath = path;
          refreshListing(true);
          return;
        }}
        if (event.detail === 2) {{
          try {{
            document.getElementById("sync-status").textContent = "Downloading from device...";
            const queued = await remoteControl("download", {{ path }});
            await pollDownload(queued.jobId);
          }} catch (error) {{
            document.getElementById("sync-status").textContent = `Download failed: ${{error.message}}`;
          }}
        }}
      }});

      document.getElementById("btn-upload").addEventListener("click", () => {{
        const fileInput = document.getElementById("upload-file");
        const uploadPath = document.getElementById("upload-path").value.trim();
        const file = fileInput.files && fileInput.files[0];
        if (!file || !uploadPath) {{
          alert("Choose a file and destination path.");
          return;
        }}
        const reader = new FileReader();
        reader.onload = async () => {{
          try {{
            const base64 = String(reader.result).split(",")[1];
            document.getElementById("sync-status").textContent = "Upload queued on device...";
            const response = await fetch("/devices/files/upload", {{
              method: "POST",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ deviceId, path: uploadPath, filename: file.name, data: base64 }}),
            }});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "Upload failed");
            document.getElementById("sync-status").textContent = "Upload sent to device";
          }} catch (error) {{
            document.getElementById("sync-status").textContent = `Upload failed: ${{error.message}}`;
          }}
        }};
        reader.readAsDataURL(file);
      }});

      setInterval(async () => {{
        if (pendingListJob) await refreshListing(false);
        if (pendingActionJob) {{
          try {{
            await pollActionJob(pendingActionJob, "Action completed");
          }} catch (error) {{
            document.getElementById("sync-status").textContent = `Action failed: ${{error.message}}`;
            pendingActionJob = "";
          }}
        }}
      }}, 700);
    </script>
    """
    return render_admin_page(
        "File Manager",
        "Browse, download, upload, and manage files on the enrolled device.",
        content,
        active_path="/devices/files",
        page_title="File Manager",
        extra_head=styles,
        extra_scripts=scripts,
    )


def render_device_shell_page(device):
    device_id = escape(device.get("deviceId"))
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-3">
        <div>
          <h2 class="h5 mb-1">Remote Shell</h2>
          <div class="text-secondary device-id">{device_id} · Uses Android <code>sh -c</code> (45s timeout)</div>
        </div>
        <div class="text-end">
          {render_device_status_badge(device)}
          <div class="small text-secondary mt-1" id="sync-status">Ready</div>
        </div>
      </div>
      <div class="d-flex flex-wrap gap-2 mb-3">
        <button type="button" class="btn btn-sm btn-success" id="btn-start-session">Start Remote Session</button>
        <button type="button" class="btn btn-sm btn-outline-danger" id="btn-stop-session">Stop Session</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" id="btn-clear">Clear Output</button>
      </div>
      <pre id="shell-output" class="bg-dark text-light p-3 rounded small" style="min-height:360px;max-height:520px;overflow:auto;white-space:pre-wrap;">Remote shell ready. Start session, then run commands below.</pre>
      <div class="input-group mt-3">
        <span class="input-group-text">$</span>
        <input class="form-control" id="shell-command" placeholder="ls -la /storage/emulated/0">
        <button class="btn btn-primary" type="button" id="btn-run">Run</button>
      </div>
      <div class="small text-secondary mt-2">
        Default folder: <code>/storage/emulated/0</code> when All Files Access is ON.
        Use full paths for best results. This is Android <code>sh</code>, not desktop bash.
      </div>
      <div class="small text-secondary mt-2">
        Works well: <code>pwd</code>, <code>ls -la</code>, <code>ls -la /storage/emulated/0/DCIM</code>,
        <code>getprop ro.product.model</code>, <code>df -h</code>, <code>pm list packages | head</code>,
        <code>dumpsys battery</code>, <code>id</code>
      </div>
      <div class="small text-secondary mt-1">
        Usually blocked without root: <code>su</code>, editing <code>/system</code>, other apps' private data.
      </div>
    </section>
    """
    scripts = f"""
    <script>
      {render_device_status_js()}
      const deviceId = "{device_id}";
      let lastHistoryId = "";
      let pendingJobId = "";

      function escapeHtml(value) {{
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;");
      }}

      function appendBlock(title, stdout, stderr, exitCode, cwd) {{
        const output = document.getElementById("shell-output");
        const cwdLine = cwd ? `[cwd ${{cwd}}]\\n` : "";
        const block = [
          `$ ${{title}}`,
          cwdLine,
          stdout ? stdout : "",
          stderr ? `[stderr]\\n${{stderr}}` : "",
          `[exit ${{exitCode}}]`,
          "",
        ].join("\\n");
        output.textContent += block;
        output.scrollTop = output.scrollHeight;
      }}

      async function remoteControl(action) {{
        const response = await fetch("/devices/files/control", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ deviceId, action }}),
        }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Request failed");
      }}

      async function runCommand() {{
        const input = document.getElementById("shell-command");
        const command = input.value.trim();
        if (!command) return;
        const syncStatus = document.getElementById("sync-status");
        syncStatus.textContent = "Running on device...";
        try {{
          const response = await fetch("/devices/shell/exec", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ deviceId, command }}),
          }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Shell request failed");
          pendingJobId = payload.jobId;
          input.value = "";
        }} catch (error) {{
          syncStatus.textContent = `Error: ${{error.message}}`;
        }}
      }}

      async function pollHistory() {{
        const syncStatus = document.getElementById("sync-status");
        try {{
          const response = await fetch(`/devices/shell/history.json?deviceId=${{encodeURIComponent(deviceId)}}&since=${{encodeURIComponent(lastHistoryId)}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to load shell history");
          (payload.items || []).forEach((item) => {{
            if (!item.command || !String(item.command).trim()) {{
              return;
            }}
            appendBlock(item.command || "-", item.stdout || "", item.stderr || "", item.exitCode ?? "?", item.cwd || "");
            lastHistoryId = item.id;
            if (pendingJobId && item.id === pendingJobId) {{
              pendingJobId = "";
              syncStatus.textContent = `Finished ${{new Date().toLocaleTimeString()}}`;
            }}
          }});
          updateDeviceStatusBadge(payload.status);
        }} catch (error) {{
          syncStatus.textContent = `Sync failed: ${{error.message}}`;
        }}
      }}

      document.getElementById("btn-start-session").addEventListener("click", async () => {{
        await remoteControl("start_session");
        document.getElementById("sync-status").textContent = "Remote session requested";
      }});
      document.getElementById("btn-stop-session").addEventListener("click", async () => {{
        await remoteControl("stop_session");
        document.getElementById("sync-status").textContent = "Remote session stop requested";
      }});
      document.getElementById("btn-clear").addEventListener("click", () => {{
        document.getElementById("shell-output").textContent = "";
      }});
      document.getElementById("btn-run").addEventListener("click", runCommand);
      document.getElementById("shell-command").addEventListener("keydown", (event) => {{
        if (event.key === "Enter") runCommand();
      }});
      setInterval(pollHistory, 700);
    </script>
    """
    return render_admin_page(
        "Remote Shell",
        "Run live shell commands on the enrolled Android device.",
        content,
        active_path="/devices/shell",
        page_title="Remote Shell",
        extra_scripts=scripts,
    )


def render_device_security_page(device, requests, message=""):
    device_id = escape(device.get("deviceId"))
    message_html = ""
    if message:
        alert_class = "alert-warning" if "could not" in message.lower() else "alert-success"
        message_html = f'<div class="alert {alert_class}">{escape(message)}</div>'
    rows = []
    for request in requests:
        request_id = int(request.get("id") or 0)
        action_label = escape(SECURITY_ACTION_LABELS.get(request.get("actionType"), request.get("actionType")))
        status = escape(str(request.get("status") or ""))
        created = escape(format_timestamp(request.get("createdAt")))
        actions = "-"
        if request.get("status") == "pending":
            actions = f"""<form method="post" action="/devices/security/approve" class="d-inline">
  <input type="hidden" name="deviceId" value="{device_id}">
  <input type="hidden" name="requestId" value="{request_id}">
  <button class="btn btn-sm btn-success" type="submit">Approve</button>
</form>
<form method="post" action="/devices/security/reject" class="d-inline ms-1">
  <input type="hidden" name="deviceId" value="{device_id}">
  <input type="hidden" name="requestId" value="{request_id}">
  <button class="btn btn-sm btn-outline-danger" type="submit">Reject</button>
</form>"""
        rows.append(
            f"<tr><td>{request_id}</td><td>{action_label}</td><td>{status}</td><td>{created}</td><td>{actions}</td></tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="5" class="text-center text-secondary py-4">No security OTP requests yet.</td></tr>')
    request_rows = "\n".join(rows)
    locked = "Yes" if device.get("appLocked") else "No"
    hidden = "Yes" if device.get("appHidden") else "No"
    content = f"""
    <div class="mb-3">{render_device_features_menu(device)}</div>
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-3">
        <div>
          <h2 class="h5 mb-1">App Security Control</h2>
          <div class="text-secondary device-id">{device_id} · {escape(device.get("manufacturer"))} {escape(device.get("model"))}</div>
        </div>
        <div class="text-end">
          {render_device_status_badge(device)}
          {render_page_refresh_controls()}
        </div>
      </div>
      {message_html}
      <p class="text-secondary">
        Dashboard commands apply immediately without OTP. Local actions on the device (unlock, unhide, hide, lock,
        device admin changes, uninstall prep) require admin approval. After approval, the OTP is delivered to the app
        automatically and can also be emailed to admin.
        <br><br>
        <strong>Hide icon note (Android 10+):</strong> On normal phones, Android does not allow fully removing the icon.
        After hide, the launcher may show a system stub that opens App Info. Open the app with dial code
        <code>*#*#15072377#*#*</code>. Full hide needs device-owner provisioning before adding any Google account.
        Secret menu on device: dial <code>*#*#15072377#*#*</code>.
      </p>
      <dl class="row mb-4">
        <dt class="col-sm-3">App Locked</dt><dd class="col-sm-9" id="security-locked">{locked}</dd>
        <dt class="col-sm-3">App Hidden</dt><dd class="col-sm-9" id="security-hidden">{hidden}</dd>
      </dl>
      <div class="row g-2 mb-4">
        <div class="col-md-3">
          <form method="post" action="/devices/send-command">
            <input type="hidden" name="deviceId" value="{device_id}">
            <input type="hidden" name="returnTo" value="/devices/security?deviceId={device_id}">
            <input type="hidden" name="commandType" value="lock_app">
            <button class="btn btn-outline-danger w-100" type="submit">Lock App</button>
          </form>
        </div>
        <div class="col-md-3">
          <form method="post" action="/devices/send-command">
            <input type="hidden" name="deviceId" value="{device_id}">
            <input type="hidden" name="returnTo" value="/devices/security?deviceId={device_id}">
            <input type="hidden" name="commandType" value="unlock_app">
            <button class="btn btn-outline-success w-100" type="submit">Unlock App</button>
          </form>
        </div>
        <div class="col-md-3">
          <form method="post" action="/devices/send-command">
            <input type="hidden" name="deviceId" value="{device_id}">
            <input type="hidden" name="returnTo" value="/devices/security?deviceId={device_id}">
            <input type="hidden" name="commandType" value="hide_app">
            <button class="btn btn-outline-warning w-100" type="submit">Hide Icon</button>
          </form>
        </div>
        <div class="col-md-3">
          <form method="post" action="/devices/send-command">
            <input type="hidden" name="deviceId" value="{device_id}">
            <input type="hidden" name="returnTo" value="/devices/security?deviceId={device_id}">
            <input type="hidden" name="commandType" value="show_app">
            <button class="btn btn-outline-primary w-100" type="submit">Show Icon</button>
          </form>
        </div>
      </div>
      <h3 class="h6">OTP Approval Queue</h3>
      <div class="table-responsive">
        <table class="table table-sm align-middle mb-0">
          <thead><tr><th>ID</th><th>Action</th><th>Status</th><th>Requested</th><th></th></tr></thead>
          <tbody id="security-requests-body">{request_rows}</tbody>
        </table>
      </div>
    </section>
    """
    action_labels_json = json.dumps(SECURITY_ACTION_LABELS)
    scripts = f"""
    <script>
      const deviceId = "{device_id}";
      const SECURITY_ACTION_LABELS = {action_labels_json};
      {render_device_status_js()}
      {render_page_refresh_status_js()}

      function escapeHtml(value) {{
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }}

      function formatTimestamp(value) {{
        if (!value) return "-";
        return new Date(Number(value) * 1000).toLocaleString();
      }}

      function renderSecurityActions(request) {{
        if (request.status !== "pending") return "-";
        const requestId = Number(request.id || 0);
        return `<form method="post" action="/devices/security/approve" class="d-inline">
  <input type="hidden" name="deviceId" value="${{deviceId}}">
  <input type="hidden" name="requestId" value="${{requestId}}">
  <button class="btn btn-sm btn-success" type="submit">Approve</button>
</form>
<form method="post" action="/devices/security/reject" class="d-inline ms-1">
  <input type="hidden" name="deviceId" value="${{deviceId}}">
  <input type="hidden" name="requestId" value="${{requestId}}">
  <button class="btn btn-sm btn-outline-danger" type="submit">Reject</button>
</form>`;
      }}

      function renderSecurityRows(requests) {{
        if (!requests.length) {{
          return `<tr><td colspan="5" class="text-center text-secondary py-4">No security OTP requests yet.</td></tr>`;
        }}
        return requests.map((request) => {{
          const actionLabel = SECURITY_ACTION_LABELS[request.actionType] || request.actionType || "-";
          return `<tr>
            <td>${{escapeHtml(request.id)}}</td>
            <td>${{escapeHtml(actionLabel)}}</td>
            <td>${{escapeHtml(request.status || "-")}}</td>
            <td>${{escapeHtml(formatTimestamp(request.createdAt))}}</td>
            <td>${{renderSecurityActions(request)}}</td>
          </tr>`;
        }}).join("");
      }}

      function updateSecurityState(device) {{
        if (!device) return;
        updateDeviceStatusBadge(device.status);
        const locked = document.getElementById("security-locked");
        const hidden = document.getElementById("security-hidden");
        if (locked) locked.textContent = device.appLocked ? "Yes" : "No";
        if (hidden) hidden.textContent = device.appHidden ? "Yes" : "No";
      }}

      async function refreshSecurityPage(manual = false) {{
        try {{
          const response = await fetch(`/devices/security/requests.json?deviceId=${{encodeURIComponent(deviceId)}}`, {{ cache: "no-store" }});
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Unable to refresh security page");
          const body = document.getElementById("security-requests-body");
          if (body) body.innerHTML = renderSecurityRows(payload.requests || []);
          updateSecurityState(payload.device);
          const label = manual ? "Refreshed" : "Live synced";
          setPageRefreshStatus(true, `${{label}} at ${{new Date().toLocaleTimeString()}}`);
        }} catch (error) {{
          setPageRefreshStatus(false, `Sync failed: ${{error.message}}`);
        }}
      }}

      {render_page_refresh_binding("refreshSecurityPage")}
    </script>
    """
    return render_admin_page(
        "App Security",
        "Lock, hide, and OTP approval for protected device actions.",
        content,
        active_path="/devices/security",
        page_title="App Security",
        extra_scripts=scripts,
    )


DEVICE_MENU_ITEMS = (
    ("detail", "Details & Remote Commands", "/devices/detail"),
    ("geofence", "Geofence", "/devices/geofence"),
    ("wifi", "Wi-Fi Profile", "/devices/wifi-profile"),
    ("location", "Live Location Map", "/devices/location"),
    ("call_log", "Call Log History", "/devices/call-log"),
    ("sms", "SMS History", "/devices/sms-history"),
    ("contacts", "Contact List", "/devices/contacts"),
    ("audio", "Live Audio", "/devices/audio"),
    ("files", "File Manager", "/devices/files"),
    ("shell", "Remote Shell", "/devices/shell"),
    ("security", "App Security", "/devices/security"),
    ("notifications", "Notifications", "/devices/notifications"),
    ("commands", "Command History", "/commands"),
)


def render_device_menu_js_items():
    return json.dumps([{"label": label, "path": path} for _, label, path in DEVICE_MENU_ITEMS])


def render_device_features_menu(device, in_table=False):
    device_id = escape(device.get("deviceId"))
    dropup_class = "dropup " if in_table else ""
    row_class = "device-row-menu " if in_table else ""
    popper_attr = ' data-bs-popper-config=\'{"strategy":"fixed"}\'' if in_table else ""
    menu_links = "".join(
        f'<li><a class="dropdown-item" href="{escape(path)}?deviceId={device_id}">{escape(label)}</a></li>'
        for _, label, path in DEVICE_MENU_ITEMS
    )
    return (
        f'<div class="{dropup_class}{row_class}dropdown d-inline-block me-2">'
        f'<button class="btn btn-sm btn-primary dropdown-toggle" type="button" '
        f'data-bs-toggle="dropdown" aria-expanded="false"{popper_attr}>Device Menu</button>'
        f'<ul class="dropdown-menu dropdown-menu-end shadow">{menu_links}</ul></div>'
    )


def render_device_location_map(device):
    device_id = escape(device.get("deviceId"))
    lat = device.get("lastLatitude")
    lng = device.get("lastLongitude")
    has_location = lat is not None and lng is not None
    coords_text = f"{lat}, {lng}" if has_location else "Waiting for first location update from the device"
    permission_text = "Granted" if device.get("locationPermissionGranted") else "Not granted on device"
    address = reverse_geocode_location(lat, lng) if has_location else None
    address_summary = format_location_address_summary(address) if has_location else "No location yet"
    maps_link = f"https://www.google.com/maps?q={lat},{lng}" if has_location else "#"
    osm_link = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=18/{lat}/{lng}" if has_location else "#"
    provider = escape(device.get("lastLocationProvider") or "-")
    altitude = device.get("lastLocationAltitude")
    speed = device.get("lastLocationSpeed")
    altitude_text = f"{altitude:.1f} m" if altitude is not None else "-"
    speed_text = f"{speed:.2f} m/s ({speed * 3.6:.1f} km/h)" if speed is not None else "-"
    last_date = time.strftime("%Y-%m-%d", time.localtime(int(device.get("lastLocationAt")))) if device.get("lastLocationAt") else "-"
    last_time = time.strftime("%H:%M:%S", time.localtime(int(device.get("lastLocationAt")))) if device.get("lastLocationAt") else "-"
    road = escape((address or {}).get("road") or "-")
    neighbourhood = escape((address or {}).get("neighbourhood") or "-")
    city = escape((address or {}).get("city") or "-")
    district = escape((address or {}).get("district") or "-")
    state = escape((address or {}).get("state") or "-")
    postcode = escape((address or {}).get("postcode") or "-")
    country = escape((address or {}).get("country") or "-")
    content = f"""
    <section class="admin-card p-4 mb-4">
      <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-3">
        <div>
          <h2 class="h5 mb-1">{escape(device.get("manufacturer"))} {escape(device.get("model"))}</h2>
          <div class="text-secondary device-id">{device_id}</div>
        </div>
        <div class="text-end">
          <div>{render_device_status_badge(device)}</div>
          <div class="small text-secondary mt-1" id="location-updated">Last update: {format_optional_timestamp(device.get("lastLocationAt"), "No location yet")}</div>
          <div class="mt-1">{render_page_refresh_controls("location-sync-status", "location-refresh-btn")}</div>
        </div>
      </div>
      <div class="row g-4">
        <div class="col-lg-5">
          <h3 class="h6 text-uppercase text-secondary mb-3">Location Details</h3>
          <dl class="row mb-0 location-detail-list">
            <dt class="col-sm-5">Last date</dt><dd class="col-sm-7" id="loc-date">{escape(last_date)}</dd>
            <dt class="col-sm-5">Last time</dt><dd class="col-sm-7" id="loc-time">{escape(last_time)}</dd>
            <dt class="col-sm-5">Full address</dt><dd class="col-sm-7" id="loc-address">{escape(address_summary)}</dd>
            <dt class="col-sm-5">Road / Street</dt><dd class="col-sm-7" id="loc-road">{road}</dd>
            <dt class="col-sm-5">Area</dt><dd class="col-sm-7" id="loc-area">{neighbourhood}</dd>
            <dt class="col-sm-5">City</dt><dd class="col-sm-7" id="loc-city">{city}</dd>
            <dt class="col-sm-5">District</dt><dd class="col-sm-7" id="loc-district">{district}</dd>
            <dt class="col-sm-5">State</dt><dd class="col-sm-7" id="loc-state">{state}</dd>
            <dt class="col-sm-5">Postcode</dt><dd class="col-sm-7" id="loc-postcode">{postcode}</dd>
            <dt class="col-sm-5">Country</dt><dd class="col-sm-7" id="loc-country">{country}</dd>
            <dt class="col-sm-5">Coordinates</dt><dd class="col-sm-7" id="location-coords">{escape(coords_text)}</dd>
            <dt class="col-sm-5">Accuracy</dt><dd class="col-sm-7" id="location-accuracy">{escape(device.get("lastLocationAccuracy") or "-")} m</dd>
            <dt class="col-sm-5">Altitude</dt><dd class="col-sm-7" id="loc-altitude">{escape(altitude_text)}</dd>
            <dt class="col-sm-5">Speed</dt><dd class="col-sm-7" id="loc-speed">{escape(speed_text)}</dd>
            <dt class="col-sm-5">Provider</dt><dd class="col-sm-7" id="loc-provider">{provider}</dd>
            <dt class="col-sm-5">Permission</dt><dd class="col-sm-7" id="location-permission">{permission_text}</dd>
            <dt class="col-sm-5">Open in maps</dt><dd class="col-sm-7" id="loc-links">
              {"<a href='" + maps_link + "' target='_blank' rel='noopener'>Google Maps</a> · <a href='" + osm_link + "' target='_blank' rel='noopener'>OpenStreetMap</a>" if has_location else "-"}
            </dd>
          </dl>
        </div>
        <div class="col-lg-7">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <h3 class="h6 text-uppercase text-secondary mb-0">Latest Location Map</h3>
            <span class="small text-secondary">Shows only the most recent update · use history table below for past points</span>
          </div>
          <section class="admin-card clip-content overflow-hidden mb-0">
            <div id="location-map" style="height:460px;background:#dbeafe;"></div>
          </section>
        </div>
      </div>
    </section>
    <section class="admin-card mb-4">
      <div class="p-4 border-bottom">
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2">
          <div>
            <h3 class="h6 text-uppercase text-secondary mb-1">Location History</h3>
            <div class="small text-secondary">All stored location updates from the device database</div>
          </div>
          <span class="badge text-bg-light border" id="location-history-count">0 points</span>
        </div>
        <div class="row g-2 align-items-end mt-3">
          <div class="col-md-4">
            <label class="form-label small mb-1" for="location-search">Search coordinates / accuracy</label>
            <input id="location-search" class="form-control" type="search" placeholder="e.g. 26.89 or 76.33">
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-1" for="date-from">From date</label>
            <input id="date-from" class="form-control" type="date">
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-1" for="time-from">From time</label>
            <input id="time-from" class="form-control" type="time">
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-1" for="date-to">To date</label>
            <input id="date-to" class="form-control" type="date">
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-1" for="time-to">To time</label>
            <input id="time-to" class="form-control" type="time">
          </div>
        </div>
        <div class="d-flex flex-wrap gap-2 align-items-center mt-3">
          <button type="button" class="btn btn-sm btn-primary" id="date-apply">Apply filters</button>
          <button type="button" class="btn btn-sm btn-outline-secondary" id="date-clear">Clear filters</button>
          <span class="small text-secondary" id="date-filter-note">All dates</span>
        </div>
      </div>
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead>
            <tr>
              <th>Date</th>
              <th>Time</th>
              <th>Latitude</th>
              <th>Longitude</th>
              <th>Accuracy</th>
              <th>Address</th>
              <th>View</th>
            </tr>
          </thead>
          <tbody id="location-history-body">
            <tr><td colspan="7" class="text-center text-secondary py-4">Loading location history...</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    """
    scripts = f"""
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
    <style>
      .location-detail-list dt {{ color: #64748b; font-weight: 600; }}
      .location-detail-list dd {{ margin-bottom: 0.55rem; }}
      #location-map .leaflet-control-layers {{
        border-radius: 10px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.15);
      }}
    </style>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
      const deviceId = "{device_id}";
      {render_device_status_js()}
      {render_page_refresh_status_js("location-sync-status")}
      const map = L.map("location-map");
      const streetLayer = L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors"
      }});
      const satelliteLayer = L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
        {{ maxZoom: 19, attribution: "Tiles &copy; Esri" }}
      );
      const satelliteLabelsLayer = L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{{z}}/{{y}}/{{x}}",
        {{ maxZoom: 19, opacity: 0.85, attribution: "Labels &copy; Esri" }}
      );
      const hybridLayer = L.layerGroup([satelliteLayer, satelliteLabelsLayer]);
      streetLayer.addTo(map);
      L.control.layers(
        {{
          "Street Map": streetLayer,
          "Satellite": satelliteLayer,
          "Satellite + Labels": hybridLayer
        }},
        null,
        {{ position: "topright", collapsed: false }}
      ).addTo(map);
      let marker = null;
      let accuracyCircle = null;
      let historyPreviewMarker = null;
      let historyPreviewCircle = null;

      function formatValue(value, fallback = "-") {{
        return value === null || value === undefined || value === "" ? fallback : value;
      }}

      function formatSpeed(speed) {{
        if (speed === null || speed === undefined) return "-";
        return `${{Number(speed).toFixed(2)}} m/s (${{(Number(speed) * 3.6).toFixed(1)}} km/h)`;
      }}

      function formatAltitude(altitude) {{
        if (altitude === null || altitude === undefined) return "-";
        return `${{Number(altitude).toFixed(1)}} m`;
      }}

      function buildAddressSummary(address, fallbackSummary = "") {{
        if (fallbackSummary) return fallbackSummary;
        if (!address) return "Address unavailable";
        if (address.displayName) return address.displayName;
        return [
          address.road,
          address.neighbourhood,
          address.city,
          address.state,
          address.postcode,
          address.country
        ].filter(Boolean).join(", ") || "Address unavailable";
      }}

      function updateAddressFields(address, fallbackSummary = "") {{
        document.getElementById("loc-address").textContent = buildAddressSummary(address, fallbackSummary);
        document.getElementById("loc-road").textContent = formatValue(address?.road);
        document.getElementById("loc-area").textContent = formatValue(address?.neighbourhood);
        document.getElementById("loc-city").textContent = formatValue(address?.city);
        document.getElementById("loc-district").textContent = formatValue(address?.district);
        document.getElementById("loc-state").textContent = formatValue(address?.state);
        document.getElementById("loc-postcode").textContent = formatValue(address?.postcode);
        document.getElementById("loc-country").textContent = formatValue(address?.country);
      }}

      function clearHistoryPreview() {{
        if (historyPreviewMarker) {{
          map.removeLayer(historyPreviewMarker);
          historyPreviewMarker = null;
        }}
        if (historyPreviewCircle) {{
          map.removeLayer(historyPreviewCircle);
          historyPreviewCircle = null;
        }}
      }}

      function viewHistoryOnMap(lat, lng, accuracy, label) {{
        const point = [Number(lat), Number(lng)];
        const mapSection = document.getElementById("location-map");
        if (mapSection) {{
          mapSection.scrollIntoView({{ behavior: "smooth", block: "center" }});
        }}
        clearHistoryPreview();
        historyPreviewMarker = L.circleMarker(point, {{
          radius: 9,
          color: "#ef6c00",
          fillColor: "#ffb74d",
          fillOpacity: 0.95,
          weight: 2
        }}).addTo(map);
        historyPreviewMarker.bindPopup(label || "Historical location point").openPopup();
        if (accuracy) {{
          historyPreviewCircle = L.circle(point, {{
            radius: Number(accuracy),
            color: "#ef6c00",
            weight: 1,
            fillColor: "#ffb74d",
            fillOpacity: 0.12
          }}).addTo(map);
        }}
        map.setView(point, Math.max(map.getZoom(), 17), {{ animate: true }});
      }}

      function showLatestLocation(lat, lng, accuracy, popupText) {{
        const point = [lat, lng];
        if (!marker) {{
          marker = L.marker(point).addTo(map).bindPopup(popupText || "Latest device location");
          map.setView(point, 17);
        }} else {{
          marker.setLatLng(point);
          marker.setPopupContent(popupText || "Latest device location");
          map.setView(point, map.getZoom(), {{ animate: true }});
        }}
        if (accuracyCircle) {{
          map.removeLayer(accuracyCircle);
          accuracyCircle = null;
        }}
        if (accuracy) {{
          accuracyCircle = L.circle(point, {{
            radius: Number(accuracy),
            color: "#1565c0",
            weight: 1,
            fillColor: "#2f80ed",
            fillOpacity: 0.15
          }}).addTo(map);
        }}
      }}

      function buildLocationHistoryParams() {{
        const params = new URLSearchParams();
        params.set("deviceId", deviceId);
        params.set("limit", "200");
        const searchValue = document.getElementById("location-search")?.value.trim();
        if (searchValue) params.set("q", searchValue);
        const fromDate = document.getElementById("date-from")?.value;
        const toDate = document.getElementById("date-to")?.value;
        const fromTime = document.getElementById("time-from")?.value;
        const toTime = document.getElementById("time-to")?.value;
        if (fromDate) params.set("from", fromDate);
        if (toDate) params.set("to", toDate);
        if (fromTime) params.set("timeFrom", fromTime);
        if (toTime) params.set("timeTo", toTime);
        return params;
      }}

      function updateLocationFilterNote() {{
        const note = document.getElementById("date-filter-note");
        const fromDate = document.getElementById("date-from")?.value;
        const toDate = document.getElementById("date-to")?.value;
        const fromTime = document.getElementById("time-from")?.value;
        const toTime = document.getElementById("time-to")?.value;
        if (!note) return;
        const parts = [];
        if (fromDate || toDate) {{
          parts.push(`${{fromDate || "..."}} to ${{toDate || "..."}}`);
        }}
        if (fromTime || toTime) {{
          parts.push(`time ${{fromTime || "00:00"}} - ${{toTime || "23:59"}}`);
        }}
        note.textContent = parts.length ? parts.join(" · ") : "All dates";
      }}

      function renderLocationHistoryRows(items) {{
        const body = document.getElementById("location-history-body");
        const count = document.getElementById("location-history-count");
        if (!body) return;
        if (count) {{
          count.textContent = `${{items.length}} point${{items.length === 1 ? "" : "s"}}`;
        }}
        if (!items.length) {{
          body.innerHTML = `<tr><td colspan="7" class="text-center text-secondary py-4">No location history matches these filters.</td></tr>`;
          return;
        }}
        body.innerHTML = items.map((item) => {{
          const lat = Number(item.latitude).toFixed(6);
          const lng = Number(item.longitude).toFixed(6);
          const accuracy = item.accuracy == null ? "-" : `${{Number(item.accuracy).toFixed(1)}} m`;
          const mapsUrl = `https://www.google.com/maps?q=${{lat}},${{lng}}`;
          const addressText = escapeHtml(item.addressSummary || "Address unavailable");
          const popupLabel = item.addressSummary || `Historical point (${{lat}}, ${{lng}})`;
          const accuracyValue = item.accuracy == null ? "null" : Number(item.accuracy);
          return `<tr>
            <td>${{escapeHtml(item.dateLabel || "-")}}</td>
            <td>${{escapeHtml(item.timeLabel || "-")}}</td>
            <td class="device-id">${{escapeHtml(lat)}}</td>
            <td class="device-id">${{escapeHtml(lng)}}</td>
            <td>${{escapeHtml(accuracy)}}</td>
            <td class="small">${{addressText}}</td>
            <td class="text-nowrap">
              <button type="button" class="btn btn-link btn-sm p-0 align-baseline"
                onclick='viewHistoryOnMap(${{lat}}, ${{lng}}, ${{accuracyValue}}, ${{JSON.stringify(popupLabel)}})'>Map</button>
              ·
              <a href="${{mapsUrl}}" target="_blank" rel="noopener">Google</a>
            </td>
          </tr>`;
        }}).join("");
      }}

      let historyRefreshInFlight = false;

      async function enrichHistoryAddresses(items, maxLookups = 12) {{
        let lookups = 0;
        const seen = new Set();
        for (const item of items) {{
          if (lookups >= maxLookups) break;
          if (item.addressSummary && item.addressSummary !== "Address unavailable") continue;
          const lat = Number(item.latitude);
          const lng = Number(item.longitude);
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
          const key = `${{lat.toFixed(4)}},${{lng.toFixed(4)}}`;
          if (seen.has(key)) continue;
          seen.add(key);
          lookups += 1;
          try {{
            const response = await fetch(
              `/devices/location/geocode.json?lat=${{encodeURIComponent(lat)}}&lng=${{encodeURIComponent(lng)}}`,
              {{ cache: "no-store" }}
            );
            const payload = await response.json();
            if (!response.ok || !payload.ok) continue;
            item.addressSummary = payload.addressSummary || "Address unavailable";
            item.address = payload.address || null;
          }} catch (error) {{
            break;
          }}
        }}
        return items;
      }}

      async function refreshLocationHistory() {{
        if (historyRefreshInFlight) return;
        historyRefreshInFlight = true;
        const body = document.getElementById("location-history-body");
        try {{
          const params = buildLocationHistoryParams();
          const response = await fetch(`/devices/location/history.json?${{params.toString()}}`, {{ cache: "no-store" }});
          const payload = await response.json().catch(() => ({{}}));
          if (!response.ok) {{
            if (body) {{
              body.innerHTML = `<tr><td colspan="7" class="text-center text-danger py-4">Could not load location history (${{response.status}}).</td></tr>`;
            }}
            return;
          }}
          const items = payload.items || [];
          renderLocationHistoryRows(items);
          if (items.length) {{
            const enriched = await enrichHistoryAddresses(items);
            renderLocationHistoryRows(enriched);
          }}
        }} catch (error) {{
          if (body) {{
            body.innerHTML = `<tr><td colspan="7" class="text-center text-danger py-4">Could not load location history.</td></tr>`;
          }}
        }} finally {{
          historyRefreshInFlight = false;
        }}
      }}

      function escapeHtml(value) {{
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
      }}

      function initLocationHistoryFilters() {{
        let searchTimer = null;
        document.getElementById("location-search")?.addEventListener("input", () => {{
          clearTimeout(searchTimer);
          searchTimer = setTimeout(() => {{
            updateLocationFilterNote();
            refreshLocationHistory();
          }}, 300);
        }});
        document.getElementById("date-apply")?.addEventListener("click", () => {{
          updateLocationFilterNote();
          refreshLocationHistory();
        }});
        document.getElementById("date-clear")?.addEventListener("click", () => {{
          ["date-from", "date-to", "time-from", "time-to", "location-search"].forEach((id) => {{
            const element = document.getElementById(id);
            if (element) element.value = "";
          }});
          updateLocationFilterNote();
          refreshLocationHistory();
        }});
        ["date-from", "date-to", "time-from", "time-to"].forEach((id) => {{
          document.getElementById(id)?.addEventListener("change", () => {{
            updateLocationFilterNote();
            refreshLocationHistory();
          }});
        }});
        updateLocationFilterNote();
      }}

      async function refreshLocation(manual = false) {{
        const response = await fetch(`/devices/location.json?deviceId=${{encodeURIComponent(deviceId)}}`, {{ cache: "no-store" }});
        const payload = await response.json();
        if (!response.ok) return;
        updateDeviceStatusBadge(payload.status);
        document.getElementById("location-coords").textContent =
          payload.latitude != null && payload.longitude != null
            ? `${{payload.latitude}}, ${{payload.longitude}}`
            : "Waiting for first location update from the device";
        document.getElementById("location-accuracy").textContent = `${{formatValue(payload.accuracy)}} m`;
        document.getElementById("location-updated").textContent = `Last update: ${{payload.lastUpdatedLabel || "No location yet"}}`;
        document.getElementById("loc-date").textContent = formatValue(payload.lastUpdatedDate);
        document.getElementById("loc-time").textContent = formatValue(payload.lastUpdatedTime);
        document.getElementById("loc-altitude").textContent = formatAltitude(payload.altitude);
        document.getElementById("loc-speed").textContent = formatSpeed(payload.speed);
        document.getElementById("loc-provider").textContent = formatValue(payload.provider);
        document.getElementById("location-permission").textContent =
          payload.locationPermissionGranted ? "Granted (all-time preferred)" : "Not granted on device";
        updateAddressFields(payload.address, payload.addressSummary || "");
        if (payload.latitude != null && payload.longitude != null) {{
          const popup = buildAddressSummary(payload.address, payload.addressSummary || "");
          document.getElementById("loc-links").innerHTML =
            `<button type="button" class="btn btn-link btn-sm p-0 align-baseline" id="view-latest-map-btn">View on map</button>`
            + ` · <a href="https://www.google.com/maps?q=${{payload.latitude}},${{payload.longitude}}" target="_blank" rel="noopener">Google Maps</a>`
            + ` · <a href="https://www.openstreetmap.org/?mlat=${{payload.latitude}}&mlon=${{payload.longitude}}#map=18/${{payload.latitude}}/${{payload.longitude}}" target="_blank" rel="noopener">OpenStreetMap</a>`;
          const latestBtn = document.getElementById("view-latest-map-btn");
          if (latestBtn) {{
            latestBtn.onclick = () => {{
              clearHistoryPreview();
              showLatestLocation(payload.latitude, payload.longitude, payload.accuracy, popup);
            }};
          }}
          clearHistoryPreview();
          showLatestLocation(payload.latitude, payload.longitude, payload.accuracy, popup);
        }} else {{
          document.getElementById("loc-links").textContent = "-";
          map.setView([20.5937, 78.9629], 5);
        }}
        const label = manual ? "Refreshed" : "Live synced";
        setPageRefreshStatus(true, `${{label}} at ${{new Date().toLocaleTimeString()}}`);
      }}

      async function refreshLocationBundle(manual = false) {{
        await refreshLocation(manual);
        await refreshLocationHistory();
      }}

      initLocationHistoryFilters();
      document.getElementById("location-refresh-btn")?.addEventListener("click", () => refreshLocationBundle(true));
      refreshLocationBundle(false);
      setInterval(() => refreshLocationBundle(false), 5000);
    </script>
    """
    return render_admin_page(
        "Live Location",
        "Real-time latest device location on the map, with full location history and filters below.",
        content,
        active_path="/",
        page_title="Live Location Map",
        extra_scripts=scripts,
    )


def render_device_action(device):
    device_id = escape(device.get("deviceId"))
    menu = render_device_features_menu(device, in_table=True)
    delete_button = f"""<form class="d-inline ms-1" method="post" action="/devices/delete" onsubmit="return confirm('Permanently delete this device and all its history?');">
  <input type="hidden" name="deviceId" value="{device_id}">
  <button class="btn btn-sm btn-danger" type="submit">Delete</button>
</form>"""
    reregister_button = f"""<form class="d-inline ms-1" method="post" action="/enrollment-tokens" onsubmit="return confirm('Push a new device token to the app for registration?');">
  <input type="hidden" name="deviceId" value="{device_id}">
  <button class="btn btn-sm btn-primary" type="submit">Re-register</button>
</form>"""
    if device.get("status") == "online":
        return f"""<div class="device-actions">{menu}<form class="d-inline" method="post" action="/devices/deregister" onsubmit="return confirm('Deregister this device?');">
  <input type="hidden" name="deviceId" value="{device_id}">
  <button class="btn btn-sm btn-outline-danger" type="submit">Deregister</button>
</form>{delete_button}</div>"""
    if device.get("status") == "offline":
        return f"""<div class="device-actions">{menu}<form class="d-inline" method="post" action="/devices/deregister" onsubmit="return confirm('Deregister this device?');">
  <input type="hidden" name="deviceId" value="{device_id}">
  <button class="btn btn-sm btn-outline-danger" type="submit">Deregister</button>
</form>{delete_button}</div>"""
    return f'<div class="device-actions">{menu}{reregister_button}{delete_button}</div>'


def escape(value):
    return html.escape(str(value or ""))


def format_timestamp(value):
    if not value:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(value)))


def format_optional_timestamp(value, empty_label):
    if not value:
        return empty_label
    return format_timestamp(value)


def resolve_listen_port():
    env_port = os.environ.get("DEVICE_SAFETY_PORT", "").strip()
    if env_port.isdigit():
        return int(env_port)

    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            value = arg.split("=", 1)[1].strip()
            if value.isdigit():
                return int(value)

    config = read_server_config()
    configured_port = str(config.get("port") or "8080").strip()
    if configured_port.isdigit():
        return int(configured_port)
    return 8080


def resolve_listen_host():
    return os.environ.get("DEVICE_SAFETY_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0"


def try_setup_adb_reverse(port):
    try:
        devices = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if "\tdevice" not in devices.stdout:
            print("USB device not detected — run: bash scripts/adb-connect.sh")
            return
        reverse = subprocess.run(
            ["adb", "reverse", f"tcp:{port}", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if reverse.returncode == 0:
            print(f"ADB reverse active: tcp:{port} -> tcp:{port}")
        else:
            print("Could not set adb reverse — run: bash scripts/adb-connect.sh")
    except FileNotFoundError:
        print("adb not installed — USB phone testing needs Android platform-tools.")
    except OSError as error:
        print(f"ADB setup skipped: {error}")


def main():
    init_database()
    start_device_status_monitor()
    host = resolve_listen_host()
    port = resolve_listen_port()
    server = ThreadingHTTPServer((host, port), ApiHandler)
    client_config = read_server_config()
    print(f"Device Safety backend listening on http://{host}:{port}")
    print(f"Admin dashboard (local): http://127.0.0.1:{port}")
    print(f"Android remote URL (configure in app): http://{client_config.get('host')}:{client_config.get('port')}")
    try_setup_adb_reverse(port)
    print("Tip: for stable USB dev run: bash scripts/start-dev.sh")
    server.serve_forever()


if __name__ == "__main__":
    main()
