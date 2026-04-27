from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTH_DIR = PROJECT_ROOT / "auth"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DEBUG_DIR = DATA_DIR / "debug"
DEFAULT_STATE_FILE = AUTH_DIR / "rentalsource_state.json"
DEFAULT_SELECTORS_FILE = PROJECT_ROOT / "selectors.rentalsource.json"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    start_url: str
    search_url: str
    location: str
    state_file: Path
    selectors_file: Path


def get_settings(
    start_url: str | None = None,
    search_url: str | None = None,
    location: str | None = None,
    state_file: str | Path | None = None,
    selectors_file: str | Path | None = None,
) -> Settings:
    return Settings(
        start_url=start_url or os.getenv("RENTALSOURCE_START_URL", "https://www.rentalsource.com/"),
        search_url=search_url or os.getenv("RENTALSOURCE_SEARCH_URL", "https://www.rentalsource.com/"),
        location=location or os.getenv("RENTALSOURCE_LOCATION", "Boston, MA"),
        state_file=Path(state_file) if state_file else DEFAULT_STATE_FILE,
        selectors_file=Path(selectors_file) if selectors_file else DEFAULT_SELECTORS_FILE,
    )


def load_selectors(path: str | Path | None = None) -> dict[str, Any]:
    selector_path = Path(path) if path else DEFAULT_SELECTORS_FILE
    if not selector_path.exists():
        raise FileNotFoundError(f"Selectors file not found: {selector_path}")
    with selector_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dirs() -> None:
    for directory in [AUTH_DIR, RAW_DIR, PROCESSED_DIR, DEBUG_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
