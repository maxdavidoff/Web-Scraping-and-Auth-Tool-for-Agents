from __future__ import annotations

import re


NEIGHBORHOOD_ONLY_LOCATIONS = frozenset(
    {
        "allston",
        "back bay",
        "brighton",
        "brookline",
        "brookline ma",
        "cambridge",
        "cambridge ma",
        "fenway",
        "somerville",
        "somerville ma",
        "south end",
        "bronx",
        "brooklyn",
        "bushwick",
        "harlem",
        "lower east side",
        "manhattan",
        "queens",
        "staten island",
        "the bronx",
        "upper east side",
        "upper west side",
        "williamsburg",
        "haight ashbury",
        "mission",
        "mission district",
        "nob hill",
        "north beach",
        "richmond",
        "soma",
        "south of market",
        "sunset",
    }
)


def normalize_location_text(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"\b(?:usa|us|united states|united states of america)\b", "", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_neighborhood_only_location(value: str | None) -> bool:
    if not value:
        return False
    return normalize_location_text(value) in NEIGHBORHOOD_ONLY_LOCATIONS


def asks_for_neighborhood_preference(question: str) -> bool:
    text = normalize_location_text(question)
    neighborhood_terms = ("neighborhood", "neighbourhood", "area")
    ask_terms = ("prefer", "preference", "preferred", "want", "like", "specific")
    return any(term in text for term in neighborhood_terms) and any(term in text for term in ask_terms)
