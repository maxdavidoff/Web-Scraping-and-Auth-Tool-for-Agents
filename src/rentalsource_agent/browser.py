from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


def build_context(
    *,
    headless: bool,
    state_file: Path | None,
    slow_mo_ms: int = 100,
) -> tuple[Any, Browser, BrowserContext, Page]:
    """Create a Chromium browser/context/page."""
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo_ms)

    kwargs: dict[str, Any] = {"viewport": {"width": 1440, "height": 1000}}
    if state_file and state_file.exists():
        kwargs["storage_state"] = str(state_file)

    context = browser.new_context(**kwargs)
    page = context.new_page()
    page.set_default_timeout(10_000)
    return playwright, browser, context, page


def save_storage_state(context: BrowserContext, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(state_file))
