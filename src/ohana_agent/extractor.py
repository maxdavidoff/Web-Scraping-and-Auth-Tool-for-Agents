from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from .parsing import DATE_RE, PRICE_RE, clean_text, normalize_listing


LISTING_TEXT_RE = ("room", "apartment", "house", "studio", "sublet")


def _first_text(card: Locator, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            loc = card.locator(selector).first
            if loc.count() > 0:
                text = clean_text(loc.inner_text(timeout=1_000))
                if text:
                    return text
        except Exception:
            continue
    return ""


def _first_attr(card: Locator, selectors: list[str], attr: str) -> str:
    for selector in selectors:
        try:
            loc = card.locator(selector).first
            if loc.count() > 0:
                value = loc.get_attribute(attr, timeout=1_000)
                if value:
                    return value
        except Exception:
            continue
    return ""


def _all_image_srcs(card: Locator) -> list[str]:
    srcs: list[str] = []
    try:
        images = card.locator("img")
        for i in range(min(images.count(), 8)):
            src = images.nth(i).get_attribute("src", timeout=1_000)
            if src:
                srcs.append(src)
    except Exception:
        pass
    return srcs


def _safe_count(locator: Locator) -> int:
    try:
        return locator.count()
    except Exception:
        return 0


def _listing_candidate_score(card: Locator, raw_text: str) -> int:
    text = clean_text(raw_text)
    lowered = text.lower()

    if not text or lowered in {"chevron_right", "chevron_left", "keyboard_arrow_right"}:
        return 0

    score = 0

    try:
        element_id = card.get_attribute("id", timeout=500) or ""
        if element_id.startswith("listing-"):
            score += 6
    except Exception:
        pass

    if PRICE_RE.search(text):
        score += 4
    if DATE_RE.search(text):
        score += 2
    if any(term in lowered for term in LISTING_TEXT_RE):
        score += 2
    if _safe_count(card.locator("img")) > 0:
        score += 1
    if len(text) >= 35:
        score += 1

    return score


def _selector_quality(page: Page, selector: str, sample_size: int = 12) -> tuple[int, int, int]:
    try:
        cards = page.locator(selector)
        count = cards.count()
    except Exception:
        return (0, 0, 0)

    valid_count = 0
    score_total = 0

    for i in range(min(count, sample_size)):
        try:
            raw_text = cards.nth(i).inner_text(timeout=1_000)
        except Exception:
            raw_text = ""
        score = _listing_candidate_score(cards.nth(i), raw_text)
        if score >= 5:
            valid_count += 1
            score_total += score

    return (valid_count, score_total, count)


def _wait_for_cards(page: Page, selector: str, timeout_ms: int = 8_000) -> None:
    try:
        page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        pass


def _capture_detail_url_from_card(page: Page, card: Locator, search_url: str, card_selector: str) -> str:
    """
    Click a listing card, capture the real /listing/... URL, then return to search page.

    Handles both:
    - same-tab navigation
    - new tab / popup navigation
    """
    try:
        card.scroll_into_view_if_needed(timeout=3_000)
        page.wait_for_timeout(500)

        before_url = page.url
        detail_url = ""

        # Some Bubble cards open detail pages in a new tab/popup.
        try:
            with page.context.expect_page(timeout=3_000) as new_page_info:
                card.click(timeout=5_000, force=True)

            new_page = new_page_info.value
            new_page.wait_for_load_state("domcontentloaded", timeout=8_000)
            new_page.wait_for_timeout(1_000)

            if "/listing/" in new_page.url:
                detail_url = new_page.url

            new_page.close()

        except Exception:
            # If no new tab opened, try same-tab navigation.
            try:
                card.click(timeout=5_000, force=True)
            except Exception:
                try:
                    card.evaluate("(el) => el.click()")
                except Exception:
                    pass

            try:
                page.wait_for_url("**/listing/**", timeout=5_000)
            except Exception:
                pass

            page.wait_for_timeout(1_000)

            if "/listing/" in page.url and page.url != before_url:
                detail_url = page.url

        # Return to search page either way.
        if page.url != search_url:
            page.goto(search_url, wait_until="domcontentloaded")

        _wait_for_cards(page, card_selector)
        page.wait_for_timeout(1_000)

        return detail_url

    except Exception as e:
        print(f"Failed to capture detail URL: {e}")

        try:
            page.goto(search_url, wait_until="domcontentloaded")
            _wait_for_cards(page, card_selector)
            page.wait_for_timeout(1_000)
        except Exception:
            pass

        return ""


def extract_listings(
    page: Page,
    selectors: dict[str, Any],
    *,
    max_listings: int = 25,
    capture_detail_urls: bool = False,
) -> list[dict]:
    result_card_selectors = selectors.get("result_card_selectors", [])
    detail_link_selectors = selectors.get("detail_link_selectors", ["a[href]"])
    title_selectors = selectors.get("title_selectors", [])
    price_selectors = selectors.get("price_selectors", [])
    location_selectors = selectors.get("location_selectors", [])

    search_url = page.url
    records: list[dict] = []
    seen_ids: set[str] = set()

    # Use the best selector directly so we can re-query after every back/navigation.
    active_selector = None
    best_quality = (0, 0, 0)

    for selector in result_card_selectors:
        quality = _selector_quality(page, selector)
        if quality > best_quality:
            best_quality = quality
            active_selector = selector

    if not active_selector:
        print("Cards found: 0")
        return []

    best_count = best_quality[2]
    max_candidates = min(best_count, max(max_listings * 3, max_listings))
    print(f"Cards found with selector '{active_selector}': {best_count}")
    print(f"Extracting up to {max_listings} listings from {max_candidates} candidates")

    for i in range(max_candidates):
        if len(records) >= max_listings:
            break
        try:
            # Re-query every time because clicking/backing can stale old locators.
            cards = page.locator(active_selector)
            card = cards.nth(i)

            raw_text = card.inner_text(timeout=2_000)
            raw_text_clean = clean_text(raw_text)
            candidate_score = _listing_candidate_score(card, raw_text_clean)

            if candidate_score < 5:
                print(f"Skipping non-listing candidate {i}: {raw_text_clean[:80]}")
                continue

            href = _first_attr(card, detail_link_selectors, "href")
            title = _first_text(card, title_selectors)
            price = _first_text(card, price_selectors)
            location = _first_text(card, location_selectors)
            image_urls = _all_image_srcs(card)

            detail_url = href

            if capture_detail_urls and (not detail_url or "/listing/" not in detail_url):
                print(f"[{i + 1}/{max_candidates}] Capturing real detail URL...")
                detail_url = _capture_detail_url_from_card(page, card, search_url, active_selector)
                print(f"  detail_url: {detail_url}")

            record = normalize_listing(
                raw_text=raw_text,
                source_url=search_url,
                base_url=search_url,
                title=title,
                price=price,
                location=location,
                url=detail_url,
                image_urls=image_urls,
            )

            if detail_url:
                record["detail_url"] = detail_url

            if record["id"] not in seen_ids:
                records.append(record)
                seen_ids.add(record["id"])

        except Exception as e:
            print(f"Failed to extract card {i}: {e}")

            try:
                if page.url != search_url:
                    page.goto(search_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(1_000)
            except Exception:
                pass

            continue

    return records


def save_debug_artifacts(page: Page, debug_dir: Path) -> dict[str, Path]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = debug_dir / "search_page.png"
    html_path = debug_dir / "search_page.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except PlaywrightTimeoutError:
        pass

    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass

    return {"screenshot": screenshot_path, "html": html_path}

