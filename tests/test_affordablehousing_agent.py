from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.affordablehousing_agent.extractor import (
    _is_useful_href,
    _model_detail_url_from_card,
)
from src.affordablehousing_agent.parsing import normalize_listing
from src.affordablehousing_agent.search_url import (
    build_affordablehousing_search_url,
    location_to_slug,
)
from src.affordablehousing_agent.storage import write_csv, write_jsonl


class FakeCard:
    def __init__(self, card_id: str):
        self.card_id = card_id

    def get_attribute(self, attr: str, timeout: int | None = None) -> str:
        if attr == "id":
            return self.card_id
        return ""


class FakePage:
    def __init__(self, property_list: list[dict]):
        self.property_list = property_list
        self.evaluated_indexes: list[int] = []

    def evaluate(self, script: str, index: int) -> dict | None:
        self.evaluated_indexes.append(index)
        if index >= len(self.property_list):
            return None
        return self.property_list[index]


class AffordableHousingSearchUrlTests(unittest.TestCase):
    def test_location_to_slug_handles_city_county_and_country_suffix(self) -> None:
        self.assertEqual(location_to_slug("Boston, MA, USA"), "boston-ma")
        self.assertEqual(location_to_slug("Suffolk County, MA"), "suffolk-county-ma")

    def test_location_to_slug_rejects_empty_and_url_values(self) -> None:
        with self.assertRaises(ValueError):
            location_to_slug("")

        with self.assertRaises(ValueError):
            location_to_slug("https://www.affordablehousing.com/boston-ma/")

    def test_build_search_url_orders_seo_filters(self) -> None:
        url = build_affordablehousing_search_url(
            "Boston, MA, USA",
            property_types=["Apartment"],
            num_bedrooms=1,
            max_price=1500,
            pet_friendly=True,
            utilities_included=True,
        )

        self.assertEqual(
            url,
            "https://www.affordablehousing.com/boston-ma/under-1500/1-bed/apartment/pet-friendly/utilities-included/",
        )

    def test_build_search_url_passthroughs_explicit_url(self) -> None:
        direct_url = "https://www.affordablehousing.com/boston-ma/page-2/"
        self.assertEqual(build_affordablehousing_search_url(direct_url), direct_url)


class AffordableHousingParsingTests(unittest.TestCase):
    def test_normalize_listing_extracts_and_normalizes_core_fields(self) -> None:
        record = normalize_listing(
            raw_text=(
                "$2,600 - $4,600\n"
                "Available Now\n"
                "Stud-4 beds | 2 baths | 512-1,350 sqft | Apartments\n"
                "Waterford Place\n"
                "180 Shawmut Ave, 701, Boston, MA 02118"
            ),
            source_url="https://www.affordablehousing.com/boston-ma/",
            base_url="https://www.affordablehousing.com/boston-ma/",
            title="Waterford Place",
            location="180 Shawmut Ave, 701, Boston, MA 02118",
            url="/boston-ma/waterford-place-963732/",
            image_urls=["/photo.jpg", "/photo.jpg", "https://cdn.example.com/other.jpg"],
            bedrooms="Stud-4 beds",
        )

        self.assertEqual(record["source"], "affordablehousing")
        self.assertEqual(record["title"], "Waterford Place")
        self.assertEqual(record["price"], "$2,600 - $4,600")
        self.assertEqual(record["availability"], "Available Now")
        self.assertEqual(record["bedrooms"], "Studio-4 beds")
        self.assertEqual(record["bathrooms"], "2 baths")
        self.assertEqual(record["sqft"], "512-1,350 sqft")
        self.assertEqual(record["property_type"], "Apartments")
        self.assertEqual(
            record["url"],
            "https://www.affordablehousing.com/boston-ma/waterford-place-963732/",
        )
        self.assertEqual(
            record["image_urls"],
            [
                "https://www.affordablehousing.com/photo.jpg",
                "https://cdn.example.com/other.jpg",
            ],
        )

    def test_normalize_listing_guesses_title_when_selectors_are_empty(self) -> None:
        record = normalize_listing(
            raw_text="Trusted Owner\n$0\nAvailable Now\nPok Oi Residences\n288 Harrison Ave",
            source_url="https://www.affordablehousing.com/boston-ma/",
            base_url="https://www.affordablehousing.com/boston-ma/",
        )

        self.assertEqual(record["title"], "Pok Oi Residences")
        self.assertEqual(record["price"], "$0")
        self.assertEqual(record["availability"], "Available Now")


