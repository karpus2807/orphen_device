# Orphen Device Safety Manager

Transparent, consent-based Android device management learning project with an admin dashboard and Python backend.

## Project structure

- `app/` — Android client (Device Safety Manager)
- `backend/` — Python admin server, SQLite database, web dashboard
- `build/` — local APK build output (ignored by git)

## Backend

```bash
python3 backend/server.py
```

Dashboard: `http://127.0.0.1:8080`

Default admin login: `admin` / `admin123`

## Android app

Build and install (requires Android SDK):

```bash
BT="$HOME/Android/Sdk/build-tools/36.1.0"
PLATFORM="$HOME/Android/Sdk/platforms/android-36/android.jar"
# See project history for full manual aapt2/d8/apksigner build command
```

For USB testing with a local backend:

```bash
adb reverse tcp:8080 tcp:8080
adb install -r build/device-safety-manager-debug.apk
```

## Server deployment (other machine + auto-update)

See **[deploy/DEPLOY.md](deploy/DEPLOY.md)** for:

- systemd service setup
- GitHub webhook auto-deploy (push → pull → restart)
- cron fallback

Quick start on a Linux server:

```bash
sudo git clone https://github.com/karpus2807/orphen_device.git /opt/device-safety-manager
cd /opt/device-safety-manager
sudo bash deploy/install-server.sh /opt/device-safety-manager https://github.com/karpus2807/orphen_device.git 9030
sudo systemctl enable --now device-safety-webhook   # optional auto-deploy
```

Dashboard: `http://SERVER_IP:9030` (production default; local dev uses 8080)

## Features

- Admin-driven device registration and token push
- Background foreground service sync
- Remote commands (policy sync, alerts, device admin request)
- Device admin uninstall protection (consent-based)
- Policy management, email reset, SQLite persistence
