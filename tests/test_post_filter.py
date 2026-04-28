from __future__ import annotations

import unittest

from src.housing_agent.post_filter import apply_hard_constraints, apply_post_filters
from src.housing_agent.types import HousingSearchIntent


class PostFilterTests(unittest.TestCase):
    def test_filters_price_bed_bath_keyword_and_amenities(self) -> None:
        intent = HousingSearchIntent(
            max_price=2000,
            bedroom_min=1,
            bedroom_max=2,
            bathroom_min=1.5,
            required_amenities=("laundry",),
            keyword="near Penn",
        )
        result = apply_post_filters(
            [
                {
                    "title": "Good unit near Penn",
                    "price": "$1,800",
                    "bedrooms": "2 beds",
                    "bathrooms": "1.5 baths",
                    "raw_text": "Laundry in building near Penn",
                },
                {
                    "title": "Too expensive",
                    "price": "$3,500",
                    "bedrooms": "2 beds",
                    "bathrooms": "2 baths",
                    "raw_text": "Laundry near Penn",
                },
                {
                    "title": "Wrong size",
                    "price": "$1,700",
                    "bedrooms": "3 beds",
                    "bathrooms": "2 baths",
                    "raw_text": "Laundry near Penn",
                },
                {
                    "title": "Missing amenity",
                    "price": "$1,700",
                    "bedrooms": "2 beds",
                    "bathrooms": "2 baths",
                    "raw_text": "Near Penn",
                },
            ],
            intent,
            ["max_price", "bedroom_min", "bedroom_max", "bathroom_min", "required_amenities", "keyword"],
        )

        self.assertEqual([record["title"] for record in result.records], ["Good unit near Penn"])
        self.assertEqual(len(result.excluded_records), 3)
        self.assertIn("max_price", result.exclusion_counts)
        self.assertIn("bedroom_max", result.exclusion_counts)
        self.assertIn("required_amenities", result.exclusion_counts)

    def test_missing_structured_numeric_fields_are_kept(self) -> None:
        result = apply_post_filters(
            [{"title": "Sparse listing", "raw_text": "Call for details"}],
            HousingSearchIntent(max_price=1800, bedroom_min=1),
            ["max_price", "bedroom_min"],
        )

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.excluded_records, [])

    def test_furnished_and_pet_negation_are_deterministic(self) -> None:
        intent = HousingSearchIntent(
            furnished=True,
            pet_policy_negated=("pets",),
        )
        result = apply_hard_constraints(
            [
                {"title": "Furnished no pet signal", "raw_text": "Furnished private room"},
                {"title": "Unfurnished", "raw_text": "Unfurnished apartment"},
                {"title": "Allows pets", "raw_text": "Furnished apartment. Pet friendly."},
            ],
            intent,
        )

        self.assertEqual([record["title"] for record in result.records], ["Furnished no pet signal"])
        reasons = "\n".join(record["excluded_reason"] for record in result.excluded_records)
        self.assertIn("unfurnished", reasons)
        self.assertIn("allows pets", reasons)

    def test_washer_dryer_required_excludes_missing_text(self) -> None:
        result = apply_post_filters(
            [
                {"title": "Has laundry", "raw_text": "Laundry facilities onsite"},
                {"title": "No mention", "raw_text": "Sunny apartment"},
            ],
            HousingSearchIntent(washer_dryer=True),
            ["washer_dryer"],
        )

        self.assertEqual([record["title"] for record in result.records], ["Has laundry"])
        self.assertEqual(result.excluded_records[0]["title"], "No mention")

    def test_commute_target_is_noted_and_lease_length_can_filter(self) -> None:
        result = apply_post_filters(
            [
                {"title": "Summer sublet", "raw_text": "Summer lease near campus", "coordinates_status": "missing"},
                {"title": "Annual lease", "raw_text": "12 month lease near campus", "coordinates_status": "present"},
            ],
            HousingSearchIntent(commute_target="UPenn", lease_length="summer"),
            ["commute_target", "lease_length"],
        )

        self.assertEqual([record["title"] for record in result.records], ["Summer sublet"])
        self.assertIn("could not verify commute", result.records[0]["post_filter_notes"][0])
        self.assertEqual(result.excluded_records[0]["title"], "Annual lease")


if __name__ == "__main__":
    unittest.main()
