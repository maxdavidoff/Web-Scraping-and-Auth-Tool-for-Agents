#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from src.housing_agent import DEFAULT_MISTRAL_MODEL, extract_housing_intent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract provider-neutral housing intent with Mistral and show provider query planning."
    )
    parser.add_argument("request", nargs="+", help="Natural-language housing request to extract.")
    parser.add_argument("--model", default=DEFAULT_MISTRAL_MODEL, help="Mistral model to use.")
    parser.add_argument(
        "--providers",
        nargs="+",
        default=None,
        help="Optional provider subset for query planning, e.g. ohana rentalsource affordablehousing.",
    )
    args = parser.parse_args()

    result = extract_housing_intent(
        " ".join(args.request),
        model=args.model,
        providers=args.providers,
    )

    print(json.dumps(_to_jsonable(result), indent=2, ensure_ascii=False))


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    main()
