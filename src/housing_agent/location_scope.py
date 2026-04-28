from __future__ import annotations

import re


NEIGHBORHOOD_ONLY_LOCATIONS = frozenset(
    {
        "allston",
        "back bay",
        "beacon hill",
        "brighton",
        "brookline",
        "brookline ma",
        "cambridge",
        "cambridge ma",
        "charlestown",
        "chinatown",
        "dorchester",
        "east boston",
        "fenway",
        "jamaica plain",
        "jp",
        "mission hill",
        "north end",
        "roxbury",
        "seaport",
        "somerville",
        "somerville ma",
        "south end",
        "astoria",
        "bronx",
        "brooklyn",
        "bushwick",
        "crown heights",
        "dumbo",
        "flushing",
        "forest hills",
        "greenpoint",
        "harlem",
        "jackson heights",
        "lic",
        "long island city",
        "lower east side",
        "manhattan",
        "park slope",
        "queens",
        "staten island",
        "the bronx",
        "upper east side",
        "upper west side",
        "williamsburg",
        "adams morgan",
        "anacostia",
        "capitol hill",
        "columbia heights",
        "dupont circle",
        "foggy bottom",
        "georgetown",
        "georgetown dc",
        "h street",
        "navy yard",
        "noma",
        "petworth",
        "shaw",
        "center city",
        "chestnut hill",
        "east falls",
        "fishtown",
        "graduate hospital",
        "manayunk",
        "mount airy",
        "northern liberties",
        "old city",
        "point breeze",
        "rittenhouse",
        "university city",
        "university city pa",
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
