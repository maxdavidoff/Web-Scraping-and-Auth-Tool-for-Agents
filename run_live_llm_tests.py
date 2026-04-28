#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    if not os.getenv("MISTRAL_API_KEY"):
        print("Set MISTRAL_API_KEY before running live LLM tests.", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env["RUN_LIVE_LLM_TESTS"] = "1"
    command = [sys.executable, "-m", "unittest", "tests.test_intent_extractor", "-v"]
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
