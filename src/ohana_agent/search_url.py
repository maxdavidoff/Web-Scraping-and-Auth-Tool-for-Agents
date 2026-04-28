from __future__ import annotations

from urllib.parse import quote, urlencode, urlparse

from src.supported_locations import supported_location_for


OHANA_BASE_URL = "https://liveohana.ai"
OHANA_SUBLET_PATH = "/sublet"

def _double_encoded_list(values: list[str]) -> str:
    """
    Ohana/Bubble expects some multi-word filter values double encoded.

    Example:
    "Private room" -> "Private%20room" -> "Private%2520room"
    """
    return ",".join(quote(value) for value in values)


def slugify_location(location: str) -> str:
    location = location.strip()
    if not location:
        raise ValueError("Location cannot be empty.")

    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        raise ValueError("slugify_location expects a location, not a URL.")

    return supported_location_for(location).ohana_slug


def format_location_label(location: str) -> str:
    return supported_location_for(location).label


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
