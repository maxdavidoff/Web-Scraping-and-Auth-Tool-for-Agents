from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except ModuleNotFoundError:
    class PlaywrightTimeoutError(Exception):
        pass

from .parsing import clean_text, normalize_listing


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
    try:
        value = card.get_attribute(attr, timeout=1_000)
        if value:
            return value
    except Exception:
        pass

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
            image = images.nth(i)
            src = image.get_attribute("src", timeout=1_000)
            data_src = image.get_attribute("data-src", timeout=1_000)
            for value in [src, data_src]:
                if value:
                    srcs.append(value)
    except Exception:
        pass
    return list(dict.fromkeys(srcs))


def _listing_id_from_url(url: str) -> str:
    pieces = [piece for piece in url.rstrip("/").split("-") if piece]
    if pieces and pieces[-1].isdigit():
        return pieces[-1]
    return ""


def _json_ld_documents_from_page(page: Page) -> list[dict]:
    documents: list[dict] = []
    try:
        scripts = page.locator("script[type='application/ld+json']")
        for i in range(scripts.count()):
            text = scripts.nth(i).text_content(timeout=1_000)
            if not text:
                continue
            try:
                documents.append(json.loads(text))
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return documents


def _iter_json_ld_nodes(obj: Any) -> list[dict]:
    nodes: list[dict] = []

    if isinstance(obj, dict):
        nodes.append(obj)
        graph = obj.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                nodes.extend(_iter_json_ld_nodes(item))
    elif isinstance(obj, list):
        for item in obj:
            nodes.extend(_iter_json_ld_nodes(item))

    return nodes


def _json_ld_listing_records(page: Page, max_listings: int) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()

    for document in _json_ld_documents_from_page(page):
        for node in _iter_json_ld_nodes(document):
            main_entity = node.get("mainEntity") if isinstance(node, dict) else None
            if not isinstance(main_entity, dict) or main_entity.get("@type") != "ItemList":
                continue

            for item in main_entity.get("itemListElement", []):
                if not isinstance(item, dict):
                    continue

                url = item.get("url", "")
                title = item.get("name", "")
                image = item.get("image", "")
                raw_text = title or url
                record = normalize_listing(
                    raw_text=raw_text,
                    source_url=page.url,
                    base_url=page.url,
                    title=title,
                    url=url,
                    image_urls=[image] if image else [],
                )

                if url:
                    record["detail_url"] = record["url"]

                listing_id = _listing_id_from_url(record["url"])
                if listing_id:
                    record["listing_id"] = listing_id

                if record["id"] in seen:
                    continue
                records.append(record)
                seen.add(record["id"])

                if len(records) >= max_listings:
                    return records

    return records


def extract_listings(
    page: Page,
    selectors: dict[str, Any],
    *,
    max_listings: int = 25,
) -> list[dict]:
    result_card_selectors = selectors.get("result_card_selectors", [])
    detail_link_selectors = selectors.get("detail_link_selectors", ["a[href*='/details/']"])
    title_selectors = selectors.get("title_selectors", [])
    price_selectors = selectors.get("price_selectors", [])
    location_selectors = selectors.get("location_selectors", [])
    property_type_selectors = selectors.get("property_type_selectors", [])

    records: list[dict] = []
    seen_ids: set[str] = set()
    active_selector = None
    best_count = 0

    for selector in result_card_selectors:
        try:
            count = page.locator(selector).count()
            if count > best_count:
                best_count = count
                active_selector = selector
        except Exception:
            continue

    if not active_selector:
        records = _json_ld_listing_records(page, max_listings)
        print(f"Cards found: 0; JSON-LD records found: {len(records)}")
        return records

    total_cards = min(best_count, max_listings)
    print(f"Cards found with selector '{active_selector}': {best_count}")
    print(f"Extracting up to {total_cards} cards")

    for i in range(total_cards):
        try:
            cards = page.locator(active_selector)
            card = cards.nth(i)

            raw_text = card.inner_text(timeout=2_000)
            raw_text_clean = clean_text(raw_text)
            if len(raw_text_clean) < 20:
                print(f"Skipping non-listing card {i}: {raw_text_clean[:80]}")
                continue

            href = _first_attr(card, detail_link_selectors, "href")
            title = _first_text(card, title_selectors)
            title_attr = _first_attr(card, [], "title")
            price = _first_text(card, price_selectors)
            location = _first_text(card, location_selectors)
            property_type = _first_text(card, property_type_selectors)
            image_urls = _all_image_srcs(card)

            record = normalize_listing(
                raw_text=raw_text,
                source_url=page.url,
                base_url=page.url,
                title=title or title_attr,
                price=price,
                location=location,
                url=href,
                image_urls=image_urls,
                property_type=property_type,
            )

            if href:
                record["detail_url"] = record["url"]

            listing_id = _listing_id_from_url(record["url"])
            if listing_id:
                record["listing_id"] = listing_id

            if record["id"] not in seen_ids:
                records.append(record)
                seen_ids.add(record["id"])

        except Exception as e:
            print(f"Failed to extract card {i}: {e}")
            continue

    if records:
        return records

    records = _json_ld_listing_records(page, max_listings)
    print(f"DOM extraction produced no records; JSON-LD records found: {len(records)}")
    return records


def save_debug_artifacts(page: Page, debug_dir: Path) -> dict[str, Path]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = debug_dir / "rentalsource_search_page.png"
    html_path = debug_dir / "rentalsource_search_page.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except PlaywrightTimeoutError:
        pass

    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass

    return {"screenshot": screenshot_path, "html": html_path}
