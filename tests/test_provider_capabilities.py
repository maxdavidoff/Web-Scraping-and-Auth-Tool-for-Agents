from __future__ import annotations

import unittest

from src.housing_agent.provider_capabilities import (
    AFFORDABLEHOUSING,
    OHANA,
    RENTALSOURCE,
    capability_matrix,
    get_provider_capabilities,
)
from src.housing_agent.types import SupportCategory


class ProviderCapabilityMatrixTests(unittest.TestCase):
    def test_matrix_contains_all_researched_providers(self) -> None:
        matrix = capability_matrix()

        self.assertEqual(
            set(matrix),
            {OHANA, RENTALSOURCE, AFFORDABLEHOUSING},
        )

    def test_ohana_requires_login_and_has_verified_student_filters(self) -> None:
        ohana = get_provider_capabilities(OHANA)

        self.assertTrue(ohana.implemented)
        self.assertTrue(ohana.requires_login)
        self.assertIn("/sublet/{location_slug}", ohana.canonical_url_pattern)
        self.assertTrue(ohana.filters["location"].verified)
        self.assertEqual(ohana.filters["location"].category, SupportCategory.PATH_SEGMENT)
        self.assertTrue(ohana.filters["type_of_places"].verified)
        self.assertTrue(ohana.filters["furnished"].verified)
        self.assertEqual(ohana.filters["move_in_date"].category, SupportCategory.QUERY_PARAM)
        self.assertFalse(ohana.filters["move_in_date"].verified)

    def test_rentalsource_has_verified_query_param_targeting(self) -> None:
        rentalsource = get_provider_capabilities("rental-source")

        self.assertTrue(rentalsource.implemented)
        self.assertFalse(rentalsource.requires_login)
        for filter_name in ["min_price", "max_price", "bedrooms", "bathrooms", "pet_policy", "sort", "page"]:
            self.assertEqual(rentalsource.filters[filter_name].category, SupportCategory.QUERY_PARAM)
            self.assertTrue(rentalsource.filters[filter_name].verified)

    def test_affordablehousing_marks_min_price_as_post_filter_with_warning(self) -> None:
        affordable = get_provider_capabilities(AFFORDABLEHOUSING)

        self.assertTrue(affordable.implemented)
        self.assertTrue(affordable.specialized)
        self.assertEqual(affordable.filters["section8"].category, SupportCategory.PATH_SEGMENT)
        self.assertTrue(affordable.filters["section8"].verified)
        self.assertEqual(affordable.filters["min_price"].category, SupportCategory.POST_FILTER)
        self.assertTrue(affordable.filters["min_price"].post_filter_possible)
        self.assertIn("minimum price", affordable.filters["min_price"].warning)


if __name__ == "__main__":
    unittest.main()
