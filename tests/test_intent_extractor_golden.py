from __future__ import annotations

import json
import unittest
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.housing_agent.intent_extractor import intent_from_mapping
from src.housing_agent.query_planner import plan_query


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "housing_intent_cases.json"


class IntentExtractorGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cls.cases = json.load(handle)

    def test_golden_intents_normalize_and_rank_expected_provider(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["name"]):
                intent = intent_from_mapping(case["model_response"])
                plan = plan_query(intent)

                self.assert_expected_fields(intent, case["expected"])
                self.assertEqual(plan.ranked_provider_names[0], case["expected_top_provider"])

                for provider, expectations in case.get("expected_provider_notes", {}).items():
                    provider_plan = plan.for_provider(provider)
                    if "implemented" in expectations:
                        self.assertEqual(provider_plan.implemented, expectations["implemented"])
                    for filter_name in expectations.get("unknown_unverified", []):
                        self.assertIn(filter_name, provider_plan.report.unknown_unverified)

    def test_fixture_cases_cover_core_intent_kinds(self) -> None:
        intent_kinds = {case["expected"].get("intent_kind") for case in self.cases}
        self.assertIn("student_sublet", intent_kinds)
        self.assertIn("general_rental", intent_kinds)
        self.assertIn("affordable", intent_kinds)
        self.assertIn("apartment", intent_kinds)

        top_providers = {case["expected_top_provider"] for case in self.cases}
        self.assertEqual(top_providers, {"ohana", "rentalsource", "affordablehousing"})

    def assert_expected_fields(self, intent, expected: dict[str, Any]) -> None:
        actual = asdict(intent)
        for field, expected_value in expected.items():
            actual_value = actual[field]
            if isinstance(actual_value, tuple):
                actual_value = list(actual_value)
            self.assertEqual(actual_value, expected_value, field)


if __name__ == "__main__":
    unittest.main()
