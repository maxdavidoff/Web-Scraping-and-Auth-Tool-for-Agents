from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Page

from .parsing import clean_text


ALLOWED_DETAIL_HOSTS = {"www.affordablehousing.com", "affordablehousing.com"}
SERVER_SIDE_VARIABLE_RE = re.compile(
    r"propertyDetailsModel\.domain\.serverSideVariables\.([A-Za-z0-9_]+)\((['\"])(.*?)\2\)",
    re.S,
)


def is_allowed_detail_url(detail_url: str) -> bool:
    parsed = urlparse(detail_url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in ALLOWED_DETAIL_HOSTS
        and bool(re.search(r"/[a-z0-9-]+-\d+/?$", parsed.path))
    )


def parse_server_side_variables(html_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, _quote, raw_value in SERVER_SIDE_VARIABLE_RE.findall(html_text):
        values[key] = html.unescape(raw_value)
    return values


def extract_detail_data(html_text: str) -> dict[str, object]:
    values = parse_server_side_variables(html_text)
    data: dict[str, object] = {}

    address = clean_text(str(values.get("propertyAddress", "")))
    city = clean_text(str(values.get("propertyCity", "")))
    state = clean_text(str(values.get("propertyState", "")))
    if address or city or state:
        city_line = clean_text(", ".join(part for part in [city, state] if part))
        data["listing_address"] = clean_text(", ".join(part for part in [address, city_line] if part))

    community_name = clean_text(str(values.get("communityName", "")))
    if community_name:
        data["detail_name"] = community_name

    try:
        data["listing_latitude"] = float(values.get("propertyLatitude", ""))
        data["listing_longitude"] = float(values.get("propertyLongitude", ""))
        data["listing_location_source"] = "server_side_variables"
    except (TypeError, ValueError):
        pass

    return {key: value for key, value in data.items() if value not in ("", None, [])}


def fetch_listing_detail_data(page: "Page", detail_url: str) -> dict[str, object]:
    if not is_allowed_detail_url(detail_url):
        raise ValueError(f"Refusing to fetch non-AffordableHousing detail URL: {detail_url}")

    response = page.request.get(detail_url)

    if not response.ok:
        raise RuntimeError(f"Detail page failed with status {response.status}: {detail_url}")

    return extract_detail_data(response.text())


def enrich_record_with_detail(
    *,
    page: "Page",
    record: dict,
    debug_dir: Path | None = None,
) -> dict:
    detail_url = record.get("detail_url") or record.get("url")
    if not detail_url:
        record["listing_detail_status"] = "skipped_no_detail_url"
        annotate_coordinate_status(record, enrichment_requested=True)
        return record
    if not is_allowed_detail_url(str(detail_url)):
        record["listing_detail_status"] = "skipped_invalid_detail_url"
        annotate_coordinate_status(record, enrichment_requested=True)
        return record

    try:
        detail_data = fetch_listing_detail_data(page, str(detail_url))
        if not detail_data:
            record["listing_detail_status"] = "ok_no_detail_coordinates"
            annotate_coordinate_status(record, enrichment_requested=True)
            return record

        record.update(detail_data)
        record["listing_detail_status"] = "ok"
        annotate_coordinate_status(record, enrichment_requested=True)

        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            listing_id = record.get("id") or "listing"
            debug_path = debug_dir / f"detail_{listing_id}.json"
            debug_path.write_text(
                json.dumps(detail_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            record["listing_detail_debug_file"] = str(debug_path)

    except Exception as e:
        record["listing_detail_status"] = "failed"
        record["listing_detail_error"] = str(e)
        annotate_coordinate_status(record, enrichment_requested=True)

    return record


def annotate_coordinate_status(record: dict, *, enrichment_requested: bool) -> None:
    if record.get("listing_latitude") is not None and record.get("listing_longitude") is not None:
        record["coordinates_status"] = "present"
        record["coordinates_source"] = record.get("listing_location_source") or "server_side_variables"
        return

    record["coordinates_source"] = "server_side_variables"
    if not enrichment_requested:
        record["coordinates_status"] = "not_requested"
        return

    if record.get("listing_detail_status") == "failed":
        record["coordinates_status"] = "failed"
        if record.get("listing_detail_error"):
            record["coordinates_error"] = record["listing_detail_error"]
        return

    record["coordinates_status"] = "missing"
