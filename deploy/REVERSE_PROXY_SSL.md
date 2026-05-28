# Subdomain + reverse proxy + SSL (HTTPS)

Use this when your Device Safety server runs on port **9030** (e.g. `ipserver.in:9030`) and you want a clean URL like **`https://devices.yourdomain.com`**.

## Overview

```
Phone / Browser  →  https://devices.example.com  (443)
                         ↓ Caddy or Nginx (SSL)
                    127.0.0.1:9030  (device-safety-backend)
```

Backend **hamesha 9030 par hi chalega** (localhost). Port **443 shift mat karo** — wahan pehle se jo websites hain unhi ke liye Caddy/Nginx **subdomain se route** karta hai.

---

## Step 1 — DNS (subdomain)

At your domain registrar (where `ipserver.in` is managed), add an **A record**:

| Type | Name | Value | TTL |
|------|------|--------|-----|
| A | `devices` | `YOUR_SERVER_PUBLIC_IP` | 300 |

Result: `devices.ipserver.in` → your VPS IP.

Optional for GitHub webhook:

| Type | Name | Value |
|------|------|--------|
| A | `hooks` | same IP |

Wait 5–15 minutes, then check:

```bash
dig +short devices.ipserver.in
```

---

## Step 2 — Firewall

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# After proxy works, you can remove public 9030:
# sudo ufw delete allow 9030/tcp
sudo ufw reload
```

Ports **80** and **443** must reach the server for free SSL (Let's Encrypt).

---

## Step 3 — Bind backend to localhost (recommended)

So nothing bypasses the proxy:

```bash
sudo nano /etc/systemd/system/device-safety-backend.service
```

Add or change:

```ini
Environment=DEVICE_SAFETY_BIND_HOST=127.0.0.1
Environment=DEVICE_SAFETY_PORT=9030
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart device-safety-backend
curl -s http://127.0.0.1:9030/health
```

---

## Option A — Caddy (easiest SSL, recommended)

Auto HTTPS with Let's Encrypt.

```bash
sudo apt update
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

Edit Caddyfile (copy from `deploy/caddy/Caddyfile.example`):

```bash
sudo nano /etc/caddy/Caddyfile
```

Example for **ipserver.in**:

```
devices.ipserver.in {
    encode gzip
    reverse_proxy 127.0.0.1:9030
}

hooks.ipserver.in {
    reverse_proxy 127.0.0.1:9001
}
```

```bash
sudo systemctl enable caddy
sudo systemctl reload caddy
sudo systemctl status caddy
```

Test: open `https://devices.ipserver.in` in a browser.

---

## Option B — Nginx + Certbot

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp /opt/device-safety-manager/deploy/nginx/device-safety.conf.example \
  /etc/nginx/sites-available/device-safety
sudo sed -i 's/devices.example.com/devices.ipserver.in/g' /etc/nginx/sites-available/device-safety
sudo ln -sf /etc/nginx/sites-available/device-safety /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d devices.ipserver.in
```

Follow certbot prompts (email, agree, redirect HTTP→HTTPS).

---

## Port 443 par pehle se sites hain — koi problem nahi

443 **sab sites ke liye ek hi port** hota hai. Nginx/Caddy **hostname** se decide karta hai:

| URL | Andar proxy kahan bhejta hai |
|-----|------------------------------|
| `https://www.ipserver.in` | pehle wala web server (jaise abhi) |
| `https://devices.ipserver.in` | `127.0.0.1:9030` (Device Safety) |
| `https://hooks.ipserver.in` | `127.0.0.1:9001` (webhook, optional) |

Purani websites **waise hi** chalengi; tum sirf **naya subdomain** add kar rahe ho.

Device Safety **9030 par bind** rahega — 443 par program **listen nahi** karega.

---

## Step 4 — Server config (admin UI)

1. Open **`https://devices.ipserver.in`** (subdomain se).
2. Login → **Server Config**.
3. Set:
   - **Host:** `devices.ipserver.in` (sirf domain, bina `https://`)
   - **Port:** **`9030`** (backend ka asli port — 443 mat likho)

4. HTTPS links ke liye systemd mein ye add karo (APK/OTA URLs `https://` banenge):

```bash
sudo systemctl edit device-safety-backend
```

```ini
[Service]
Environment=DEVICE_SAFETY_PUBLIC_SCHEME=https
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart device-safety-backend
```

Check **App Build & OTA** — URL aisa ho: `https://devices.ipserver.in/apk/dsm.apk` (bina `:9030`).

---

## Step 5 — Android apps

**Orphen APK Installer** default server is in prefs — open installer → set:

- Host: `devices.ipserver.in`
- Port installer prefs: host = subdomain; agar app `host:port` mangti hai to proxy ke baad bhi often `9030` internal rehta hai — public URL push se `https://devices...` milega

**Device Safety app** — enrollment / remote config must use the same HTTPS base URL.

---

## Step 6 — GitHub webhook (HTTPS)

Instead of `http://IP:9001/webhook`, use:

**Payload URL:** `https://hooks.ipserver.in/webhook`  
**Content type:** `application/json`  
**Secret:** same as `deploy/webhook.env`

Ensure `device-safety-webhook` listens on `127.0.0.1:9001` and Caddy proxies `hooks` subdomain.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| SSL certificate failed | DNS must point to this server; port 80 open |
| 502 Bad Gateway | `curl http://127.0.0.1:9030/health` — restart backend |
| Admin loads but phones fail | Update Server Config host + HTTPS URL |
| Webhook not firing | Use HTTPS URL; check `sudo journalctl -u device-safety-webhook -f` |

```bash
sudo journalctl -u device-safety-backend -f
sudo journalctl -u caddy -f
curl -vk https://devices.ipserver.in/health
```

---

## Example (your setup)

If VPS IP is the one behind **ipserver.in** and subdomain is **devices.ipserver.in**:

1. DNS A record `devices` → VPS IP  
2. Caddy reverse proxy → `127.0.0.1:9030`  
3. Admin: `https://devices.ipserver.in`  
4. Installer APK: `https://devices.ipserver.in/apk/oui.apk`  
5. Close public `9030` in firewall after testing  
