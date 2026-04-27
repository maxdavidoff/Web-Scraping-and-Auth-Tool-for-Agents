#!/usr/bin/env python3
from __future__ import annotations

import argparse

from src.ohana_agent.search_runner import OhanaSearchOptions, run_ohana_search


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

    run_ohana_search(
        OhanaSearchOptions(
            search_url=args.search_url,
            state_file=args.state_file,
            selectors_file=args.selectors_file,
            max_listings=args.max_listings,
            scrolls=args.scrolls,
            headless=args.headless,
            manual_search=args.manual_search,
            keep_open=args.keep_open,
            fetch_listing_api=args.fetch_listing_api,
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
            capture_detail_urls=args.capture_detail_urls,
        )
    )


if __name__ == "__main__":
    main()
