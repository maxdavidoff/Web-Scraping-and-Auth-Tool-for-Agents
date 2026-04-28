from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.housing_agent.listing_evaluator import (
    compare_listings,
    evaluate_listings,
    filter_under_price,
    hide_missing_address,
    sort_listings,
)
from src.housing_agent.types import HousingSearchIntent


class ListingEvaluatorTests(unittest.TestCase):
    def test_evaluate_listings_scores_price_and_location_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = evaluate_listings(
                HousingSearchIntent(
                    location="Philadelphia, PA",
                    max_price=1800,
                    campus_or_school="UPenn",
                    type_of_places=("Private room",),
                    furnished=True,
                ),
                [
                    {
                        "title": "Furnished private room",
                        "price": "$1,600",
                        "address": "Near UPenn, Philadelphia, PA",
                        "listing_latitude": 39.9525,
                        "listing_longitude": -75.194,
                        "provider": "ohana",
                        "url": "https://example.com/1",
                    },
                    {
                        "title": "Expensive apartment",
                        "price": "$2,400",
                        "address": "Philadelphia, PA",
                        "provider": "rentalsource",
                    },
                ],
                output_dir=Path(tmpdir),
            )

        self.assertEqual(result.listings[0].title, "Furnished private room")
        self.assertGreater(result.listings[0].metrics.overall, result.listings[1].metrics.overall)
        self.assertEqual(result.listings[1].status, "excluded")
        self.assertIn("over budget", " ".join(result.listings[1].concerns))
        self.assertIsNotNone(result.map_path)

    def test_sort_filter_and_compare_helpers(self) -> None:
        result = evaluate_listings(
            HousingSearchIntent(max_price=2000),
            [
                {"title": "B", "price": "$1,900", "address": "Boston, MA"},
                {"title": "A", "price": "$1,500"},
            ],
            create_map=False,
        )

        by_price = sort_listings(result.listings, "price")
        self.assertEqual(by_price[0].title, "A")
        self.assertEqual(len(filter_under_price(result.listings, 1600)), 1)
        self.assertEqual(len(hide_missing_address(result.listings)), 1)
        self.assertIn("#1", compare_listings(result.listings, [1]))


if __name__ == "__main__":
    unittest.main()
