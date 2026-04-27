#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.ohana_agent.browser import build_context, save_storage_state
from src.ohana_agent.config import DEBUG_DIR, PROCESSED_DIR, RAW_DIR, ensure_dirs, get_settings, load_selectors
from src.ohana_agent.extractor import extract_listings, save_debug_artifacts
from src.ohana_agent.storage import write_csv, write_jsonl

from src.ohana_agent.search_url import build_ohana_search_url
from src.ohana_agent.listing_api import (
    build_init_data_url,
    fetch_listing_init_data,
    extract_address_geographic_address,
)


def try_automated_search(page, location: str, selectors: dict) -> bool:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an Ohana search using a saved login session and save listing results."
    )
    parser.add_argument("--search-url", default=None, help="Ohana page to open for searching.")
    parser.add_argument("--state-file", default=None, help="Saved Playwright storage state from save_ohana_login.py.")
    parser.add_argument("--selectors-file", default=None, help="JSON file with editable selectors.")
    parser.add_argument("--max-listings", type=int, default=25, help="Max cards to extract.")
    parser.add_argument("--scrolls", type=int, default=3, help="How many times to scroll before extraction.")
    parser.add_argument("--headless", action="store_true", help="Run browser hidden. Keep off while testing.")
    parser.add_argument(
        "--manual-search",
        action="store_true",
        help="Open browser and let you run the search manually before extraction.",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep browser open at the end until you press ENTER.",
    )
    parser.add_argument(
        "--fetch-listing-api",
        action="store_true",
        help="Capture real listing URLs and call Ohana init/data API for exact listing location.",
    )
    parser.add_argument("--location", default=None, help="Location, e.g. 'Boston, MA, USA'")
    parser.add_argument("--movein", default=None, help="Move-in date, e.g. 'May 1, 2026'")
    parser.add_argument("--moveout", default=None, help="Move-out date, e.g. 'May 31, 2026'")
    parser.add_argument("--property-types", nargs="+", default=None, help="Property types, e.g. Apartment House")
    parser.add_argument("--type-of-places", nargs="+", default=None, help="Place types, e.g. 'Private room'")
    parser.add_argument("--num-bedrooms", type=int, default=None, help="Number of bedrooms")
    parser.add_argument("--min-price", type=int, default=None, help="Minimum price")
    parser.add_argument("--max-price", type=int, default=None, help="Maximum price")
    parser.add_argument("--pet-policy", nargs="+", default=None, help="Pet policy filters")
    parser.add_argument("--furnished-status", nargs="+", default=None, help="Furnished status filters")
    parser.add_argument(
        "--capture-detail-urls",
        action="store_true",
        help="Click each listing card and capture the real /listing/... URL.",
    )
    args = parser.parse_args()

    ensure_dirs()
    if args.search_url:
        search_url = args.search_url
    else:
        if not args.location:
            raise ValueError("Provide either --search-url or --location.")

        search_url = build_ohana_search_url(
            location=args.location,
            movein=args.movein,
            moveout=args.moveout,
            property_types=args.property_types,
            type_of_places=args.type_of_places,
            num_bedrooms=args.num_bedrooms,
            min_price=args.min_price,
            max_price=args.max_price,
            pet_policy=args.pet_policy,
            furnished_status=args.furnished_status,
        )

    print(f"Using search URL: {search_url}")

    settings = get_settings(
        search_url=search_url,
        location=args.location,
        state_file=args.state_file,
        selectors_file=args.selectors_file,
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
        headless=args.headless,
        state_file=settings.state_file,
        slow_mo_ms=100,
    )
    try:
        print(f"Opening search page: {search_url}")
        page.goto(search_url, wait_until="domcontentloaded")    
        page.wait_for_timeout(2_000)

        if args.manual_search:
            print("\nRun the search manually in the browser window.")
            print("When the results are visible, return here and press ENTER.")
            input("Press ENTER to extract visible results... ")
        else:
            if "/search?" in search_url:
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

        scroll_for_results(page, args.scrolls, pause_ms=1_000)
        debug = save_debug_artifacts(page, DEBUG_DIR)
        print("Calling extract_listings...")
        records = extract_listings(
            page,
            selectors,
            max_listings=args.max_listings,
            capture_detail_urls=args.capture_detail_urls or args.fetch_listing_api,
        )

        if args.fetch_listing_api:
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

        if args.keep_open:
            input("\nPress ENTER to close the browser... ")
    finally:
        context.close()
        browser.close()
        playwright.stop()


if __name__ == "__main__":
    main()
