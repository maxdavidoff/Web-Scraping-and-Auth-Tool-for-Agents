from __future__ import annotations

import unittest

from src.housing_agent.listing_parsing import add_structured_listing_fields, parse_count_range, parse_dates, parse_price_values


class ListingNormalizationTests(unittest.TestCase):
    def test_price_bed_bath_and_date_fields_are_structured(self) -> None:
        record = add_structured_listing_fields(
            {
                "price": "$1,250 - $1,800/mo",
                "bedrooms": "Studio-2 beds",
                "bathrooms": "1.5 baths",
                "availability": "Available Jun 1 - Aug 31, 2026",
            }
        )

        self.assertEqual(record["price_min_int"], 1250)
        self.assertEqual(record["price_max_int"], 1800)
        self.assertEqual(record["bedroom_min_count"], 0)
        self.assertEqual(record["bedroom_max_count"], 2)
        self.assertIsNone(record["bedroom_count"])
        self.assertEqual(record["bathroom_count"], 1.5)
        self.assertIn("2026-08-31", (record["available_from_iso"], record["available_to_iso"]))

    def test_parsers_handle_common_edge_shapes(self) -> None:
        self.assertEqual(parse_price_values("$1,250/mo"), (1250,))
        self.assertEqual(parse_count_range("Studio", kind="bedroom"), (0.0, 0.0))
        self.assertEqual(parse_count_range("1 to 2 beds", kind="bedroom"), (1.0, 2.0))
        self.assertEqual(parse_count_range("2.5 baths", kind="bathroom"), (2.5, 2.5))
        self.assertEqual(parse_dates("Move in 6/1/2026"), ("2026-06-01",))


if __name__ == "__main__":
    unittest.main()
