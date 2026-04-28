from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.housing_agent.search_app import build_housing_search_response


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "housing_user_scenarios.json"


class FakeJsonClient:
    model = "fake-mistral"

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = []

    def complete_json(self, messages, *, temperature=0.0, max_tokens=1200):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return json.dumps(self.response)


class HousingUserScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cls.scenarios = json.load(handle)

    def test_planning_mode_matches_user_scenarios_without_scraping(self) -> None:
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["name"]):
                runner = Mock(side_effect=AssertionError("planning mode must not execute scrapers"))
                response = build_housing_search_response(
                    scenario["user_message"],
                    client=FakeJsonClient(scenario["model_response"]),
                    execute=False,
                    runner=runner,
                    today="2026-04-28",
                )

                self.assertEqual(response["status"], "planned")
                self.assertEqual(response["mode"], "planning")
                self.assertEqual(response["records"], [])
                self.assertEqual(response["provider_results"], [])
                runner.assert_not_called()

                self.assert_expected_intent(response["intent"], scenario["expected_intent"])
                self.assertEqual(
                    response["query_plan"]["ranked_provider_names"][0],
                    scenario["expected_top_provider"],
                )
                self.assert_filter_application(response, scenario.get("expected_filter_application", {}))
                self.assert_provider_score_order(response, scenario.get("expected_score_greater_than", []))
                self.assert_skipped_providers(response, scenario.get("must_not_execute", []))
                self.assert_warning_substrings(response, scenario.get("expected_user_visible_warnings", []))

    def test_execution_mode_calls_router_with_only_executable_providers(self) -> None:
        scenario = self._scenario("student_sublet_boston")
        runner = Mock(return_value=self._fake_routed_result(errors={}))

        response = build_housing_search_response(
            scenario["user_message"],
            client=FakeJsonClient(scenario["model_response"]),
            execute=True,
            runner=runner,
            today="2026-04-28",
            max_listings=3,
        )

        self.assertEqual(response["status"], "executed")
        runner.assert_called_once()
        executed_providers = runner.call_args.kwargs["providers"]
        self.assertIn("ohana", executed_providers)
        self.assertIn("rentalsource", executed_providers)
        self.assertIn("affordablehousing", executed_providers)
        self.assertNotIn("apartments_com", executed_providers)
        self.assertEqual(response["execution"]["executed_providers"], list(executed_providers))
        self.assertEqual(response["records"][0]["provider"], "ohana")
        self.assert_skipped_providers(response, ["apartments_com"])

    def test_execution_mode_surfaces_provider_failures_without_crashing(self) -> None:
        scenario = self._scenario("general_pet_friendly_apartment_philly")
        runner = Mock(return_value=self._fake_routed_result(errors={"rentalsource": "RentalSource unavailable"}))

        response = build_housing_search_response(
            scenario["user_message"],
            client=FakeJsonClient(scenario["model_response"]),
            execute=True,
            runner=runner,
            today="2026-04-28",
        )

        self.assertEqual(response["status"], "partial_execution")
        self.assertEqual(response["errors"], {"rentalsource": "RentalSource unavailable"})
        statuses = {result["provider"]: result["status"] for result in response["provider_results"]}
        self.assertEqual(statuses["rentalsource"], "failed")
        self.assertEqual(statuses["ohana"], "ok")

    def test_execution_mode_does_not_call_router_when_only_unimplemented_provider_is_selected(self) -> None:
        scenario = self._scenario("amenity_heavy_apartment_new_york")
        runner = Mock(side_effect=AssertionError("apartments_com must not be executed"))

        response = build_housing_search_response(
            scenario["user_message"],
            client=FakeJsonClient(scenario["model_response"]),
            providers=["apartments_com"],
            execute=True,
            runner=runner,
            today="2026-04-28",
        )

        self.assertEqual(response["status"], "no_executable_providers")
        runner.assert_not_called()
        self.assertEqual(response["execution"]["executed_providers"], [])
        self.assert_skipped_providers(response, ["apartments_com"])

    def _scenario(self, name: str) -> dict:
        for scenario in self.scenarios:
            if scenario["name"] == name:
                return scenario
        raise AssertionError(f"Missing scenario fixture: {name}")

    def _fake_routed_result(self, *, errors: dict[str, str]):
        provider_results = [
            SimpleNamespace(
                provider="ohana",
                status="ok",
                error="",
                search_url="https://liveohana.ai/sublet/boston",
                records=[{"provider": "ohana", "title": "Furnished room"}],
                filter_application={"source_applied": ["location"]},
                query_quality={"status": "partial"},
                raw_output=None,
                csv_output=None,
                debug_artifacts={},
            ),
            SimpleNamespace(
                provider="rentalsource",
                status="failed" if errors.get("rentalsource") else "ok",
                error=errors.get("rentalsource", ""),
                search_url="https://www.rentalsource.com/boston-ma/",
                records=[] if errors.get("rentalsource") else [{"provider": "rentalsource", "title": "Backup"}],
                filter_application={"source_applied": ["location"]},
                query_quality={"status": "source_applied"},
                raw_output=None,
                csv_output=None,
                debug_artifacts={},
            ),
        ]
        records = [
            record
            for provider_result in provider_results
            for record in provider_result.records
        ]
        return SimpleNamespace(
            provider_results=provider_results,
            records=records,
            errors=errors,
        )

    def assert_expected_intent(self, actual: dict, expected: dict) -> None:
        for field, expected_value in expected.items():
            self.assertEqual(actual[field], expected_value, field)

    def assert_filter_application(self, response: dict, expected_by_provider: dict) -> None:
        plans = {
            provider_plan["provider"]: provider_plan
            for provider_plan in response["query_plan"]["provider_plans"]
        }
        for provider, expected in expected_by_provider.items():
            self.assertIn(provider, plans)
            application = plans[provider]["filter_application"]
            for section, expected_filters in expected.items():
                for filter_name in expected_filters:
                    self.assertIn(filter_name, application[section], f"{provider}.{section}.{filter_name}")

    def assert_skipped_providers(self, response: dict, providers: list[str]) -> None:
        skipped = {
            skipped_provider["provider"]
            for skipped_provider in response["execution"]["skipped_providers"]
        }
        for provider in providers:
            self.assertIn(provider, skipped)

    def assert_provider_score_order(self, response: dict, comparisons: list[list[str]]) -> None:
        scores = {
            provider_plan["provider"]: provider_plan["score"]
            for provider_plan in response["query_plan"]["provider_plans"]
        }
        for higher_provider, lower_provider in comparisons:
            self.assertGreater(scores[higher_provider], scores[lower_provider])

    def assert_warning_substrings(self, response: dict, substrings: list[str]) -> None:
        warning_text = "\n".join(response["warnings"]).lower()
        for substring in substrings:
            self.assertIn(substring.lower(), warning_text)


if __name__ == "__main__":
    unittest.main()
