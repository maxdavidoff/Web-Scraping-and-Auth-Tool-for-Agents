from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from playwright.sync_api import Page


OHANA_BASE_URL = "https://liveohana.ai"
OHANA_INIT_DATA_URL = "https://liveohana.ai/api/1.1/init/data"
DEFAULT_TIMEZONE = "America/New_York"


def slugify_title(title: str) -> str:
    """
    Convert a listing title into an Ohana-style URL slug.

    Example:
    "Summer Sublet in Symphony!" -> "summer-sublet-in-symphony"
    """
    text = title.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def readable_date_to_epoch_ms(date_text: str, timezone: str = DEFAULT_TIMEZONE) -> int:
    """
    Convert dates like 'May 1, 2026' into epoch milliseconds.

    Ohana listing URLs appear to use midnight in America/New_York.
    Example:
    May 1, 2026 -> 1777608000000
    """
    dt = datetime.strptime(date_text, "%B %d, %Y")
    localized = dt.replace(tzinfo=ZoneInfo(timezone))
    return int(localized.timestamp() * 1000)


def build_listing_url(
    *,
    title: str,
    location: str | None = None,
    movein: str | None = None,
    moveout: str | None = None,
) -> str:
    """
    Build a guessed Ohana listing detail URL from the listing title and search context.

    Example:
    https://liveohana.ai/listing/summer-sublet-in-symphony?location=New+York+City&movein=...
    """
    slug = slugify_title(title)
    base_url = f"{OHANA_BASE_URL}/listing/{slug}"

    params: dict[str, str] = {}

    if location:
        params["location"] = location

    if movein:
        params["movein"] = str(readable_date_to_epoch_ms(movein))

    if moveout:
        params["moveout"] = str(readable_date_to_epoch_ms(moveout))

    if not params:
        return base_url

    return f"{base_url}?{urlencode(params)}"


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


def enrich_record_with_listing_api(
    *,
    page: Page,
    record: dict,
    location: str | None,
    movein: str | None,
    moveout: str | None,
    debug_dir: Path | None = None,
) -> dict:
    """
    Build guessed listing URL from title, call Ohana init/data,
    and merge exact listing address/coordinates into the record.
    """
    title = record.get("title", "")

    if not title:
        record["listing_api_status"] = "skipped_no_title"
        return record

    listing_url = build_listing_url(
        title=title,
        location=location,
        movein=movein,
        moveout=moveout,
    )

    init_data_url = build_init_data_url(listing_url)

    record["guessed_listing_url"] = listing_url
    record["init_data_url"] = init_data_url

    try:
        data = fetch_listing_init_data(page, listing_url)

        location_data = extract_address_geographic_address(data)

        if location_data:
            record.update(location_data)
            record["listing_api_status"] = "ok"
        else:
            record["listing_api_status"] = "ok_no_address_geographic_address_found"

        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            safe_slug = slugify_title(title)[:80] or "listing"
            debug_path = debug_dir / f"init_data_{safe_slug}.json"
            debug_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            record["init_data_debug_file"] = str(debug_path)

    except Exception as e:
        record["listing_api_status"] = "failed"
        record["listing_api_error"] = str(e)

    return record