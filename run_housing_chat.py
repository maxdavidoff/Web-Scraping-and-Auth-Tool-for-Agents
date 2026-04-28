#!/usr/bin/env python3
from __future__ import annotations

import argparse

from src.housing_agent import DEFAULT_MISTRAL_MODEL
from src.housing_agent.interactive_agent import InteractiveHousingAgent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chat with the provider-aware housing agent. Plans first; executes only after confirmation."
    )
    parser.add_argument("--model", default=DEFAULT_MISTRAL_MODEL, help="Mistral model to use.")
    parser.add_argument(
        "--providers",
        nargs="+",
        default=None,
        help="Optional provider subset, e.g. ohana rentalsource affordablehousing.",
    )
    parser.add_argument("--max-listings", type=int, default=10, help="Maximum listings per provider when executing.")
    parser.add_argument("--scrolls", type=int, default=3, help="Browser scroll count per provider when executing.")
    parser.add_argument("--headed", action="store_true", help="Show browser windows when executing live scrapers.")
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

    agent = InteractiveHousingAgent(
        model=args.model,
        providers=args.providers,
        max_listings=args.max_listings,
        scrolls=args.scrolls,
        headless=not args.headed,
        state_file=args.state_file,
        selectors_file=args.selectors_file,
        fetch_listing_api=args.fetch_listing_api,
        capture_detail_urls=args.capture_detail_urls,
    )

    print("Housing chat agent")
    print("Tell me what you are looking for. Type `help` for commands or `quit` to exit.")
    while True:
        try:
            user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        turn = agent.handle_user_message(user_input)
        print(turn.message)
        if turn.state == "quit":
            break


if __name__ == "__main__":
    main()
