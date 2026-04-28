from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.rentalsource_agent.detail import (
    enrich_record_with_detail,
    extract_detail_data,
    find_real_estate_listing,
    is_allowed_detail_url,
    parse_json_ld_documents,
)
from src.rentalsource_agent.extractor import extract_listings
from src.rentalsource_agent.config import load_selectors
from src.rentalsource_agent.parsing import normalize_listing
from src.rentalsource_agent.search_url import build_rentalsource_search_url, slugify_location
from src.rentalsource_agent.storage import write_csv, write_jsonl


DETAIL_LISTING = {
    "@context": "https://schema.org",
    "@type": ["Thing", "RealEstateListing"],
    "identifier": "83402038",
    "name": "770 Boylston St, Boston, MA, 02199",
    "datePosted": "2026-04-09",
    "dateModified": "2026-04-26",
    "lastReviewed": "2026-04-27",
    "description": "Apartments for rent in Boston.",
    "image": [
        "https://images.rentalsource.com/listings/83402038-cre6.jpg",
        "https://images.rentalsource.com/listings/83402038-wxr1.jpg",
    ],
    "offers": [
        {
            "@type": "OfferForLease",
            "price": "3214",
            "priceCurrency": "USD",
            "itemOffered": {
                "@type": "Apartment",
                "name": "770 Boylston St",
                "numberOfBedrooms": 1,
                "numberOfBathroomsTotal": 1,
                "floorSize": {"@type": "QuantitativeValue", "value": 543, "unitCode": "FTK"},
                "petsAllowed": True,
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "770 Boylston St",
                    "addressLocality": "Boston",
                    "addressRegion": "MA",
                    "postalCode": "02199",
                    "addressCountry": "US",
                },
                "geo": {
                    "@type": "GeoCoordinates",
                    "latitude": "42.348142",
                    "longitude": "-71.079629",
                },
            },
        },
        {
            "@type": "OfferForLease",
            "price": 4054,
            "priceCurrency": "USD",
            "itemOffered": {
                "@type": "Apartment",
                "floorSize": {"@type": "QuantitativeValue", "value": 658, "unitCode": "FTK"},
            },
        },
    ],
}


def html_with_json_ld(*documents: dict | str) -> str:
    scripts = []
    for document in documents:
        body = document if isinstance(document, str) else json.dumps(document)
        scripts.append(f'<script type="application/ld+json">{body}</script>')
    return "<html><head>" + "".join(scripts) + "</head><body></body></html>"


class FakeResponse:
    def __init__(self, text: str, ok: bool = True, status: int = 200) -> None:
        self._text = text
        self.ok = ok
        self.status = status

    def text(self) -> str:
        return self._text


class FakeRequest:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.urls.append(url)
        return self.response


class FakePageWithRequest:
    def __init__(self, response: FakeResponse) -> None:
        self.request = FakeRequest(response)


class EmptyLocator:
    def count(self) -> int:
        return 0


class ScriptNode:
    def __init__(self, text: str) -> None:
        self.text = text

    def text_content(self, timeout: int = 0) -> str:
        return self.text


class ScriptLocator:
    def __init__(self, scripts: list[str]) -> None:
        self.scripts = scripts

    def count(self) -> int:
        return len(self.scripts)

    def nth(self, index: int) -> ScriptNode:
        return ScriptNode(self.scripts[index])


class FakeSearchPage:
    url = "https://www.rentalsource.com/boston-ma/"

    def __init__(self, scripts: list[dict]) -> None:
        self.scripts = [json.dumps(script) for script in scripts]

    def locator(self, selector: str):
        if selector == "script[type='application/ld+json']":
            return ScriptLocator(self.scripts)
        return EmptyLocator()


