#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run opt-in live Mistral intent extraction tests."
    )
    parser.add_argument(
        "--failfast",
        action="store_true",
        help="Stop on the first test failure.",
    )
    args = parser.parse_args()

    if not os.getenv("MISTRAL_API_KEY"):
        print("Set MISTRAL_API_KEY before running live LLM tests.", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env["RUN_LIVE_LLM_TESTS"] = "1"
    command = [sys.executable, "-m", "unittest", "-v"]
    if args.failfast:
        command.append("-f")
    command.append("tests.test_intent_extractor")
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
