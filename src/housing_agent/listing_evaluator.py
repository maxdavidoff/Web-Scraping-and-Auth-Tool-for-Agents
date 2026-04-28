from __future__ import annotations

import html
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.ohana_agent.config import PROCESSED_DIR, ensure_dirs

from .types import HousingSearchIntent


CAMPUS_COORDS = {
    "upenn": (39.9522, -75.1932),
    "penn": (39.9522, -75.1932),
    "university of pennsylvania": (39.9522, -75.1932),
    "northeastern": (42.3398, -71.0892),
    "northeastern university": (42.3398, -71.0892),
    "nyu": (40.7295, -73.9965),
    "new york university": (40.7295, -73.9965),
    "mit": (42.3601, -71.0942),
    "massachusetts institute of technology": (42.3601, -71.0942),
    "harvard": (42.3770, -71.1167),
    "harvard university": (42.3770, -71.1167),
    "boston university": (42.3505, -71.1054),
    "bu": (42.3505, -71.1054),
    "columbia": (40.8075, -73.9626),
    "columbia university": (40.8075, -73.9626),
}


@dataclass(frozen=True)
class ListingMetrics:
    price: float
    location: float
    timing: float
    housing_type: float
    requirements: float
    confidence: float
    overall: float


@dataclass(frozen=True)
class EvaluatedListing:
    index: int
    listing_id: str
    title: str
    url: str
    provider: str
    price_text: str = ""
    price_amount: int | None = None
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    distance_to_target_miles: float | None = None
    metrics: ListingMetrics = field(default_factory=lambda: ListingMetrics(0, 0, 0, 0, 0, 0, 0))
    matched: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    concerns: tuple[str, ...] = ()
    status: str = "candidate"
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ListingDecisionSet:
    listings: tuple[EvaluatedListing, ...]
    target_label: str = ""
    target_latitude: float | None = None
    target_longitude: float | None = None
    map_path: Path | None = None
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.map_path is not None:
            data["map_path"] = str(self.map_path)
        return data


def evaluate_listings(
    intent: HousingSearchIntent,
    records: Sequence[Mapping[str, Any]],
    *,
    create_map: bool = True,
    output_dir: Path = PROCESSED_DIR,
) -> ListingDecisionSet:
    target_label, target = _target_for_intent(intent)
    listings = tuple(
        sorted(
            (
                _evaluate_listing(index, intent, record, target)
                for index, record in enumerate(records, start=1)
            ),
            key=lambda item: (-item.metrics.overall, item.index),
        )
    )
    listings = tuple(_renumber(listings))
    map_path = _write_map(listings, target_label, target, output_dir) if create_map else None
    return ListingDecisionSet(
        listings=listings,
        target_label=target_label,
        target_latitude=target[0] if target else None,
        target_longitude=target[1] if target else None,
        map_path=map_path,
        summary=_summary(listings),
    )


def sort_listings(listings: Sequence[EvaluatedListing], key: str) -> tuple[EvaluatedListing, ...]:
    if key == "price":
        sorted_items = sorted(
            listings,
            key=lambda item: (
                item.price_amount is None,
                item.price_amount if item.price_amount is not None else 10**9,
                -item.metrics.overall,
            ),
        )
    elif key == "location":
        sorted_items = sorted(
            listings,
            key=lambda item: (
                item.distance_to_target_miles is None,
                item.distance_to_target_miles if item.distance_to_target_miles is not None else 10**9,
                -item.metrics.overall,
            ),
        )
    else:
        sorted_items = sorted(listings, key=lambda item: (-item.metrics.overall, item.index))
    return tuple(_renumber(sorted_items))


def filter_under_price(listings: Sequence[EvaluatedListing], max_price: int) -> tuple[EvaluatedListing, ...]:
    return tuple(
        _renumber(
            item
            for item in listings
            if item.price_amount is not None and item.price_amount <= max_price
        )
    )


def hide_missing_address(listings: Sequence[EvaluatedListing]) -> tuple[EvaluatedListing, ...]:
    return tuple(_renumber(item for item in listings if item.address))


def compare_listings(listings: Sequence[EvaluatedListing], indexes: Sequence[int]) -> str:
    selected = [item for item in listings if item.index in set(indexes)]
    if not selected:
        return "No matching listings to compare."

    lines = ["Comparison", ""]
    for item in selected:
        lines.extend(_listing_detail_lines(item))
        lines.append("")
    return "\n".join(lines).strip()


