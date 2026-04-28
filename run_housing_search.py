#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from src.housing_agent import DEFAULT_MISTRAL_MODEL
from src.housing_agent.search_app import build_housing_search_response


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan a provider-aware housing search, and optionally execute executable scrapers."
    )
    parser.add_argument("request", nargs="+", help="Natural-language housing search request.")
    parser.add_argument("--model", default=DEFAULT_MISTRAL_MODEL, help="Mistral model to use.")
    parser.add_argument(
        "--providers",
        nargs="+",
        default=None,
        help="Optional provider subset, e.g. ohana rentalsource affordablehousing apartments_com.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run executable provider scrapers after planning. Without this flag, no scraping happens.",
    )
    parser.add_argument("--max-listings", type=int, default=10, help="Maximum listings per provider when executing.")
    parser.add_argument("--scrolls", type=int, default=3, help="Browser scroll count per provider when executing.")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser windows when executing live scrapers.",
    )
    parser.add_argument("--state-file", default=None, help="Optional saved browser state file for providers that need it.")
    parser.add_argument("--selectors-file", default=None, help="Optional selector file for providers that need it.")
    parser.add_argument(
        "--fetch-listing-api",
        action="store_true",
        help="Enable provider detail/API enrichment where supported.",
    )
    parser.add_argument(
        "--capture-detail-urls",
        action="store_true",
        help="Capture detail URLs where supported.",
    )
    args = parser.parse_args()

    response = build_housing_search_response(
        " ".join(args.request),
        model=args.model,
        providers=args.providers,
        execute=args.execute,
        max_listings=args.max_listings,
        scrolls=args.scrolls,
        headless=not args.headed,
        state_file=args.state_file,
        selectors_file=args.selectors_file,
        fetch_listing_api=args.fetch_listing_api,
        capture_detail_urls=args.capture_detail_urls,
    )
    print(json.dumps(response, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