class AffordableHousingExtractorHelperTests(unittest.TestCase):
    def test_is_useful_href_filters_fake_links(self) -> None:
        for value in ["", "javascript:void(0);", "#", "mailto:test@example.com", "tel:5555555555"]:
            self.assertFalse(_is_useful_href(value))

        self.assertTrue(_is_useful_href("/boston-ma/pok-oi-residences-963727/"))
        self.assertTrue(_is_useful_href("https://www.affordablehousing.com/boston-ma/pok-oi-residences-963727/"))

    def test_model_detail_url_from_card_uses_client_rendered_property_model(self) -> None:
        page = FakePage(
            [
                {
                    "communityId": 963727,
                    "communityName": "Pok Oi Residences",
                    "tagLine": "Pok Oi Residences",
                    "addressLine1": "288 Harrison Ave",
                    "city": "Boston",
                    "state": "MA",
                }
            ]
        )

        url = _model_detail_url_from_card(page, FakeCard("premium-card-0"))

        self.assertEqual(
            url,
            "https://www.affordablehousing.com/boston-ma/pok-oi-residences-963727/",
        )
        self.assertEqual(page.evaluated_indexes, [0])

    def test_model_detail_url_from_card_falls_back_to_address_for_unnamed_cards(self) -> None:
        page = FakePage(
            [
                {},
                {},
                {},
                {
                    "communityId": 911695,
                    "communityName": "",
                    "tagLine": "TWO BED ONE BATH",
                    "addressLine1": "1782 Washington St",
                    "city": "Boston",
                    "state": "MA",
                },
            ]
        )

        url = _model_detail_url_from_card(page, FakeCard("tnresult-card-3"))

        self.assertEqual(
            url,
            "https://www.affordablehousing.com/boston-ma/1782-washington-st-911695/",
        )
        self.assertEqual(page.evaluated_indexes, [3])

    def test_model_detail_url_from_card_returns_empty_for_missing_data(self) -> None:
        self.assertEqual(_model_detail_url_from_card(FakePage([]), FakeCard("not-a-card")), "")
        self.assertEqual(
            _model_detail_url_from_card(
                FakePage([{"communityId": "", "city": "Boston", "state": "MA"}]),
                FakeCard("premium-card-0"),
            ),
            "",
        )


class AffordableHousingStorageTests(unittest.TestCase):
    def test_write_jsonl_and_csv_outputs_records(self) -> None:
        records = [
            {
                "source": "affordablehousing",
                "title": "Pok Oi Residences",
                "price": "$0",
                "image_urls": ["https://example.com/a.jpg", "https://example.com/b.jpg"],
                "url": "https://www.affordablehousing.com/boston-ma/pok-oi-residences-963727/",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jsonl_path = tmp_path / "records.jsonl"
            csv_path = tmp_path / "records.csv"

            self.assertEqual(write_jsonl(records, jsonl_path), 1)
            self.assertEqual(write_csv(records, csv_path), 1)

            jsonl_records = [
                json.loads(line)
                for line in jsonl_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(jsonl_records, records)

            with csv_path.open(newline="", encoding="utf-8") as f:
                csv_rows = list(csv.DictReader(f))

            self.assertEqual(len(csv_rows), 1)
            self.assertEqual(csv_rows[0]["title"], "Pok Oi Residences")
            self.assertEqual(
                csv_rows[0]["image_urls"],
                "https://example.com/a.jpg | https://example.com/b.jpg",
            )


if __name__ == "__main__":
    unittest.main()
