import base64
import collections
import struct
import threading
import time
import uuid
from pathlib import Path

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
MAX_CHUNKS = 400
RECORDINGS_DIR = Path(__file__).resolve().parent / "data" / "audio_recordings"

_lock = threading.Lock()
_sessions = {}
_chunks = {}
_recordings = {}
_active_recordings = {}


def _empty_session():
    return {
        "active": False,
        "requested": False,
        "recording": False,
        "startedAt": None,
        "lastChunkAt": None,
        "lastSeq": 0,
        "sampleRate": SAMPLE_RATE,
        "channels": CHANNELS,
        "format": "pcm16le",
        "chunkCount": 0,
    }


def get_session(device_id):
    with _lock:
        return dict(_sessions.get(device_id, _empty_session()))


def request_stream(device_id, enabled):
    with _lock:
        session = _sessions.setdefault(device_id, _empty_session())
        session["requested"] = bool(enabled)
        if not enabled:
            session["active"] = False
        return dict(session)


def stop_stream(device_id):
    with _lock:
        session = _sessions.setdefault(device_id, _empty_session())
        session["requested"] = False
        session["active"] = False
        session["recording"] = False
        if device_id in _active_recordings:
            _finalize_recording_locked(device_id)
        return dict(session)


def append_chunk(device_id, seq, pcm_bytes, sample_rate=SAMPLE_RATE, channels=CHANNELS, fmt="pcm16le"):
    if not device_id or not pcm_bytes:
        return None
    now = int(time.time())
    with _lock:
        session = _sessions.setdefault(device_id, _empty_session())
        session["active"] = True
        session["requested"] = True
        session["startedAt"] = session["startedAt"] or now
        session["lastChunkAt"] = now
        session["lastSeq"] = int(seq or 0)
        session["sampleRate"] = int(sample_rate or SAMPLE_RATE)
        session["channels"] = int(channels or CHANNELS)
        session["format"] = str(fmt or "pcm16le")
        buffer = _chunks.setdefault(device_id, collections.deque(maxlen=MAX_CHUNKS))
        entry = {
            "seq": int(seq or 0),
            "timestamp": now,
            "format": session["format"],
            "sampleRate": session["sampleRate"],
            "channels": session["channels"],
            "data": base64.b64encode(pcm_bytes).decode("ascii"),
        }
        buffer.append(entry)
        session["chunkCount"] = len(buffer)
        if device_id in _active_recordings:
            _active_recordings[device_id]["handle"].write(pcm_bytes)
            _active_recordings[device_id]["bytesWritten"] += len(pcm_bytes)
        return entry


def get_chunks_since(device_id, since_seq=0):
    with _lock:
        buffer = list(_chunks.get(device_id, collections.deque()))
        session = dict(_sessions.get(device_id, _empty_session()))
    since_seq = int(since_seq or 0)
    items = [item for item in buffer if int(item.get("seq") or 0) > since_seq]
    return session, items


def build_wav_bytes(pcm_bytes, sample_rate=SAMPLE_RATE, channels=CHANNELS):
    data_size = len(pcm_bytes)
    byte_rate = sample_rate * channels * SAMPLE_WIDTH
    block_align = channels * SAMPLE_WIDTH
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        SAMPLE_WIDTH * 8,
        b"data",
        data_size,
    )
    return header + pcm_bytes


def start_server_recording(device_id):
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    recording_id = uuid.uuid4().hex[:12]
    path = RECORDINGS_DIR / f"{device_id}_{recording_id}.pcm"
    with _lock:
        if device_id in _active_recordings:
            _finalize_recording_locked(device_id)
        handle = open(path, "wb")
        meta = {
            "id": recording_id,
            "deviceId": device_id,
            "startedAt": int(time.time()),
            "path": str(path),
            "handle": handle,
            "bytesWritten": 0,
        }
        _active_recordings[device_id] = meta
        session = _sessions.setdefault(device_id, _empty_session())
        session["recording"] = True
        return {
            "id": recording_id,
            "startedAt": meta["startedAt"],
        }


def _finalize_recording_locked(device_id):
    meta = _active_recordings.pop(device_id, None)
    if not meta:
        return None
    handle = meta.get("handle")
    if handle:
        handle.close()
    pcm_path = Path(meta["path"])
    if not pcm_path.exists():
        return None
    pcm_bytes = pcm_path.read_bytes()
    wav_path = pcm_path.with_suffix(".wav")
    wav_path.write_bytes(build_wav_bytes(pcm_bytes))
    try:
        pcm_path.unlink()
    except OSError:
        pass
    finished = {
        "id": meta["id"],
        "deviceId": device_id,
        "startedAt": meta["startedAt"],
        "finishedAt": int(time.time()),
        "bytes": len(pcm_bytes),
        "durationSeconds": round(len(pcm_bytes) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH), 2),
        "format": "wav",
        "path": str(wav_path),
    }
    _recordings.setdefault(device_id, []).insert(0, finished)
    session = _sessions.setdefault(device_id, _empty_session())
    session["recording"] = False
    return finished


def stop_server_recording(device_id):
    with _lock:
        return _finalize_recording_locked(device_id)


def list_recordings(device_id):
    with _lock:
        return list(_recordings.get(device_id, []))


def get_recording_file(device_id, recording_id):
    for item in list_recordings(device_id):
        if item.get("id") == recording_id:
            path = Path(item.get("path", ""))
            if path.exists():
                return path
    return None


def build_live_wav_snapshot(device_id, max_chunks=120):
    with _lock:
        buffer = list(_chunks.get(device_id, collections.deque()))
    if not buffer:
        return b""
    selected = buffer[-max_chunks:]
    pcm = b"".join(base64.b64decode(item["data"]) for item in selected)
    return build_wav_bytes(pcm)
