from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Mapping


PRICE_RE = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d{3,6}|0)(?!\s*(?:sq|sf|ft|bed|beds|bath|baths)\b)", re.I)
BEDROOM_RE = re.compile(
    r"\b(?:(studio)|(\d+(?:\.\d+)?)(?:\s*(?:-|to)\s*(\d+(?:\.\d+)?))?\s*(?:br|bed|beds|bedroom|bedrooms))\b",
    re.I,
)
BATHROOM_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)(?:\s*(?:-|to)\s*(\d+(?:\.\d+)?))?\s*(?:bath|baths|bathroom|bathrooms)\b",
    re.I,
)
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
SLASH_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
MONTH_DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b",
    re.I,
)

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def add_structured_listing_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of a listing record with comparable numeric/date fields."""
    enriched = dict(record)

    price_min, price_max = price_range_from_record(enriched)
    enriched["price_min_int"] = price_min
    enriched["price_max_int"] = price_max

    bedroom_min, bedroom_max = count_range_from_record(
        enriched,
        field_names=("bedrooms", "bedroom_count", "beds"),
        kind="bedroom",
    )
    enriched["bedroom_min_count"] = bedroom_min
    enriched["bedroom_max_count"] = bedroom_max
    enriched["bedroom_count"] = bedroom_min if bedroom_min == bedroom_max else None

    bathroom_min, bathroom_max = count_range_from_record(
        enriched,
        field_names=("bathrooms", "bathroom_count", "baths"),
        kind="bathroom",
    )
    enriched["bathroom_min_count"] = bathroom_min
    enriched["bathroom_max_count"] = bathroom_max
    enriched["bathroom_count"] = bathroom_min if bathroom_min == bathroom_max else None

    available_from, available_to = date_range_from_record(enriched)
    enriched["available_from_iso"] = available_from
    enriched["available_to_iso"] = available_to
    return enriched


def price_range_from_record(record: Mapping[str, Any]) -> tuple[int | None, int | None]:
    explicit_min = _optional_int(_first_present(record, ("price_min_int", "price_min")))
    explicit_max = _optional_int(_first_present(record, ("price_max_int", "price_max")))
    if explicit_min is not None or explicit_max is not None:
        return explicit_min, explicit_max if explicit_max is not None else explicit_min

    values = [
        record.get("price"),
        record.get("rent"),
        record.get("monthly_rent"),
        record.get("raw_text"),
    ]
    prices = parse_price_values(" ".join(str(value) for value in values if value))
    if not prices:
        return None, None
    return min(prices), max(prices)


def _first_present(record: Mapping[str, Any], field_names: tuple[str, ...]) -> Any:
    for field_name in field_names:
        value = record.get(field_name)
        if value is not None and value != "":
            return value
    return None


def parse_price_values(text: str) -> tuple[int, ...]:
    values: list[int] = []
    for match in PRICE_RE.finditer(text or ""):
        value = _optional_int(match.group(1))
        if value is not None:
            values.append(value)
    return tuple(values)


def count_range_from_record(
    record: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    kind: str,
) -> tuple[float | None, float | None]:
    for field_name in field_names:
        direct = _optional_float(record.get(field_name))
        if direct is not None:
            return direct, direct

    values = [record.get(field_name) for field_name in field_names]
    values.append(record.get("raw_text"))
    text = " ".join(str(value) for value in values if value)
    return parse_count_range(text, kind=kind)


def parse_count_range(text: str, *, kind: str) -> tuple[float | None, float | None]:
    if not text:
        return None, None

    if kind == "bedroom":
        studio_range = re.search(r"\bstud(?:io)?\s*-\s*(\d+(?:\.\d+)?)\s*(?:br|bed|beds|bedroom|bedrooms)\b", text, re.I)
        if studio_range:
            return 0.0, _optional_float(studio_range.group(1))
        match = _best_bedroom_match(text)
        if not match:
            return None, None
        if match.group(1):
            min_value = 0.0
            max_value = _optional_float(match.group(3)) if match.group(3) else 0.0
        else:
            min_value = _optional_float(match.group(2))
            max_value = _optional_float(match.group(3)) if match.group(3) else min_value
    else:
        match = BATHROOM_RE.search(text)
        if not match:
            return None, None
        min_value = _optional_float(match.group(1))
        max_value = _optional_float(match.group(2)) if match.group(2) else min_value

    return min_value, max_value


def date_range_from_record(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    explicit_from = _optional_iso(record.get("available_from_iso") or record.get("available_from"))
    explicit_to = _optional_iso(record.get("available_to_iso") or record.get("available_to"))
    if explicit_from or explicit_to:
        return explicit_from, explicit_to

    text = " ".join(
        str(value)
        for value in (
            record.get("availability"),
            record.get("available"),
            record.get("dates"),
            record.get("raw_text"),
        )
        if value
    )
    dates = parse_dates(text)
    if not dates:
        return None, None
    return dates[0], dates[-1]


def parse_dates(text: str, *, default_year: int | None = None) -> tuple[str, ...]:
    year = default_year or date.today().year
    values: list[str] = []

    for match in ISO_DATE_RE.finditer(text or ""):
        values.append(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")

    for match in SLASH_DATE_RE.finditer(text or ""):
        month, day, year_text = match.groups()
        values.append(_date_to_iso(int(year_text), int(month), int(day)))

    for match in MONTH_DATE_RE.finditer(text or ""):
        month_text, day, year_text = match.groups()
        month = MONTHS.get(month_text[:4].lower()) or MONTHS.get(month_text[:3].lower())
        if month is None:
            continue
        values.append(_date_to_iso(int(year_text or year), month, int(day)))

    return tuple(dict.fromkeys(value for value in values if value))


def _best_bedroom_match(text: str) -> re.Match[str] | None:
    matches = list(BEDROOM_RE.finditer(text))
    if not matches:
        return None
    for match in matches:
        sample = match.group(0).lower()
        if "bed" in sample or "br" in sample or "studio" in sample:
            return match
    return matches[0]


def _date_to_iso(year: int, month: int, day: int) -> str:
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return ""


def _optional_iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    match = ISO_DATE_RE.fullmatch(text)
    return text if match else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).replace("$", "").replace(",", "").strip()
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in {"studio", "stud"}:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


__all__ = [
    "add_structured_listing_fields",
    "count_range_from_record",
    "date_range_from_record",
    "parse_count_range",
    "parse_dates",
    "parse_price_values",
    "price_range_from_record",
]
