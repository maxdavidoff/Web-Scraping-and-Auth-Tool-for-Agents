from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from .provider_capabilities import AFFORDABLEHOUSING, OHANA, RENTALSOURCE, capability_matrix, get_provider_capabilities
from .types import (
    FilterApplicationReport,
    FilterCapability,
    HousingSearchIntent,
    ProviderCapabilities,
    ProviderQueryPlan,
    QueryPlan,
    SupportCategory,
)


SOURCE_SCORE = 3.0
POST_FILTER_SCORE = 1.0
UNKNOWN_SCORE = -0.5
UNSUPPORTED_SCORE = -2.0


def plan_query(
    intent: HousingSearchIntent | Mapping[str, Any] | Any,
    *,
    providers: Iterable[str] | None = None,
) -> QueryPlan:
    housing_intent = coerce_intent(intent)
    matrix = capability_matrix()
    selected_capabilities = (
        tuple(get_provider_capabilities(provider) for provider in providers)
        if providers is not None
        else tuple(matrix.values())
    )
    provider_plans = tuple(
        sorted(
            (
                plan_provider_query(housing_intent, provider_capabilities)
                for provider_capabilities in selected_capabilities
            ),
            key=lambda plan: (-plan.score, plan.provider),
        )
    )
    return QueryPlan(intent=housing_intent, provider_plans=provider_plans)


def plan_provider_query(intent: HousingSearchIntent, capabilities: ProviderCapabilities) -> ProviderQueryPlan:
    requested = requested_filters(intent)
    report = classify_filters(intent, capabilities)
    score, reasons, warnings = score_provider_query(intent, capabilities, report)

    if not requested:
        quality = "no_filters"
    elif score >= 11:
        quality = "strong"
    elif score >= 5:
        quality = "usable"
    elif score >= 0:
        quality = "weak"
    else:
        quality = "poor"

    return ProviderQueryPlan(
        provider=capabilities.provider,
        score=score,
        quality=quality,
        implemented=capabilities.implemented,
        requires_login=capabilities.requires_login,
        experimental=capabilities.experimental,
        report=report,
        reasons=reasons,
        warnings=warnings,
    )


def classify_filters(intent: HousingSearchIntent, capabilities: ProviderCapabilities) -> FilterApplicationReport:
    requested = requested_filters(intent)
    applied_at_source: dict[str, Any] = {}
    post_filters: dict[str, Any] = {}
    unsupported: dict[str, Any] = {}
    unknown_unverified: dict[str, Any] = {}
    capability_by_filter: dict[str, FilterCapability] = {}
    warnings: list[str] = []

    for filter_name, value in requested.items():
        capability = capabilities.capability_for(filter_name)
        capability_by_filter[filter_name] = capability

        if capability.warning:
            warnings.append(f"{filter_name}: {capability.warning}")

        if capability.is_verified_source_filter:
            applied_at_source[filter_name] = value
        elif capability.category == SupportCategory.POST_FILTER or capability.post_filter_possible:
            post_filters[filter_name] = value
        elif capability.category == SupportCategory.UNSUPPORTED:
            unsupported[filter_name] = value
        else:
            unknown_unverified[filter_name] = value

    if not capabilities.implemented:
        warnings.append(f"{capabilities.provider}: provider scraper is not implemented.")
    if capabilities.experimental:
        warnings.append(f"{capabilities.provider}: provider capability research is experimental.")

    return FilterApplicationReport(
        provider=capabilities.provider,
        applied_at_source=applied_at_source,
        post_filters=post_filters,
        unsupported=unsupported,
        unknown_unverified=unknown_unverified,
        capabilities=capability_by_filter,
        warnings=tuple(warnings),
    )


