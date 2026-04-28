from __future__ import annotations

import re
from urllib.parse import urlencode

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


def slugify_location(location: str) -> str:
    """
    Convert locations like 'Boston, MA, USA' to RentalSource path slugs.

    For ambiguous values, pass --search-url directly.
    """
    location = location.strip()
    if not location:
        raise ValueError("Location cannot be empty.")

    if re.fullmatch(r"\d{5}", location):
        return location

    parts = [part.strip() for part in location.split(",") if part.strip()]
    if len(parts) >= 2 and re.fullmatch(r"[A-Za-z]{2}", parts[1]):
        city = parts[0]
        state = parts[1].lower()
        city_slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
        return f"{city_slug}-{state}"

    return re.sub(r"[^a-z0-9]+", "-", location.lower()).strip("-")


def _type_code(property_type: str) -> str:
    key = property_type.strip().lower()
    return TYPE_PARAM_MAP.get(key, key)


def build_rentalsource_search_url(
    location: str,
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
) -> str:
    slug = slugify_location(location)
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
