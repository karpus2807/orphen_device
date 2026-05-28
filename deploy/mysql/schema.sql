-- MySQL schema mirror for phpMyAdmin (optional admin DB).
-- Runtime app uses SQLite at backend/data/device_safety.db unless DEVICE_SAFETY_USE_MYSQL=1.

CREATE TABLE IF NOT EXISTS devices (
    device_id VARCHAR(64) PRIMARY KEY,
    manufacturer VARCHAR(128) NOT NULL DEFAULT '',
    model VARCHAR(128) NOT NULL DEFAULT '',
    android_version VARCHAR(32) NOT NULL DEFAULT '',
    api_level VARCHAR(16) NOT NULL DEFAULT '',
    registered TINYINT(1) NOT NULL DEFAULT 1,
    created_at BIGINT NOT NULL,
    last_seen_at BIGINT NOT NULL
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
