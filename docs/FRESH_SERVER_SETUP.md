# Fresh server setup (feature branch)

Branch: `feature/server-update-manager` (do **not** merge to `main` until reviewed).

## One command (Ubuntu/Debian)

```bash
sudo bash deploy/setup-all.sh \
  --branch feature/server-update-manager \
  --app-dir /opt/device-safety-manager \
  --port 9030 \
  --with-android-sdk
```

Installs: git, Python, Docker, MariaDB + **phpMyAdmin** (localhost), clones repo, systemd backend, unlimited data mode.

| Service | URL |
|---------|-----|
| Dashboard | `http://SERVER:9030` |
| App Build & OTA | `http://SERVER:9030/app-release-center` |
| phpMyAdmin | `http://127.0.0.1:8081` (SSH tunnel) |

phpMyAdmin credentials: see `/opt/device-safety-manager/deploy/.env.docker`

**Note:** App runtime DB is still **SQLite** (`backend/data/device_safety.db`). MariaDB is for admin/SQL tools; full MySQL backend is planned later.

## Workflow (your process)

1. Edit code locally → push to `feature/server-update-manager` on GitHub  
2. On server: `git pull` or webhook auto-deploy  
3. Open **App Build & OTA** → Build APK → Register → **Push to all devices**  
4. Phones with Device Safety installed receive `push_app_update` on next sync  

## Update Manager APK (auto-install helper)

Build:

```bash
bash scripts/build-update-manager-apk.sh
```

Install **once** on each phone (before or after DSM). Set server host/port in the app. It polls `/api/update-manager/catalog` every 5 minutes and installs newer APKs.

Upload to server:

```bash
scp apk/orphen-update-manager.apk SERVER:/opt/device-safety-manager/apk/
```

## Unlimited storage

`DEVICE_SAFETY_UNLIMITED=1` in `deploy/server.env` removes the 2500-row history cap.

## SSH tunnel for phpMyAdmin

```bash
ssh -L 8081:127.0.0.1:8081 user@SERVER
```

Then open http://127.0.0.1:8081
