from __future__ import annotations

import unittest

from src.housing_agent.location_scope import is_neighborhood_only_location
from src.housing_agent.readiness_evaluator import apply_readiness_guards, readiness_from_mapping
from src.housing_agent.types import HousingSearchIntent
from src.supported_locations import supported_location_for


class SupportedLocationReadinessTests(unittest.TestCase):
    def test_unsupported_city_is_blocked_before_execution(self) -> None:
        guarded = apply_readiness_guards(
            readiness_from_mapping(
                {
                    "ready_to_search": True,
                    "ready_to_recommend": True,
                    "confidence": "high",
                    "next_action": "execute_search",
                }
            ),
            HousingSearchIntent(location="Chicago", property_types=("Apartment",), intent_kind="general_rental"),
            transcript=[{"role": "user", "content": "apartment in Chicago"}],
        )

        self.assertFalse(guarded.ready_to_search)
        self.assertEqual(guarded.next_action, "ask_followup")
        self.assertIn("Boston", guarded.followup_questions[0])
        self.assertIn("Philadelphia", guarded.followup_questions[0])

    def test_new_neighborhood_aliases_resolve_but_still_require_city_scope(self) -> None:
        aliases = {
            "Jamaica Plain": "boston",
            "Astoria": "new_york",
            "Foggy Bottom": "washington_dc",
            "Rittenhouse": "philadelphia",
        }
        for alias, key in aliases.items():
            with self.subTest(alias=alias):
                self.assertEqual(supported_location_for(alias).key, key)
                self.assertTrue(is_neighborhood_only_location(alias))


if __name__ == "__main__":
    unittest.main()