def listing_explanation(listings: Sequence[EvaluatedListing], index: int) -> str:
    for item in listings:
        if item.index == index:
            return "\n".join(_listing_detail_lines(item))
    return f"No listing #{index} is available in the current results."


def _evaluate_listing(
    index: int,
    intent: HousingSearchIntent,
    record: Mapping[str, Any],
    target: tuple[float, float] | None,
) -> EvaluatedListing:
    title = _first_text(record, "title", "name") or "Untitled listing"
    url = _first_text(record, "listing_url", "url", "detail_url")
    provider = _first_text(record, "provider", "source")
    price_text = _first_text(record, "price", "rent")
    price_amount = _price_amount(record, price_text)
    address = _first_text(record, "address", "listing_address", "location")
    latitude = _float_value(_first_text(record, "listing_latitude", "latitude", "lat"))
    longitude = _float_value(_first_text(record, "listing_longitude", "longitude", "lon", "lng"))
    distance = _distance_miles((latitude, longitude), target) if latitude is not None and longitude is not None else None

    matched: list[str] = []
    missing: list[str] = []
    concerns: list[str] = []

    price_score = _price_score(price_amount, intent, matched, missing, concerns)
    location_score = _location_score(address, distance, intent, matched, missing)
    timing_score = _timing_score(record, intent, matched, missing)
    housing_score = _housing_type_score(record, intent, matched, missing, concerns)
    requirements_score = _requirements_score(record, intent, matched, missing, concerns)
    confidence_score = max(0, 100 - 12 * len(missing) - 18 * len(concerns))
    overall = (
        price_score * 0.30
        + location_score * 0.25
        + housing_score * 0.20
        + timing_score * 0.10
        + requirements_score * 0.10
        + confidence_score * 0.05
    )
    if _hard_budget_failure(price_amount, intent):
        overall = min(overall, 35)
    status = "excluded" if _hard_budget_failure(price_amount, intent) else ("needs_verification" if missing else "candidate")

    return EvaluatedListing(
        index=index,
        listing_id=_first_text(record, "listing_id", "id") or str(index),
        title=title,
        url=url,
        provider=provider,
        price_text=price_text,
        price_amount=price_amount,
        address=address,
        latitude=latitude,
        longitude=longitude,
        distance_to_target_miles=distance,
        metrics=ListingMetrics(
            price=round(price_score, 1),
            location=round(location_score, 1),
            timing=round(timing_score, 1),
            housing_type=round(housing_score, 1),
            requirements=round(requirements_score, 1),
            confidence=round(confidence_score, 1),
            overall=round(overall, 1),
        ),
        matched=tuple(_unique(matched)),
        missing=tuple(_unique(missing)),
        concerns=tuple(_unique(concerns)),
        status=status,
        raw=dict(record),
    )


def _price_score(
    price_amount: int | None,
    intent: HousingSearchIntent,
    matched: list[str],
    missing: list[str],
    concerns: list[str],
) -> float:
    if price_amount is None:
        missing.append("price")
        return 50
    if intent.max_price is None:
        matched.append("price visible")
        return 75
    if price_amount <= intent.max_price:
        matched.append("within budget")
        return 100
    concerns.append(f"over budget by ${price_amount - intent.max_price:,}")
    over_ratio = (price_amount - intent.max_price) / max(intent.max_price, 1)
    return max(0, 60 - over_ratio * 100)


def _location_score(
    address: str,
    distance: float | None,
    intent: HousingSearchIntent,
    matched: list[str],
    missing: list[str],
) -> float:
    if distance is not None:
        matched.append(f"{distance:.1f} mi from target")
        return max(35, 100 - distance * 12)
    if address and intent.location and intent.location.split(",")[0].lower() in address.lower():
        matched.append("city appears in address")
        return 75
    if address:
        matched.append("address present")
        return 65
    missing.append("address or coordinates")
    return 45


def _timing_score(
    record: Mapping[str, Any],
    intent: HousingSearchIntent,
    matched: list[str],
    missing: list[str],
) -> float:
    availability = _first_text(record, "availability", "available", "available_date")
    if not intent.move_in_date and not intent.move_out_date:
        return 75 if availability else 65
    if availability:
        matched.append("availability visible")
        return 70
    missing.append("availability")
    return 45


