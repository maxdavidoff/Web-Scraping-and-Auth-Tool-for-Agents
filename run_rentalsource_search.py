#!/usr/bin/env python3
from __future__ import annotations

import argparse

from src.rentalsource_agent.search_runner import (
    RentalSourceSearchOptions,
    run_rentalsource_search,
)


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

    run_rentalsource_search(
        RentalSourceSearchOptions(
            search_url=args.search_url,
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
            state_file=args.state_file,
            selectors_file=args.selectors_file,
            max_listings=args.max_listings,
            scrolls=args.scrolls,
            headless=args.headless,
            manual_search=args.manual_search,
            keep_open=args.keep_open,
            fetch_listing_detail=args.fetch_listing_detail or args.fetch_listing_api,
            save_detail_debug=args.save_detail_debug,
        )
    )


if __name__ == "__main__":
    main()
