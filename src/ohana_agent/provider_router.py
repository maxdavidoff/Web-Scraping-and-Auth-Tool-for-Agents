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


def _provider_success_result(provider: str, result: Any) -> ProviderSearchResult:
    records = [_normalize_record(provider, record) for record in result.records]
    return ProviderSearchResult(
        provider=provider,
        records=records,
        search_url=result.search_url,
        raw_output=result.raw_output,
        csv_output=result.csv_output,
        debug_artifacts=result.debug_artifacts,
        status="ok" if records else "empty",
    )


def _provider_failure_result(provider: str, exc: Exception) -> ProviderSearchResult:
    return ProviderSearchResult(
        provider=provider,
        records=[],
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
        return _provider_success_result(provider, result)

    if provider == RENTALSOURCE:
        result = run_rentalsource_search(
            RentalSourceSearchOptions(
                location=_plan_value(plan, "location"),
                property_types=_plan_value(plan, "property_types"),
                num_bedrooms=_plan_value(plan, "num_bedrooms"),
                min_price=_plan_value(plan, "min_price"),
                max_price=_plan_value(plan, "max_price"),
                pets=_truthy_list(_plan_value(plan, "pet_policy")),
                state_file=None,
                selectors_file=None,
                max_listings=max_listings,
                scrolls=scrolls,
                headless=headless,
                fetch_listing_detail=fetch_listing_api,
            )
        )
        return _provider_success_result(provider, result)

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
        return _provider_success_result(provider, result)

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
            provider_results.append(_provider_failure_result(provider, exc))

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
