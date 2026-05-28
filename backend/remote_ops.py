import base64
import collections
import hashlib
import threading
import time
import uuid
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_THUMB_BYTES = 120000
MAX_THUMBS_PER_LIST = 48
MAX_SHELL_HISTORY = 300
MAX_JOBS = 50
JOB_TIMEOUT_SECONDS = 120

DOWNLOADS_DIR = Path(__file__).resolve().parent / "data" / "remote_downloads"
UPLOADS_DIR = Path(__file__).resolve().parent / "data" / "remote_uploads"

_lock = threading.Lock()
_sessions = {}
_jobs = {}
_job_results = {}
_listings = {}
_downloads = {}
_uploads = {}
_shell_history = {}
_clipboard = {}
_thumbnails = {}


def _empty_session():
    return {
        "active": False,
        "requested": False,
        "lastPollAt": None,
        "lastJobAt": None,
    }


def get_session(device_id):
    with _lock:
        return dict(_sessions.get(device_id, _empty_session()))


def request_session(device_id, enabled):
    with _lock:
        session = _sessions.setdefault(device_id, _empty_session())
        session["requested"] = bool(enabled)
        if not enabled:
            session["active"] = False
        return dict(session)


def stop_session(device_id):
    return request_session(device_id, False)


def _normalize_path(path):
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        return "/storage/emulated/0"
    if raw == "/":
        return "/storage/emulated/0"
    while "//" in raw:
        raw = raw.replace("//", "/")
    if raw.endswith("/") and raw != "/":
        raw = raw.rstrip("/")
    return raw


def _listing_key(device_id, path):
    return f"{device_id}:{_normalize_path(path)}"


def enqueue_job(device_id, job_type, payload=None):
    device_id = str(device_id or "").strip()
    job_type = str(job_type or "").strip()
    if not device_id or not job_type:
        return None
    job_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    job = {
        "id": job_id,
        "type": job_type,
        "payload": payload or {},
        "status": "pending",
        "createdAt": now,
    }
    with _lock:
        queue = _jobs.setdefault(device_id, collections.deque(maxlen=MAX_JOBS))
        queue.append(job)
        session = _sessions.setdefault(device_id, _empty_session())
        session["requested"] = True
    return job_id


def fetch_pending_jobs(device_id, limit=8):
    device_id = str(device_id or "").strip()
    now = int(time.time())
    with _lock:
        queue = _jobs.get(device_id, collections.deque())
        pending = [dict(job) for job in queue if job.get("status") == "pending"][:limit]
        for job in queue:
            if job.get("status") == "pending" and job["id"] in {item["id"] for item in pending}:
                job["status"] = "processing"
        session = _sessions.setdefault(device_id, _empty_session())
        if pending:
            session["active"] = True
            session["lastPollAt"] = now
        return pending


def complete_job(device_id, job_id, success, result=None, error=""):
    device_id = str(device_id or "").strip()
    job_id = str(job_id or "").strip()
    now = int(time.time())
    with _lock:
        queue = _jobs.get(device_id, collections.deque())
        matched = None
        for job in queue:
            if job.get("id") == job_id:
                matched = job
                job["status"] = "done" if success else "failed"
                job["completedAt"] = now
                break
        if not matched:
            return False
        payload = {
            "ok": bool(success),
            "result": result or {},
            "error": str(error or ""),
            "completedAt": now,
        }
        _job_results[job_id] = payload
        session = _sessions.setdefault(device_id, _empty_session())
        session["lastJobAt"] = now
    if success and matched:
        _store_job_result(device_id, matched, result or {})
        if matched.get("type") == "file_action":
            invalidate_listings(device_id)
            if str((matched.get("payload") or {}).get("action") or "").lower() == "move":
                clear_clipboard(device_id)
    elif matched and matched.get("type") == "list_dir":
        path = _normalize_path((matched.get("payload") or {}).get("path"))
        _listings[_listing_key(device_id, path)] = {
            "path": path,
            "entries": [],
            "updatedAt": int(time.time()),
            "error": str(error or "List directory failed"),
        }
    return True


