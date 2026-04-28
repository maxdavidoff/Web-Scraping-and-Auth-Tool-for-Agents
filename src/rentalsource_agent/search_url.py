from __future__ import annotations

import re
from urllib.parse import urlencode, urlparse

from src.supported_locations import supported_location_for

RENTALSOURCE_BASE_URL = "https://www.rentalsource.com"

TYPE_PARAM_MAP = {
    "apartment": "apt",
    "apartments": "apt",
    "apt": "apt",
    "house": "hous",
    "houses": "hous",
    "home": "hous",
    "homes": "hous",
    "hous": "hous",
    "townhouse": "town",
    "townhouses": "town",
    "townhome": "town",
    "townhomes": "town",
    "town": "town",
    "condo": "cond",
    "condos": "cond",
    "cond": "cond",
}

SORT_MAP = {
    "relevance": "relevance",
    "homes-for-you": "relevance",
    "verified": "verified",
    "price": "price",
    "price-low": "price",
    "price-low-to-high": "price",
    "price-high": "price-high",
    "price-high-to-low": "price-high",
    "newest": "newest",
    "updated": "updated",
    "popular": "popular",
}

CATEGORY_PATH_MAP = {
    "apt": "apartments",
    "hous": "houses",
}


def slugify_location(location: str) -> str:
    """
    Convert locations like 'Boston, MA, USA' to RentalSource path slugs.

    City/state/ZIP locations use the known canonical city ZIP shape, e.g.
    'Boston, MA 02118' -> 'boston-ma-02118'. ZIP-only inputs are rejected
    because a supported market city is required for canonical RentalSource URLs.

    For ambiguous values, pass --search-url directly.
    """
    location = location.strip()
    if not location:
        raise ValueError("Location cannot be empty.")

    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        raise ValueError("slugify_location expects a location, not a URL.")

    parts = [part.strip() for part in location.split(",") if part.strip()]
    if len(parts) >= 2:
        state_zip = parts[1].split()
        if len(state_zip) >= 2 and re.fullmatch(r"[A-Za-z]{2}", state_zip[0]) and re.fullmatch(r"\d{5}", state_zip[1]):
            base_slug = supported_location_for(f"{parts[0]}, {state_zip[0]}").city_state_slug
            return f"{base_slug}-{state_zip[1]}"

    return supported_location_for(location).city_state_slug


def _type_code(property_type: str) -> str:
    key = property_type.strip().lower()
    return TYPE_PARAM_MAP.get(key, key)


def _category_path(property_types: list[str] | None) -> str:
    codes = [
        _type_code(property_type)
        for property_type in property_types or []
        if _type_code(property_type) and _type_code(property_type) != "all"
    ]
    if len(codes) == 1:
        return CATEGORY_PATH_MAP.get(codes[0], "")
    return ""


def build_rentalsource_search_url(
    location: str | None = None,
    property_types: list[str] | None = None,
    num_bedrooms: int | None = None,
    num_bathrooms: float | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    pets: bool = False,
    photos: bool = False,
    verified: bool = False,
    featured: bool = False,
    sort: str | None = None,
    page: int | None = None,
    search_url: str | None = None,
) -> str:
    if search_url:
        return search_url

    if not location:
        raise ValueError("Provide either search_url or location.")

    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        return location

    slug = slugify_location(location)
    category_path = _category_path(property_types)
    if category_path:
        base_url = f"{RENTALSOURCE_BASE_URL}/{slug}/{category_path}/"
    else:
        base_url = f"{RENTALSOURCE_BASE_URL}/{slug}/"
    params: list[tuple[str, str]] = []

    if min_price is not None:
        params.append(("min", str(min_price)))

    if max_price is not None:
        params.append(("max", str(max_price)))

    if num_bedrooms is not None:
        params.append(("beds", str(num_bedrooms)))

    if num_bathrooms is not None:
        params.append(("baths", str(num_bathrooms).rstrip("0").rstrip(".")))

    for property_type in property_types or []:
        code = _type_code(property_type)
        if code and code != "all":
            params.append(("types[]", code))

    if pets:
        params.append(("pets", "Y"))

    if photos:
        params.append(("photos", "Y"))

    if verified:
        params.append(("verified", "Y"))

    if featured:
        params.append(("featured", "Y"))

    if sort:
        params.append(("sort", SORT_MAP.get(sort.strip().lower(), sort)))

    if page is not None:
        params.append(("page", str(page)))

    if not params:
        return base_url

    return f"{base_url}?{urlencode(params)}"
