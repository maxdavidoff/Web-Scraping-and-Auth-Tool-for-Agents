#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.rentalsource_agent.browser import build_context, save_storage_state
from src.rentalsource_agent.config import DEBUG_DIR, PROCESSED_DIR, RAW_DIR, ensure_dirs, get_settings, load_selectors
from src.rentalsource_agent.detail import enrich_record_with_detail
from src.rentalsource_agent.extractor import extract_listings, save_debug_artifacts
from src.rentalsource_agent.search_url import build_rentalsource_search_url
from src.rentalsource_agent.storage import write_csv, write_jsonl


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


def _any_truthy(values: list[str] | None) -> bool:
    if not values:
        return False
    return any(value.strip().lower() not in {"", "0", "false", "no", "none"} for value in values)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a RentalSource search and save listing results."
    )
    parser.add_argument("--search-url", default=None, help="RentalSource page to open for searching.")
    parser.add_argument("--state-file", default=None, help="Saved Playwright storage state from save_rentalsource_login.py.")
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
        "--fetch-listing-detail",
        action="store_true",
        help="Fetch each RentalSource detail page and merge JSON-LD address/price/lat/lng fields.",
    )
    parser.add_argument(
        "--fetch-listing-api",
        action="store_true",
        help="Compatibility alias for --fetch-listing-detail.",
    )
    parser.add_argument(
        "--capture-detail-urls",
        action="store_true",
        help="Accepted for Ohana CLI parity; RentalSource result cards already include detail URLs.",
    )
    parser.add_argument(
        "--save-detail-debug",
        action="store_true",
        help="Save parsed detail JSON-LD snippets under data/debug/rentalsource_detail/.",
    )
    parser.add_argument("--location", default=None, help="Location, e.g. 'Boston, MA'")
    parser.add_argument("--property-types", nargs="+", default=None, help="Property types, e.g. Apartment House Condo")
    parser.add_argument("--num-bedrooms", type=int, default=None, help="Minimum bedrooms.")
    parser.add_argument("--num-bathrooms", type=float, default=None, help="Minimum bathrooms.")
    parser.add_argument("--min-price", type=int, default=None, help="Minimum monthly rent.")
    parser.add_argument("--max-price", type=int, default=None, help="Maximum monthly rent.")
    parser.add_argument("--pets", action="store_true", help="Only pet-friendly listings.")
    parser.add_argument("--photos", action="store_true", help="Only listings with photos.")
    parser.add_argument("--verified", action="store_true", help="Only verified listings.")
    parser.add_argument("--featured", action="store_true", help="Only featured listings.")
    parser.add_argument(
        "--sort",
        default=None,
        help="Sort value, e.g. relevance, verified, price, price-high, newest, updated, popular.",
    )
    parser.add_argument("--page", type=int, default=None, help="RentalSource result page number.")
    parser.add_argument("--movein", default=None, help="Accepted for Ohana CLI parity; RentalSource search URLs ignore it.")
    parser.add_argument("--moveout", default=None, help="Accepted for Ohana CLI parity; RentalSource search URLs ignore it.")
    parser.add_argument("--type-of-places", nargs="+", default=None, help="Accepted for Ohana CLI parity; ignored.")
    parser.add_argument("--pet-policy", nargs="+", default=None, help="Ohana-style pet flag; any value enables --pets.")
    parser.add_argument("--furnished-status", nargs="+", default=None, help="Accepted for Ohana CLI parity; ignored.")
    args = parser.parse_args()

    ensure_dirs()
    if args.search_url:
        search_url = args.search_url
    else:
        if not args.location:
            raise ValueError("Provide either --search-url or --location.")

        search_url = build_rentalsource_search_url(
            location=args.location,
            property_types=args.property_types,
            num_bedrooms=args.num_bedrooms,
            num_bathrooms=args.num_bathrooms,
            min_price=args.min_price,
            max_price=args.max_price,
            pets=args.pets or _any_truthy(args.pet_policy),
            photos=args.photos,
            verified=args.verified,
            featured=args.featured,
            sort=args.sort,
            page=args.page,
        )

    print(f"Using search URL: {search_url}")

    settings = get_settings(
        search_url=search_url,
        location=args.location,
        state_file=args.state_file,
        selectors_file=args.selectors_file,
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
        headless=args.headless,
        state_file=state_file,
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
            if args.search_url or args.location:
                print("Using RentalSource URL directly; skipping automated search input.")
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(2_000)
            else:
                print(f"Trying automated search for: {settings.location}")
                ok = try_automated_search(page, settings.location, selectors)
                if not ok:
                    print("Could not find a search input with the current selectors.")
                    print("Run again with --manual-search or edit selectors.rentalsource.json.")
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
            capture_detail_urls=False,
        )

        if args.fetch_listing_detail or args.fetch_listing_api:
            print("\nFetching RentalSource detail pages for each extracted record...")
            detail_debug_dir = DEBUG_DIR / "rentalsource_detail" if args.save_detail_debug else None
            for i, record in enumerate(records, start=1):
                detail_url = record.get("detail_url") or record.get("url")
                print(f"[{i}/{len(records)}] {record.get('title', 'Untitled listing')}")
                print(f"  detail_url: {detail_url}")

                enrich_record_with_detail(
                    page=page,
                    record=record,
                    debug_dir=detail_debug_dir,
                )

                status = record.get("listing_detail_status")
                if status == "ok":
                    print(
                        f"  exact location: "
                        f"{record.get('listing_latitude')}, "
                        f"{record.get('listing_longitude')}"
                    )
                    print(f"  address: {record.get('listing_address')}")
                else:
                    print(f"  detail status: {status}")

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
            print("\nNo records were extracted. Open data/debug/rentalsource_search_page.html, inspect the listing card HTML,")
            print("then update selectors.rentalsource.json and rerun with --manual-search.")

        if args.keep_open:
            input("\nPress ENTER to close the browser... ")
    finally:
        context.close()
        browser.close()
        playwright.stop()


if __name__ == "__main__":
    main()
