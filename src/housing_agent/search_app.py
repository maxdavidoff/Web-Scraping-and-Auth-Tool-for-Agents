from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from src.affordablehousing_agent.search_url import build_affordablehousing_search_url
from src.ohana_agent.provider_router import run_provider_searches
from src.ohana_agent.search_url import build_ohana_search_url
from src.rentalsource_agent.search_url import build_rentalsource_search_url

from .intent_extractor import JsonChatClient, extract_housing_intent
from .provider_capabilities import AFFORDABLEHOUSING, OHANA, RENTALSOURCE
from .types import HousingSearchIntent, ProviderQueryPlan, QueryPlan


EXECUTABLE_PROVIDERS = frozenset({OHANA, RENTALSOURCE, AFFORDABLEHOUSING})


Runner = Callable[..., Any]


def build_housing_search_response(
    user_request: str,
    *,
    client: JsonChatClient | None = None,
    model: str | None = None,
    providers: Sequence[str] | None = None,
    execute: bool = False,
    runner: Runner = run_provider_searches,
    today: str | None = None,
    max_listings: int = 10,
    scrolls: int = 3,
    headless: bool = True,
    state_file: str | None = None,
    selectors_file: str | None = None,
    fetch_listing_api: bool = False,
    capture_detail_urls: bool = False,
) -> dict[str, Any]:
    extraction = extract_housing_intent(
        user_request,
        client=client,
        model=model,
        providers=providers,
        today=today,
    )
    intent = extraction.intent
    query_plan = extraction.query_plan
    executable_providers, skipped_providers = executable_provider_plan(query_plan)

    response: dict[str, Any] = {
        "status": "planned",
        "mode": "execution" if execute else "planning",
        "model": extraction.model,
        "intent": _to_jsonable(intent),
        "query_plan": query_plan_to_dict(query_plan),
        "execution": {
            "requested": execute,
            "executed_providers": [],
            "skipped_providers": skipped_providers,
            "max_listings": max_listings,
        },
        "provider_results": [],
        "records": [],
        "errors": {},
        "warnings": user_visible_warnings(query_plan, execute=execute, skipped_providers=skipped_providers),
    }

    if not execute:
        return response

    if not executable_providers:
        response["status"] = "no_executable_providers"
        response["warnings"].append("No executable provider is available for this plan.")
        return response

    execution_plan = legacy_router_plan_from_intent(
        intent,
        providers=executable_providers,
        max_listings=max_listings,
    )
    routed_result = runner(
        execution_plan,
        providers=executable_providers,
        max_listings=max_listings,
        scrolls=scrolls,
        headless=headless,
        state_file=state_file,
        selectors_file=selectors_file,
        fetch_listing_api=fetch_listing_api,
        capture_detail_urls=capture_detail_urls,
    )

    response["status"] = "executed"
    response["execution"]["executed_providers"] = list(executable_providers)
    response["provider_results"] = [_provider_result_to_dict(result) for result in routed_result.provider_results]
    response["records"] = [_to_jsonable(record) for record in routed_result.records]
    response["errors"] = dict(getattr(routed_result, "errors", {}) or {})
    if response["errors"]:
        response["status"] = "partial_execution"
    return response


def executable_provider_plan(query_plan: QueryPlan) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    executable: list[str] = []
    skipped: list[dict[str, str]] = []

    for provider_plan in query_plan.provider_plans:
        provider = provider_plan.provider
        if not provider_plan.implemented:
            skipped.append(
                {
                    "provider": provider,
                    "reason": "Provider capability exists, but the scraper is not implemented.",
                }
            )
            continue

        if provider not in EXECUTABLE_PROVIDERS:
            skipped.append(
                {
                    "provider": provider,
                    "reason": "Provider is not wired to an executable scraper.",
                }
            )
            continue

        executable.append(provider)

    return tuple(executable), skipped


def query_plan_to_dict(query_plan: QueryPlan) -> dict[str, Any]:
    return {
        "ranked_provider_names": list(query_plan.ranked_provider_names),
        "provider_plans": [
            provider_plan_to_dict(provider_plan, query_plan.intent)
            for provider_plan in query_plan.provider_plans
        ],
    }


def provider_plan_to_dict(provider_plan: ProviderQueryPlan, intent: HousingSearchIntent) -> dict[str, Any]:
    report = provider_plan.report
    return {
        "provider": provider_plan.provider,
        "score": provider_plan.score,
        "quality": provider_plan.quality,
        "implemented": provider_plan.implemented,
        "requires_login": provider_plan.requires_login,
        "experimental": provider_plan.experimental,
        "search_url_preview": build_search_url_preview(provider_plan.provider, intent),
        "filter_application": {
            "applied_at_source": _to_jsonable(report.applied_at_source),
            "post_filters": _to_jsonable(report.post_filters),
            "unsupported": _to_jsonable(report.unsupported),
            "unknown_unverified": _to_jsonable(report.unknown_unverified),
            "warnings": list(report.warnings),
        },
        "reasons": list(provider_plan.reasons),
        "warnings": list(provider_plan.warnings),
    }


