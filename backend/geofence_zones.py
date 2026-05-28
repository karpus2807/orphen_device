"""Per-device Wi-Fi and GPS geofence evaluation and alerts."""
from __future__ import annotations

import json
import math
import time
import uuid

GEOFENCE_CONFIG_KEY = "geofence_config_json"
GEOFENCE_STATE_KEY = "geofence_state_json"
NEARBY_WIFI_KEY = "nearby_wifi_json"


def default_geofence_config():
    return {
        "wifiNetworks": [],
        "locationZones": [],
        "alertOnLeave": True,
        "alertOnEnter": True,
    }


def _parse_json(raw, default):
    if not raw:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return default


def normalize_geofence_config(raw_config):
    config = default_geofence_config()
    if isinstance(raw_config, str):
        raw_config = _parse_json(raw_config, {})
    if not isinstance(raw_config, dict):
        return config

    legacy_ssid = str(raw_config.get("officeWifiSsid") or "").strip()
    wifi_networks = raw_config.get("wifiNetworks")
    if not isinstance(wifi_networks, list):
        wifi_networks = []
    if legacy_ssid and not wifi_networks:
        wifi_networks = [
            {
                "ssid": legacy_ssid,
                "alertOnConnect": bool(raw_config.get("alertOnEnter", True)),
                "alertOnDisconnect": bool(raw_config.get("alertOnLeave", True)),
            }
        ]

    normalized_wifi = []
    seen = set()
    for entry in wifi_networks:
        if not isinstance(entry, dict):
            continue
        ssid = str(entry.get("ssid") or "").strip()
        if not ssid or ssid.lower() in seen:
            continue
        seen.add(ssid.lower())
        normalized_wifi.append(
            {
                "ssid": ssid,
                "alertOnConnect": bool(entry.get("alertOnConnect", True)),
                "alertOnDisconnect": bool(entry.get("alertOnDisconnect", True)),
            }
        )

    location_zones = raw_config.get("locationZones")
    if not isinstance(location_zones, list):
        location_zones = []
    normalized_zones = []
    for entry in location_zones:
        if not isinstance(entry, dict):
            continue
        try:
            lat = float(entry.get("latitude"))
            lng = float(entry.get("longitude"))
        except (TypeError, ValueError):
            continue
        zone_id = str(entry.get("id") or "").strip() or f"zone_{uuid.uuid4().hex[:8]}"
        try:
            radius = float(entry.get("radiusMeters") or 200)
        except (TypeError, ValueError):
            radius = 200.0
        radius = max(25.0, min(radius, 50000.0))
        normalized_zones.append(
            {
                "id": zone_id,
                "label": str(entry.get("label") or "Zone").strip() or "Zone",
                "latitude": lat,
                "longitude": lng,
                "radiusMeters": radius,
                "alertOnEnter": bool(entry.get("alertOnEnter", True)),
                "alertOnExit": bool(entry.get("alertOnExit", True)),
            }
        )

    return {
        "wifiNetworks": normalized_wifi,
        "locationZones": normalized_zones,
        "alertOnLeave": bool(raw_config.get("alertOnLeave", True)),
        "alertOnEnter": bool(raw_config.get("alertOnEnter", True)),
    }


def default_geofence_state():
    return {"wifiInside": None, "locationInside": None, "locationZoneId": "", "matchedWifiSsid": ""}


def normalize_geofence_state(raw_state):
    state = default_geofence_state()
    if isinstance(raw_state, str):
        raw_state = _parse_json(raw_state, {})
    if not isinstance(raw_state, dict):
        return state
    if "wifiInside" in raw_state:
        value = raw_state.get("wifiInside")
        state["wifiInside"] = None if value is None else bool(value)
    if "locationInside" in raw_state:
        value = raw_state.get("locationInside")
        state["locationInside"] = None if value is None else bool(value)
    state["locationZoneId"] = str(raw_state.get("locationZoneId") or "")
    state["matchedWifiSsid"] = str(raw_state.get("matchedWifiSsid") or "")
    return state


def haversine_meters(lat1, lon1, lat2, lon2):
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def evaluate_wifi_match(config, wifi_ssid):
    ssid = str(wifi_ssid or "").strip()
    networks = config.get("wifiNetworks") or []
    if not networks:
        return False, ""
    if not ssid:
        return False, ""
    lowered = ssid.lower()
    for entry in networks:
        if str(entry.get("ssid") or "").strip().lower() == lowered:
            return True, entry.get("ssid") or ssid
    return False, ""


def evaluate_location_zone(config, latitude, longitude):
    zones = config.get("locationZones") or []
    if latitude is None or longitude is None or not zones:
        return False, ""
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        return False, ""
    for zone in zones:
        distance = haversine_meters(lat, lng, float(zone["latitude"]), float(zone["longitude"]))
        if distance <= float(zone.get("radiusMeters") or 200):
            return True, str(zone.get("id") or "")
    return False, ""


def merge_wifi_suggestions(device, config, nearby_raw):
    suggestions = []
    seen = set()

    def add(value):
        text = str(value or "").strip()
        if not text or text.lower() in seen or text == "<unknown ssid>":
            return
        seen.add(text.lower())
        suggestions.append(text)

    nearby = _parse_json(nearby_raw, [])
    if isinstance(nearby, list):
        for item in nearby:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                add(item.get("ssid"))

    add(device.get("lastWifiSsid"))
    for entry in config.get("wifiNetworks") or []:
        add(entry.get("ssid"))

    return suggestions