def _store_job_result(device_id, job, result):
    job_type = job.get("type")
    if job_type == "list_dir":
        path = _normalize_path((job.get("payload") or {}).get("path"))
        entries = result.get("entries") or []
        for entry in entries:
            thumb = entry.get("thumbnail")
            if thumb and entry.get("path"):
                store_thumbnail(device_id, entry.get("path"), thumb, entry.get("thumbnailMime") or "image/jpeg")
                entry.pop("thumbnail", None)
        _listings[_listing_key(device_id, path)] = {
            "path": path,
            "entries": entries,
            "updatedAt": int(time.time()),
            "error": result.get("error") or "",
        }
        return
    if job_type == "read_file":
        path = str((job.get("payload") or {}).get("path") or "")
        data_b64 = str(result.get("data") or "")
        if not data_b64:
            _downloads[job["id"]] = {
                "ready": False,
                "error": result.get("error") or "Empty file payload",
                "path": path,
            }
            return
        try:
            raw = base64.b64decode(data_b64)
        except Exception as exc:
            _downloads[job["id"]] = {"ready": False, "error": str(exc), "path": path}
            return
        if len(raw) > MAX_FILE_BYTES:
            _downloads[job["id"]] = {
                "ready": False,
                "error": f"File exceeds {MAX_FILE_BYTES} byte limit",
                "path": path,
            }
            return
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(raw).hexdigest()[:16]
        filename = Path(path).name or "download.bin"
        safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename) or "download.bin"
        file_path = DOWNLOADS_DIR / f"{device_id}_{digest}_{safe_name}"
        file_path.write_bytes(raw)
        _downloads[job["id"]] = {
            "ready": True,
            "path": path,
            "filePath": str(file_path),
            "size": len(raw),
            "mimeType": result.get("mimeType") or "application/octet-stream",
        }
        return
    if job_type == "write_file":
        return
    if job_type == "file_action":
        return
    if job_type == "shell_exec":
        entry = {
            "id": job["id"],
            "command": str((job.get("payload") or {}).get("command") or ""),
            "stdout": str(result.get("stdout") or ""),
            "stderr": str(result.get("stderr") or ""),
            "cwd": str(result.get("cwd") or ""),
            "exitCode": result.get("exitCode"),
            "finishedAt": int(time.time()),
            "ok": bool(result.get("ok", True)),
        }
        history = _shell_history.setdefault(device_id, collections.deque(maxlen=MAX_SHELL_HISTORY))
        history.append(entry)


def get_listing(device_id, path):
    key = _listing_key(device_id, path)
    with _lock:
        listing = _listings.get(key)
        return dict(listing) if listing else None


def get_job_result(job_id):
    with _lock:
        payload = _job_results.get(str(job_id or "").strip())
        return dict(payload) if payload else None


def get_download(job_id):
    with _lock:
        payload = _downloads.get(str(job_id or "").strip())
        return dict(payload) if payload else None


def get_download_file(job_id):
    meta = get_download(job_id)
    if not meta or not meta.get("ready"):
        return None
    path = Path(meta.get("filePath") or "")
    if path.exists():
        return path
    return None


def stage_upload(device_id, dest_path, file_bytes, filename=""):
    device_id = str(device_id or "").strip()
    dest_path = _normalize_path(dest_path)
    if not device_id or not file_bytes:
        return None, "invalid_upload"
    if len(file_bytes) > MAX_FILE_BYTES:
        return None, "file_too_large"
    upload_id = uuid.uuid4().hex[:12]
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOADS_DIR / f"{device_id}_{upload_id}.bin"
    file_path.write_bytes(file_bytes)
    with _lock:
        _uploads[upload_id] = {
            "id": upload_id,
            "deviceId": device_id,
            "destPath": dest_path,
            "filename": str(filename or Path(dest_path).name or "upload.bin"),
            "size": len(file_bytes),
            "path": str(file_path),
            "createdAt": int(time.time()),
            "consumed": False,
        }
    return upload_id, None


