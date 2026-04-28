from __future__ import annotations

import re
from urllib.parse import quote, urlencode, urlparse


OHANA_BASE_URL = "https://liveohana.ai"
OHANA_SUBLET_PATH = "/sublet"

CANONICAL_LOCATION_SLUGS = {
    "boston": "boston",
    "boston ma": "boston",
    "new york": "new-york-city",
    "new york ny": "new-york-city",
    "new york city": "new-york-city",
    "new york city ny": "new-york-city",
    "nyc": "new-york-city",
    "washington dc": "washington",
    "washington d c": "washington",
    "washington district of columbia": "washington",
    "philadelphia": "philadelphia",
    "philadelphia pa": "philadelphia",
    "philly": "philadelphia",
}

CANONICAL_LOCATION_LABELS = {
    "boston": "Boston, MA, USA",
    "boston ma": "Boston, MA, USA",
    "new york": "New York, NY, USA",
    "new york ny": "New York, NY, USA",
    "new york city": "New York, NY, USA",
    "new york city ny": "New York, NY, USA",
    "nyc": "New York, NY, USA",
    "washington dc": "Washington, DC, USA",
    "washington d c": "Washington, DC, USA",
    "washington district of columbia": "Washington, DC, USA",
    "philadelphia": "Philadelphia, PA, USA",
    "philadelphia pa": "Philadelphia, PA, USA",
    "philly": "Philadelphia, PA, USA",
}


def _double_encoded_list(values: list[str]) -> str:
    """
    Ohana/Bubble expects some multi-word filter values double encoded.

    Example:
    "Private room" -> "Private%20room" -> "Private%2520room"
    """
    return ",".join(quote(value) for value in values)


def _normalize_location_key(location: str) -> str:
    text = location.lower().strip()
    text = re.sub(r"\b(?:usa|us|united states|united states of america)\b", "", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify_location(location: str) -> str:
    location = location.strip()
    if not location:
        raise ValueError("Location cannot be empty.")

    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        raise ValueError("slugify_location expects a location, not a URL.")

    zip_match = re.search(r"\b\d{5}(?:-\d{4})?\b", location)
    if zip_match:
        return zip_match.group(0)

    key = _normalize_location_key(location)
    if key in CANONICAL_LOCATION_SLUGS:
        return CANONICAL_LOCATION_SLUGS[key]

    parts = [part.strip() for part in location.split(",") if part.strip()]
    if len(parts) >= 2 and parts[-1].lower() in {"usa", "us", "united states"}:
        parts = parts[:-1]

    if len(parts) >= 2 and re.fullmatch(r"[A-Za-z]{2}", parts[1]):
        key = _normalize_location_key(f"{parts[0]} {parts[1]}")
        if key in CANONICAL_LOCATION_SLUGS:
            return CANONICAL_LOCATION_SLUGS[key]
        return re.sub(r"[^a-z0-9]+", "-", parts[0].lower()).strip("-")

    return re.sub(r"[^a-z0-9]+", "-", key).strip("-")


def format_location_label(location: str) -> str:
    key = _normalize_location_key(location)
    return CANONICAL_LOCATION_LABELS.get(key, location.strip())


def build_ohana_search_url(
    location: str | None = None,
    movein: str | None = None,
    moveout: str | None = None,
    property_types: list[str] | None = None,
    type_of_places: list[str] | None = None,
    num_bedrooms: int | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    pet_policy: list[str] | None = None,
    furnished_status: list[str] | None = None,
    search_url: str | None = None,
) -> str:
    if search_url:
        return search_url

    if not location:
        raise ValueError("Provide either search_url or location.")

    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        return location

    location_slug = slugify_location(location)
    params = {
        "location": format_location_label(location),
    }

    if movein:
        params["movein"] = movein

    if moveout:
        params["moveout"] = moveout

    if property_types:
        params["property_types"] = ",".join(property_types)

    if type_of_places:
        params["type_of_places"] = _double_encoded_list(type_of_places)

    if num_bedrooms is not None:
        params["num_bedrooms"] = str(num_bedrooms)

    if min_price is not None:
        params["min_price"] = str(min_price)

    if max_price is not None:
        params["max_price"] = str(max_price)

    if pet_policy:
        params["pet_policy"] = _double_encoded_list(pet_policy)

    if furnished_status:
        params["furnished_status"] = _double_encoded_list(furnished_status)

    return f"{OHANA_BASE_URL}{OHANA_SUBLET_PATH}/{location_slug}?{urlencode(params)}"
