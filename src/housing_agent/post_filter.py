from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .listing_parsing import add_structured_listing_fields
from .query_planner import coerce_intent
from .types import HousingSearchIntent


HARD_CONSTRAINT_FILTERS = (
    "min_price",
    "max_price",
    "bedrooms",
    "bedroom_min",
    "bedroom_max",
    "bathrooms",
    "bathroom_min",
    "furnished",
    "pet_policy",
    "pet_policy_negated",
    "utilities_included",
    "washer_dryer",
    "wheelchair_accessible",
    "required_amenities",
    "avoid_neighborhoods",
)

VERIFICATION_FILTERS = (
    "lease_length",
    "move_in_date",
    "move_out_date",
    "campus_or_school",
    "commute_target",
    "preferred_amenities",
    "neighborhoods",
    "amenities",
    "keyword",
)

FILTER_POLICY = {
    **{name: "hard" for name in HARD_CONSTRAINT_FILTERS},
    **{name: "verification" for name in VERIFICATION_FILTERS},
}


@dataclass(frozen=True)
class PostFilterResult:
    records: list[dict[str, Any]]
    excluded_records: list[dict[str, Any]]
    exclusion_counts: dict[str, int]


def apply_post_filters(
    records: Sequence[Mapping[str, Any]],
    intent: HousingSearchIntent | Mapping[str, Any] | Any,
    filter_names: Iterable[str] | None = None,
    *,
    exclusion_source: str = "post_filter",
) -> PostFilterResult:
    housing_intent = coerce_intent(intent)
    active_filters = _normalize_filter_names(filter_names)
    if not active_filters:
        return PostFilterResult(
            records=[add_structured_listing_fields(record) for record in records],
            excluded_records=[],
            exclusion_counts={},
        )

    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for raw_record in records:
        record = add_structured_listing_fields(raw_record)
        _annotate_post_filter_notes(record, housing_intent, active_filters)
        reasons = exclusion_reasons(record, housing_intent, active_filters)
        if not reasons:
            kept.append(record)
            continue

        excluded_record = dict(record)
        excluded_record["excluded_reason"] = reasons[0]
        excluded_record["excluded_reasons"] = reasons
        excluded_record["exclusion_source"] = exclusion_source
        excluded_record["post_filter_excluded"] = True
        for reason in reasons:
            key = reason.split(":", 1)[0]
            counts[key] = counts.get(key, 0) + 1
        excluded.append(excluded_record)

    return PostFilterResult(records=kept, excluded_records=excluded, exclusion_counts=counts)


def apply_hard_constraints(
    records: Sequence[Mapping[str, Any]],
    intent: HousingSearchIntent | Mapping[str, Any] | Any,
) -> PostFilterResult:
    return apply_post_filters(
        records,
        intent,
        HARD_CONSTRAINT_FILTERS,
        exclusion_source="hard_constraint",
    )