def consume_upload(upload_id):
    upload_id = str(upload_id or "").strip()
    with _lock:
        meta = _uploads.get(upload_id)
        if not meta or meta.get("consumed"):
            return None
        meta = dict(meta)
        meta["consumed"] = True
        _uploads[upload_id] = meta
    path = Path(meta.get("path") or "")
    if not path.exists():
        return None
    data = path.read_bytes()
    try:
        path.unlink()
    except OSError:
        pass
    return {
        "uploadId": upload_id,
        "destPath": meta.get("destPath"),
        "filename": meta.get("filename"),
        "size": len(data),
        "data": base64.b64encode(data).decode("ascii"),
    }


def queue_list_dir(device_id, path, with_thumbnails=True):
    path = _normalize_path(path)
    job_id = enqueue_job(device_id, "list_dir", {"path": path, "withThumbnails": bool(with_thumbnails)})
    return job_id, path


def queue_read_file(device_id, path):
    path = _normalize_path(path)
    job_id = enqueue_job(device_id, "read_file", {"path": path})
    return job_id, path


def queue_write_file(device_id, dest_path, upload_id):
    dest_path = _normalize_path(dest_path)
    job_id = enqueue_job(device_id, "write_file", {"path": dest_path, "uploadId": upload_id})
    return job_id, dest_path


def queue_shell_exec(device_id, command):
    command = str(command or "").strip()
    if not command:
        return None
    job_id = enqueue_job(device_id, "shell_exec", {"command": command})
    return job_id


def get_shell_history(device_id, since_id=""):
    device_id = str(device_id or "").strip()
    since_id = str(since_id or "").strip()
    with _lock:
        items = list(_shell_history.get(device_id, collections.deque()))
    if since_id:
        filtered = []
        seen = False
        for item in items:
            if seen:
                filtered.append(dict(item))
            elif item.get("id") == since_id:
                seen = True
        return filtered
    # First poll should still return recent command output so the UI can bootstrap.
    return [dict(item) for item in items]


def set_clipboard(device_id, mode, paths):
    device_id = str(device_id or "").strip()
    mode = str(mode or "copy").strip().lower()
    cleaned = [_normalize_path(path) for path in (paths or []) if str(path or "").strip()]
    if not device_id or not cleaned:
        return None
    with _lock:
        _clipboard[device_id] = {
            "mode": "cut" if mode == "cut" else "copy",
            "paths": cleaned,
            "updatedAt": int(time.time()),
        }
    return dict(_clipboard[device_id])


def get_clipboard(device_id):
    device_id = str(device_id or "").strip()
    with _lock:
        payload = _clipboard.get(device_id)
        return dict(payload) if payload else {"mode": "", "paths": [], "updatedAt": 0}


def clear_clipboard(device_id):
    device_id = str(device_id or "").strip()
    with _lock:
        _clipboard.pop(device_id, None)


def invalidate_listings(device_id):
    device_id = str(device_id or "").strip()
    prefix = f"{device_id}:"
    with _lock:
        for key in [key for key in _listings if key.startswith(prefix)]:
            _listings.pop(key, None)
        for key in [key for key in _thumbnails if key.startswith(prefix)]:
            _thumbnails.pop(key, None)


def store_thumbnail(device_id, path, data_b64, mime_type="image/jpeg"):
    if not device_id or not path or not data_b64:
        return
    key = f"{device_id}:{_normalize_path(path)}"
    with _lock:
        _thumbnails[key] = {
            "path": _normalize_path(path),
            "data": str(data_b64),
            "mimeType": mime_type or "image/jpeg",
            "updatedAt": int(time.time()),
        }


def get_thumbnail(device_id, path):
    key = f"{device_id}:{_normalize_path(path)}"
    with _lock:
        payload = _thumbnails.get(key)
        return dict(payload) if payload else None


def queue_file_action(device_id, action, paths, dest_path=""):
    action = str(action or "").strip().lower()
    cleaned = [_normalize_path(path) for path in (paths or []) if str(path or "").strip()]
    if not cleaned:
        return None
    dest = _normalize_path(dest_path) if dest_path else ""
    return enqueue_job(
        device_id,
        "file_action",
        {"action": action, "paths": cleaned, "destPath": dest},
    )