def _housing_type_score(
    record: Mapping[str, Any],
    intent: HousingSearchIntent,
    matched: list[str],
    missing: list[str],
    concerns: list[str],
) -> float:
    text = _record_text(record)
    if intent.type_of_places:
        if any(place.lower() in text for place in intent.type_of_places):
            matched.append("matches room/place type")
            return 100
        missing.append("room/place type")
        return 55
    if intent.property_types:
        if any(prop.lower() in text for prop in intent.property_types):
            matched.append("matches property type")
            return 100
        concerns.append("property type not confirmed")
        return 60
    if intent.roommate_count is not None and intent.roommate_count >= 2:
        if any(term in text for term in ("apartment", "house", "townhouse", "condo")):
            matched.append("full-rental candidate")
            return 85
    return 70


def _requirements_score(
    record: Mapping[str, Any],
    intent: HousingSearchIntent,
    matched: list[str],
    missing: list[str],
    concerns: list[str],
) -> float:
    score = 80
    text = _record_text(record)
    if intent.furnished is True:
        if "furnished" in text:
            matched.append("furnished")
            score += 15
        else:
            missing.append("furnished status")
            score -= 20
    for amenity in (*intent.required_amenities, *intent.amenities):
        if amenity.lower() in text:
            matched.append(amenity)
        else:
            missing.append(amenity)
            score -= 8
    for dealbreaker in intent.dealbreakers:
        if dealbreaker.lower() in text:
            concerns.append(f"mentions {dealbreaker}")
            score -= 25
    return max(0, min(100, score))


def _target_for_intent(intent: HousingSearchIntent) -> tuple[str, tuple[float, float] | None]:
    for value in (intent.campus_or_school, intent.commute_target):
        if not value:
            continue
        key = _clean_key(value)
        if key in CAMPUS_COORDS:
            return value, CAMPUS_COORDS[key]
    return (intent.campus_or_school or intent.commute_target or intent.location or ""), None


def _write_map(
    listings: Sequence[EvaluatedListing],
    target_label: str,
    target: tuple[float, float] | None,
    output_dir: Path,
) -> Path | None:
    mappable = [item for item in listings if item.latitude is not None and item.longitude is not None]
    if not mappable:
        return None

    ensure_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"listing_map_{timestamp}.html"
    markers = [
        {
            "index": item.index,
            "title": item.title,
            "price": item.price_text,
            "score": item.metrics.overall,
            "lat": item.latitude,
            "lon": item.longitude,
            "provider": item.provider,
            "url": item.url,
        }
        for item in mappable
    ]
    target_obj = {"label": target_label, "lat": target[0], "lon": target[1]} if target else None
    path.write_text(_map_html(markers, target_obj), encoding="utf-8")
    return path


