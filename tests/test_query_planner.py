from __future__ import annotations

import unittest

from src.housing_agent.provider_capabilities import AFFORDABLEHOUSING, OHANA, RENTALSOURCE
from src.housing_agent.query_planner import plan_query
from src.housing_agent.types import HousingSearchIntent


class QueryPlannerTests(unittest.TestCase):
    def test_student_sublet_intent_ranks_ohana_and_classifies_date_as_unknown(self) -> None:
        intent = HousingSearchIntent(
            location="Boston, MA",
            max_price=1800,
            bedrooms=1,
            type_of_places=("Private room",),
            furnished=True,
            move_in_date="June 1, 2026",
            intent_kind="student_sublet",
            notes=("Student wants a private furnished sublet near campus.",),
        )

        plan = plan_query(intent)
        ohana = plan.for_provider(OHANA)
        rentalsource = plan.for_provider(RENTALSOURCE)

        self.assertEqual(plan.ranked_provider_names[0], OHANA)
        self.assertGreater(ohana.score, rentalsource.score)
        for filter_name in ["location", "max_price", "bedrooms", "type_of_places", "furnished"]:
            self.assertIn(filter_name, ohana.report.applied_at_source)
        self.assertIn("move_in_date", ohana.report.unknown_unverified)
        self.assertIn("type_of_places", rentalsource.report.unknown_unverified)
        self.assertIn("furnished", rentalsource.report.post_filters)

    def test_general_rental_intent_ranks_rentalsource(self) -> None:
        intent = HousingSearchIntent(
            location="Philadelphia, PA",
            min_price=1200,
            max_price=2600,
            bedrooms=2,
            bathrooms=1.5,
            property_types=("Apartment", "House"),
            pet_policy=("Cats allowed",),
            sort="price-low-to-high",
            intent_kind="general_rental",
        )

        plan = plan_query(intent)
        rentalsource = plan.for_provider(RENTALSOURCE)
        ohana = plan.for_provider(OHANA)

        self.assertEqual(plan.ranked_provider_names[0], RENTALSOURCE)
        self.assertGreater(rentalsource.score, ohana.score)
        for filter_name in [
            "location",
            "min_price",
            "max_price",
            "bedrooms",
            "bathrooms",
            "property_types",
            "pet_policy",
            "sort",
        ]:
            self.assertIn(filter_name, rentalsource.report.applied_at_source)
        self.assertIn("bathrooms", ohana.report.post_filters)
        self.assertIn("sort", ohana.report.unknown_unverified)

    def test_multiple_roommates_rank_rentalsource_even_for_student_context(self) -> None:
        intent = HousingSearchIntent(
            location="Boston, MA",
            max_price=4200,
            furnished=True,
            roommate_count=3,
            intent_kind="student_sublet",
            notes=("My roommates and I need a full rental.",),
        )

        plan = plan_query(intent)

        self.assertEqual(plan.ranked_provider_names[0], RENTALSOURCE)
        self.assertGreater(plan.for_provider(RENTALSOURCE).score, plan.for_provider(OHANA).score)

    def test_single_person_room_search_ranks_ohana(self) -> None:
        intent = HousingSearchIntent(
            location="Boston, MA",
            max_price=1800,
            furnished=True,
            roommate_count=0,
            notes=("Just me looking for a place.",),
        )

        plan = plan_query(intent)

        self.assertEqual(plan.ranked_provider_names[0], OHANA)
        self.assertGreater(plan.for_provider(OHANA).score, plan.for_provider(RENTALSOURCE).score)

    def test_affordable_conditions_outrank_multiple_roommates(self) -> None:
        intent = HousingSearchIntent(
            location="Boston, MA",
            max_price=2600,
            property_types=("Apartment",),
            roommate_count=3,
            section8=True,
            income_restricted=True,
            intent_kind="affordable",
            notes=("Voucher holder searching with roommates.",),
        )

        plan = plan_query(intent)

        self.assertEqual(plan.ranked_provider_names[0], AFFORDABLEHOUSING)
        self.assertGreater(plan.for_provider(AFFORDABLEHOUSING).score, plan.for_provider(RENTALSOURCE).score)

    def test_section8_intent_ranks_affordablehousing_and_warns_on_min_price(self) -> None:
        intent = HousingSearchIntent(
            location="Boston, MA",
            min_price=500,
            max_price=1600,
            bedrooms=1,
            property_types=("Apartment",),
            pet_policy=("Pet friendly",),
            section8=True,
            income_restricted=True,
            intent_kind="affordable",
            notes=("Voucher holder looking for income restricted housing.",),
        )

        plan = plan_query(intent)
        affordable = plan.for_provider(AFFORDABLEHOUSING)
        rentalsource = plan.for_provider(RENTALSOURCE)

        self.assertEqual(plan.ranked_provider_names[0], AFFORDABLEHOUSING)
        self.assertGreater(affordable.score, rentalsource.score)
        for filter_name in [
            "location",
            "max_price",
            "bedrooms",
            "property_types",
            "pet_policy",
            "section8",
            "income_restricted",
        ]:
            self.assertIn(filter_name, affordable.report.applied_at_source)
        self.assertIn("min_price", affordable.report.post_filters)
        self.assertTrue(any("minimum price" in warning for warning in affordable.report.warnings))
        self.assertIn("section8", rentalsource.report.unsupported)

    def test_amenity_heavy_apartment_intent_uses_rentalsource_and_reports_post_filters(self) -> None:
        intent = HousingSearchIntent(
            location="New York, NY",
            min_price=2500,
            max_price=4200,
            bedroom_min=1,
            bedroom_max=2,
            bathroom_min=1,
            property_types=("Apartment",),
            pet_policy=("Dogs allowed",),
            amenities=("In-unit laundry", "Gym", "Doorman"),
            move_in_date="September 1, 2026",
            map_bounds={"west": -74.02, "south": 40.70, "east": -73.94, "north": 40.80},
            sort="newest",
            keyword="near NYU",
            intent_kind="apartment",
        )

        plan = plan_query(intent)
        rentalsource = plan.for_provider(RENTALSOURCE)

        self.assertEqual(plan.ranked_provider_names[0], RENTALSOURCE)
        for filter_name in [
            "location",
            "min_price",
            "max_price",
            "bedroom_min",
            "bathroom_min",
            "property_types",
            "pet_policy",
            "sort",
        ]:
            self.assertIn(filter_name, rentalsource.report.applied_at_source)
        for filter_name in ["amenities", "keyword"]:
            self.assertIn(filter_name, rentalsource.report.post_filters)
        self.assertIn("bedroom_max", rentalsource.report.post_filters)
        for filter_name in ["move_in_date"]:
            self.assertIn(filter_name, rentalsource.report.unknown_unverified)
        self.assertIn("map_bounds", rentalsource.report.unsupported)


if __name__ == "__main__":
    unittest.main()