class RentalSourceUrlTests(unittest.TestCase):
    def test_slugify_location_handles_city_state_zip_and_empty_values(self) -> None:
        self.assertEqual(slugify_location("Boston, MA, USA"), "boston-ma")
        self.assertEqual(slugify_location("New York City, NY"), "new-york-city-ny")
        self.assertEqual(slugify_location("Boston, MA 02118"), "boston-ma-02118")
        self.assertEqual(slugify_location("Cambridge, MA 02139, USA"), "cambridge-ma-02139")
        self.assertEqual(slugify_location("02139"), "02139")
        with self.assertRaises(ValueError):
            slugify_location("   ")

    def test_build_search_url_uses_confirmed_rentalsource_filter_params(self) -> None:
        url = build_rentalsource_search_url(
            location="Boston, MA, USA",
            property_types=["Apartment", "House", "all"],
            num_bedrooms=1,
            num_bathrooms=1.5,
            min_price=1000,
            max_price=3000,
            pets=True,
            photos=True,
            verified=True,
            featured=True,
            sort="price-high-to-low",
            page=2,
        )

        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "www.rentalsource.com")
        self.assertEqual(parsed.path, "/boston-ma/")

        query = parse_qs(parsed.query)
        self.assertEqual(query["min"], ["1000"])
        self.assertEqual(query["max"], ["3000"])
        self.assertEqual(query["beds"], ["1"])
        self.assertEqual(query["baths"], ["1.5"])
        self.assertEqual(query["types[]"], ["apt", "hous"])
        self.assertEqual(query["pets"], ["Y"])
        self.assertEqual(query["photos"], ["Y"])
        self.assertEqual(query["verified"], ["Y"])
        self.assertEqual(query["featured"], ["Y"])
        self.assertEqual(query["sort"], ["price-high"])
        self.assertEqual(query["page"], ["2"])

    def test_build_search_url_uses_category_path_for_single_apartment_or_house(self) -> None:
        apartment_url = build_rentalsource_search_url(
            location="Boston, MA",
            property_types=["Apartment"],
        )
        apartment = urlparse(apartment_url)
        self.assertEqual(apartment.path, "/boston-ma/apartments/")
        self.assertEqual(parse_qs(apartment.query)["types[]"], ["apt"])

        house_url = build_rentalsource_search_url(
            location="Philadelphia, PA",
            property_types=["House"],
        )
        house = urlparse(house_url)
        self.assertEqual(house.path, "/philadelphia-pa/houses/")
        self.assertEqual(parse_qs(house.query)["types[]"], ["hous"])

    def test_build_search_url_passthroughs_explicit_url(self) -> None:
        direct_url = "https://www.rentalsource.com/boston-ma/apartments/?page=2"
        self.assertEqual(build_rentalsource_search_url(search_url=direct_url), direct_url)
        self.assertEqual(build_rentalsource_search_url(location=direct_url), direct_url)

    def test_build_search_url_keeps_existing_positional_argument_order(self) -> None:
        url = build_rentalsource_search_url("Boston, MA", ["Apartment"], 1)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.path, "/boston-ma/apartments/")
        self.assertEqual(query["types[]"], ["apt"])
        self.assertEqual(query["beds"], ["1"])


class RentalSourceParsingTests(unittest.TestCase):
    def test_normalize_listing_extracts_card_fields_and_absolute_urls(self) -> None:
        raw = "\n".join(
            [
                "Managed by FUB Yu",
                "$3,214 - $4,054",
                "Apartment 1 Bed 1 Bath 543-658 ft2",
                "770 Boylston St",
                "Boston, MA 02199",
                "Apartments near Back Bay.",
            ]
        )

        record = normalize_listing(
            raw_text=raw,
            source_url="https://www.rentalsource.com/boston-ma/",
            base_url="https://www.rentalsource.com/boston-ma/",
            title="770 Boylston St",
            url="/details/770-boylston-st-boston-ma-83402038/",
            image_urls=["/photo.jpg", "/photo.jpg"],
        )

        self.assertEqual(record["source"], "rentalsource")
        self.assertEqual(record["title"], "770 Boylston St")
        self.assertEqual(record["price"], "$3,214 - $4,054")
        self.assertEqual(record["property_type"], "Apartment")
        self.assertEqual(record["bedrooms"], "1 Bed")
        self.assertEqual(record["bathrooms"], "1 Bath")
        self.assertEqual(record["square_feet"], "543-658 ft2")
        self.assertEqual(record["location"], "Boston, MA 02199")
        self.assertEqual(
            record["url"],
            "https://www.rentalsource.com/details/770-boylston-st-boston-ma-83402038/",
        )
        self.assertEqual(record["image_urls"], ["https://www.rentalsource.com/photo.jpg"])


