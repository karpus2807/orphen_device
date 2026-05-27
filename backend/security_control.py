import hashlib
import secrets
import time

OTP_TTL_SECONDS = 900
ALLOWED_ACTIONS = {
    "unlock",
    "unhide",
    "hide",
    "lock",
    "enable_device_admin",
    "disable_device_admin",
    "allow_uninstall",
}


def hash_otp(code):
    return hashlib.sha256(str(code or "").strip().encode("utf-8")).hexdigest()


def generate_otp_code():
    return f"{secrets.randbelow(10000):04d}"


def get_device_otp(connection, request_id, device_id):
    request_id = int(request_id or 0)
    device_id = str(device_id or "").strip()
    row = connection.execute(
        "SELECT device_id, status, device_otp_code, expires_at, used_at "
        "FROM security_otp_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    if not row or str(row["device_id"]) != device_id:
        return ""
    if row["status"] != "approved" or row["used_at"]:
        return ""
    if int(row["expires_at"] or 0) < int(time.time()):
        return ""
    return str(row["device_otp_code"] or "").strip()


def clear_device_otp(connection, request_id):
    connection.execute(
        "UPDATE security_otp_requests SET device_otp_code = NULL WHERE id = ?",
        (int(request_id or 0),),
    )


def normalize_action(action):
    value = str(action or "").strip().lower()
    return value if value in ALLOWED_ACTIONS else ""


def create_otp_request(connection, device_id, action_type):
    action_type = normalize_action(action_type)
    device_id = str(device_id or "").strip()
    if not device_id or not action_type:
        return None, "invalid_request"
    now = int(time.time())
    connection.execute(
        "UPDATE security_otp_requests SET status = 'superseded' "
        "WHERE device_id = ? AND status = 'pending'",
        (device_id,),
    )
    cursor = connection.execute(
        "INSERT INTO security_otp_requests (device_id, action_type, status, created_at) "
        "VALUES (?, ?, 'pending', ?)",
        (device_id, action_type, now),
    )
    request_id = cursor.lastrowid
    return {
        "id": request_id,
        "deviceId": device_id,
        "actionType": action_type,
        "status": "pending",
        "createdAt": now,
    }, None


def get_request_by_id(connection, request_id):
    row = connection.execute(
        "SELECT id, device_id, action_type, status, created_at, approved_at, expires_at, used_at "
        "FROM security_otp_requests WHERE id = ?",
        (int(request_id),),
    ).fetchone()
    if not row:
        return None
    return _row_to_request(row)


def get_latest_pending_request(connection, device_id):
    row = connection.execute(
        "SELECT id, device_id, action_type, status, created_at, approved_at, expires_at, used_at "
        "FROM security_otp_requests WHERE device_id = ? AND status = 'pending' "
        "ORDER BY id DESC LIMIT 1",
        (device_id,),
    ).fetchone()
    if not row:
        return None
    return _row_to_request(row)


def list_requests(connection, device_id="", limit=50):
    device_id = str(device_id or "").strip()
    if device_id:
        rows = connection.execute(
            "SELECT id, device_id, action_type, status, created_at, approved_at, expires_at, used_at "
            "FROM security_otp_requests WHERE device_id = ? ORDER BY id DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT id, device_id, action_type, status, created_at, approved_at, expires_at, used_at "
            "FROM security_otp_requests ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_request(row) for row in rows]


def approve_request(connection, request_id):
    request_id = int(request_id or 0)
    row = connection.execute(
        "SELECT id, device_id, action_type, status FROM security_otp_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    if not row or row["status"] != "pending":
        return None, "request_not_pending"
    otp_code = generate_otp_code()
    now = int(time.time())
    connection.execute(
        "UPDATE security_otp_requests SET status = 'approved', otp_hash = ?, device_otp_code = ?, "
        "approved_at = ?, expires_at = ? WHERE id = ?",
        (hash_otp(otp_code), otp_code, now, now + OTP_TTL_SECONDS, request_id),
    )
    return {
        "id": request_id,
        "deviceId": row["device_id"],
        "actionType": row["action_type"],
        "status": "approved",
        "otpCode": otp_code,
        "expiresAt": now + OTP_TTL_SECONDS,
    }, None


def reject_request(connection, request_id):
    request_id = int(request_id or 0)
    row = connection.execute(
        "SELECT id, status FROM security_otp_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    if not row or row["status"] != "pending":
        return False
    connection.execute(
        "UPDATE security_otp_requests SET status = 'rejected', device_otp_code = NULL WHERE id = ?",
        (request_id,),
    )
    return True


def verify_request_otp(connection, device_id, request_id, otp_code):
    device_id = str(device_id or "").strip()
    request_id = int(request_id or 0)
    otp_code = str(otp_code or "").strip()
    if len(otp_code) != 4 or not otp_code.isdigit():
        return None, "invalid_otp_format"
    row = connection.execute(
        "SELECT id, device_id, action_type, status, otp_hash, expires_at, used_at "
        "FROM security_otp_requests WHERE id = ? AND device_id = ?",
        (request_id, device_id),
    ).fetchone()
    if not row:
        return None, "request_not_found"
    if row["status"] != "approved":
        return None, "request_not_approved"
    if row["used_at"]:
        return None, "otp_already_used"
    if int(row["expires_at"] or 0) < int(time.time()):
        return None, "otp_expired"
    if not secrets.compare_digest(str(row["otp_hash"]), hash_otp(otp_code)):
        return None, "otp_invalid"
    now = int(time.time())
    connection.execute(
        "UPDATE security_otp_requests SET status = 'used', used_at = ?, device_otp_code = NULL WHERE id = ?",
        (now, request_id),
    )
    return {
        "id": request_id,
        "deviceId": device_id,
        "actionType": row["action_type"],
        "status": "used",
        "verifiedAt": now,
    }, None


def _row_to_request(row):
    return {
        "id": row["id"],
        "deviceId": row["device_id"],
        "actionType": row["action_type"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "approvedAt": row["approved_at"],
        "expiresAt": row["expires_at"],
        "usedAt": row["used_at"],
    }