def score_provider_query(
    intent: HousingSearchIntent,
    capabilities: ProviderCapabilities,
    report: FilterApplicationReport,
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    score = 0.0
    reasons: list[str] = []
    warnings = list(report.warnings)

    applied_count = len(report.applied_at_source)
    post_count = len(report.post_filters)
    unknown_count = len(report.unknown_unverified)
    unsupported_count = len(report.unsupported)

    if applied_count:
        contribution = applied_count * SOURCE_SCORE
        score += contribution
        reasons.append(f"{applied_count} verified source filter(s) (+{contribution:g})")
    if post_count:
        contribution = post_count * POST_FILTER_SCORE
        score += contribution
        reasons.append(f"{post_count} post-filterable criterion/criteria (+{contribution:g})")
    if unknown_count:
        contribution = unknown_count * UNKNOWN_SCORE
        score += contribution
        reasons.append(f"{unknown_count} unknown or unverified criterion/criteria ({contribution:g})")
    if unsupported_count:
        contribution = unsupported_count * UNSUPPORTED_SCORE
        score += contribution
        reasons.append(f"{unsupported_count} unsupported criterion/criteria ({contribution:g})")

    if capabilities.implemented:
        score += 1.0
        reasons.append("implemented provider (+1)")
    else:
        score -= 6.0
        reasons.append("unimplemented provider (-6)")

    if capabilities.requires_login:
        score -= 0.5
        reasons.append("requires login (-0.5)")

    profile_bonus, profile_reason = _profile_bonus(intent, capabilities.provider)
    if profile_bonus:
        score += profile_bonus
        reasons.append(profile_reason)
    elif capabilities.specialized:
        score -= 3.0
        reasons.append("specialized provider without matching intent (-3)")

    if capabilities.experimental:
        score -= 1.0
        reasons.append("experimental capability research (-1)")

    return round(score, 2), tuple(reasons), tuple(warnings)


def requested_filters(intent: HousingSearchIntent) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    _add_if_value(filters, "location", intent.location)
    _add_if_value(filters, "neighborhoods", intent.neighborhoods)
    _add_if_value(filters, "min_price", intent.min_price)
    _add_if_value(filters, "max_price", intent.max_price)
    _add_if_value(filters, "bedrooms", intent.bedrooms)
    _add_if_value(filters, "bedroom_min", intent.bedroom_min)
    _add_if_value(filters, "bedroom_max", intent.bedroom_max)
    _add_if_value(filters, "bathrooms", intent.bathrooms)
    _add_if_value(filters, "bathroom_min", intent.bathroom_min)
    _add_if_value(filters, "property_types", intent.property_types)
    _add_if_value(filters, "type_of_places", intent.type_of_places)
    _add_if_value(filters, "pet_policy", intent.pet_policy)
    _add_if_value(filters, "pet_policy_negated", intent.pet_policy_negated)
    if intent.furnished is not None:
        filters["furnished"] = intent.furnished
    _add_if_value(filters, "move_in_date", intent.move_in_date)
    _add_if_value(filters, "move_out_date", intent.move_out_date)
    amenities = _unique_strings((*intent.amenities, *intent.required_amenities, *intent.preferred_amenities))
    _add_if_value(filters, "amenities", amenities)
    _add_if_value(filters, "preferred_amenities", intent.preferred_amenities)
    _add_if_value(filters, "sort", intent.sort)
    _add_if_value(filters, "map_bounds", intent.map_bounds)
    if intent.photos:
        filters["photos"] = intent.photos
    if intent.verified_listings:
        filters["verified_listings"] = intent.verified_listings
    if intent.featured:
        filters["featured"] = intent.featured
    _add_if_value(filters, "page", intent.page)
    if intent.section8:
        filters["section8"] = intent.section8
    if intent.income_restricted:
        filters["income_restricted"] = intent.income_restricted
    if intent.wheelchair_accessible:
        filters["wheelchair_accessible"] = intent.wheelchair_accessible
    if intent.utilities_included:
        filters["utilities_included"] = intent.utilities_included
    if intent.washer_dryer:
        filters["washer_dryer"] = intent.washer_dryer
    _add_if_value(filters, "keyword", intent.keyword)
    _add_if_value(filters, "required_amenities", intent.required_amenities)
    _add_if_value(filters, "avoid_neighborhoods", intent.avoid_neighborhoods)
    _add_if_value(filters, "lease_length", intent.lease_length)
    _add_if_value(filters, "campus_or_school", intent.campus_or_school)
    _add_if_value(filters, "commute_target", intent.commute_target)
    return filters


def coerce_intent(value: HousingSearchIntent | Mapping[str, Any] | Any) -> HousingSearchIntent:
    if isinstance(value, HousingSearchIntent):
        return value

    if isinstance(value, Mapping):
        data = dict(value)
    else:
        data = {
            field_name: getattr(value, field_name)
            for field_name in HousingSearchIntent.__dataclass_fields__
            if hasattr(value, field_name)
        }

        if hasattr(value, "num_bedrooms") and "bedrooms" not in data:
            data["bedrooms"] = getattr(value, "num_bedrooms")
        if hasattr(value, "furnished_status") and "furnished" not in data:
            furnished_status = getattr(value, "furnished_status")
            data["furnished"] = bool(furnished_status) if furnished_status else None

    if "num_bedrooms" in data and "bedrooms" not in data:
        data["bedrooms"] = data.pop("num_bedrooms")
    if "type_of_place" in data and "type_of_places" not in data:
        data["type_of_places"] = data.pop("type_of_place")
    if "furnished_status" in data and "furnished" not in data:
        furnished_status = data.pop("furnished_status")
        data["furnished"] = bool(furnished_status) if furnished_status else None

    intent = HousingSearchIntent()
    allowed = set(HousingSearchIntent.__dataclass_fields__)
    normalized = {name: data[name] for name in allowed if name in data}

    for tuple_field in (
        "property_types",
        "type_of_places",
        "pet_policy",
        "pet_policy_negated",
        "neighborhoods",
        "avoid_neighborhoods",
        "amenities",
        "required_amenities",
        "preferred_amenities",
        "dealbreakers",
        "flexibility_notes",
        "notes",
    ):
        if tuple_field in normalized:
            normalized[tuple_field] = _as_tuple(normalized[tuple_field])

    return replace(intent, **normalized)


def _add_if_value(filters: dict[str, Any], filter_name: str, value: Any) -> None:
    if value is None:
        return
    if value == "":
        return
    if isinstance(value, (tuple, list, set, frozenset)) and not value:
        return
    if isinstance(value, Mapping) and not value:
        return
    filters[filter_name] = value


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if str(item).strip())


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            unique.append(text)
    return tuple(unique)


