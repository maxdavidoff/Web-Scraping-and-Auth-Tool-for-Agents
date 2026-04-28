from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .browser import build_context, save_storage_state
from .config import DEBUG_DIR, PROCESSED_DIR, RAW_DIR, ensure_dirs, get_settings, load_selectors
from .detail import annotate_coordinate_status, enrich_record_with_detail
from .extractor import extract_listings, save_debug_artifacts
from .search_url import build_affordablehousing_search_url
from .storage import write_csv, write_jsonl


@dataclass(frozen=True)
class AffordableHousingSearchOptions:
    search_url: str | None = None
    location: str | None = None
    property_types: list[str] | None = None
    num_bedrooms: int | None = None
    min_price: int | None = None
    max_price: int | None = None
    pet_friendly: bool = False
    section8: bool = False
    income_restricted: bool = False
    wheelchair_accessible: bool = False
    utilities_included: bool = False
    washer_dryer: bool = False
    state_file: str | Path | None = None
    selectors_file: str | Path | None = None
    max_listings: int = 25
    scrolls: int = 3
    headless: bool = False
    manual_search: bool = False
    keep_open: bool = False
    capture_detail_urls: bool = False
    fetch_listing_detail: bool = False
    save_detail_debug: bool = False


@dataclass(frozen=True)
class AffordableHousingSearchResult:
    records: list[dict[str, Any]]
    raw_output: Path
    csv_output: Path
    debug_artifacts: dict[str, Path]
    search_url: str


def build_search_url(options: AffordableHousingSearchOptions) -> str:
    if options.search_url:
        return options.search_url

    if not options.location:
        raise ValueError("Provide either search_url or location.")

    return build_affordablehousing_search_url(
        location=options.location,
        property_types=options.property_types,
        num_bedrooms=options.num_bedrooms,
        max_price=options.max_price,
        pet_friendly=options.pet_friendly,
        section8=options.section8,
        income_restricted=options.income_restricted,
        wheelchair_accessible=options.wheelchair_accessible,
        utilities_included=options.utilities_included,
        washer_dryer=options.washer_dryer,
    )


def try_automated_search(page, location: str, selectors: dict[str, Any]) -> bool:
    search_input_selectors = selectors.get("search_input_selectors", [])
    for selector in search_input_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() == 0:
                continue
            loc.click(timeout=2_000)
            loc.fill(location, timeout=3_000)
            loc.press("Enter", timeout=3_000)
            return True
        except Exception:
            continue
    return False


def scroll_for_results(page, scrolls: int, pause_ms: int) -> None:
    for _ in range(max(scrolls, 0)):
        page.mouse.wheel(0, 2200)
        page.wait_for_timeout(pause_ms)


def has_concrete_search_path(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.path.strip("/"))


def run_affordablehousing_search(options: AffordableHousingSearchOptions) -> AffordableHousingSearchResult:
    ensure_dirs()
    search_url = build_search_url(options)
    print(f"Using AffordableHousing search URL: {search_url}")
    if options.min_price is not None:
        print("Note: min_price is accepted for parity, but AffordableHousing URLs do not expose a stable min-price filter.")

    settings = get_settings(
        search_url=search_url,
        location=options.location,
        state_file=options.state_file,
        selectors_file=options.selectors_file,
    )
    selectors = load_selectors(settings.selectors_file)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_output = RAW_DIR / f"affordablehousing_results_{timestamp}.jsonl"
    csv_output = PROCESSED_DIR / f"affordablehousing_results_{timestamp}.csv"

    playwright, browser, context, page = build_context(
        headless=options.headless,
        state_file=settings.state_file,
        slow_mo_ms=100,
    )
    try:
        if not settings.state_file.exists():
            print(f"No saved AffordableHousing session found at {settings.state_file}; continuing as a visitor.")

        print(f"Opening AffordableHousing search page: {search_url}")
        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2_000)

        if options.manual_search:
            print("\nRun the AffordableHousing search manually in the browser window.")
            print("When the results are visible, return here and press ENTER.")
            input("Press ENTER to extract visible results... ")
        else:
            if has_concrete_search_path(search_url):
                print("Using AffordableHousing search URL directly; skipping automated search input.")
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(3_000)
            else:
                print(f"Trying automated AffordableHousing search for: {settings.location}")
                ok = try_automated_search(page, settings.location, selectors)
                if not ok:
                    print("Could not find a search input with the current selectors.")
                    input("Run the search manually now, then press ENTER to extract visible results... ")
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(2_000)

        scroll_for_results(page, options.scrolls, pause_ms=1_000)
        debug = save_debug_artifacts(page, DEBUG_DIR)
        print("Calling AffordableHousing extract_listings...")
        records = extract_listings(
            page,
            selectors,
            max_listings=options.max_listings,
            capture_detail_urls=options.capture_detail_urls or options.fetch_listing_detail,
        )

        fallback_location = options.location or settings.location
        if not records and not options.manual_search and fallback_location and not has_concrete_search_path(search_url):
            fallback_url = build_affordablehousing_search_url(
                location=fallback_location,
                property_types=options.property_types,
                num_bedrooms=options.num_bedrooms,
                max_price=options.max_price,
                pet_friendly=options.pet_friendly,
                section8=options.section8,
                income_restricted=options.income_restricted,
                wheelchair_accessible=options.wheelchair_accessible,
                utilities_included=options.utilities_included,
                washer_dryer=options.washer_dryer,
            )
            if fallback_url != page.url:
                print(f"No cards found from search input; trying direct search URL: {fallback_url}")
                page.goto(fallback_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(2_000)
                scroll_for_results(page, options.scrolls, pause_ms=1_000)
                debug = save_debug_artifacts(page, DEBUG_DIR)
                records = extract_listings(
                    page,
                    selectors,
                    max_listings=options.max_listings,
                    capture_detail_urls=options.capture_detail_urls or options.fetch_listing_detail,
                )

        if options.fetch_listing_detail:
            print("\nFetching AffordableHousing detail pages for listing coordinates...")
            detail_debug_dir = DEBUG_DIR / "affordablehousing_detail" if options.save_detail_debug else None
            for i, record in enumerate(records, start=1):
                print(f"[{i}/{len(records)}] {record.get('title', 'Untitled listing')}")
                enrich_record_with_detail(page=page, record=record, debug_dir=detail_debug_dir)
                page.wait_for_timeout(500)
        else:
            for record in records:
                annotate_coordinate_status(record, enrichment_requested=False)

        jsonl_count = write_jsonl(records, raw_output)
        csv_count = write_csv(records, csv_output)
        save_storage_state(context, settings.state_file)

        print("\nAffordableHousing done.")
        print(f"Extracted records: {len(records)}")
        print(f"JSONL: {raw_output} ({jsonl_count} records)")
        print(f"CSV:   {csv_output} ({csv_count} records)")

        if options.keep_open:
            input("\nPress ENTER to close the browser... ")

        return AffordableHousingSearchResult(
            records=records,
            raw_output=raw_output,
            csv_output=csv_output,
            debug_artifacts=debug,
            search_url=search_url,
        )
    finally:
        context.close()
        browser.close()
        playwright.stop()
