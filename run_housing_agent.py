#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from src.ohana_agent.housing_agent import (
    DEFAULT_AGENT_MODEL,
    collect_interactive_housing_request,
    run_student_housing_agent,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Use an LLM to plan a student housing search, then run one or more provider scrapers."
    )
    parser.add_argument("request", nargs="*", help="Optional natural language housing request to seed the intake.")
    parser.add_argument("--model", default=DEFAULT_AGENT_MODEL, help="OpenAI model to use for planning/summarizing.")
    parser.add_argument("--state-file", default=None, help="Saved Playwright storage state from save_ohana_login.py.")
    parser.add_argument("--selectors-file", default=None, help="JSON file with editable selectors.")
    parser.add_argument("--max-listings", type=int, default=None, help="Override the planner's listing count.")
    parser.add_argument("--max-followups", type=int, default=6, help="Maximum intake follow-up questions before searching.")
    parser.add_argument("--scrolls", type=int, default=3, help="How many times to scroll before extraction.")
    parser.add_argument("--headed", action="store_true", help="Show the browser while scraping.")
    parser.add_argument("--one-shot", action="store_true", help="Skip intake follow-ups and search from the request immediately.")
    parser.add_argument(
        "--providers",
        nargs="+",
        default=None,
        help="Provider(s) to search: ohana, rentalsource, affordablehousing, or all. Defaults to the LLM plan.",
    )
    parser.add_argument(
        "--fetch-listing-api",
        action="store_true",
        help="Capture real listing URLs and call Ohana init/data API for exact listing location.",
    )
    parser.add_argument(
        "--capture-detail-urls",
        action="store_true",
        help="Click each listing card and capture the real /listing/... URL.",
    )
    parser.add_argument("--no-summary", action="store_true", help="Skip the LLM summary after scraping.")
    args = parser.parse_args()

    seed_request = " ".join(args.request).strip()
    if args.one_shot:
        if not seed_request:
            parser.error("--one-shot requires a request.")
        user_request = seed_request
    else:
        user_request = collect_interactive_housing_request(
            model=args.model,
            initial_request=seed_request or None,
            max_followups=args.max_followups,
        )
        if not user_request:
            return

    result = run_student_housing_agent(
        user_request,
        model=args.model,
        state_file=args.state_file,
        selectors_file=args.selectors_file,
        max_listings=args.max_listings,
        scrolls=args.scrolls,
        headless=not args.headed,
        fetch_listing_api=args.fetch_listing_api,
        capture_detail_urls=args.capture_detail_urls,
        providers=args.providers,
        summarize=not args.no_summary,
    )

    print("\nSearch plan:")
    print(json.dumps(asdict(result.plan), indent=2, ensure_ascii=False))
    print("\nProvider results:")
    for provider_result in result.search.provider_results:
        print(
            f"- {provider_result.provider}: {provider_result.status}, "
            f"{len(provider_result.records)} records"
        )
        if provider_result.search_url:
            print(f"  Search URL: {provider_result.search_url}")
        if provider_result.error:
            print(f"  Error: {provider_result.error}")

    print(f"\nSearch URL: {result.search.search_url}")
    print(f"CSV: {result.search.csv_output}")
    print(f"JSONL: {result.search.raw_output}")

    if result.summary:
        print("\nStudent-facing summary:")
        print(result.summary)


if __name__ == "__main__":
    main()
