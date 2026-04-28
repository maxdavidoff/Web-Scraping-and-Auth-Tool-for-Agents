from __future__ import annotations

import re
from urllib.parse import urlparse

from src.supported_locations import supported_location_for

AFFORDABLEHOUSING_BASE_URL = "https://www.affordablehousing.com"

PROPERTY_TYPE_SLUGS = {
    "apartment": "apartment",
    "apartments": "apartment",
    "house": "house",
    "houses": "house",
    "single family house": "house",
    "single-family house": "house",
    "townhouse": "townhouse",
    "townhouses": "townhouse",
    "condo": "condo",
    "condos": "condo",
}

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\b(?:usa|united states|united states of america)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def location_to_slug(location: str) -> str:
    """
    Convert common locations into AffordableHousing SEO slugs.

    Examples:
    - "Boston, MA" -> "boston-ma"
    - "Boston, MA, USA" -> "boston-ma"
    - "University City" -> "philadelphia-pa"
    """
    if not location:
        raise ValueError("Location is required.")

    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        raise ValueError("location_to_slug expects a location, not a URL.")

    return supported_location_for(location).city_state_slug


def _bedroom_slug(num_bedrooms: int | None) -> str:
    if num_bedrooms is None:
        return ""
    if num_bedrooms <= 0:
        return "studio"
    return f"{num_bedrooms}-bed"


def _property_type_slug(property_types: list[str] | None) -> str:
    if not property_types:
        return ""
    return PROPERTY_TYPE_SLUGS.get(property_types[0].strip().lower(), _slugify(property_types[0]))


def build_affordablehousing_search_url(
    location: str,
    property_types: list[str] | None = None,
    num_bedrooms: int | None = None,
    max_price: int | None = None,
    pet_friendly: bool = False,
    section8: bool = False,
    income_restricted: bool = False,
    wheelchair_accessible: bool = False,
    utilities_included: bool = False,
    washer_dryer: bool = False,
) -> str:
    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        return location

    segments = [location_to_slug(location)]

    if max_price is not None:
        segments.append(f"under-{max_price}")

    bedroom_slug = _bedroom_slug(num_bedrooms)
    if bedroom_slug:
        segments.append(bedroom_slug)

    property_type_slug = _property_type_slug(property_types)
    if property_type_slug:
        segments.append(property_type_slug)

    if section8:
        segments.append("section8-owners")
    if pet_friendly:
        segments.append("pet-friendly")
    if wheelchair_accessible:
        segments.append("wheelchair-accessible")
    if utilities_included:
        segments.append("utilities-included")
    if washer_dryer:
        segments.append("washer-dryer")
    if income_restricted:
        segments.append("income-restricted")

    path = "/".join(segment for segment in segments if segment)
    return f"{AFFORDABLEHOUSING_BASE_URL}/{path}/"
