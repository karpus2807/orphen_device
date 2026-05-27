# Server deployment (systemd + auto-update)

Default production port: **9030** (local dev may still use 8080).

## 1. Push code to GitHub

Repo: https://github.com/karpus2807/orphen_device

```bash
git add -A
git commit -m "Your message"
git push origin main
```

## 2. One-time setup on the remote Linux server

```bash
# Port 9030 (default) — use 3rd argument to change
sudo git clone https://github.com/karpus2807/orphen_device.git /opt/device-safety-manager
cd /opt/device-safety-manager
sudo bash deploy/install-server.sh /opt/device-safety-manager https://github.com/karpus2807/orphen_device.git 9030
```

Open firewall if needed:

```bash
sudo ufw allow 9030/tcp    # dashboard + API
sudo ufw allow 9001/tcp    # GitHub webhook (optional)
```

Dashboard: `http://SERVER_IP:9030`  
Default login: `admin` / `admin123` (change after first login)

## 3. Change port on an already installed server

Edit the systemd unit:

```bash
sudo nano /etc/systemd/system/device-safety-backend.service
```

Change this line:

```ini
Environment=DEVICE_SAFETY_PORT=9030
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart device-safety-backend
sudo ufw allow 9030/tcp
```

Or set in `deploy/server.env` and ensure the service uses it (default install sets port in systemd).

## 4. Run backend as a service (manual commands)

```bash
sudo systemctl status device-safety-backend
sudo systemctl restart device-safety-backend
sudo journalctl -u device-safety-backend -f
```

## 5. Auto-deploy when GitHub repo changes

### Option A — GitHub webhook (recommended, instant)

1. Start webhook service on server:

```bash
sudo systemctl enable --now device-safety-webhook.service
sudo cat /opt/device-safety-manager/deploy/webhook.env   # copy WEBHOOK_SECRET
```

2. GitHub repo → **Settings → Webhooks → Add webhook**
   - Payload URL: `http://YOUR_SERVER_IP:9001/webhook`
   - Content type: `application/json`
   - Secret: same as `WEBHOOK_SECRET` in `deploy/webhook.env`
   - Events: **Just the push event**

3. Push to `main` → server runs `deploy/deploy.sh` → `git pull` + `systemctl restart`

Manual deploy anytime:

```bash
sudo APP_DIR=/opt/device-safety-manager bash /opt/device-safety-manager/deploy/deploy.sh
```

### Option B — Cron (simple, every 5 minutes)

```bash
crontab -e
```

Add:

```cron
*/5 * * * * APP_DIR=/opt/device-safety-manager /opt/device-safety-manager/deploy/deploy.sh >> /var/log/device-safety-deploy.log 2>&1
```

## 6. Environment variables

| Variable | Default (server) | Purpose |
|----------|------------------|---------|
| `DEVICE_SAFETY_BIND_HOST` | `0.0.0.0` | Listen address |
| `DEVICE_SAFETY_PORT` | `9030` | HTTP port |

Edit `/etc/systemd/system/device-safety-backend.service` and run `sudo systemctl daemon-reload && sudo systemctl restart device-safety-backend`.

## 7. Notes

- Runtime data (`backend/data/*.db`, `*.json`) stays on the server and is **not** in git.
- Android app remote URL must point to `http://SERVER_IP:9030`.
- For HTTPS, put **nginx/caddy** in front and reverse-proxy to port 9030.
