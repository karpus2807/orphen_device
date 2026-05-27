#!/usr/bin/env python3
"""Resolve GPS coordinates to a postal address (CLI helper)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from geocode import format_location_address_summary, reverse_geocode_location  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/reverse-geocode.py <latitude> <longitude>")
        print("Example: python3 scripts/reverse-geocode.py 26.906396 76.350842")
        raise SystemExit(1)

    latitude = float(sys.argv[1])
    longitude = float(sys.argv[2])
    address = reverse_geocode_location(latitude, longitude)
    if not address:
        print(json.dumps({"ok": False, "error": "Could not resolve address"}, indent=2))
        raise SystemExit(2)

    payload = {
        "ok": True,
        "latitude": latitude,
        "longitude": longitude,
        "summary": format_location_address_summary(address),
        "address": address,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
