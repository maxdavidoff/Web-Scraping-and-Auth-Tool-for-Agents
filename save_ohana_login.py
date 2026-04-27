#!/usr/bin/env python3
from __future__ import annotations

import argparse

from src.ohana_agent.browser import build_context, save_storage_state
from src.ohana_agent.config import ensure_dirs, get_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open Ohana, let you log in manually, then save the browser session."
    )
    parser.add_argument("--start-url", default=None, help="URL to open first.")
    parser.add_argument("--state-file", default=None, help="Where to save Playwright storage state.")
    args = parser.parse_args()

    ensure_dirs()
    settings = get_settings(start_url=args.start_url, state_file=args.state_file)

    playwright, browser, context, page = build_context(
        headless=False,
        state_file=None,
        slow_mo_ms=100,
    )
    try:
        print(f"Opening: {settings.start_url}")
        page.goto(settings.start_url, wait_until="domcontentloaded")
        print("\nLog into Ohana in the browser window.")
        print("When you can see your logged-in account/search page, return here and press ENTER.")
        input("Press ENTER to save the login session... ")
        save_storage_state(context, settings.state_file)
        print(f"Saved login session to: {settings.state_file}")
    finally:
        context.close()
        browser.close()
        playwright.stop()


if __name__ == "__main__":
    main()
