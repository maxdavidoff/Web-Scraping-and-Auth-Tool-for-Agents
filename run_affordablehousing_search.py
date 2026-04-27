#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.affordablehousing_agent.browser import build_context, save_storage_state
from src.affordablehousing_agent.config import DEBUG_DIR, PROCESSED_DIR, RAW_DIR, ensure_dirs, get_settings, load_selectors
from src.affordablehousing_agent.extractor import extract_listings, save_debug_artifacts
from src.affordablehousing_agent.search_url import build_affordablehousing_search_url
from src.affordablehousing_agent.storage import write_csv, write_jsonl


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


def has_concrete_search_path(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    return bool(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an AffordableHousing.com search and save listing results."
    )
    parser.add_argument("--search-url", default=None, help="AffordableHousing.com page to open for searching.")
    parser.add_argument("--state-file", default=None, help="Saved Playwright storage state from save_affordablehousing_login.py.")
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
        "--capture-detail-urls",
        action="store_true",
        help="Click any listing card without a direct href and capture the resulting detail URL.",
    )
    parser.add_argument("--location", default=None, help="Location, e.g. 'Boston, MA'")
    parser.add_argument("--property-types", nargs="+", default=None, help="Property types, e.g. Apartment House")
    parser.add_argument("--num-bedrooms", type=int, default=None, help="Number of bedrooms. Use 0 for studio.")
    parser.add_argument("--min-price", type=int, default=None, help="Accepted for CLI parity; use manual filters for min price.")
    parser.add_argument("--max-price", type=int, default=None, help="Maximum price, e.g. 1500.")
    parser.add_argument("--pet-friendly", action="store_true", help="Add the pet-friendly SEO filter.")
    parser.add_argument("--section8", action="store_true", help="Add the Section 8 owner SEO filter.")
    parser.add_argument("--income-restricted", action="store_true", help="Add the income-restricted SEO filter.")
    parser.add_argument("--wheelchair-accessible", action="store_true", help="Add the wheelchair-accessible SEO filter.")
    parser.add_argument("--utilities-included", action="store_true", help="Add the utilities-included SEO filter.")
    parser.add_argument("--washer-dryer", action="store_true", help="Add the washer-dryer SEO filter.")
    args = parser.parse_args()

    ensure_dirs()
    if args.search_url:
        search_url = args.search_url
    else:
        if not args.location:
            raise ValueError("Provide either --search-url or --location.")

        search_url = build_affordablehousing_search_url(
            location=args.location,
            property_types=args.property_types,
            num_bedrooms=args.num_bedrooms,
            max_price=args.max_price,
            pet_friendly=args.pet_friendly,
            section8=args.section8,
            income_restricted=args.income_restricted,
            wheelchair_accessible=args.wheelchair_accessible,
            utilities_included=args.utilities_included,
            washer_dryer=args.washer_dryer,
        )

    print(f"Using search URL: {search_url}")
    if args.min_price is not None:
        print("Note: --min-price is accepted for CLI parity, but this tool does not guess a stable min-price URL.")

    settings = get_settings(
        search_url=search_url,
        location=args.location,
        state_file=args.state_file,
        selectors_file=args.selectors_file,
    )

    selectors = load_selectors(settings.selectors_file)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_output = RAW_DIR / f"affordablehousing_results_{timestamp}.jsonl"
    csv_output = PROCESSED_DIR / f"affordablehousing_results_{timestamp}.csv"

    playwright, browser, context, page = build_context(
        headless=args.headless,
        state_file=settings.state_file,
        slow_mo_ms=100,
    )
    try:
        if not settings.state_file.exists():
            print(f"No saved browser session found at {settings.state_file}; continuing as a visitor.")

        print(f"Opening search page: {search_url}")
        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2_000)

        if args.manual_search:
            print("\nRun the search manually in the browser window.")
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
                print(f"Trying automated search for: {settings.location}")
                ok = try_automated_search(page, settings.location, selectors)
                if not ok:
                    print("Could not find a search input with the current selectors.")
                    print("Run again with --manual-search or edit selectors.affordablehousing.json.")
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
            capture_detail_urls=args.capture_detail_urls,
        )

        fallback_location = args.location or settings.location
        if not records and not args.manual_search and fallback_location and not has_concrete_search_path(search_url):
            fallback_url = build_affordablehousing_search_url(
                location=fallback_location,
                property_types=args.property_types,
                num_bedrooms=args.num_bedrooms,
                max_price=args.max_price,
                pet_friendly=args.pet_friendly,
                section8=args.section8,
                income_restricted=args.income_restricted,
                wheelchair_accessible=args.wheelchair_accessible,
                utilities_included=args.utilities_included,
                washer_dryer=args.washer_dryer,
            )

            if fallback_url != page.url:
                print(f"No cards found from search input; trying direct search URL: {fallback_url}")
                page.goto(fallback_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(2_000)
                scroll_for_results(page, args.scrolls, pause_ms=1_000)
                debug = save_debug_artifacts(page, DEBUG_DIR)
                records = extract_listings(
                    page,
                    selectors,
                    max_listings=args.max_listings,
                    capture_detail_urls=args.capture_detail_urls,
                )

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
            print("\nNo records were extracted. Open data/debug/affordablehousing_search_page.html,")
            print("inspect the listing card HTML, then update selectors.affordablehousing.json.")

        if args.keep_open:
            input("\nPress ENTER to close the browser... ")
    finally:
        context.close()
        browser.close()
        playwright.stop()


if __name__ == "__main__":
    main()
