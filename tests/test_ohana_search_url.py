from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from src.ohana_agent.search_url import build_ohana_search_url, format_location_label, slugify_location


class OhanaSearchUrlTests(unittest.TestCase):
    def test_slugify_location_uses_only_supported_ohana_city_slugs(self) -> None:
        self.assertEqual(slugify_location("Boston, MA, USA"), "boston")
        self.assertEqual(slugify_location("New York, NY"), "new-york-city")
        self.assertEqual(slugify_location("San Francisco, CA"), "san-francisco")

    def test_slugify_location_maps_known_neighborhoods_to_supported_ohana_cities(self) -> None:
        self.assertEqual(slugify_location("Cambridge"), "boston")
        self.assertEqual(slugify_location("Williamsburg"), "new-york-city")
        self.assertEqual(slugify_location("Mission District"), "san-francisco")

    def test_slugify_location_rejects_unsupported_places(self) -> None:
        with self.assertRaisesRegex(ValueError, "only support"):
            slugify_location("Philadelphia, PA")
        with self.assertRaisesRegex(ValueError, "only support"):
            slugify_location("Washington, DC")
        with self.assertRaisesRegex(ValueError, "only support"):
            slugify_location("02139")

    def test_format_location_label_uses_supported_ohana_city_labels(self) -> None:
        self.assertEqual(format_location_label("Boston, MA"), "Boston, MA, USA")
        self.assertEqual(format_location_label("New York, NY"), "New York, NY, USA")
        self.assertEqual(format_location_label("San Francisco, CA"), "San Francisco, CA, USA")
        self.assertEqual(format_location_label("Cambridge"), "Boston, MA, USA")

    def test_build_search_url_uses_canonical_sublet_path_and_observed_params(self) -> None:
        url = build_ohana_search_url(
            location="New York, NY",
            property_types=["Apartment", "House"],
            type_of_places=["Private room", "Shared room"],
            num_bedrooms=1,
            min_price=1000,
            max_price=3000,
            pet_policy=["Dog friendly"],
            furnished_status=["Furnished"],
        )

        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "liveohana.ai")
        self.assertEqual(parsed.path, "/sublet/new-york-city")

        query = parse_qs(parsed.query)
        self.assertEqual(query["location"], ["New York, NY, USA"])
        self.assertEqual(query["min_price"], ["1000"])
        self.assertEqual(query["max_price"], ["3000"])
        self.assertEqual(query["num_bedrooms"], ["1"])
        self.assertEqual(query["property_types"], ["Apartment,House"])
        self.assertEqual(query["type_of_places"], ["Private%20room,Shared%20room"])
        self.assertEqual(query["pet_policy"], ["Dog%20friendly"])
        self.assertEqual(query["furnished_status"], ["Furnished"])

    def test_build_search_url_uses_city_for_supported_neighborhood(self) -> None:
        url = build_ohana_search_url(
            location="Cambridge",
            movein="2026-05-01",
            moveout="2026-05-31",
            type_of_places=["Private room"],
            max_price=1800,
            furnished_status=["Furnished"],
        )

        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.path, "/sublet/boston")
        self.assertEqual(query["location"], ["Boston, MA, USA"])
        self.assertNotIn("Cambridge", url)

    def test_build_search_url_passthroughs_explicit_url(self) -> None:
        direct_url = "https://liveohana.ai/sublet/boston?location=Boston"
        self.assertEqual(build_ohana_search_url(search_url=direct_url), direct_url)
        self.assertEqual(build_ohana_search_url(location=direct_url), direct_url)

    def test_build_search_url_keeps_existing_positional_argument_order(self) -> None:
        url = build_ohana_search_url("Boston, MA", "May 1, 2026", "August 31, 2026")
        query = parse_qs(urlparse(url).query)

        self.assertEqual(urlparse(url).path, "/sublet/boston")
        self.assertEqual(query["movein"], ["May 1, 2026"])
        self.assertEqual(query["moveout"], ["August 31, 2026"])


if __name__ == "__main__":
    unittest.main()
