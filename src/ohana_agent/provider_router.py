from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.affordablehousing_agent.search_runner import (
    AffordableHousingSearchOptions,
    run_affordablehousing_search,
)
from src.rentalsource_agent.search_runner import RentalSourceSearchOptions, run_rentalsource_search

from .config import PROCESSED_DIR, RAW_DIR, ensure_dirs
from .search_runner import OhanaSearchOptions, run_ohana_search
from .storage import write_csv, write_jsonl

try:
    from src.housing_agent.query_planner import plan_query as plan_provider_query_metadata
except ImportError:
    plan_provider_query_metadata = None


OHANA = "ohana"
RENTALSOURCE = "rentalsource"
AFFORDABLEHOUSING = "affordablehousing"
ALL_PROVIDERS = (OHANA, RENTALSOURCE, AFFORDABLEHOUSING)

PROVIDER_ALIASES = {
    "ohana": OHANA,
    "liveohana": OHANA,
    "rental-source": RENTALSOURCE,
    "rental_source": RENTALSOURCE,
    "rentalsource": RENTALSOURCE,
    "rental source": RENTALSOURCE,
    "affordable": AFFORDABLEHOUSING,
    "affordable housing": AFFORDABLEHOUSING,
    "affordable-housing": AFFORDABLEHOUSING,
    "affordable_housing": AFFORDABLEHOUSING,
    "affordablehousing": AFFORDABLEHOUSING,
    "affordablehousing.com": AFFORDABLEHOUSING,
}


@dataclass(frozen=True)
class ProviderSearchResult:
    provider: str
    records: list[dict[str, Any]]
    search_url: str = ""
    raw_output: Path | None = None
    csv_output: Path | None = None
    debug_artifacts: dict[str, Path] | None = None
    status: str = "ok"
    error: str = ""
    filter_application: dict[str, Any] | None = None
    query_quality: dict[str, Any] | None = None


@dataclass(frozen=True)
class RoutedSearchResult:
    records: list[dict[str, Any]]
    provider_results: list[ProviderSearchResult]
    search_url: str
    raw_output: Path | None
    csv_output: Path | None
    debug_artifacts: dict[str, Path]
    errors: dict[str, str]

    @property
    def search_urls(self) -> dict[str, str]:
        return {
            result.provider: result.search_url
            for result in self.provider_results
            if result.search_url
        }