def exclusion_reasons(
    record: Mapping[str, Any],
    intent: HousingSearchIntent,
    filter_names: Iterable[str],
) -> list[str]:
    names = set(_normalize_filter_names(filter_names)) & set(HARD_CONSTRAINT_FILTERS)
    reasons: list[str] = []

    if "max_price" in names and intent.max_price is not None:
        price_min = _number(record.get("price_min_int"))
        if price_min is not None and price_min > intent.max_price:
            reasons.append(f"max_price: listing starts at ${price_min:,}, above max ${intent.max_price:,}")

    if "min_price" in names and intent.min_price is not None:
        price_max = _number(record.get("price_max_int"))
        if price_max is not None and price_max < intent.min_price:
            reasons.append(f"min_price: listing tops out at ${price_max:,}, below min ${intent.min_price:,}")

    if "bedrooms" in names and intent.bedrooms is not None and not _skip_hard_bedroom_filter(record):
        if not _range_contains(
            _number(record.get("bedroom_min_count")),
            _number(record.get("bedroom_max_count")),
            float(intent.bedrooms),
        ):
            reasons.append(f"bedrooms: listing does not appear to include {intent.bedrooms} bedroom(s)")

    if "bedroom_min" in names and intent.bedroom_min is not None and not _skip_hard_bedroom_filter(record):
        max_count = _number(record.get("bedroom_max_count"))
        if max_count is not None and max_count < intent.bedroom_min:
            reasons.append(f"bedroom_min: listing appears below {intent.bedroom_min} bedroom(s)")

    if "bedroom_max" in names and intent.bedroom_max is not None and not _skip_hard_bedroom_filter(record):
        min_count = _number(record.get("bedroom_min_count"))
        if min_count is not None and min_count > intent.bedroom_max:
            reasons.append(f"bedroom_max: listing appears above {intent.bedroom_max} bedroom(s)")

    if "bathrooms" in names and intent.bathrooms is not None:
        if not _range_contains(
            _number(record.get("bathroom_min_count")),
            _number(record.get("bathroom_max_count")),
            float(intent.bathrooms),
        ):
            reasons.append(f"bathrooms: listing does not appear to include {intent.bathrooms:g} bathroom(s)")

    if "bathroom_min" in names and intent.bathroom_min is not None:
        max_count = _number(record.get("bathroom_max_count"))
        if max_count is not None and max_count < intent.bathroom_min:
            reasons.append(f"bathroom_min: listing appears below {intent.bathroom_min:g} bathroom(s)")

    text = record_text(record)

    if "furnished" in names and intent.furnished is not None:
        if intent.furnished and _mentions_unfurnished(text):
            reasons.append("furnished: listing explicitly says unfurnished")
        elif intent.furnished is False and _mentions_furnished(text):
            reasons.append("furnished: listing explicitly says furnished")

    if "pet_policy" in names and intent.pet_policy:
        if _wants_pet_friendly(intent.pet_policy) and _mentions_no_pets(text):
            reasons.append("pet_policy: listing explicitly says pets are not allowed")

    if "pet_policy_negated" in names and intent.pet_policy_negated:
        if _mentions_pets_allowed(text):
            reasons.append("pet_policy_negated: listing explicitly allows pets")

    if "utilities_included" in names and intent.utilities_included:
        if text and not _contains_any(text, ("utilities included", "utility included", "all utilities", "heat included")):
            reasons.append("utilities_included: utilities included was not found in listing text")

    if "washer_dryer" in names and intent.washer_dryer:
        if text and not _contains_any(text, ("washer", "dryer", "w/d", "laundry")):
            reasons.append("washer_dryer: washer/dryer or laundry was not found in listing text")

    if "wheelchair_accessible" in names and intent.wheelchair_accessible:
        if text and not _contains_any(text, ("wheelchair", "accessible", "ada", "mobility")):
            reasons.append("wheelchair_accessible: accessibility was not found in listing text")

    required_terms = _required_terms(intent, names)
    for term in required_terms:
        if term.lower() not in text:
            reasons.append(f"required_amenities: {term!r} was not found in listing text")

    for neighborhood in intent.avoid_neighborhoods if "avoid_neighborhoods" in names else ():
        if neighborhood.strip() and neighborhood.strip().lower() in text:
            reasons.append(f"avoid_neighborhoods: listing mentions avoided area {neighborhood!r}")

    return reasons


def _annotate_post_filter_notes(record: dict[str, Any], intent: HousingSearchIntent, filter_names: Sequence[str]) -> None:
    notes = list(record.get("post_filter_notes") or [])
    text = record_text(record)
    names = set(_normalize_filter_names(filter_names))

    if "lease_length" in names and intent.lease_length:
        lease_length = intent.lease_length.strip().lower()
        if lease_length and lease_length not in text:
            notes.append(f"Lease length needs verification: {intent.lease_length}.")

    if "move_in_date" in names and intent.move_in_date and not record.get("available_from_iso"):
        notes.append(f"Move-in date needs verification: {intent.move_in_date}.")

    if "move_out_date" in names and intent.move_out_date and not record.get("available_to_iso"):
        notes.append(f"Move-out date needs verification: {intent.move_out_date}.")

    if "campus_or_school" in names and intent.campus_or_school:
        school = intent.campus_or_school.strip()
        if school and school.lower() not in text:
            notes.append(f"Campus proximity needs verification: {school}.")

    if "commute_target" in names and intent.commute_target:
        if record.get("coordinates_status") == "present":
            notes.append(f"Coordinates are present; commute to {intent.commute_target} still needs route-time verification.")
        else:
            notes.append(f"Coordinates missing; could not verify commute to {intent.commute_target}.")

    if "neighborhoods" in names and intent.neighborhoods:
        missing = [value for value in intent.neighborhoods if value.strip() and value.strip().lower() not in text]
        if missing:
            notes.append(f"Neighborhood preference needs verification: {', '.join(missing)}.")

    if "preferred_amenities" in names and intent.preferred_amenities:
        missing = [value for value in intent.preferred_amenities if value.strip() and value.strip().lower() not in text]
        if missing:
            notes.append(f"Preferred amenities need verification: {', '.join(missing)}.")

    if "amenities" in names and intent.amenities:
        missing = [value for value in intent.amenities if value.strip() and value.strip().lower() not in text]
        if missing:
            notes.append(f"Amenities need verification: {', '.join(missing)}.")

    if "keyword" in names and intent.keyword:
        keyword = intent.keyword.strip()
        if keyword and keyword.lower() not in text:
            notes.append(f"Keyword needs verification: {keyword}.")

    if _skip_hard_bedroom_filter(record):
        bedroom_need = _bedroom_need_text(intent, names)
        if bedroom_need:
            notes.append(
                f"Bedroom count needs verification for Ohana sublet listing: {bedroom_need}."
            )

    if notes:
        unique_notes = list(dict.fromkeys(str(note).strip() for note in notes if str(note).strip()))
        record["post_filter_notes"] = unique_notes
        record["verification_notes"] = unique_notes


