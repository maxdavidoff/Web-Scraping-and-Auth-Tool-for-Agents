from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping


AMENITY_KEYWORDS = {
    "air conditioning": ("air conditioning", "a/c", "ac "),
    "balcony": ("balcony", "patio", "deck"),
    "dishwasher": ("dishwasher",),
    "doorman": ("doorman", "concierge"),
    "elevator": ("elevator",),
    "furnished": ("furnished",),
    "gym": ("gym", "fitness center"),
    "in-unit laundry": ("in-unit laundry", "in unit laundry", "washer/dryer", "washer dryer"),
    "laundry": ("laundry",),
    "parking": ("parking", "garage"),
    "pet friendly": ("pet friendly", "pets allowed", "dog", "cat"),
    "private bathroom": ("private bathroom", "private bath"),
    "roof deck": ("roof deck", "rooftop"),
    "utilities included": ("utilities included", "utilities incl"),
    "wifi": ("wifi", "wi-fi", "internet included"),
}


@dataclass(frozen=True)
class CampusLocation:
    label: str
    latitude: float | None = None
    longitude: float | None = None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_coordinates(record: Mapping[str, Any]) -> dict[str, float | None]:
    latitude = next(
        (
            value
            for value in (
                _optional_float(record.get("listing_latitude")),
                _optional_float(record.get("latitude")),
                _optional_float(record.get("lat")),
            )
            if value is not None
        ),
        None,
    )
    longitude = next(
        (
            value
            for value in (
                _optional_float(record.get("listing_longitude")),
                _optional_float(record.get("longitude")),
                _optional_float(record.get("lng")),
            )
            if value is not None
        ),
        None,
    )
    return {"latitude": latitude, "longitude": longitude}


def _parse_price_amount(price: Any) -> int | None:
    text = str(price or "")
    match = re.search(r"\$?\s*([\d,]+)", text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _normalize_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        candidates = re.split(r"[,|;/\n]+", value)
    elif isinstance(value, Mapping):
        candidates = [str(key) for key, enabled in value.items() if enabled]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(item) for item in value]
    else:
        return []

    cleaned = []
    for candidate in candidates:
        text = re.sub(r"\s+", " ", candidate).strip()
        if text:
            cleaned.append(text)
    return list(dict.fromkeys(cleaned))


def _extract_amenities(record: Mapping[str, Any]) -> list[str]:
    explicit = []
    for key in ("amenities", "building_amenities", "room_amenities", "unit_amenities"):
        explicit.extend(_normalize_string_list(record.get(key)))

    lowered_text = " ".join(
        str(record.get(key) or "")
        for key in ("title", "raw_text", "description", "notes")
    ).lower()
    inferred = [
        label
        for label, needles in AMENITY_KEYWORDS.items()
        if any(needle in lowered_text for needle in needles)
    ]

    return list(dict.fromkeys(explicit + inferred))


def _haversine_miles(
    lat1: float | None,
    lng1: float | None,
    lat2: float | None,
    lng2: float | None,
) -> float | None:
    if None in (lat1, lng1, lat2, lng2):
        return None

    radius_miles = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _normalize_distance_score(distance_miles: float | None) -> float:
    if distance_miles is None:
        return 0.35
    return max(0.0, 1.0 - min(distance_miles, 6.0) / 6.0)


def _normalize_price_score(price_amount: int | None, prices: list[int]) -> float:
    if price_amount is None or not prices:
        return 0.35
    cheapest = min(prices)
    most_expensive = max(prices)
    if cheapest == most_expensive:
        return 0.75
    return 1.0 - ((price_amount - cheapest) / (most_expensive - cheapest))


def _listing_id(record: Mapping[str, Any], index: int) -> str:
    return str(record.get("id") or f"listing_{index + 1}")


def _fit_signals(
    *,
    listing: Mapping[str, Any],
    cheapest_price: int | None,
    closest_distance: float | None,
) -> list[str]:
    signals = []
    price_amount = listing.get("price_amount")
    distance_miles = listing.get("distance_to_campus_miles")
    amenities = listing.get("amenities") or []

    if price_amount is not None and price_amount == cheapest_price:
        signals.append("lowest scraped price")
    if distance_miles is not None and distance_miles == closest_distance:
        signals.append("closest option with exact coordinates")
    if "furnished" in amenities:
        signals.append("furnished")
    if any(item in amenities for item in ("in-unit laundry", "laundry")):
        signals.append("laundry signal present")
    if listing.get("move_in_dates"):
        signals.append("move-in timing visible")
    if listing.get("photo_count", 0) >= 3:
        signals.append("multiple photos available")
    return signals[:5]