def _profile_bonus(intent: HousingSearchIntent, provider: str) -> tuple[float, str]:
    text = _intent_text(intent)
    sublet_terms = ("sublet", "sublease", "student", "campus", "roommate", "private room", "shared room")
    affordable_terms = ("section 8", "section8", "voucher", "affordable", "income restricted", "income-restricted")
    affordable_negated = any(
        term in text
        for term in (
            "not affordable",
            "not affordable housing",
            "no voucher",
            "without voucher",
            "normal apartment",
            "regular rental",
        )
    )

    if provider == OHANA and _wants_multi_roommate_rental(intent):
        return -4.0, "multi-roommate full-rental fit (-4)"

    if provider == RENTALSOURCE and _wants_multi_roommate_rental(intent):
        return 6.0, "multiple-roommate rental fit (+6)"

    if provider == OHANA and (
        intent.intent_kind == "student_sublet"
        or bool(intent.type_of_places)
        or _wants_single_room_search(intent)
        or any(term in text for term in sublet_terms)
    ):
        return 4.0, "single-room or student/sublet fit (+4)"

    if provider == RENTALSOURCE and (
        intent.intent_kind in {"general_rental", "apartment"}
        or ("apartment" in text and not any(term in text for term in affordable_terms))
    ):
        return 2.0, "general rental fit (+2)"

    if provider == AFFORDABLEHOUSING and (
        intent.section8
        or intent.income_restricted
        or intent.wheelchair_accessible
        or (not affordable_negated and any(term in text for term in affordable_terms))
    ):
        return 4.0, "affordable housing fit (+4)"

    return 0.0, ""


def _wants_multi_roommate_rental(intent: HousingSearchIntent) -> bool:
    text = _intent_text(intent)
    if intent.roommate_count is not None and intent.roommate_count >= 2:
        return True
    cues = (
        "multiple roommates",
        "several roommates",
        "with roommates",
        "roommates and i",
        "roommates and me",
        "my roommates",
        "group rental",
        "for our group",
        "we need",
        "we are looking",
    )
    return any(cue in text for cue in cues)


def _wants_single_room_search(intent: HousingSearchIntent) -> bool:
    text = _intent_text(intent)
    if intent.roommate_count is not None and intent.roommate_count <= 1:
        return True
    cues = (
        "just me",
        "only me",
        "for myself",
        "by myself",
        "solo",
        "single person",
        "private room",
        "shared room",
    )
    return any(cue in text for cue in cues)


def _intent_text(intent: HousingSearchIntent) -> str:
    pieces: list[str] = []
    if intent.intent_kind:
        pieces.append(intent.intent_kind)
    if intent.roommate_count is not None:
        pieces.append(f"roommate_count {intent.roommate_count}")
    pieces.extend(intent.notes)
    pieces.extend(intent.flexibility_notes)
    pieces.extend(intent.property_types)
    pieces.extend(intent.type_of_places)
    pieces.extend(intent.amenities)
    pieces.extend(intent.required_amenities)
    pieces.extend(intent.preferred_amenities)
    pieces.extend(intent.dealbreakers)
    if intent.campus_or_school:
        pieces.append(intent.campus_or_school)
    if intent.commute_target:
        pieces.append(intent.commute_target)
    return " ".join(pieces).lower()
