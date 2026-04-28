from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SupportedLocation:
    key: str
    label: str
    ohana_slug: str
    city_state_slug: str


SUPPORTED_LOCATIONS = {
    "boston": SupportedLocation(
        key="boston",
        label="Boston, MA, USA",
        ohana_slug="boston",
        city_state_slug="boston-ma",
    ),
    "new_york": SupportedLocation(
        key="new_york",
        label="New York, NY, USA",
        ohana_slug="new-york-city",
        city_state_slug="new-york-ny",
    ),
    "washington_dc": SupportedLocation(
        key="washington_dc",
        label="Washington, DC, USA",
        ohana_slug="washington",
        city_state_slug="washington-dc",
    ),
    "philadelphia": SupportedLocation(
        key="philadelphia",
        label="Philadelphia, PA, USA",
        ohana_slug="philadelphia",
        city_state_slug="philadelphia-pa",
    ),
}


SUPPORTED_LOCATION_ALIASES = {
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
    "washington": "washington_dc",
    "washington dc": "washington_dc",
    "washington d c": "washington_dc",
    "dc": "washington_dc",
    "d c": "washington_dc",
    "georgetown": "washington_dc",
    "georgetown dc": "washington_dc",
    "dupont circle": "washington_dc",
    "capitol hill": "washington_dc",
    "philadelphia": "philadelphia",
    "philadelphia pa": "philadelphia",
    "philly": "philadelphia",
    "university city": "philadelphia",
    "university city pa": "philadelphia",
    "upenn": "philadelphia",
    "u penn": "philadelphia",
    "university of pennsylvania": "philadelphia",
}


def normalize_location_key(location: str) -> str:
    text = location.lower().strip()
    text = re.sub(r"\b(?:usa|us|united states|united states of america)\b", "", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def supported_location_for(location: str) -> SupportedLocation:
    key = normalize_location_key(location)
    if not key:
        raise ValueError("Location cannot be empty.")

    city_key = SUPPORTED_LOCATION_ALIASES.get(key)
    if city_key:
        return SUPPORTED_LOCATIONS[city_key]

    for supported_key in ("new york", "washington dc", "washington", "philadelphia", "boston"):
        if re.search(rf"\b{re.escape(supported_key)}\b", key):
            return SUPPORTED_LOCATIONS[SUPPORTED_LOCATION_ALIASES[supported_key]]

    supported = ", ".join(location.label for location in SUPPORTED_LOCATIONS.values())
    raise ValueError(
        f"Location searches only support {supported}. "
        "Use one of those cities, or a known neighborhood within one of them."
    )