def _concerns(listing: Mapping[str, Any]) -> list[str]:
    concerns = []
    if listing.get("coordinates", {}).get("latitude") is None:
        concerns.append("exact coordinates missing")
    if listing.get("price_amount") is None:
        concerns.append("price needs confirmation")
    if not listing.get("amenities"):
        concerns.append("amenities are thin or not scraped")
    if not listing.get("photos"):
        concerns.append("no photos captured")
    if listing.get("distance_to_campus_miles") is None:
        concerns.append("campus distance not computed yet")
    return concerns[:5]


def _comparison_rows(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for listing in listings:
        rows.append(
            {
                "id": listing["id"],
                "title": listing["title"],
                "price": listing["price"],
                "price_amount": listing["price_amount"],
                "location": listing["address"] or listing["location"],
                "distance_to_campus_miles": listing["distance_to_campus_miles"],
                "move_in_dates": listing["move_in_dates"],
                "bedrooms": listing["bedrooms"],
                "top_amenities": listing["amenities"][:6],
                "photo_count": listing["photo_count"],
                "url": listing["url"],
            }
        )
    return rows


def _map_data(campus: CampusLocation, listings: list[dict[str, Any]]) -> dict[str, Any]:
    markers = []
    if campus.latitude is not None and campus.longitude is not None:
        markers.append(
            {
                "id": "campus",
                "type": "campus",
                "label": campus.label,
                "latitude": campus.latitude,
                "longitude": campus.longitude,
            }
        )

    for listing in listings:
        latitude = listing["coordinates"]["latitude"]
        longitude = listing["coordinates"]["longitude"]
        if latitude is None or longitude is None:
            continue
        markers.append(
            {
                "id": listing["id"],
                "type": "listing",
                "label": listing["title"],
                "latitude": latitude,
                "longitude": longitude,
                "price": listing["price"],
                "score": listing["score"],
                "url": listing["url"],
                "photo": listing["photos"][0] if listing["photos"] else None,
            }
        )

    coordinates = [(marker["latitude"], marker["longitude"]) for marker in markers]
    bounds = None
    if coordinates:
        bounds = {
            "south": min(lat for lat, _ in coordinates),
            "west": min(lng for _, lng in coordinates),
            "north": max(lat for lat, _ in coordinates),
            "east": max(lng for _, lng in coordinates),
        }

    return {
        "campus": {
            "label": campus.label,
            "latitude": campus.latitude,
            "longitude": campus.longitude,
        },
        "markers": markers,
        "bounds": bounds,
        "layers": ["price", "score", "distance_to_campus"],
        "routes": [],
    }


def _suggested_next_tool_calls(campus: CampusLocation, listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    missing_location_ids = [
        listing["id"]
        for listing in listings
        if listing["coordinates"]["latitude"] is None or listing["coordinates"]["longitude"] is None
    ]
    listings_with_coordinates = [
        {
            "id": listing["id"],
            "latitude": listing["coordinates"]["latitude"],
            "longitude": listing["coordinates"]["longitude"],
        }
        for listing in listings
        if listing["coordinates"]["latitude"] is not None and listing["coordinates"]["longitude"] is not None
    ]

    if campus.latitude is None or campus.longitude is None:
        calls.append(
            {
                "tool": "geocode_location",
                "reason": "Resolve the campus/search location so listing distances and commute routes can be computed.",
                "input": {"location": campus.label},
            }
        )

    if missing_location_ids:
        calls.append(
            {
                "tool": "geocode_listing_addresses",
                "reason": "Some listings lack exact coordinates, so they cannot appear on the map yet.",
                "input": {"listing_ids": missing_location_ids},
            }
        )

    if campus.latitude is not None and campus.longitude is not None and listings_with_coordinates:
        calls.append(
            {
                "tool": "directions_matrix",
                "reason": "Compute walk, bike, transit, and drive commutes from each option to campus.",
                "input": {
                    "origin_listing_locations": listings_with_coordinates,
                    "destination": {
                        "label": campus.label,
                        "latitude": campus.latitude,
                        "longitude": campus.longitude,
                    },
                    "modes": ["walking", "bicycling", "transit", "driving"],
                },
            }
        )
        calls.append(
            {
                "tool": "nearby_places",
                "reason": "Enrich neighborhood tradeoffs with gyms, groceries, parks, cafes, libraries, and transit stops.",
                "input": {
                    "listing_locations": listings_with_coordinates,
                    "categories": ["gym", "grocery", "park", "cafe", "library", "transit_stop"],
                    "radius_meters": 1200,
                },
            }
        )

    thin_amenity_ids = [listing["id"] for listing in listings if len(listing["amenities"]) < 3]
    if thin_amenity_ids:
        calls.append(
            {
                "tool": "probe_listing_amenities",
                "reason": "Amenities are sparse for some listings; fetch detail pages or listing APIs before asking the user to decide.",
                "input": {"listing_ids": thin_amenity_ids},
            }
        )

    return calls


def _fallback_follow_up_questions(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    questions = []
    prices = [listing for listing in listings if listing["price_amount"] is not None]
    distances = [listing for listing in listings if listing["distance_to_campus_miles"] is not None]
    amenities = sorted({amenity for listing in listings for amenity in listing["amenities"]})

    if prices and distances:
        cheapest = min(prices, key=lambda listing: listing["price_amount"])
        closest = min(distances, key=lambda listing: listing["distance_to_campus_miles"])
        if cheapest["id"] != closest["id"]:
            questions.append(
                {
                    "question": (
                        f"Would you rather prioritize the lower price at {cheapest['title']} "
                        f"or the shorter campus distance at {closest['title']}?"
                    ),
                    "why": "The scraped options show a price-versus-location tradeoff.",
                    "option_ids": [cheapest["id"], closest["id"]],
                }
            )

    if amenities:
        questions.append(
            {
                "question": f"Which amenities should be must-haves: {', '.join(amenities[:6])}?",
                "why": "Amenity preferences can separate otherwise similar options.",
                "option_ids": [listing["id"] for listing in listings[:5]],
            }
        )

    questions.append(
        {
            "question": "Should I narrow this to the top three, or would you rather zoom into one listing first?",
            "why": "This determines whether the next step should compare broadly or investigate one property deeply.",
            "option_ids": [listing["id"] for listing in listings[:5]],
        }
    )
    return questions[:4]


def create_housing_decision_packet(
    *,
    user_request: str,
    search_plan: Mapping[str, Any],
    records: list[dict[str, Any]],
    campus: CampusLocation,
    follow_up_questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prices = [_parse_price_amount(record.get("price")) for record in records]
    known_prices = [price for price in prices if price is not None]

    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        coordinates = _record_coordinates(record)
        amenities = _extract_amenities(record)
        photos = _normalize_string_list(record.get("image_urls") or record.get("photos"))
        price_amount = prices[index]
        distance = _haversine_miles(
            coordinates["latitude"],
            coordinates["longitude"],
            campus.latitude,
            campus.longitude,
        )
        normalized.append(
            {
                "id": _listing_id(record, index),
                "title": str(record.get("title") or f"Listing {index + 1}"),
                "price": str(record.get("price") or ""),
                "price_amount": price_amount,
                "address": str(record.get("listing_address") or ""),
                "location": str(record.get("location") or ""),
                "coordinates": coordinates,
                "move_in_dates": str(record.get("dates") or record.get("move_in_date") or ""),
                "bedrooms": str(record.get("bedrooms") or ""),
                "amenities": amenities,
                "photos": photos,
                "photo_count": len(photos),
                "url": str(record.get("detail_url") or record.get("url") or ""),
                "distance_to_campus_miles": round(distance, 2) if distance is not None else None,
                "source_record_id": record.get("id"),
            }
        )

    known_distances = [
        listing["distance_to_campus_miles"]
        for listing in normalized
        if listing["distance_to_campus_miles"] is not None
    ]
    cheapest_price = min(known_prices) if known_prices else None
    closest_distance = min(known_distances) if known_distances else None

    for listing in normalized:
        price_score = _normalize_price_score(listing["price_amount"], known_prices)
        distance_score = _normalize_distance_score(listing["distance_to_campus_miles"])
        amenity_score = min(len(listing["amenities"]), 8) / 8
        photo_score = min(listing["photo_count"], 5) / 5
        listing["score"] = round(
            price_score * 0.30 + distance_score * 0.35 + amenity_score * 0.20 + photo_score * 0.15,
            3,
        )
        listing["fit_signals"] = _fit_signals(
            listing=listing,
            cheapest_price=cheapest_price,
            closest_distance=closest_distance,
        )
        listing["concerns"] = _concerns(listing)

    ranked = sorted(normalized, key=lambda listing: listing["score"], reverse=True)
    packet = {
        "packet_type": "housing_decision_packet",
        "student_request": user_request,
        "search_plan": dict(search_plan),
        "decision_weights": {
            "price": 0.30,
            "distance_to_campus": 0.35,
            "amenities": 0.20,
            "photos": 0.15,
            "note": "Temporary default weights until the student answers the follow-up questions.",
        },
        "map_data": _map_data(campus, ranked),
        "ranked_options": ranked,
        "comparison_table": _comparison_rows(ranked),
        "missing_data": {
            "campus_coordinates_missing": campus.latitude is None or campus.longitude is None,
            "listing_ids_missing_coordinates": [
                listing["id"]
                for listing in ranked
                if listing["coordinates"]["latitude"] is None or listing["coordinates"]["longitude"] is None
            ],
            "listing_ids_with_sparse_amenities": [
                listing["id"] for listing in ranked if len(listing["amenities"]) < 3
            ],
        },
        "recommended_follow_up_questions": follow_up_questions or _fallback_follow_up_questions(ranked),
        "suggested_next_tool_calls": _suggested_next_tool_calls(campus, ranked),
    }
    return packet
