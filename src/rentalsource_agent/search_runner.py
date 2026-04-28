from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .browser import build_context, save_storage_state
from .config import DEBUG_DIR, PROCESSED_DIR, RAW_DIR, ensure_dirs, get_settings, load_selectors
from .detail import enrich_record_with_detail
from .extractor import extract_listings, save_debug_artifacts
from .search_url import build_rentalsource_search_url
from .storage import write_csv, write_jsonl


@dataclass(frozen=True)
class RentalSourceSearchOptions:
    search_url: str | None = None
    location: str | None = None
    property_types: list[str] | None = None
    num_bedrooms: int | None = None
    num_bathrooms: float | None = None
    min_price: int | None = None
    max_price: int | None = None
    pets: bool = False
    photos: bool = False
    verified: bool = False
    featured: bool = False
    sort: str | None = None
    page: int | None = None
    state_file: str | Path | None = None
    selectors_file: str | Path | None = None
    max_listings: int = 25
    scrolls: int = 3
    headless: bool = False
    manual_search: bool = False
    keep_open: bool = False
    fetch_listing_detail: bool = False
    save_detail_debug: bool = False


@dataclass(frozen=True)
class RentalSourceSearchResult:
    records: list[dict[str, Any]]
    raw_output: Path
    csv_output: Path
    debug_artifacts: dict[str, Path]
    search_url: str


def build_search_url(options: RentalSourceSearchOptions) -> str:
    if options.search_url:
        return options.search_url

    if not options.location:
        raise ValueError("Provide either search_url or location.")

    return build_rentalsource_search_url(
        location=options.location,
        property_types=options.property_types,
        num_bedrooms=options.num_bedrooms,
        num_bathrooms=options.num_bathrooms,
        min_price=options.min_price,
        max_price=options.max_price,
        pets=options.pets,
        photos=options.photos,
        verified=options.verified,
        featured=options.featured,
        sort=options.sort,
        page=options.page,
    )


def scroll_for_results(page, scrolls: int, pause_ms: int) -> None:
    for _ in range(max(scrolls, 0)):
        page.mouse.wheel(0, 2200)
        page.wait_for_timeout(pause_ms)


def run_rentalsource_search(options: RentalSourceSearchOptions) -> RentalSourceSearchResult:
    ensure_dirs()
    search_url = build_search_url(options)
    print(f"Using RentalSource search URL: {search_url}")

    settings = get_settings(
        search_url=search_url,
        location=options.location,
        state_file=options.state_file,
        selectors_file=options.selectors_file,
    )
    selectors = load_selectors(settings.selectors_file)

    state_file = settings.state_file if settings.state_file.exists() else None
    if state_file:
        print(f"Using saved RentalSource session: {state_file}")
    else:
        print(f"No saved RentalSource session found at {settings.state_file}; continuing with a public session.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_output = RAW_DIR / f"rentalsource_results_{timestamp}.jsonl"
    csv_output = PROCESSED_DIR / f"rentalsource_results_{timestamp}.csv"

    playwright, browser, context, page = build_context(
        headless=options.headless,
        state_file=state_file,
        slow_mo_ms=100,
    )
    try:
        print(f"Opening RentalSource search page: {search_url}")
        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2_000)

        if options.manual_search:
            print("\nRun the RentalSource search manually in the browser window.")
            print("When the results are visible, return here and press ENTER.")
            input("Press ENTER to extract visible results... ")
        else:
            print("Using RentalSource URL directly; skipping automated search input.")
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(2_000)

        scroll_for_results(page, options.scrolls, pause_ms=1_000)
        debug = save_debug_artifacts(page, DEBUG_DIR)
        print("Calling RentalSource extract_listings...")
        records = extract_listings(page, selectors, max_listings=options.max_listings)

        if options.fetch_listing_detail:
            print("\nFetching RentalSource detail pages for each extracted record...")
            detail_debug_dir = DEBUG_DIR / "rentalsource_detail" if options.save_detail_debug else None
            for i, record in enumerate(records, start=1):
                print(f"[{i}/{len(records)}] {record.get('title', 'Untitled listing')}")
                enrich_record_with_detail(page=page, record=record, debug_dir=detail_debug_dir)
                page.wait_for_timeout(500)

        jsonl_count = write_jsonl(records, raw_output)
        csv_count = write_csv(records, csv_output)
        save_storage_state(context, settings.state_file)

        print("\nRentalSource done.")
        print(f"Extracted records: {len(records)}")
        print(f"JSONL: {raw_output} ({jsonl_count} records)")
        print(f"CSV:   {csv_output} ({csv_count} records)")

        if options.keep_open:
            input("\nPress ENTER to close the browser... ")

        return RentalSourceSearchResult(
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
