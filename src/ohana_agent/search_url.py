from __future__ import annotations

import re
from urllib.parse import quote, urlencode, urlparse


OHANA_BASE_URL = "https://liveohana.ai"
OHANA_SUBLET_PATH = "/sublet"

OHANA_CITY_SLUGS = {
    "boston": "boston",
    "new_york": "new-york-city",
    "san_francisco": "san-francisco",
}

OHANA_CITY_LABELS = {
    "boston": "Boston, MA, USA",
    "new_york": "New York, NY, USA",
    "san_francisco": "San Francisco, CA, USA",
}

SUPPORTED_OHANA_CITY_NAMES = tuple(OHANA_CITY_LABELS.values())

OHANA_LOCATION_CITY_ALIASES = {
    "boston": "boston",
    "boston ma": "boston",
    "boston massachusetts": "boston",
    "cambridge": "boston",
    "cambridge ma": "boston",
    "cambridge massachusetts": "boston",
    "somerville": "boston",
    "somerville ma": "boston",
    "brookline": "boston",
    "brookline ma": "boston",
    "allston": "boston",
    "brighton": "boston",
    "back bay": "boston",
    "fenway": "boston",
    "south end": "boston",
    "new york": "new_york",
    "new york ny": "new_york",
    "new york city": "new_york",
    "new york city ny": "new_york",
    "nyc": "new_york",
    "manhattan": "new_york",
    "brooklyn": "new_york",
    "queens": "new_york",
    "bronx": "new_york",
    "the bronx": "new_york",
    "staten island": "new_york",
    "williamsburg": "new_york",
    "bushwick": "new_york",
    "harlem": "new_york",
    "upper west side": "new_york",
    "upper east side": "new_york",
    "lower east side": "new_york",
    "san francisco": "san_francisco",
    "san francisco ca": "san_francisco",
    "san francisco california": "san_francisco",
    "sf": "san_francisco",
    "s f": "san_francisco",
    "mission": "san_francisco",
    "mission district": "san_francisco",
    "soma": "san_francisco",
    "south of market": "san_francisco",
    "nob hill": "san_francisco",
    "north beach": "san_francisco",
    "haight ashbury": "san_francisco",
    "sunset": "san_francisco",
    "richmond": "san_francisco",
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


def _city_key_for_location(location: str) -> str:
    key = _normalize_location_key(location)
    if not key:
        raise ValueError("Location cannot be empty.")

    city_key = OHANA_LOCATION_CITY_ALIASES.get(key)
    if city_key:
        return city_key

    for supported_key in ("new york", "san francisco", "boston"):
        if re.search(rf"\b{re.escape(supported_key)}\b", key):
            return OHANA_LOCATION_CITY_ALIASES[supported_key]

    supported = ", ".join(SUPPORTED_OHANA_CITY_NAMES)
    raise ValueError(
        f"Ohana URL searches only support {supported}. "
        "Use one of those cities, or a known neighborhood within one of them."
    )


def slugify_location(location: str) -> str:
    location = location.strip()
    if not location:
        raise ValueError("Location cannot be empty.")

    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        raise ValueError("slugify_location expects a location, not a URL.")

    return OHANA_CITY_SLUGS[_city_key_for_location(location)]


def format_location_label(location: str) -> str:
    return OHANA_CITY_LABELS[_city_key_for_location(location)]


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
