from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.housing_agent.interactive_agent import InteractiveHousingAgent


class FakeJsonClient:
    model = "fake-mistral"

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, messages, *, temperature=0.0, max_tokens=1200):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if not self.responses:
            raise AssertionError("FakeJsonClient response queue is empty")
        return json.dumps(self.responses.pop(0))


def fake_router_result(records: list[dict] | None = None, errors: dict[str, str] | None = None):
    records = records or [{"provider": "rentalsource", "title": "Test Apartment", "price": "$1,800"}]
    errors = errors or {}
    provider_results = [
        SimpleNamespace(
            provider="rentalsource",
            status="failed" if errors.get("rentalsource") else "ok",
            error=errors.get("rentalsource", ""),
            search_url="https://www.rentalsource.com/boston-ma/",
            records=[] if errors.get("rentalsource") else records,
            raw_output=Path("data/raw/fake.jsonl"),
            csv_output=Path("data/processed/fake.csv"),
            debug_artifacts={},
        )
    ]
    return SimpleNamespace(provider_results=provider_results, records=records, errors=errors)


class InteractiveHousingAgentTests(unittest.TestCase):
    def test_missing_location_triggers_clarification(self) -> None:
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "max_price": 1800,
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                    }
                ]
            )
        )

        turn = agent.handle_user_message("I need a one bedroom under 1800")

        self.assertEqual(turn.state, "needs_clarification")
        self.assertIn("city", turn.message.lower())
        self.assertIsNone(agent.current_intent.location)

    def test_vague_place_with_location_triggers_purpose_clarification(self) -> None:
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "intent_kind": "unknown",
                        "notes": ["cheap place"],
                    }
                ]
            )
        )

        turn = agent.handle_user_message("I need a cheap place in Boston")

        self.assertEqual(turn.state, "needs_clarification")
        self.assertIn("student/sublet", turn.message)
        self.assertIn("regular rental", turn.message)
        self.assertIn("affordable/voucher", turn.message)

    def test_clear_purpose_signals_do_not_over_clarify(self) -> None:
        scenarios = [
            (
                {
                    "location": "Boston, MA",
                    "section8": True,
                    "intent_kind": "affordable",
                    "notes": ["voucher holder"],
                },
                "affordablehousing",
            ),
            (
                {
                    "location": "Boston, MA",
                    "type_of_places": ["Private room"],
                    "furnished": True,
                    "intent_kind": "student_sublet",
                },
                "ohana",
            ),
            (
                {
                    "location": "Boston, MA",
                    "property_types": ["Apartment"],
                    "intent_kind": "general_rental",
                    "notes": ["normal apartment"],
                },
                "rentalsource",
            ),
        ]

        for response, expected_provider in scenarios:
            with self.subTest(provider=expected_provider):
                agent = InteractiveHousingAgent(client=FakeJsonClient([response]))
                turn = agent.handle_user_message("housing request")

                self.assertEqual(turn.state, "planned")
                self.assertEqual(turn.query_plan.ranked_provider_names[0], expected_provider)
                self.assertIn("Provider ranking", turn.message)

    def test_multi_turn_messages_update_same_intent(self) -> None:
        client = FakeJsonClient(
            [
                {
                    "type_of_places": ["Private room"],
                    "furnished": True,
                    "intent_kind": "student_sublet",
                },
                {
                    "location": "Boston, MA",
                    "max_price": 1800,
                    "type_of_places": ["Private room"],
                    "furnished": True,
                    "intent_kind": "student_sublet",
                },
            ]
        )
        agent = InteractiveHousingAgent(client=client)

        first = agent.handle_user_message("I need a furnished private room")
        second = agent.handle_user_message("Boston under 1800")

        self.assertEqual(first.state, "needs_clarification")
        self.assertEqual(second.state, "planned")
        self.assertEqual(agent.current_intent.location, "Boston, MA")
        self.assertEqual(agent.current_intent.max_price, 1800)
        self.assertEqual(agent.current_intent.type_of_places, ("Private room",))
        second_payload = json.loads(client.calls[1]["messages"][1]["content"])
        self.assertEqual(second_payload["previous_intent"]["type_of_places"], ["Private room"])

    def test_newer_user_message_overrides_older_location(self) -> None:
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "max_price": 1800,
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                    },
                    {
                        "location": "Philadelphia, PA",
                        "max_price": 1800,
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                    },
                ]
            )
        )

        agent.handle_user_message("I need an apartment in Boston under 1800")
        turn = agent.handle_user_message("actually make it Philadelphia")

        self.assertEqual(turn.state, "planned")
        self.assertEqual(agent.current_intent.location, "Philadelphia, PA")

    def test_negation_can_clear_prior_pet_policy(self) -> None:
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "property_types": ["Apartment"],
                        "pet_policy": ["dogs allowed"],
                        "intent_kind": "general_rental",
                    },
                    {
                        "location": "Boston, MA",
                        "property_types": ["Apartment"],
                        "pet_policy": [],
                        "intent_kind": "general_rental",
                        "notes": ["user no longer needs pet-friendly housing"],
                    },
                ]
            )
        )

        agent.handle_user_message("I need a dog friendly apartment in Boston")
        turn = agent.handle_user_message("actually no pets")

        self.assertEqual(turn.state, "planned")
        self.assertEqual(agent.current_intent.pet_policy, ())

    def test_not_affordable_housing_ranks_rentalsource_above_affordablehousing(self) -> None:
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                        "notes": ["normal apartment, not affordable housing"],
                    }
                ]
            )
        )

        turn = agent.handle_user_message("I need a normal apartment, not affordable housing, in Boston")

        self.assertEqual(turn.state, "planned")
        self.assertEqual(turn.query_plan.ranked_provider_names[0], "rentalsource")
        self.assertGreater(
            turn.query_plan.for_provider("rentalsource").score,
            turn.query_plan.for_provider("affordablehousing").score,
        )

    def test_execute_before_planning_is_blocked(self) -> None:
        runner = Mock()
        agent = InteractiveHousingAgent(client=FakeJsonClient([]), runner=runner)

        turn = agent.handle_user_message("execute")

        self.assertEqual(turn.state, "blocked")
        runner.assert_not_called()
        self.assertIn("blocked", turn.message.lower())

    def test_execute_then_yes_calls_router_with_confirmation(self) -> None:
        runner = Mock(return_value=fake_router_result())
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                    }
                ]
            ),
            runner=runner,
            max_listings=5,
        )

        plan_turn = agent.handle_user_message("I need an apartment in Boston")
        confirmation = agent.handle_user_message("execute")
        execution = agent.handle_user_message("yes")

        self.assertEqual(plan_turn.state, "planned")
        self.assertEqual(confirmation.state, "execution_confirmation_requested")
        self.assertIn("Max listings per provider: 5", confirmation.message)
        self.assertEqual(execution.state, "executed")
        runner.assert_called_once()
        self.assertEqual(runner.call_args.kwargs["max_listings"], 5)
        self.assertIn("rentalsource", runner.call_args.kwargs["providers"])

    def test_yes_and_no_too_early_do_not_execute(self) -> None:
        runner = Mock()
        agent = InteractiveHousingAgent(client=FakeJsonClient([]), runner=runner)

        yes_turn = agent.handle_user_message("yes")
        no_turn = agent.handle_user_message("no")

        self.assertEqual(yes_turn.state, "blocked")
        self.assertEqual(no_turn.state, "blocked")
        self.assertIn("no search awaiting confirmation", yes_turn.message.lower())
        self.assertIn("nothing is awaiting confirmation", no_turn.message.lower())
        runner.assert_not_called()

    def test_no_cancels_pending_execution_confirmation(self) -> None:
        runner = Mock()
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                    }
                ]
            ),
            runner=runner,
        )

        agent.handle_user_message("I need an apartment in Boston")
        agent.handle_user_message("execute")
        turn = agent.handle_user_message("no")

        self.assertEqual(turn.state, "planned")
        self.assertFalse(agent.pending_execution_confirmation)
        runner.assert_not_called()

    def test_max_listings_command_updates_execution_settings(self) -> None:
        runner = Mock(return_value=fake_router_result())
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                    }
                ]
            ),
            runner=runner,
        )

        agent.handle_user_message("I need an apartment in Boston")
        max_turn = agent.handle_user_message("max-listings 3")
        confirmation = agent.handle_user_message("execute")
        agent.handle_user_message("yes")

        self.assertIn("3", max_turn.message)
        self.assertIn("Max listings per provider: 3", confirmation.message)
        self.assertEqual(runner.call_args.kwargs["max_listings"], 3)

    def test_json_before_planning_returns_valid_current_state(self) -> None:
        agent = InteractiveHousingAgent(client=FakeJsonClient([]))

        turn = agent.handle_user_message("json")
        parsed = json.loads(turn.message)

        self.assertEqual(turn.state, "collecting")
        self.assertEqual(parsed["state"], "collecting")
        self.assertIsNone(parsed["intent"])
        self.assertIsNone(parsed["query_plan"])
        self.assertIsNone(parsed["execution_result"])

    def test_reset_clears_state(self) -> None:
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                    }
                ]
            )
        )

        agent.handle_user_message("I need an apartment in Boston")
        agent.handle_user_message("execute")
        turn = agent.handle_user_message("reset")

        self.assertEqual(turn.state, "reset")
        self.assertEqual(agent.transcript, [])
        self.assertIsNone(agent.current_intent)
        self.assertIsNone(agent.latest_plan)
        self.assertFalse(agent.pending_execution_confirmation)
        self.assertIsNone(agent.latest_execution_result)

    def test_interactive_agent_does_not_import_provider_specific_scraper_runners(self) -> None:
        source = Path("src/housing_agent/interactive_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_names.append(node.module or "")
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)

        forbidden = {
            "run_ohana_search",
            "run_rentalsource_search",
            "run_affordablehousing_search",
            "src.ohana_agent.search_runner",
            "src.rentalsource_agent.search_runner",
            "src.affordablehousing_agent.search_runner",
        }
        self.assertTrue(forbidden.isdisjoint(imported_names))


if __name__ == "__main__":
    unittest.main()
