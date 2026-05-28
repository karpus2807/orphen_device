-- Device Safety Manager database schema.
-- This file is the source of truth for tables. Keep it updated as features add tables/columns.
-- SQLite uses INTEGER for booleans; MySQL can map these to TINYINT(1).

CREATE TABLE IF NOT EXISTS admins (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    manufacturer TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    android_version TEXT NOT NULL DEFAULT '',
    api_level TEXT NOT NULL DEFAULT '',
    device_token_hash TEXT,
    pending_device_token TEXT,
    device_token_sealed TEXT,
    device_admin_active INTEGER NOT NULL DEFAULT 0,
    last_wifi_ssid TEXT,
    geofence_ok INTEGER,
    usage_summary_json TEXT,
    battery_summary_json TEXT,
    usage_summary_at INTEGER,
    battery_summary_at INTEGER,
    last_latitude REAL,
    last_longitude REAL,
    last_location_accuracy REAL,
    last_location_at INTEGER,
    location_permission_granted INTEGER,
    last_location_provider TEXT,
    last_location_altitude REAL,
    last_location_speed REAL,
    usage_access_granted INTEGER,
    call_log_permission_granted INTEGER,
    sms_permission_granted INTEGER,
    contacts_permission_granted INTEGER,
    audio_permission_granted INTEGER,
    audio_stream_active INTEGER,
    storage_permission_granted INTEGER,
    notification_access_granted INTEGER,
    app_locked INTEGER NOT NULL DEFAULT 0,
    app_hidden INTEGER NOT NULL DEFAULT 0,
    registered INTEGER NOT NULL DEFAULT 1,
    device_group TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    deregistered_at INTEGER
);

CREATE TABLE IF NOT EXISTS heartbeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    event TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_heartbeats_device_time
ON heartbeats (device_id, timestamp);

CREATE TABLE IF NOT EXISTS enrollment_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    used_by_device_id TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_enrollment_tokens_hash
ON enrollment_tokens (token_hash);

CREATE TABLE IF NOT EXISTS policy_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS server_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS smtp_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS geofence_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ota_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS wifi_profile_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS device_settings (
    device_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (device_id, key),
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_resets_token
ON password_resets (token_hash);

CREATE TABLE IF NOT EXISTS device_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    delivered_at INTEGER,
    completed_at INTEGER,
    result TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_device_commands_device_status
ON device_commands (device_id, status);

CREATE TABLE IF NOT EXISTS device_location_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    accuracy REAL,
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_device_location_history_device_time
ON device_location_history (device_id, timestamp);

CREATE TABLE IF NOT EXISTS device_call_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    phone_number TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    call_type TEXT NOT NULL DEFAULT '',
    country_iso TEXT NOT NULL DEFAULT '',
    location_label TEXT NOT NULL DEFAULT '',
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_device_call_history_device_time
ON device_call_history (device_id, timestamp);

CREATE UNIQUE INDEX IF NOT EXISTS idx_device_call_history_unique
ON device_call_history (device_id, source_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_device_call_history_fallback
ON device_call_history (device_id, timestamp, phone_number, call_type, duration_seconds)
WHERE source_id = '';

CREATE TABLE IF NOT EXISTS device_sms_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    sms_type TEXT NOT NULL DEFAULT '',
    read_state TEXT NOT NULL DEFAULT '',
    thread_id TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_device_sms_history_device_time
ON device_sms_history (device_id, timestamp);

CREATE UNIQUE INDEX IF NOT EXISTS idx_device_sms_history_unique
ON device_sms_history (device_id, source_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_device_sms_history_fallback
ON device_sms_history (device_id, timestamp, address, sms_type, body)
WHERE source_id = '';

CREATE TABLE IF NOT EXISTS device_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    contact_id TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    phone_number TEXT NOT NULL DEFAULT '',
    phone_type TEXT NOT NULL DEFAULT '',
    phone_label TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    organization TEXT NOT NULL DEFAULT '',
    starred INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_device_contacts_device_name
ON device_contacts (device_id, display_name);

CREATE UNIQUE INDEX IF NOT EXISTS idx_device_contacts_unique
ON device_contacts (device_id, source_id);

CREATE TABLE IF NOT EXISTS security_otp_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    otp_hash TEXT,
    device_otp_code TEXT,
    created_at INTEGER NOT NULL,
    approved_at INTEGER,
    expires_at INTEGER,
    used_at INTEGER,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_security_otp_requests_device_status
ON security_otp_requests (device_id, status);

CREATE TABLE IF NOT EXISTS device_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    package_name TEXT NOT NULL DEFAULT '',
    app_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_device_notifications_device_time
ON device_notifications (device_id, timestamp);

CREATE UNIQUE INDEX IF NOT EXISTS idx_device_notifications_unique
ON device_notifications (device_id, source_id);

CREATE TABLE IF NOT EXISTS app_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_name TEXT NOT NULL,
    app_label TEXT NOT NULL DEFAULT '',
    version_name TEXT NOT NULL,
    version_code INTEGER NOT NULL,
    apk_filename TEXT NOT NULL,
    release_notes TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_app_releases_pkg ON app_releases (package_name, version_code);

CREATE TABLE IF NOT EXISTS update_manager_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_name TEXT NOT NULL UNIQUE,
    app_label TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1
);
