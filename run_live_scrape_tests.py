#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys


LIVE_TEST_TARGETS = [
    "tests.test_rentalsource_agent.RentalSourceLiveBrowserScrapeTests",
    "tests.test_affordablehousing_agent.AffordableHousingLiveBrowserScrapeTests",
]


def run(command: list[str], *, env: dict[str, str] | None = None) -> int:
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, env=env).returncode


def playwright_is_installed() -> bool:
    try:
        import playwright  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run opt-in live scrape tests against RentalSource and AffordableHousing.com."
    )
    parser.add_argument(
        "--install-chromium",
        action="store_true",
        help="Run `python -m playwright install chromium` before the tests.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run full unittest discovery with live scrape tests enabled instead of only live tests.",
    )
    parser.add_argument(
        "--failfast",
        action="store_true",
        help="Stop on the first test failure.",
    )
    args = parser.parse_args()

    if not playwright_is_installed():
        print(
            "Playwright is not installed for this interpreter. Run:\n"
            "  python3 -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    if args.install_chromium:
        code = run([sys.executable, "-m", "playwright", "install", "chromium"])
        if code != 0:
            return code

    env = os.environ.copy()
    env["RUN_LIVE_SCRAPE_TESTS"] = "1"

    command = [sys.executable, "-m", "unittest", "-v"]
    if args.failfast:
        command.append("-f")

    if args.all:
        command.extend(["discover", "-s", "tests"])
    else:
        command.extend(LIVE_TEST_TARGETS)

    return run(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
