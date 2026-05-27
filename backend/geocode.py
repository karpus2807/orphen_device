import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

GEOCODE_CACHE = {}


def _cache_key(latitude, longitude):
    return f"{round(float(latitude), 4)},{round(float(longitude), 4)}"


def _empty_address():
    return {
        "displayName": "",
        "road": "",
        "neighbourhood": "",
        "city": "",
        "district": "",
        "state": "",
        "postcode": "",
        "country": "",
        "source": "",
    }


def _normalize_address(**fields):
    result = _empty_address()
    for key, value in fields.items():
        if key in result:
            result[key] = str(value or "").strip()
    parts = [
        result.get("road"),
        result.get("neighbourhood"),
        result.get("city"),
        result.get("district"),
        result.get("state"),
        result.get("postcode"),
        result.get("country"),
    ]
    if not result.get("displayName"):
        result["displayName"] = ", ".join(part for part in parts if part)
    return result


def _geocode_nominatim(latitude, longitude):
    query = urlencode(
        {
            "lat": latitude,
            "lon": longitude,
            "format": "json",
            "addressdetails": 1,
            "zoom": 18,
        }
    )
    url = f"https://nominatim.openstreetmap.org/reverse?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DeviceSafetyManager/1.0 (learning-mdm; admin-dashboard)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        return None
    address = data.get("address") if isinstance(data.get("address"), dict) else {}
    result = _normalize_address(
        displayName=str(data.get("display_name") or "").strip(),
        road=str(address.get("road") or address.get("pedestrian") or address.get("footway") or "").strip(),
        neighbourhood=str(
            address.get("neighbourhood")
            or address.get("suburb")
            or address.get("quarter")
            or address.get("hamlet")
            or ""
        ).strip(),
        city=str(
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("county")
            or ""
        ).strip(),
        district=str(address.get("state_district") or address.get("district") or "").strip(),
        state=str(address.get("state") or "").strip(),
        postcode=str(address.get("postcode") or "").strip(),
        country=str(address.get("country") or "").strip(),
        source="nominatim",
    )
    return result if result.get("displayName") else None


def _geocode_bigdatacloud(latitude, longitude):
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "localityLanguage": "en",
        }
    )
    url = f"https://api.bigdatacloud.net/data/reverse-geocode-client?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DeviceSafetyManager/1.0 (learning-mdm; admin-dashboard)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        return None

    district = ""
    neighbourhood = ""
    admin_levels = (data.get("localityInfo") or {}).get("administrative") or []
    for entry in admin_levels:
        name = str(entry.get("name") or "").strip()
        description = str(entry.get("description") or "").lower()
        if not district and "district" in description:
            district = name
        if not neighbourhood and entry.get("adminLevel") in {6, 7, 8} and name != data.get("city"):
            neighbourhood = name

    result = _normalize_address(
        displayName=", ".join(
            part
            for part in [
                data.get("locality"),
                data.get("city"),
                data.get("principalSubdivision"),
                data.get("countryName"),
            ]
            if part
        ),
        city=str(data.get("city") or data.get("locality") or "").strip(),
        district=district or str(data.get("principalSubdivision") or "").strip(),
        neighbourhood=neighbourhood or str(data.get("locality") or "").strip(),
        state=str(data.get("principalSubdivision") or "").strip(),
        postcode=str(data.get("postcode") or "").strip(),
        country=str(data.get("countryName") or "").strip(),
        source="bigdatacloud",
    )
    return result if result.get("displayName") else None


def reverse_geocode_location(latitude, longitude):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None

    cache_key = _cache_key(latitude, longitude)
    if cache_key in GEOCODE_CACHE:
        cached = GEOCODE_CACHE[cache_key]
        return dict(cached) if cached else None

    result = _geocode_nominatim(latitude, longitude)
    if not result:
        time.sleep(0.15)
        result = _geocode_bigdatacloud(latitude, longitude)

    GEOCODE_CACHE[cache_key] = result or None
    return dict(result) if result else None


def format_location_address_summary(address):
    if not address:
        return "Address unavailable"
    if address.get("displayName"):
        return address["displayName"]
    parts = [
        address.get("road"),
        address.get("neighbourhood"),
        address.get("city"),
        address.get("state"),
        address.get("postcode"),
        address.get("country"),
    ]
    cleaned = [str(part).strip() for part in parts if part]
    return ", ".join(cleaned) if cleaned else "Address unavailable"


def enrich_location_items_with_addresses(items, max_lookups=40, cache_only=False):
    enriched = []
    lookups = 0
    for item in items:
        row = dict(item)
        cache_key = _cache_key(row["latitude"], row["longitude"])
        if cache_key in GEOCODE_CACHE:
            address = GEOCODE_CACHE.get(cache_key)
        elif cache_only or lookups >= max_lookups:
            address = None
        else:
            lookups += 1
            address = reverse_geocode_location(row["latitude"], row["longitude"])
        row["address"] = address
        row["addressSummary"] = format_location_address_summary(address)
        enriched.append(row)
    return enriched
