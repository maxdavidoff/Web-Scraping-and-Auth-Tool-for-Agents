from __future__ import annotations

import unittest

from src.housing_agent.intent_guards import OPEN_BUDGET_NOTE, apply_intent_guards
from src.housing_agent.types import HousingSearchIntent


class IntentGuardTests(unittest.TestCase):
    def test_budget_phrases_become_expected_price_bounds(self) -> None:
        cases = [
            ("$3k/month", None, 3000),
            ("3k a month", None, 3000),
            ("budget is 3000", None, 3000),
            ("around 2000", None, 2000),
            ("about 2000", None, 2000),
            ("up to 2000", None, 2000),
            ("under 2000", None, 2000),
            ("from 1500 to 3000", 1500, 3000),
            ("between 1500 and 3000", 1500, 3000),
            ("1500-3000", 1500, 3000),
            ("1.5k to 2.5k", 1500, 2500),
            ("at least 1500", 1500, None),
            ("minimum 1500", 1500, None),
            ("from 1500", 1500, None),
            ("exactly 3000", 3000, 3000),
        ]

        for message, expected_min, expected_max in cases:
            with self.subTest(message=message):
                intent = HousingSearchIntent(min_price=999, max_price=999)
                guarded = apply_intent_guards(intent, latest_user_message=message)
                self.assertEqual(guarded.min_price, expected_min)
                self.assertEqual(guarded.max_price, expected_max)

    def test_open_budget_clears_price_filters_and_sets_flexibility(self) -> None:
        guarded = apply_intent_guards(
            HousingSearchIntent(min_price=1200, max_price=3000),
            latest_user_message="no budget, I'm flexible",
        )

        self.assertIsNone(guarded.min_price)
        self.assertIsNone(guarded.max_price)
        self.assertIn(OPEN_BUDGET_NOTE, guarded.flexibility_notes)

    def test_equal_budget_without_exact_language_is_treated_as_max_only(self) -> None:
        guarded = apply_intent_guards(
            HousingSearchIntent(min_price=3000, max_price=3000),
            latest_user_message="3k a month is my budget",
        )

        self.assertIsNone(guarded.min_price)
        self.assertEqual(guarded.max_price, 3000)

    def test_private_room_for_self_does_not_force_whole_unit_bedroom_count(self) -> None:
        guarded = apply_intent_guards(
            HousingSearchIntent(
                bedrooms=1,
                type_of_places=("Private room",),
                notes=("The flat itself can have more than one bedroom if it is a sublet.",),
            ),
            latest_user_message="just the one bedroom for myself but the flat itself can have more than one bedroom",
        )

        self.assertIsNone(guarded.bedrooms)

    def test_explicit_one_bedroom_whole_unit_keeps_bedroom_count(self) -> None:
        guarded = apply_intent_guards(
            HousingSearchIntent(bedrooms=1),
            latest_user_message="I want a one-bedroom apartment",
        )

        self.assertEqual(guarded.bedrooms, 1)


if __name__ == "__main__":
    unittest.main()
