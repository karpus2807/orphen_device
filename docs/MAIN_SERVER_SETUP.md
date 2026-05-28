# Main server — fresh setup + GitHub `main` auto-update

Jab bhi GitHub par **`main`** branch mein code push hoga, server purana program code hata kar naya pull karega aur backend **khud start** ho jayega.

## Pehle (ek baar)

1. GitHub par `feature/server-update-manager` ko **`main`** mein merge karo (ya `main` par wahi code ho).
2. Server par purana install ho to pehle hatao (optional):
   ```bash
   sudo systemctl stop device-safety-backend device-safety-webhook 2>/dev/null || true
   sudo systemctl disable device-safety-backend device-safety-webhook 2>/dev/null || true
   sudo rm -rf /opt/device-safety-manager
   ```

## Naya server — ek command

SSH se server par login karke:

```bash
curl -fsSL https://raw.githubusercontent.com/karpus2807/orphen_device/main/deploy/setup-all.sh | sudo bash -s -- \
  --branch main \
  --app-dir /opt/device-safety-manager \
  --port 9030
```

Agar `setup-all.sh` abhi sirf feature branch par hai (merge se pehle):

```bash
curl -fsSL https://raw.githubusercontent.com/karpus2807/orphen_device/feature/server-update-manager/deploy/setup-all.sh | sudo bash -s -- \
  --branch feature/server-update-manager \
  --app-dir /opt/device-safety-manager \
  --port 9030
```

Merge ke baad hamesha `--branch main` use karo.

Firewall:

```bash
sudo ufw allow 9030/tcp
sudo ufw allow 9001/tcp
```

## GitHub webhook (auto-deploy on `main` push)

Setup script webhook service **khud enable** karta hai. Sirf GitHub par webhook add karna hai:

1. Repo → **Settings → Webhooks → Add webhook**
2. **Payload URL:** `http://YOUR_SERVER_IP:9001/webhook`
3. **Content type:** `application/json`
4. **Secret:** server par dekho:
   ```bash
   sudo grep WEBHOOK_SECRET /opt/device-safety-manager/deploy/webhook.env
   ```
5. **Events:** Just the push event

Test: `main` par chhota commit push karo → 10–30 sec mein server update.

Deploy log:

```bash
sudo tail -f /var/log/device-safety-deploy.log
```

## Kya hota hai har push par

1. GitHub `push` event → port **9001** webhook
2. `deploy/deploy.sh` chalta hai:
   - `git fetch` + `git reset --hard origin/main` (purana **code** replace; `backend/data/` DB safe — gitignore)
   - systemd units refresh (agar service files badle)
   - `device-safety-backend` **restart** → program auto start
3. Webhook service bhi restart hoti hai agar enabled ho

Manual deploy (bina GitHub ke):

```bash
sudo -u "$(stat -c '%U' /opt/device-safety-manager)" \
  APP_DIR=/opt/device-safety-manager DEPLOY_BRANCH=main \
  bash /opt/device-safety-manager/deploy/deploy.sh
```

## URLs

| Service | URL |
|---------|-----|
| Dashboard | `http://SERVER:9030` |
| App Build & OTA | `http://SERVER:9030/app-release-center` |
| Webhook health | `http://SERVER:9001/health` |
| phpMyAdmin | `http://127.0.0.1:8081` (SSH tunnel) |

## Cron backup (webhook na ho to)

```cron
*/5 * * * * APP_DIR=/opt/device-safety-manager DEPLOY_BRANCH=main /opt/device-safety-manager/deploy/deploy.sh >> /var/log/device-safety-deploy.log 2>&1
```

## Android phones

Server code auto-update hota hai; **phone par APK** alag se Web UI / OTA se push karna padta hai (`/app-release-center`).