class RentalSourceDetailTests(unittest.TestCase):
    def test_allowed_detail_url_requires_https_rentalsource_detail_page(self) -> None:
        self.assertTrue(
            is_allowed_detail_url(
                "https://www.rentalsource.com/details/770-boylston-st-boston-ma-83402038/"
            )
        )
        self.assertFalse(is_allowed_detail_url("http://www.rentalsource.com/details/insecure/"))
        self.assertFalse(is_allowed_detail_url("https://evil.example/details/770-boylston/"))
        self.assertFalse(is_allowed_detail_url("javascript:https://www.rentalsource.com/details/770/"))

    def test_extract_detail_data_reads_real_estate_listing_json_ld(self) -> None:
        document = {"@graph": [{"@type": "BreadcrumbList"}, DETAIL_LISTING]}
        html = html_with_json_ld("{not valid json", document)
        parsed = parse_json_ld_documents(html)
        listing = find_real_estate_listing(parsed)

        data = extract_detail_data(listing)

        self.assertEqual(data["listing_id"], "83402038")
        self.assertEqual(data["detail_name"], "770 Boylston St, Boston, MA, 02199")
        self.assertEqual(data["price"], "$3,214 - $4,054")
        self.assertEqual(data["price_min"], 3214)
        self.assertEqual(data["price_max"], 4054)
        self.assertEqual(data["price_currency"], "USD")
        self.assertEqual(data["property_type"], "Apartment")
        self.assertEqual(data["bedrooms"], "1")
        self.assertEqual(data["bathrooms"], "1")
        self.assertEqual(data["square_feet"], "543")
        self.assertEqual(data["square_feet_min"], 543)
        self.assertEqual(data["square_feet_max"], 658)
        self.assertEqual(data["listing_address"], "770 Boylston St, Boston, MA 02199")
        self.assertEqual(data["listing_latitude"], 42.348142)
        self.assertEqual(data["listing_longitude"], -71.079629)
        self.assertEqual(data["image_urls"][0], "https://images.rentalsource.com/listings/83402038-cre6.jpg")

    def test_enrich_record_with_detail_merges_images_and_writes_debug_json(self) -> None:
        html = html_with_json_ld(DETAIL_LISTING)
        page = FakePageWithRequest(FakeResponse(html))
        record = {
            "url": "https://www.rentalsource.com/details/770-boylston-st-boston-ma-83402038/",
            "image_urls": [
                "https://images.rentalsource.com/listings/83402038-cre6.jpg",
                "https://example.com/extra.jpg",
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            enriched = enrich_record_with_detail(
                page=page,
                record=record,
                debug_dir=Path(tmpdir),
            )
            debug_path = Path(enriched["listing_detail_debug_file"])
            self.assertTrue(debug_path.exists())
            debug_data = json.loads(debug_path.read_text(encoding="utf-8"))

        self.assertEqual(enriched["listing_detail_status"], "ok")
        self.assertEqual(enriched["listing_id"], "83402038")
        self.assertEqual(enriched["price"], "$3,214 - $4,054")
        self.assertEqual(
            enriched["image_urls"],
            [
                "https://images.rentalsource.com/listings/83402038-cre6.jpg",
                "https://example.com/extra.jpg",
                "https://images.rentalsource.com/listings/83402038-wxr1.jpg",
            ],
        )
        self.assertEqual(debug_data["listing_id"], "83402038")
        self.assertEqual(
            page.request.urls,
            ["https://www.rentalsource.com/details/770-boylston-st-boston-ma-83402038/"],
        )

    def test_enrich_record_with_detail_marks_http_failures(self) -> None:
        page = FakePageWithRequest(FakeResponse("nope", ok=False, status=503))
        record = {"url": "https://www.rentalsource.com/details/failing-boston-ma-1/"}

        enriched = enrich_record_with_detail(page=page, record=record)

        self.assertEqual(enriched["listing_detail_status"], "failed")
        self.assertIn("503", enriched["listing_detail_error"])

    def test_enrich_record_with_detail_does_not_fetch_untrusted_detail_url(self) -> None:
        page = FakePageWithRequest(FakeResponse(html_with_json_ld(DETAIL_LISTING)))
        record = {"url": "https://evil.example/details/770-boylston-st-boston-ma-83402038/"}

        enriched = enrich_record_with_detail(page=page, record=record)

        self.assertEqual(enriched["listing_detail_status"], "skipped_invalid_detail_url")
        self.assertEqual(page.request.urls, [])


class RentalSourceExtractorTests(unittest.TestCase):
    def test_extract_listings_falls_back_to_json_ld_item_list_and_dedupes(self) -> None:
        item_list = {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "mainEntity": {
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "url": "https://www.rentalsource.com/details/770-boylston-st-boston-ma-83402038/",
                        "name": "770 Boylston St, Boston, MA, 02199",
                        "image": "https://images.rentalsource.com/listings/83402038-cre6.jpg",
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "url": "https://www.rentalsource.com/details/770-boylston-st-boston-ma-83402038/",
                        "name": "770 Boylston St, Boston, MA, 02199",
                        "image": "https://images.rentalsource.com/listings/83402038-cre6.jpg",
                    },
                    {
                        "@type": "ListItem",
                        "position": 3,
                        "url": "https://www.rentalsource.com/details/1-india-st-boston-ma-83415389/",
                        "name": "1 India St #4J, Boston, MA, 02109",
                        "image": "https://images.rentalsource.com/listings/83415389-icn0.jpg",
                    },
                ],
            },
        }
        page = FakeSearchPage([{"@type": "BreadcrumbList"}, item_list])

        records = extract_listings(
            page,
            {"result_card_selectors": ["a.missing-card"]},
            max_listings=10,
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["listing_id"], "83402038")
        self.assertEqual(records[0]["title"], "770 Boylston St, Boston, MA, 02199")
        self.assertEqual(
            records[0]["detail_url"],
            "https://www.rentalsource.com/details/770-boylston-st-boston-ma-83402038/",
        )
        self.assertEqual(records[1]["listing_id"], "83415389")