def build_search_url_preview(provider: str, intent: HousingSearchIntent) -> str | None:
    try:
        if provider == OHANA:
            return build_ohana_search_url(
                location=intent.location,
                movein=intent.move_in_date,
                moveout=intent.move_out_date,
                property_types=list(intent.property_types) or None,
                type_of_places=list(intent.type_of_places) or None,
                num_bedrooms=intent.bedrooms,
                min_price=intent.min_price,
                max_price=intent.max_price,
                pet_policy=(list(intent.pet_policy) or None) if not intent.pet_policy_negated else None,
                furnished_status=_ohana_furnished_status(intent),
            )
        if provider == RENTALSOURCE:
            return build_rentalsource_search_url(
                location=intent.location,
                property_types=list(intent.property_types) or None,
                num_bedrooms=intent.bedrooms or intent.bedroom_min,
                num_bathrooms=intent.bathrooms or intent.bathroom_min,
                min_price=intent.min_price,
                max_price=intent.max_price,
                pets=bool(intent.pet_policy) and not bool(intent.pet_policy_negated),
                photos=intent.photos,
                verified=intent.verified_listings,
                featured=intent.featured,
                sort=intent.sort,
                page=intent.page,
            )
        if provider == AFFORDABLEHOUSING and intent.location:
            return build_affordablehousing_search_url(
                location=intent.location,
                property_types=list(intent.property_types) or None,
                num_bedrooms=intent.bedrooms,
                max_price=intent.max_price,
                pet_friendly=bool(intent.pet_policy) and not bool(intent.pet_policy_negated),
                section8=intent.section8,
                income_restricted=intent.income_restricted,
                wheelchair_accessible=intent.wheelchair_accessible,
                utilities_included=intent.utilities_included,
                washer_dryer=intent.washer_dryer,
            )
    except ValueError:
        return None
    return None


def user_visible_warnings(
    query_plan: QueryPlan,
    *,
    execute: bool,
    skipped_providers: Sequence[Mapping[str, str]],
) -> list[str]:
    warnings: list[str] = []
    if not execute:
        warnings.append("Planning mode only; no scraping executed.")

    date_filters = {"move_in_date", "move_out_date"}
    if any(
        date_filters.intersection(provider_plan.report.unknown_unverified)
        or date_filters.intersection(provider_plan.report.unsupported)
        for provider_plan in query_plan.provider_plans
    ):
        warnings.append("Date filters are unverified or not source-applied for at least one provider.")

    for provider_plan in query_plan.provider_plans:
        for warning in provider_plan.warnings:
            if warning not in warnings:
                warnings.append(warning)

    for skipped in skipped_providers:
        provider = skipped.get("provider", "")
        reason = skipped.get("reason", "")
        if provider:
            warnings.append(f"{provider} will not be executed: {reason}")

    return warnings


def legacy_router_plan_from_intent(
    intent: HousingSearchIntent,
    *,
    providers: Sequence[str],
    max_listings: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        location=intent.location,
        providers=list(providers),
        movein=intent.move_in_date,
        moveout=intent.move_out_date,
        property_types=list(intent.property_types) or None,
        type_of_places=list(intent.type_of_places) or None,
        num_bedrooms=intent.bedrooms or intent.bedroom_min,
        bedroom_min=intent.bedroom_min,
        bedroom_max=intent.bedroom_max,
        num_bathrooms=intent.bathrooms or intent.bathroom_min,
        bathroom_min=intent.bathroom_min,
        min_price=intent.min_price,
        max_price=intent.max_price,
        pet_policy=list(intent.pet_policy) or None,
        pet_policy_negated=list(intent.pet_policy_negated) or None,
        furnished_status=_ohana_furnished_status(intent),
        photos=intent.photos,
        verified=intent.verified_listings,
        featured=intent.featured,
        sort=intent.sort,
        page=intent.page,
        max_listings=max_listings,
        amenities=list(intent.amenities) or None,
        required_amenities=list(intent.required_amenities) or None,
        preferred_amenities=list(intent.preferred_amenities) or None,
        avoid_neighborhoods=list(intent.avoid_neighborhoods) or None,
        lease_length=intent.lease_length,
        commute_target=intent.commute_target,
        keyword=intent.keyword,
        notes=list(intent.notes),
        assumptions=None,
    )


def _ohana_furnished_status(intent: HousingSearchIntent) -> list[str] | None:
    if intent.furnished is True:
        return ["Furnished"]
    if intent.furnished is False:
        return ["Unfurnished"]
    return None


def _provider_result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "provider": getattr(result, "provider", ""),
        "status": getattr(result, "status", ""),
        "error": getattr(result, "error", ""),
        "search_url": getattr(result, "search_url", ""),
        "records_count": len(getattr(result, "records", []) or []),
        "excluded_records_count": len(getattr(result, "excluded_records", []) or []),
        "exclusion_counts": _to_jsonable(getattr(result, "exclusion_counts", None)),
        "filter_application": _to_jsonable(getattr(result, "filter_application", None)),
        "query_quality": _to_jsonable(getattr(result, "query_quality", None)),
        "artifacts": {
            "raw_output": _to_jsonable(getattr(result, "raw_output", None)),
            "csv_output": _to_jsonable(getattr(result, "csv_output", None)),
            "debug_artifacts": _to_jsonable(getattr(result, "debug_artifacts", None)),
        },
    }


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "__fspath__"):
        return value.__fspath__()
    return value
