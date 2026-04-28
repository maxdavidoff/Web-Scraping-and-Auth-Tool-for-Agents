from __future__ import annotations

from typing import Any
from urllib.parse import quote

from playwright.sync_api import Page


OHANA_INIT_DATA_URL = "https://liveohana.ai/api/1.1/init/data"


def build_init_data_url(listing_url: str) -> str:
    """
    Build Ohana Bubble init/data URL for a listing detail page.
    """
    encoded_listing_url = quote(listing_url, safe="")
    return f"{OHANA_INIT_DATA_URL}?location={encoded_listing_url}"


def find_key_recursive(obj: Any, target_key: str) -> list[Any]:
    """
    Recursively find all values for a given key in JSON-like data.
    """
    matches: list[Any] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key) == target_key:
                matches.append(value)
            matches.extend(find_key_recursive(value, target_key))

    elif isinstance(obj, list):
        for item in obj:
            matches.extend(find_key_recursive(item, target_key))

    return matches


def extract_address_geographic_address(data: Any) -> dict:
    """
    Extract the actual listing/property location.

    Important:
    Do NOT blindly use the first lat/lng in the response.
    The response may also contain user hometown coordinates or neighborhood coordinates.
    We specifically prioritize address_geographic_address.
    """
    candidates = find_key_recursive(data, "address_geographic_address")

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        lat = candidate.get("lat")
        lng = candidate.get("lng")
        address = candidate.get("address")

        try:
            lat_float = float(lat)
            lng_float = float(lng)
        except Exception:
            continue

        if not (-90 <= lat_float <= 90 and -180 <= lng_float <= 180):
            continue

        return {
            "listing_address": address or "",
            "listing_latitude": lat_float,
            "listing_longitude": lng_float,
            "listing_location_source": "address_geographic_address",
        }

    return {}


def fetch_listing_init_data(page: Page, listing_url: str) -> Any:
    """
    Fetch Ohana init/data using Playwright's logged-in browser context.
    """
    init_data_url = build_init_data_url(listing_url)

    response = page.request.get(init_data_url)

    if not response.ok:
        raise RuntimeError(
            f"Init/data failed with status {response.status}: {init_data_url}"
        )

    return response.json()