class RentalSourceLiveBrowserScrapeTests(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RUN_LIVE_SCRAPE_TESTS") == "1",
        "Set RUN_LIVE_SCRAPE_TESTS=1 to run live RentalSource scrape tests",
    )
    def test_live_browser_scrape_extracts_and_enriches_rentalsource_listing(self) -> None:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

            from src.rentalsource_agent.browser import build_context
        except ModuleNotFoundError as exc:
            self.fail(
                "Live RentalSource scrape tests require Playwright. "
                "Run `python3 -m pip install -r requirements.txt` and "
                "`python3 -m playwright install chromium` before testing. "
                f"Original error: {exc}"
            )

        search_url = build_rentalsource_search_url(
            location="Boston, MA",
            property_types=["Apartment"],
            num_bedrooms=1,
            max_price=5000,
            photos=True,
            sort="price",
        )
        selectors = load_selectors("selectors.rentalsource.json")
        playwright = browser = context = page = None

        try:
            playwright, browser, context, page = build_context(
                headless=True,
                state_file=None,
                slow_mo_ms=0,
            )
            page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_selector("a[href*='/details/']", timeout=20_000)
            page.mouse.wheel(0, 2_000)
            page.wait_for_timeout(500)

            records = extract_listings(page, selectors, max_listings=3)

            self.assertGreaterEqual(
                len(records),
                1,
                f"Expected RentalSource to expose at least one live listing at {search_url}",
            )

            first = records[0]
            detail_url = first.get("detail_url") or first.get("url", "")
            self.assertEqual(first["source"], "rentalsource")
            self.assertRegex(detail_url, r"^https://www\.rentalsource\.com/details/.+-\d+/?$")
            self.assertRegex(first.get("listing_id", ""), r"^\d+$")
            self.assertRegex(first.get("price", ""), r"^\$")
            self.assertTrue(first.get("title"))

            enriched = enrich_record_with_detail(page=page, record=first)

            self.assertEqual(enriched["listing_detail_status"], "ok")
            self.assertTrue(enriched.get("listing_address"))
            self.assertIsInstance(enriched.get("listing_latitude"), float)
            self.assertIsInstance(enriched.get("listing_longitude"), float)
            self.assertTrue(enriched.get("image_urls"))
        except PlaywrightError as exc:
            self.fail(f"Live Playwright RentalSource scrape failed for {search_url}: {exc}")
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
            if playwright is not None:
                playwright.stop()


class RentalSourceStorageTests(unittest.TestCase):
    def test_write_jsonl_and_csv_preserve_records_and_flatten_images(self) -> None:
        records = [
            {
                "source": "rentalsource",
                "listing_id": "83402038",
                "title": "770 Boylston St",
                "price": "$3,214 - $4,054",
                "url": "https://www.rentalsource.com/details/770-boylston-st-boston-ma-83402038/",
                "image_urls": ["https://example.com/one.jpg", "https://example.com/two.jpg"],
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "nested" / "results.jsonl"
            csv_path = Path(tmpdir) / "nested" / "results.csv"

            self.assertEqual(write_jsonl(records, jsonl_path), 1)
            self.assertEqual(write_csv(records, csv_path), 1)

            json_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            with csv_path.open(newline="", encoding="utf-8") as f:
                csv_rows = list(csv.DictReader(f))

        self.assertEqual(len(json_lines), 1)
        self.assertEqual(json.loads(json_lines[0])["listing_id"], "83402038")
        self.assertEqual(csv_rows[0]["listing_id"], "83402038")
        self.assertEqual(
            csv_rows[0]["image_urls"],
            "https://example.com/one.jpg | https://example.com/two.jpg",
        )


if __name__ == "__main__":
    unittest.main()
