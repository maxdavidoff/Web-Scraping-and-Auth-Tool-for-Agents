from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Page

from .parsing import clean_text

JSON_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.I | re.S,
)
ALLOWED_DETAIL_HOSTS = {"www.rentalsource.com", "rentalsource.com"}


def is_allowed_detail_url(detail_url: str) -> bool:
    parsed = urlparse(detail_url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in ALLOWED_DETAIL_HOSTS
        and parsed.path.startswith("/details/")
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _iter_json_ld_nodes(obj: Any) -> list[dict]:
    nodes: list[dict] = []

    if isinstance(obj, dict):
        nodes.append(obj)
        graph = obj.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                nodes.extend(_iter_json_ld_nodes(item))
    elif isinstance(obj, list):
        for item in obj:
            nodes.extend(_iter_json_ld_nodes(item))

    return nodes


def parse_json_ld_documents(html_text: str) -> list[dict]:
    documents: list[dict] = []
    for match in JSON_LD_RE.finditer(html_text):
        raw = html.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            documents.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return documents


def find_real_estate_listing(documents: list[dict]) -> dict:
    for document in documents:
        for node in _iter_json_ld_nodes(document):
            node_type = node.get("@type")
            node_types = set(node_type if isinstance(node_type, list) else [node_type])
            if "RealEstateListing" in node_types:
                return node
    return {}


def _address_to_text(address: dict) -> str:
    pieces = [
        address.get("streetAddress", ""),
        address.get("addressLocality", ""),
        address.get("addressRegion", ""),
        address.get("postalCode", ""),
    ]
    street, city, state, postal = [clean_text(str(piece)) for piece in pieces]
    locality = clean_text(", ".join(part for part in [city, state] if part))
    city_line = clean_text(" ".join(part for part in [locality, postal] if part))
    return clean_text(", ".join(part for part in [street, city_line] if part))


def _price_summary(prices: list[float | int]) -> tuple[str, float | int | None, float | int | None]:
    if not prices:
        return "", None, None

    price_min = min(prices)
    price_max = max(prices)

    def fmt(value: float | int) -> str:
        if isinstance(value, float) and not value.is_integer():
            return f"${value:,.2f}"
        return f"${int(value):,}"

    if price_min == price_max:
        return fmt(price_min), price_min, price_max

    return f"{fmt(price_min)} - {fmt(price_max)}", price_min, price_max


def _property_type(value: Any) -> str:
    if isinstance(value, list):
        value = next((item for item in value if item), "")
    if not value:
        return ""
    return str(value).replace("_", " ").strip().title()


def extract_detail_data(listing: dict) -> dict:
    offers = [offer for offer in _as_list(listing.get("offers")) if isinstance(offer, dict)]
    first_offer = offers[0] if offers else {}
    item = first_offer.get("itemOffered") if isinstance(first_offer.get("itemOffered"), dict) else {}
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    geo = item.get("geo") if isinstance(item.get("geo"), dict) else {}
    floor_size = item.get("floorSize") if isinstance(item.get("floorSize"), dict) else {}

    prices: list[float | int] = []
    square_feet_values: list[float | int] = []
    for offer in offers:
        price = offer.get("price")
        try:
            price_number = float(price)
        except (TypeError, ValueError):
            continue
        prices.append(int(price_number) if price_number.is_integer() else price_number)

        offered_item = offer.get("itemOffered") if isinstance(offer.get("itemOffered"), dict) else {}
        offered_floor_size = (
            offered_item.get("floorSize") if isinstance(offered_item.get("floorSize"), dict) else {}
        )
        try:
            square_feet_number = float(offered_floor_size.get("value"))
        except (TypeError, ValueError):
            continue
        square_feet_values.append(
            int(square_feet_number) if square_feet_number.is_integer() else square_feet_number
        )

    price, price_min, price_max = _price_summary(prices)

    image_urls = listing.get("image")
    images = [str(image) for image in _as_list(image_urls) if image]

    data = {
        "listing_id": clean_text(str(listing.get("identifier", ""))),
        "detail_name": clean_text(str(listing.get("name", ""))),
        "detail_description": clean_text(str(listing.get("description", ""))),
        "date_posted": clean_text(str(listing.get("datePosted", ""))),
        "date_modified": clean_text(str(listing.get("dateModified", ""))),
        "last_reviewed": clean_text(str(listing.get("lastReviewed", ""))),
        "listing_address": _address_to_text(address),
        "listing_location_source": "json_ld",
        "property_type": _property_type(item.get("@type")),
        "bedrooms": clean_text(str(item.get("numberOfBedrooms", ""))),
        "bathrooms": clean_text(str(item.get("numberOfBathroomsTotal", ""))),
        "square_feet": clean_text(str(floor_size.get("value", ""))),
        "square_feet_min": min(square_feet_values) if square_feet_values else "",
        "square_feet_max": max(square_feet_values) if square_feet_values else "",
        "pets_allowed": item.get("petsAllowed", ""),
        "price": price,
        "price_min": price_min,
        "price_max": price_max,
        "price_currency": clean_text(str(first_offer.get("priceCurrency", ""))),
        "image_urls": images,
    }

    try:
        data["listing_latitude"] = float(geo.get("latitude"))
        data["listing_longitude"] = float(geo.get("longitude"))
    except (TypeError, ValueError):
        pass

    return {key: value for key, value in data.items() if value not in ("", None, [])}


def fetch_listing_detail_data(page: "Page", detail_url: str) -> dict:
    if not is_allowed_detail_url(detail_url):
        raise ValueError(f"Refusing to fetch non-RentalSource detail URL: {detail_url}")

    response = page.request.get(detail_url)

    if not response.ok:
        raise RuntimeError(f"Detail page failed with status {response.status}: {detail_url}")

    documents = parse_json_ld_documents(response.text())
    listing = find_real_estate_listing(documents)
    if not listing:
        return {}

    return extract_detail_data(listing)


def enrich_record_with_detail(
    *,
    page: "Page",
    record: dict,
    debug_dir: Path | None = None,
) -> dict:
    detail_url = record.get("detail_url") or record.get("url")
    if not detail_url:
        record["listing_detail_status"] = "skipped_no_detail_url"
        return record
    if not is_allowed_detail_url(str(detail_url)):
        record["listing_detail_status"] = "skipped_invalid_detail_url"
        return record

    try:
        detail_data = fetch_listing_detail_data(page, str(detail_url))
        if not detail_data:
            record["listing_detail_status"] = "ok_no_real_estate_listing_json_ld"
            return record

        existing_images = record.get("image_urls")
        if isinstance(existing_images, list):
            detail_images = detail_data.get("image_urls")
            if isinstance(detail_images, list):
                detail_data["image_urls"] = list(dict.fromkeys(existing_images + detail_images))

        record.update(detail_data)
        record["listing_detail_status"] = "ok"

        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            listing_id = record.get("listing_id") or record.get("id") or "listing"
            debug_path = debug_dir / f"detail_{listing_id}.json"
            debug_path.write_text(
                json.dumps(detail_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            record["listing_detail_debug_file"] = str(debug_path)

    except Exception as e:
        record["listing_detail_status"] = "failed"
        record["listing_detail_error"] = str(e)

    return record