def record_text(record: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "title",
        "name",
        "address",
        "listing_address",
        "location",
        "property_type",
        "availability",
        "price",
        "bedrooms",
        "bathrooms",
        "description",
        "raw_text",
    ):
        value = record.get(key)
        if value:
            values.append(str(value))
    for key in ("amenities", "image_alt_text"):
        value = record.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            values.extend(str(item) for item in value if item)
    return re.sub(r"\s+", " ", " ".join(values)).strip().lower()


def _normalize_filter_names(filter_names: Iterable[str] | None) -> tuple[str, ...]:
    if filter_names is None:
        return ()
    aliases = {
        "num_bedrooms": "bedrooms",
        "num_bathrooms": "bathrooms",
        "furnished_status": "furnished",
        "pets": "pet_policy",
        "pet_friendly": "pet_policy",
        "neighborhoods": "neighborhoods",
        "campus": "campus_or_school",
    }
    normalized: list[str] = []
    for name in filter_names:
        key = aliases.get(str(name), str(name))
        if key not in normalized:
            normalized.append(key)
    return tuple(normalized)


def _skip_hard_bedroom_filter(record: Mapping[str, Any]) -> bool:
    provider = str(record.get("provider") or record.get("source") or "").strip().lower()
    return provider == "ohana"


def _bedroom_need_text(intent: HousingSearchIntent, names: set[str]) -> str:
    if "bedrooms" in names and intent.bedrooms is not None:
        return f"{intent.bedrooms} bedroom(s)"
    if (
        "bedroom_min" in names
        and "bedroom_max" in names
        and intent.bedroom_min is not None
        and intent.bedroom_max is not None
    ):
        return f"{intent.bedroom_min}-{intent.bedroom_max} bedroom(s)"
    if "bedroom_min" in names and intent.bedroom_min is not None:
        return f"at least {intent.bedroom_min} bedroom(s)"
    if "bedroom_max" in names and intent.bedroom_max is not None:
        return f"at most {intent.bedroom_max} bedroom(s)"
    return ""


def _required_terms(intent: HousingSearchIntent, names: set[str]) -> tuple[str, ...]:
    terms: list[str] = []
    if "required_amenities" in names:
        terms.extend(intent.required_amenities)
        terms.extend(intent.amenities)
    return tuple(dict.fromkeys(term for term in terms if str(term).strip()))


def _range_contains(min_value: float | None, max_value: float | None, target: float) -> bool:
    if min_value is None and max_value is None:
        return True
    if min_value is not None and max_value is not None:
        return min_value <= target <= max_value
    if min_value is not None:
        return min_value <= target
    return bool(max_value is not None and target <= max_value)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mentions_unfurnished(text: str) -> bool:
    return "unfurnished" in text or "not furnished" in text


def _mentions_furnished(text: str) -> bool:
    return "furnished" in text and not _mentions_unfurnished(text)


def _wants_pet_friendly(values: Sequence[str]) -> bool:
    text = " ".join(values).lower()
    return bool(text) and not _mentions_no_pets(text)


def _mentions_no_pets(text: str) -> bool:
    return _contains_any(text, ("no pets", "pets prohibited", "not pet friendly", "no dogs", "no cats"))


def _mentions_pets_allowed(text: str) -> bool:
    return _contains_any(text, ("pet friendly", "pets allowed", "dogs allowed", "cats allowed", "allows pets"))


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle in text for needle in needles)


__all__ = [
    "HARD_CONSTRAINT_FILTERS",
    "FILTER_POLICY",
    "PostFilterResult",
    "VERIFICATION_FILTERS",
    "apply_hard_constraints",
    "apply_post_filters",
    "exclusion_reasons",
    "record_text",
]