def normalize_provider_names(providers: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if providers is None:
        return [OHANA]

    if isinstance(providers, str):
        raw_values = _split_provider_value(providers)
    else:
        raw_values = []
        for provider in providers:
            raw_values.extend(_split_provider_value(str(provider)))

    normalized: list[str] = []
    for raw in raw_values:
        key = raw.strip().lower()
        if not key:
            continue
        if key in {"all", "multi", "multiple"}:
            for provider in ALL_PROVIDERS:
                if provider not in normalized:
                    normalized.append(provider)
            continue

        provider = PROVIDER_ALIASES.get(key)
        if not provider:
            raise ValueError(
                f"Unknown housing provider '{raw}'. Expected one of: {', '.join(ALL_PROVIDERS)}."
            )
        if provider not in normalized:
            normalized.append(provider)

    return normalized or [OHANA]


def _split_provider_value(value: str) -> list[str]:
    text = value.strip()
    key = text.lower()
    if key in PROVIDER_ALIASES or key in {"all", "multi", "multiple"}:
        return [text]
    return text.replace(",", " ").split()


def _plan_value(plan: Any, name: str, default: Any = None) -> Any:
    if isinstance(plan, dict):
        return plan.get(name, default)
    return getattr(plan, name, default)


def _truthy_list(values: list[str] | None) -> bool:
    if not values:
        return False
    return any(str(value).strip().lower() not in {"", "0", "false", "no", "none"} for value in values)


def _plan_text(plan: Any) -> str:
    pieces: list[str] = []
    for field in ["notes", "assumptions", "pet_policy", "furnished_status"]:
        value = _plan_value(plan, field)
        if isinstance(value, list):
            pieces.extend(str(item) for item in value)
        elif value:
            pieces.append(str(value))
    return " ".join(pieces).lower()


def _has_plan_value(plan: Any, name: str) -> bool:
    value = _plan_value(plan, name)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return _truthy_list(value)
    return True


def _truthy_plan_value(plan: Any, name: str) -> bool:
    value = _plan_value(plan, name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(value, list):
        return _truthy_list(value)
    return bool(value)


def _append_present_fields(plan: Any, target: list[str], fields: list[str]) -> None:
    for field in fields:
        if _has_plan_value(plan, field):
            target.append(field)


def _append_truthy_fields(plan: Any, target: list[str], fields: list[str]) -> None:
    for field in fields:
        if _truthy_plan_value(plan, field):
            target.append(field)


def _plan_provider_metadata(plan: Any, provider: str, name: str) -> dict[str, Any] | None:
    metadata = _plan_value(plan, "provider_metadata")
    if isinstance(metadata, dict):
        provider_metadata = metadata.get(provider)
        if isinstance(provider_metadata, dict) and isinstance(provider_metadata.get(name), dict):
            return provider_metadata[name]

    by_provider = _plan_value(plan, f"{name}_by_provider")
    if isinstance(by_provider, dict) and isinstance(by_provider.get(provider), dict):
        return by_provider[provider]

    return None


def _planner_query_intent(plan: Any) -> dict[str, Any]:
    text = _plan_text(plan)
    furnished_status = _plan_value(plan, "furnished_status")
    return {
        "location": _plan_value(plan, "location"),
        "min_price": _plan_value(plan, "min_price"),
        "max_price": _plan_value(plan, "max_price"),
        "bedrooms": _plan_value(plan, "num_bedrooms"),
        "bathrooms": _plan_value(plan, "num_bathrooms"),
        "property_types": _plan_value(plan, "property_types") or (),
        "type_of_places": _plan_value(plan, "type_of_places") or (),
        "pet_policy": _plan_value(plan, "pet_policy") or (),
        "furnished": bool(furnished_status) if furnished_status else None,
        "move_in_date": _plan_value(plan, "movein"),
        "move_out_date": _plan_value(plan, "moveout"),
        "sort": _plan_value(plan, "sort"),
        "photos": _truthy_plan_value(plan, "photos"),
        "verified_listings": _truthy_plan_value(plan, "verified"),
        "featured": _truthy_plan_value(plan, "featured"),
        "page": _plan_value(plan, "page"),
        "section8": "section 8" in text or "section8" in text,
        "income_restricted": "income restricted" in text or "income-restricted" in text,
        "wheelchair_accessible": "wheelchair" in text,
        "utilities_included": "utilities included" in text,
        "washer_dryer": "washer dryer" in text or "washer-dryer" in text,
        "notes": _plan_value(plan, "notes") or (),
    }


def _with_filter_aliases(filter_names: list[str]) -> list[str]:
    aliases = {
        "bedrooms": "num_bedrooms",
        "bathrooms": "num_bathrooms",
        "move_in_date": "movein",
        "move_out_date": "moveout",
        "furnished": "furnished_status",
        "verified_listings": "verified",
    }
    expanded: list[str] = []
    for name in filter_names:
        if name not in expanded:
            expanded.append(name)
        alias = aliases.get(name)
        if alias and alias not in expanded:
            expanded.append(alias)
    return expanded


def _planner_filter_application(provider_plan: Any) -> dict[str, Any]:
    report = provider_plan.report
    post_filters = _with_filter_aliases(list(report.post_filters))
    unsupported = _with_filter_aliases(list(report.unsupported))
    unknown_unverified = _with_filter_aliases(list(report.unknown_unverified))
    return {
        "source_applied": _with_filter_aliases(list(report.applied_at_source)),
        "post_filters": post_filters,
        "unsupported": unsupported,
        "not_source_applied": post_filters + unsupported + unknown_unverified,
        "unverified_source_filters": unknown_unverified,
        "warnings": list(report.warnings),
    }


def _planner_query_metadata(provider: str, plan: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if plan_provider_query_metadata is None:
        return None

    try:
        query_plan = plan_provider_query_metadata(
            _planner_query_intent(plan),
            providers=[provider],
        )
        provider_plan = query_plan.for_provider(provider)
    except Exception:
        return None

    filter_application = _planner_filter_application(provider_plan)
    status = "partial" if filter_application["not_source_applied"] else "source_applied"
    query_quality = {
        "status": status,
        "quality": provider_plan.quality,
        "score": provider_plan.score,
        "warnings": list(provider_plan.warnings),
        "reasons": list(provider_plan.reasons),
    }
    return filter_application, query_quality


def _default_filter_application(provider: str, plan: Any) -> dict[str, Any]:
    source_applied: list[str] = []
    not_source_applied: list[str] = []
    unverified_source_filters: list[str] = []

    if provider == OHANA:
        _append_present_fields(
            plan,
            source_applied,
            [
                "location",
                "min_price",
                "max_price",
                "num_bedrooms",
                "property_types",
                "type_of_places",
                "pet_policy",
                "furnished_status",
            ],
        )
        _append_present_fields(plan, unverified_source_filters, ["movein", "moveout"])

    elif provider == RENTALSOURCE:
        _append_present_fields(
            plan,
            source_applied,
            [
                "location",
                "min_price",
                "max_price",
                "num_bedrooms",
                "num_bathrooms",
                "property_types",
                "sort",
                "page",
            ],
        )
        if _truthy_list(_plan_value(plan, "pet_policy")) or _truthy_plan_value(plan, "pets"):
            source_applied.append("pets")
        _append_truthy_fields(plan, source_applied, ["photos", "verified", "featured"])
        _append_present_fields(plan, not_source_applied, ["movein", "moveout", "type_of_places", "furnished_status"])

    elif provider == AFFORDABLEHOUSING:
        _append_present_fields(
            plan,
            source_applied,
            ["location", "max_price", "num_bedrooms", "property_types"],
        )
        if _truthy_list(_plan_value(plan, "pet_policy")) or _truthy_plan_value(plan, "pets"):
            source_applied.append("pet_policy")

        text = _plan_text(plan)
        for field, matched in [
            ("section8", "section 8" in text or "section8" in text),
            ("income_restricted", "income restricted" in text or "income-restricted" in text),
            ("wheelchair_accessible", "wheelchair" in text),
            ("utilities_included", "utilities included" in text),
            ("washer_dryer", "washer dryer" in text or "washer-dryer" in text),
        ]:
            if matched:
                source_applied.append(field)

        _append_present_fields(
            plan,
            not_source_applied,
            [
                "min_price",
                "movein",
                "moveout",
                "type_of_places",
                "furnished_status",
                "num_bathrooms",
                "photos",
                "verified",
                "featured",
                "sort",
                "page",
            ],
        )

    return {
        "source_applied": source_applied,
        "not_source_applied": not_source_applied,
        "unverified_source_filters": unverified_source_filters,
    }


def _default_query_quality(filter_application: dict[str, Any]) -> dict[str, Any]:
    not_source_applied = filter_application.get("not_source_applied") or []
    unverified = filter_application.get("unverified_source_filters") or []
    status = "source_applied"
    if not_source_applied:
        status = "partial"
    elif unverified:
        status = "unverified"

    return {
        "status": status,
        "source_applied_count": len(filter_application.get("source_applied") or []),
        "not_source_applied_count": len(not_source_applied),
        "unverified_source_filter_count": len(unverified),
    }


def _provider_query_metadata(provider: str, plan: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    override_filter_application = _plan_provider_metadata(plan, provider, "filter_application")
    override_query_quality = _plan_provider_metadata(plan, provider, "query_quality")
    if override_filter_application and override_query_quality:
        return override_filter_application, override_query_quality

    planner_metadata = _planner_query_metadata(provider, plan)
    if planner_metadata:
        return planner_metadata

    filter_application = (
        override_filter_application
        or _default_filter_application(provider, plan)
    )
    query_quality = (
        override_query_quality
        or _default_query_quality(filter_application)
    )
    return filter_application, query_quality


def _normalize_record(provider: str, record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized["provider"] = provider
    normalized["source"] = normalized.get("source") or provider
    normalized["listing_url"] = normalized.get("detail_url") or normalized.get("url") or ""
    normalized["address"] = normalized.get("listing_address") or normalized.get("location") or ""
    normalized["bathrooms"] = normalized.get("bathrooms", "")
    normalized["property_type"] = normalized.get("property_type", "")
    normalized["square_feet"] = normalized.get("square_feet") or normalized.get("sqft") or ""
    normalized["availability"] = normalized.get("availability", "")
    normalized["price_min"] = normalized.get("price_min", "")
    normalized["price_max"] = normalized.get("price_max", "")
    return normalized


def _provider_success_result(provider: str, result: Any, plan: Any) -> ProviderSearchResult:
    records = [_normalize_record(provider, record) for record in result.records]
    filter_application, query_quality = _provider_query_metadata(provider, plan)
    return ProviderSearchResult(
        provider=provider,
        records=records,
        search_url=result.search_url,
        raw_output=result.raw_output,
        csv_output=result.csv_output,
        debug_artifacts=result.debug_artifacts,
        filter_application=filter_application,
        query_quality=query_quality,
        status="ok" if records else "empty",
    )


def _provider_failure_result(provider: str, exc: Exception, plan: Any | None = None) -> ProviderSearchResult:
    filter_application: dict[str, Any] | None = None
    query_quality: dict[str, Any] | None = None
    if plan is not None:
        filter_application, query_quality = _provider_query_metadata(provider, plan)

    return ProviderSearchResult(
        provider=provider,
        records=[],
        filter_application=filter_application,
        query_quality=query_quality,
        status="failed",
        error=str(exc),
    )


def _run_provider(
    provider: str,
    plan: Any,
    *,
    state_file: str | None,
    selectors_file: str | None,
    max_listings: int,
    scrolls: int,
    headless: bool,
    fetch_listing_api: bool,
    capture_detail_urls: bool,
) -> ProviderSearchResult:
    if provider == OHANA:
        result = run_ohana_search(
            OhanaSearchOptions(
                location=_plan_value(plan, "location"),
                movein=_plan_value(plan, "movein"),
                moveout=_plan_value(plan, "moveout"),
                property_types=_plan_value(plan, "property_types"),
                type_of_places=_plan_value(plan, "type_of_places"),
                num_bedrooms=_plan_value(plan, "num_bedrooms"),
                min_price=_plan_value(plan, "min_price"),
                max_price=_plan_value(plan, "max_price"),
                pet_policy=_plan_value(plan, "pet_policy"),
                furnished_status=_plan_value(plan, "furnished_status"),
                state_file=state_file,
                selectors_file=selectors_file,
                max_listings=max_listings,
                scrolls=scrolls,
                headless=headless,
                fetch_listing_api=fetch_listing_api,
                capture_detail_urls=capture_detail_urls,
            )
        )
        return _provider_success_result(provider, result, plan)

    if provider == RENTALSOURCE:
        result = run_rentalsource_search(
            RentalSourceSearchOptions(
                location=_plan_value(plan, "location"),
                property_types=_plan_value(plan, "property_types"),
                num_bedrooms=_plan_value(plan, "num_bedrooms"),
                num_bathrooms=_plan_value(plan, "num_bathrooms"),
                min_price=_plan_value(plan, "min_price"),
                max_price=_plan_value(plan, "max_price"),
                pets=_truthy_list(_plan_value(plan, "pet_policy")) or _truthy_plan_value(plan, "pets"),
                photos=_truthy_plan_value(plan, "photos"),
                verified=_truthy_plan_value(plan, "verified"),
                featured=_truthy_plan_value(plan, "featured"),
                sort=_plan_value(plan, "sort"),
                page=_plan_value(plan, "page"),
                state_file=None,
                selectors_file=None,
                max_listings=max_listings,
                scrolls=scrolls,
                headless=headless,
                fetch_listing_detail=fetch_listing_api,
            )
        )
        return _provider_success_result(provider, result, plan)

    if provider == AFFORDABLEHOUSING:
        text = _plan_text(plan)
        result = run_affordablehousing_search(
            AffordableHousingSearchOptions(
                location=_plan_value(plan, "location"),
                property_types=_plan_value(plan, "property_types"),
                num_bedrooms=_plan_value(plan, "num_bedrooms"),
                min_price=_plan_value(plan, "min_price"),
                max_price=_plan_value(plan, "max_price"),
                pet_friendly=_truthy_list(_plan_value(plan, "pet_policy")),
                section8="section 8" in text or "section8" in text,
                income_restricted="income restricted" in text or "income-restricted" in text,
                wheelchair_accessible="wheelchair" in text,
                utilities_included="utilities included" in text,
                washer_dryer="washer dryer" in text or "washer-dryer" in text,
                state_file=None,
                selectors_file=None,
                max_listings=max_listings,
                scrolls=scrolls,
                headless=headless,
                capture_detail_urls=capture_detail_urls,
            )
        )
        return _provider_success_result(provider, result, plan)

    raise ValueError(f"Unknown housing provider: {provider}")


def run_provider_searches(
    plan: Any,
    *,
    providers: list[str] | tuple[str, ...] | str | None = None,
    state_file: str | None = None,
    selectors_file: str | None = None,
    max_listings: int | None = None,
    scrolls: int = 3,
    headless: bool = True,
    fetch_listing_api: bool = False,
    capture_detail_urls: bool = False,
) -> RoutedSearchResult:
    ensure_dirs()
    selected_providers = normalize_provider_names(providers)
    listing_limit = max_listings or int(_plan_value(plan, "max_listings", 10) or 10)

    provider_results: list[ProviderSearchResult] = []
    for provider in selected_providers:
        try:
            provider_results.append(
                _run_provider(
                    provider,
                    plan,
                    state_file=state_file,
                    selectors_file=selectors_file,
                    max_listings=listing_limit,
                    scrolls=scrolls,
                    headless=headless,
                    fetch_listing_api=fetch_listing_api,
                    capture_detail_urls=capture_detail_urls,
                )
            )
        except Exception as exc:
            provider_results.append(_provider_failure_result(provider, exc, plan))

    records = [
        record
        for result in provider_results
        for record in result.records
    ]
    errors = {
        result.provider: result.error
        for result in provider_results
        if result.status == "failed" and result.error
    }

    if len(provider_results) == 1:
        only = provider_results[0]
        return RoutedSearchResult(
            records=records,
            provider_results=provider_results,
            search_url=only.search_url,
            raw_output=only.raw_output,
            csv_output=only.csv_output,
            debug_artifacts=only.debug_artifacts or {},
            errors=errors,
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_output = RAW_DIR / f"housing_provider_results_{timestamp}.jsonl"
    csv_output = PROCESSED_DIR / f"housing_provider_results_{timestamp}.csv"
    write_jsonl(records, raw_output)
    write_csv(records, csv_output)

    debug_artifacts: dict[str, Path] = {}
    for result in provider_results:
        for name, path in (result.debug_artifacts or {}).items():
            debug_artifacts[f"{result.provider}_{name}"] = path

    return RoutedSearchResult(
        records=records,
        provider_results=provider_results,
        search_url=", ".join(
            result.search_url for result in provider_results if result.search_url
        ),
        raw_output=raw_output,
        csv_output=csv_output,
        debug_artifacts=debug_artifacts,
        errors=errors,
    )
