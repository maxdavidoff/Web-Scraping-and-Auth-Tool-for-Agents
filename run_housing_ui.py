#!/usr/bin/env python3
from __future__ import annotations

from src.housing_agent.ui_server import build_arg_parser, run_from_args


def main() -> None:
    run_from_args(build_arg_parser().parse_args())


if __name__ == "__main__":
    main()
