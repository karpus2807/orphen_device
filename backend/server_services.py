"""Device provisioning service helpers extracted from server.py."""


def build_devices_provision_payload(
    device_id,
    consume_pending_device_token,
    redeliver_sealed_device_token,
    get_device_by_id,
):
    """Build payload/status tuple for GET /devices/provision responses."""
    if not device_id:
        return {"error": "deviceId_required"}, 400
    pending_token = consume_pending_device_token(device_id)
    if not pending_token:
        pending_token = redeliver_sealed_device_token(device_id)
    if pending_token:
        return {"ok": True, "deviceToken": pending_token, "registered": True}, 200
    device = get_device_by_id(device_id)
    is_registered = bool(device and device.get("registered"))
    return {
        "ok": True,
        "registered": is_registered,
        "pending": not is_registered,
    }, 200
