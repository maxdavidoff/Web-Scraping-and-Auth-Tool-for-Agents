from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .browser import build_context, save_storage_state
from .config import DEBUG_DIR, PROCESSED_DIR, RAW_DIR, ensure_dirs, get_settings, load_selectors
from .extractor import extract_listings, save_debug_artifacts
from .listing_api import build_init_data_url, extract_address_geographic_address, fetch_listing_init_data
from .search_url import build_ohana_search_url
from .storage import write_csv, write_jsonl


@dataclass(frozen=True)
class OhanaSearchOptions:
    search_url: str | None = None
    location: str | None = None
    movein: str | None = None
    moveout: str | None = None
    property_types: list[str] | None = None
    type_of_places: list[str] | None = None
    num_bedrooms: int | None = None
    min_price: int | None = None
    max_price: int | None = None
    pet_policy: list[str] | None = None
    furnished_status: list[str] | None = None
    state_file: str | Path | None = None
    selectors_file: str | Path | None = None
    max_listings: int = 25
    scrolls: int = 3
    headless: bool = False
    manual_search: bool = False
    keep_open: bool = False
    fetch_listing_api: bool = False
    capture_detail_urls: bool = False


@dataclass(frozen=True)
class OhanaSearchResult:
    records: list[dict[str, Any]]
    raw_output: Path
    csv_output: Path
    debug_artifacts: dict[str, Path]
    search_url: str


def build_search_url(options: OhanaSearchOptions) -> str:
    if options.search_url:
        return options.search_url

    if not options.location:
        raise ValueError("Provide either search_url or location.")

    return build_ohana_search_url(
        location=options.location,
        movein=options.movein,
        moveout=options.moveout,
        property_types=options.property_types,
        type_of_places=options.type_of_places,
        num_bedrooms=options.num_bedrooms,
        min_price=options.min_price,
        max_price=options.max_price,
        pet_policy=options.pet_policy,
        furnished_status=options.furnished_status,
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


def _fetch_listing_api_data(page, records: list[dict[str, Any]]) -> None:
    print("\nFetching listing init/data for each extracted record...")

    for i, record in enumerate(records, start=1):
        detail_url = record.get("detail_url") or record.get("url")

        print(f"[{i}/{len(records)}] {record.get('title', 'Untitled listing')}")
        print(f"  detail_url: {detail_url}")

        if not detail_url or "/listing/" not in detail_url:
            record["listing_api_status"] = "skipped_no_detail_url"
            print("  skipped: no real listing URL")
            continue

        try:
            data = fetch_listing_init_data(page, detail_url)
            location_data = extract_address_geographic_address(data)

            record["init_data_url"] = build_init_data_url(detail_url)

            if location_data:
                record.update(location_data)
                record["listing_api_status"] = "ok"
                print(
                    f"  exact location: "
                    f"{record.get('listing_latitude')}, "
                    f"{record.get('listing_longitude')}"
                )
                print(f"  address: {record.get('listing_address')}")
            else:
                record["listing_api_status"] = "ok_no_address_geographic_address_found"
                print("  API worked, but no address_geographic_address found")

        except Exception as e:
            record["listing_api_status"] = "failed"
            record["listing_api_error"] = str(e)
            print(f"  failed: {e}")

        page.wait_for_timeout(500)


def run_ohana_search(options: OhanaSearchOptions) -> OhanaSearchResult:
    ensure_dirs()
    search_url = build_search_url(options)
    print(f"Using search URL: {search_url}")

    settings = get_settings(
        search_url=search_url,
        location=options.location,
        state_file=options.state_file,
        selectors_file=options.selectors_file,
    )
    selectors = load_selectors(settings.selectors_file)

    if not settings.state_file.exists():
        raise FileNotFoundError(
            f"No saved login session found at {settings.state_file}. Run: python save_ohana_login.py"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_output = RAW_DIR / f"ohana_results_{timestamp}.jsonl"
    csv_output = PROCESSED_DIR / f"ohana_results_{timestamp}.csv"

    playwright, browser, context, page = build_context(
        headless=options.headless,
        state_file=settings.state_file,
        slow_mo_ms=100,
    )
    try:
        print(f"Opening search page: {search_url}")
        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2_000)

        if options.manual_search:
            print("\nRun the search manually in the browser window.")
            print("When the results are visible, return here and press ENTER.")
            input("Press ENTER to extract visible results... ")
        else:
            if "/search?" in search_url or "/sublet/" in search_url:
                print("Using filtered search URL directly; skipping automated search input.")
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(3_000)
            else:
                print(f"Trying automated search for: {settings.location}")
                ok = try_automated_search(page, settings.location, selectors)
                if not ok:
                    print("Could not find a search input with the current selectors.")
                    print("Run again with --manual-search or edit selectors.example.json.")
                    input("Run the search manually now, then press ENTER to extract visible results... ")
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(2_000)

        scroll_for_results(page, options.scrolls, pause_ms=1_000)
        debug = save_debug_artifacts(page, DEBUG_DIR)
        print("Calling extract_listings...")
        records = extract_listings(
            page,
            selectors,
            max_listings=options.max_listings,
            capture_detail_urls=options.capture_detail_urls or options.fetch_listing_api,
        )

        if options.fetch_listing_api:
            _fetch_listing_api_data(page, records)

        jsonl_count = write_jsonl(records, raw_output)
        csv_count = write_csv(records, csv_output)
        save_storage_state(context, settings.state_file)

        print("\nDone.")
        print(f"Extracted records: {len(records)}")
        print(f"JSONL: {raw_output} ({jsonl_count} records)")
        print(f"CSV:   {csv_output} ({csv_count} records)")
        print(f"Debug screenshot: {debug.get('screenshot')}")
        print(f"Debug HTML:       {debug.get('html')}")
        if len(records) == 0:
            print("\nNo records were extracted. Open data/debug/search_page.html, inspect the listing card HTML,")
            print("then update selectors.example.json and rerun with --manual-search.")

        if options.keep_open:
            input("\nPress ENTER to close the browser... ")

        return OhanaSearchResult(
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
