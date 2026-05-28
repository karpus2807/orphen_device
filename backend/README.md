# Device Safety Backend

Small dependency-free Python backend for learning Android device registration.

## Run

```bash
python3 backend/server.py
```

## Endpoints

- `GET /health` - backend health check
- `GET /hi` - simple hello endpoint
- `POST /devices/register` - register or update a device
- `GET /devices` - list registered devices

Example registration:

```bash
curl -X POST http://127.0.0.1:8080/devices/register \
  -H 'Content-Type: application/json' \
  -d '{"deviceId":"demo","manufacturer":"OnePlus","model":"CPH2491","androidVersion":"16","apiLevel":"36"}'
```