def process_geofence_update(
    device_id,
    device,
    body,
    config,
    previous_state,
    *,
    record_event_fn,
    notify_wifi_connect_fn,
    notify_wifi_disconnect_fn,
    notify_location_enter_fn,
    notify_location_exit_fn,
):
    """Update device geofence fields and fire email alerts on transitions."""
    config = normalize_geofence_config(config)
    state = normalize_geofence_state(previous_state)
    updates = {}

    wifi_ssid = str(body.get("wifiSsid", "")).strip()
    if wifi_ssid or "wifiSsid" in body:
        device["lastWifiSsid"] = wifi_ssid

    nearby = body.get("nearbyWifi")
    if nearby is not None:
        updates[NEARBY_WIFI_KEY] = json.dumps(nearby if isinstance(nearby, list) else [])

    wifi_inside, matched_ssid = evaluate_wifi_match(config, wifi_ssid)
    device["geofenceWifiOk"] = wifi_inside if config.get("wifiNetworks") else None
    prev_wifi = state.get("wifiInside")

    if config.get("wifiNetworks"):
        if prev_wifi is True and not wifi_inside:
            left_ssid = str(state.get("matchedWifiSsid") or wifi_ssid or "disconnected")
            record_event_fn(device_id, "geofence_wifi_left", f"Left Wi-Fi zone ({left_ssid})")
            entry = _wifi_entry_for_ssid(config, state.get("matchedWifiSsid") or "")
            if entry and entry.get("alertOnDisconnect"):
                notify_wifi_disconnect_fn(device_id, device, wifi_ssid, entry.get("ssid") or left_ssid)
        elif prev_wifi is False and wifi_inside:
            record_event_fn(device_id, "geofence_wifi_enter", f"Connected to {matched_ssid}")
            entry = _wifi_entry_for_ssid(config, matched_ssid)
            if entry and entry.get("alertOnConnect"):
                notify_wifi_connect_fn(device_id, device, matched_ssid)
        elif prev_wifi is None and wifi_inside:
            record_event_fn(device_id, "geofence_wifi_enter", f"Connected to {matched_ssid}")
            entry = _wifi_entry_for_ssid(config, matched_ssid)
            if entry and entry.get("alertOnConnect"):
                notify_wifi_connect_fn(device_id, device, matched_ssid)
        state["wifiInside"] = wifi_inside
        state["matchedWifiSsid"] = matched_ssid if wifi_inside else ""

    location_values = body.get("location") if isinstance(body.get("location"), dict) else None
    lat = device.get("lastLatitude")
    lng = device.get("lastLongitude")
    if location_values:
        try:
            lat = float(location_values.get("latitude"))
            lng = float(location_values.get("longitude"))
        except (TypeError, ValueError):
            pass

    loc_inside, zone_id = evaluate_location_zone(config, lat, lng)
    device["geofenceLocationOk"] = loc_inside if config.get("locationZones") else None
    prev_loc = state.get("locationInside")
    prev_zone = str(state.get("locationZoneId") or "")

    if config.get("locationZones") and lat is not None and lng is not None:
        if prev_loc is True and not loc_inside:
            zone = _zone_by_id(config, prev_zone)
            label = zone.get("label") if zone else "geofence zone"
            record_event_fn(device_id, "geofence_location_exit", f"Left {label}")
            if zone and zone.get("alertOnExit"):
                notify_location_exit_fn(device_id, device, zone, lat, lng)
        elif prev_loc is False and loc_inside:
            zone = _zone_by_id(config, zone_id)
            label = zone.get("label") if zone else "geofence zone"
            record_event_fn(device_id, "geofence_location_enter", f"Entered {label}")
            if zone and zone.get("alertOnEnter"):
                notify_location_enter_fn(device_id, device, zone, lat, lng)
        elif prev_loc is None and loc_inside:
            zone = _zone_by_id(config, zone_id)
            if zone and zone.get("alertOnEnter"):
                notify_location_enter_fn(device_id, device, zone, lat, lng)
        state["locationInside"] = loc_inside
        state["locationZoneId"] = zone_id if loc_inside else ""

    combined_ok = None
    if config.get("wifiNetworks") or config.get("locationZones"):
        checks = []
        if config.get("wifiNetworks"):
            checks.append(bool(wifi_inside))
        if config.get("locationZones") and lat is not None and lng is not None:
            checks.append(bool(loc_inside))
        if checks:
            combined_ok = all(checks) if len(checks) > 1 else checks[0]
    device["geofenceOk"] = combined_ok

    updates[GEOFENCE_STATE_KEY] = json.dumps(state)
    return updates


def _wifi_entry_for_ssid(config, ssid):
    target = str(ssid or "").strip().lower()
    for entry in config.get("wifiNetworks") or []:
        if str(entry.get("ssid") or "").strip().lower() == target:
            return entry
    return None


def _wifi_entry_for_any(config):
    networks = config.get("wifiNetworks") or []
    return networks[0] if networks else None


def _zone_by_id(config, zone_id):
    for zone in config.get("locationZones") or []:
        if str(zone.get("id") or "") == str(zone_id or ""):
            return zone
    return None
