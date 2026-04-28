#!/usr/bin/env python3
from __future__ import annotations

import argparse

from src.affordablehousing_agent.search_runner import (
    AffordableHousingSearchOptions,
    run_affordablehousing_search,
)


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
    parser.add_argument(
        "--fetch-listing-detail",
        action="store_true",
        help="Fetch each AffordableHousing detail page and merge exact address/lat/lng fields when available.",
    )
    parser.add_argument(
        "--fetch-listing-api",
        action="store_true",
        help="Compatibility alias for --fetch-listing-detail.",
    )
    parser.add_argument(
        "--save-detail-debug",
        action="store_true",
        help="Save parsed detail snippets under data/debug/affordablehousing_detail/.",
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

    run_affordablehousing_search(
        AffordableHousingSearchOptions(
            search_url=args.search_url,
            location=args.location,
            property_types=args.property_types,
            num_bedrooms=args.num_bedrooms,
            min_price=args.min_price,
            max_price=args.max_price,
            pet_friendly=args.pet_friendly,
            section8=args.section8,
            income_restricted=args.income_restricted,
            wheelchair_accessible=args.wheelchair_accessible,
            utilities_included=args.utilities_included,
            washer_dryer=args.washer_dryer,
            state_file=args.state_file,
            selectors_file=args.selectors_file,
            max_listings=args.max_listings,
            scrolls=args.scrolls,
            headless=args.headless,
            manual_search=args.manual_search,
            keep_open=args.keep_open,
            capture_detail_urls=args.capture_detail_urls,
            fetch_listing_detail=args.fetch_listing_detail or args.fetch_listing_api,
            save_detail_debug=args.save_detail_debug,
        )
    )


if __name__ == "__main__":
    main()