def _map_html(markers: list[dict[str, Any]], target: dict[str, Any] | None) -> str:
    points = list(markers)
    if target:
        points.append({"lat": target["lat"], "lon": target["lon"]})
    min_lat = min(float(point["lat"]) for point in points)
    max_lat = max(float(point["lat"]) for point in points)
    min_lon = min(float(point["lon"]) for point in points)
    max_lon = max(float(point["lon"]) for point in points)
    lat_span = max(max_lat - min_lat, 0.01)
    lon_span = max(max_lon - min_lon, 0.01)

    def position(lat: float, lon: float) -> tuple[float, float]:
        x = 6 + ((lon - min_lon) / lon_span) * 88
        y = 94 - ((lat - min_lat) / lat_span) * 88
        return x, y

    marker_html = []
    if target:
        x, y = position(float(target["lat"]), float(target["lon"]))
        marker_html.append(
            f'<div class="marker target" style="left:{x:.2f}%;top:{y:.2f}%;" title="{html.escape(str(target["label"]))}">T</div>'
        )
    for marker in markers:
        x, y = position(float(marker["lat"]), float(marker["lon"]))
        title = html.escape(f'#{marker["index"]} {marker["title"]} {marker["price"]}')
        marker_html.append(
            f'<a class="marker listing" style="left:{x:.2f}%;top:{y:.2f}%;" title="{title}" href="{html.escape(str(marker["url"]))}">{marker["index"]}</a>'
        )
    rows = "\n".join(
        "<tr>"
        f"<td>{marker['index']}</td>"
        f"<td>{html.escape(str(marker['title']))}</td>"
        f"<td>{html.escape(str(marker['price']))}</td>"
        f"<td>{html.escape(str(marker['provider']))}</td>"
        f"<td>{marker['score']:.1f}</td>"
        "</tr>"
        for marker in markers
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Housing Listing Map</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #172026; }}
    .map {{ position: relative; height: 520px; border: 1px solid #b7c1c9; background: #eef3f4; overflow: hidden; }}
    .map:before {{ content: ""; position: absolute; inset: 0; background-image: linear-gradient(#d8e0e4 1px, transparent 1px), linear-gradient(90deg, #d8e0e4 1px, transparent 1px); background-size: 48px 48px; }}
    .marker {{ position: absolute; transform: translate(-50%, -50%); width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; text-decoration: none; }}
    .listing {{ background: #1f7a8c; color: white; }}
    .target {{ background: #d1495b; color: white; z-index: 2; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
    th, td {{ border-bottom: 1px solid #d7dee2; padding: 8px; text-align: left; }}
  </style>
</head>
<body>
  <h1>Housing Listing Map</h1>
  <p>Relative visualization from listing coordinates. It is not a street map; verify exact addresses before deciding.</p>
  <div class="map">{''.join(marker_html)}</div>
  <table>
    <thead><tr><th>#</th><th>Listing</th><th>Price</th><th>Provider</th><th>Score</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""


def _listing_detail_lines(item: EvaluatedListing) -> list[str]:
    distance = (
        f"{item.distance_to_target_miles:.1f} mi from target"
        if item.distance_to_target_miles is not None
        else "location needs verification"
    )
    lines = [
        f"#{item.index} {item.title} - {item.metrics.overall:g}/100",
        f"Price: {item.price_text or 'unknown'} | Provider: {item.provider or 'unknown'} | {distance}",
        (
            f"Scores: price {item.metrics.price:g}, location {item.metrics.location:g}, "
            f"type {item.metrics.housing_type:g}, timing {item.metrics.timing:g}, "
            f"requirements {item.metrics.requirements:g}, confidence {item.metrics.confidence:g}"
        ),
    ]
    if item.matched:
        lines.append("Matches: " + ", ".join(item.matched[:5]))
    if item.missing:
        lines.append("Missing: " + ", ".join(item.missing[:5]))
    if item.concerns:
        lines.append("Concerns: " + ", ".join(item.concerns[:5]))
    if item.url:
        lines.append(f"URL: {item.url}")
    return lines


def _summary(listings: Sequence[EvaluatedListing]) -> str:
    if not listings:
        return "No listings were available for decision scoring."
    candidates = sum(1 for item in listings if item.status == "candidate")
    needs_verification = sum(1 for item in listings if item.status == "needs_verification")
    excluded = sum(1 for item in listings if item.status == "excluded")
    return (
        f"Scored {len(listings)} listing(s): {candidates} candidate(s), "
        f"{needs_verification} needing verification, {excluded} excluded by hard constraints."
    )


def _renumber(listings: Sequence[EvaluatedListing]) -> tuple[EvaluatedListing, ...]:
    return tuple(
        EvaluatedListing(
            **{
                **asdict(item),
                "index": index,
                "metrics": item.metrics,
                "raw": item.raw,
            }
        )
        for index, item in enumerate(listings, start=1)
    )


def _price_amount(record: Mapping[str, Any], price_text: str) -> int | None:
    for key in ("price_min", "price_amount", "rent_amount"):
        value = record.get(key)
        number = _int_value(value)
        if number is not None:
            return number
    numbers = [
        int(match.replace(",", ""))
        for match in re.findall(r"\$?\s*([0-9][0-9,]{2,})", price_text or "")
    ]
    return min(numbers) if numbers else None


def _first_text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _record_text(record: Mapping[str, Any]) -> str:
    return " ".join(str(value) for value in record.values() if value is not None).lower()


def _float_value(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(str(value).replace(",", "").replace("$", "")))
    except (TypeError, ValueError):
        return None


def _distance_miles(
    point: tuple[float | None, float | None],
    target: tuple[float, float] | None,
) -> float | None:
    if target is None or point[0] is None or point[1] is None:
        return None
    lat1, lon1 = math.radians(point[0]), math.radians(point[1])
    lat2, lon2 = math.radians(target[0]), math.radians(target[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(hav))


def _hard_budget_failure(price_amount: int | None, intent: HousingSearchIntent) -> bool:
    return price_amount is not None and intent.max_price is not None and price_amount > intent.max_price


def _clean_key(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)
