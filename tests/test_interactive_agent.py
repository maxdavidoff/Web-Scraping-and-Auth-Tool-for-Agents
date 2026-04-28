from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.housing_agent.interactive_agent import BACKUP_PROVIDER_SCORE_RATIO, InteractiveHousingAgent
from src.housing_agent.topic_guard import MessageTopicResult
from src.housing_agent.types import ListingRankingResult, RankedListing, SearchReadiness


class FakeJsonClient:
    model = "fake-mistral"

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, messages, *, temperature=0.0, max_tokens=1200):
        if "housing-message topic guard" in messages[0].get("content", ""):
            return json.dumps({"is_on_topic": True, "confidence": "high"})
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


def fake_multi_provider_result(records: list[dict] | None = None):
    records = records or [
        {"provider": "ohana", "title": "Ohana room", "price": "$1,800", "raw_text": "Private room"},
        {"provider": "rentalsource", "title": "RentalSource studio", "price": "$2,700", "raw_text": "Studio apartment"},
    ]
    provider_results = [
        SimpleNamespace(
            provider="ohana",
            status="ok",
            error="",
            search_url="https://liveohana.ai/sublet/boston",
            records=[record for record in records if record.get("provider") == "ohana"],
            raw_output=Path("data/raw/ohana.jsonl"),
            csv_output=Path("data/processed/ohana.csv"),
            debug_artifacts={},
            excluded_records=[],
            exclusion_counts={},
        ),
        SimpleNamespace(
            provider="rentalsource",
            status="ok",
            error="",
            search_url="https://www.rentalsource.com/boston-ma/",
            records=[record for record in records if record.get("provider") == "rentalsource"],
            raw_output=Path("data/raw/rentalsource.jsonl"),
            csv_output=Path("data/processed/rentalsource.csv"),
            debug_artifacts={},
            excluded_records=[],
            exclusion_counts={},
        ),
    ]
    return SimpleNamespace(provider_results=provider_results, records=records, excluded_records=[], exclusion_counts={}, errors={})


def ready_readiness(intent, **kwargs):
    return SearchReadiness(
        ready_to_search=True,
        ready_to_recommend=True,
        confidence="high",
        next_action="request_confirmation",
        hard_constraints=tuple(filter(None, [intent.location])),
        reasoning_summary="I have enough information to run a targeted search.",
    )


def not_ready_readiness(*questions: str):
    def evaluator(intent, **kwargs):
        return SearchReadiness(
            ready_to_search=False,
            ready_to_recommend=False,
            confidence="medium",
            next_action="ask_followup",
            missing_required_fields=tuple(question.rstrip("?") for question in questions),
            followup_questions=tuple(questions),
            reasoning_summary="A couple of details would materially improve the search.",
        )

    return evaluator


def readiness_sequence(*items):
    queue = list(items)

    def evaluator(intent, **kwargs):
        if not queue:
            raise AssertionError("Readiness response queue is empty")
        item = queue.pop(0)
        return item(intent, **kwargs) if callable(item) else item

    return evaluator


def fake_listing_ranker(intent, readiness, records, **kwargs):
    first = records[0]
    return ListingRankingResult(
        recommended=(
            RankedListing(
                listing_id=str(first.get("listing_id", "")),
                title=first.get("title", "Test listing"),
                url=first.get("url", ""),
                fit_score=88,
                matched_constraints=("location",),
                why_it_fits="Matches the mocked search intent.",
                provider=first.get("provider", first.get("source", "")),
            ),
        ),
        overall_summary="Ranked against the current housing intent.",
    )


class InteractiveHousingAgentTests(unittest.TestCase):
    def test_backup_provider_threshold_is_pinned(self) -> None:
        self.assertEqual(BACKUP_PROVIDER_SCORE_RATIO, 0.60)

    def test_off_topic_message_is_blocked_before_intent_update(self) -> None:
        client = FakeJsonClient(
            [
                {
                    "location": "Boston, MA",
                    "property_types": ["Apartment"],
                    "intent_kind": "general_rental",
                }
            ]
        )
        agent = InteractiveHousingAgent(
            client=client,
            topic_evaluator=lambda *args, **kwargs: MessageTopicResult(
                is_on_topic=False,
                confidence="high",
                reasoning_summary="The message is not about rental housing.",
            ),
        )

        turn = agent.handle_user_message("write me a song about toast")

        self.assertEqual(turn.state, "off_topic")
        self.assertIn("rental housing", turn.message)
        self.assertIn("rental details again", turn.message)
        self.assertEqual(agent.transcript, [])
        self.assertIsNone(agent.current_intent)
        self.assertEqual(len(client.responses), 1)

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
            ),
            readiness_evaluator=not_ready_readiness("What larger city or metro area should I search in?"),
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
            ),
            readiness_evaluator=not_ready_readiness(
                "Is this a student/sublet room search, a regular rental search, or affordable/voucher housing?"
            ),
        )

        turn = agent.handle_user_message("I need a cheap place in Boston")

        self.assertEqual(turn.state, "needs_clarification")
        self.assertIn("student/sublet", turn.message)
        self.assertIn("regular rental", turn.message)
        self.assertIn("affordable/voucher", turn.message)

    def test_vague_housing_with_city_gets_routing_clarification(self) -> None:
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "max_price": 1800,
                    }
                ]
            ),
            readiness_evaluator=ready_readiness,
        )

        turn = agent.handle_user_message("I need housing in Boston under 1800")

        self.assertEqual(turn.state, "needs_clarification")
        self.assertIn("private room", turn.message)
        self.assertIn("multiple roommates", turn.message)
        self.assertIn("affordable", turn.message)

    def test_clear_purpose_signals_do_not_over_clarify(self) -> None:
        scenarios = [
            (
                {
                    "location": "Boston, MA",
                    "max_price": 1600,
                    "section8": True,
                    "intent_kind": "affordable",
                    "notes": ["voucher holder"],
                },
                "affordablehousing",
            ),
            (
                {
                    "location": "Boston, MA",
                    "max_price": 1800,
                    "type_of_places": ["Private room"],
                    "furnished": True,
                    "move_in_date": "2026-06-01",
                    "intent_kind": "student_sublet",
                },
                "ohana",
            ),
            (
                {
                    "location": "Boston, MA",
                    "max_price": 2200,
                    "bedrooms": 1,
                    "property_types": ["Apartment"],
                    "move_in_date": "2026-06-01",
                    "intent_kind": "general_rental",
                    "notes": ["normal apartment"],
                },
                "rentalsource",
            ),
        ]

        for response, expected_provider in scenarios:
            with self.subTest(provider=expected_provider):
                agent = InteractiveHousingAgent(
                    client=FakeJsonClient([response]),
                    readiness_evaluator=ready_readiness,
                )
                turn = agent.handle_user_message("housing request")

                self.assertEqual(turn.state, "execution_confirmation_requested")
                self.assertEqual(turn.query_plan.ranked_provider_names[0], expected_provider)
                self.assertIn("Want me to run it?", turn.message)

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
        agent = InteractiveHousingAgent(
            client=client,
            readiness_evaluator=readiness_sequence(
                not_ready_readiness("What larger city or metro area should I search in?"),
                ready_readiness,
            ),
        )

        first = agent.handle_user_message("I need a furnished private room")
        second = agent.handle_user_message("Boston under 1800")

        self.assertEqual(first.state, "needs_clarification")
        self.assertEqual(second.state, "execution_confirmation_requested")
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
            ),
            readiness_evaluator=ready_readiness,
        )

        agent.handle_user_message("I need an apartment in Boston under 1800")
        turn = agent.handle_user_message("actually make it Philadelphia")

        self.assertEqual(turn.state, "execution_confirmation_requested")
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
            ),
            readiness_evaluator=ready_readiness,
        )

        agent.handle_user_message("I need a dog friendly apartment in Boston")
        turn = agent.handle_user_message("actually no pets")

        self.assertEqual(turn.state, "execution_confirmation_requested")
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
            ),
            readiness_evaluator=ready_readiness,
        )

        turn = agent.handle_user_message("I need a normal apartment, not affordable housing, in Boston")

        self.assertEqual(turn.state, "execution_confirmation_requested")
        self.assertEqual(turn.query_plan.ranked_provider_names[0], "rentalsource")
        self.assertGreater(
            turn.query_plan.for_provider("rentalsource").score,
            turn.query_plan.for_provider("affordablehousing").score,
        )

    def test_student_program_summary_does_not_echo_broad_property_types_first(self) -> None:
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "University of Pennsylvania, Philadelphia, PA",
                        "campus_or_school": "UPenn",
                        "max_price": 5000,
                        "property_types": ["Apartment", "House", "Townhouse", "Condo"],
                        "lease_length": "summer",
                        "intent_kind": "student_sublet",
                        "notes": ["summer program"],
                    }
                ]
            ),
            readiness_evaluator=ready_readiness,
        )

        turn = agent.handle_user_message("probably like 5k")

        self.assertEqual(turn.state, "execution_confirmation_requested")
        self.assertIn("student summer housing near UPenn", turn.message)
        self.assertNotIn("apartment, house, townhouse, condo", turn.message.lower())

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
            readiness_evaluator=ready_readiness,
            listing_ranker=fake_listing_ranker,
            max_listings=5,
        )

        confirmation = agent.handle_user_message("I need an apartment in Boston")
        execution = agent.handle_user_message("yes")

        self.assertEqual(confirmation.state, "execution_confirmation_requested")
        self.assertIn("return up to 5 listings", confirmation.message)
        self.assertEqual(execution.state, "executed")
        self.assertIn("Recommended:", execution.message)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.kwargs["max_listings"], 5)
        self.assertEqual(runner.call_args.kwargs["providers"], ("rentalsource", "ohana"))

    def test_failing_upenn_to_boston_transcript_keeps_broad_candidates_visible(self) -> None:
        runner = Mock(return_value=fake_multi_provider_result())
        ranker = Mock(side_effect=fake_listing_ranker)
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "University of Pennsylvania, Philadelphia, PA",
                        "campus_or_school": "UPenn",
                        "intent_kind": "student_sublet",
                        "lease_length": "summer",
                    },
                    {
                        "location": "University of Pennsylvania, Philadelphia, PA",
                        "campus_or_school": "UPenn",
                        "intent_kind": "student_sublet",
                        "type_of_places": ["Private room"],
                        "flexibility_notes": ["budget_open"],
                    },
                    {
                        "location": "University of Pennsylvania, Philadelphia, PA",
                        "campus_or_school": "UPenn",
                        "min_price": 3000,
                        "max_price": 3000,
                        "intent_kind": "student_sublet",
                        "type_of_places": ["Private room"],
                        "move_in_date": "2026-06-01",
                        "move_out_date": "2026-08-01",
                    },
                    {
                        "location": "Boston",
                        "campus_or_school": "Boston University",
                        "min_price": 3000,
                        "max_price": 3000,
                        "intent_kind": "student_sublet",
                        "type_of_places": ["Private room", "Shared room", "Entire place"],
                        "move_in_date": "2026-06-01",
                        "move_out_date": "2026-08-01",
                    },
                    {
                        "location": "Boston",
                        "campus_or_school": "Boston University",
                        "min_price": 3000,
                        "max_price": 3000,
                        "bedrooms": 1,
                        "intent_kind": "student_sublet",
                        "type_of_places": ["Private room", "Shared room", "Entire place"],
                        "move_in_date": "2026-06-01",
                        "move_out_date": "2026-08-01",
                        "notes": [
                            "The flat itself can have more than one bedroom if it is a sublet.",
                        ],
                    },
                ]
            ),
            runner=runner,
            readiness_evaluator=ready_readiness,
            listing_ranker=ranker,
            max_listings=5,
        )

        agent.handle_user_message("i need a flat this summer for a program im taking at Upenn")
        agent.handle_user_message("no budget, i want a private room.")
        agent.handle_user_message("3k a month, 1st june to 1st aug")
        agent.handle_user_message("ok lets look for listings in Boston instead for the same dates and preferences.")
        confirmation = agent.handle_user_message(
            "just the one bedroom for myself but the flat itself can of course have more than one bedroom if its a sublet. "
            "its only for me for 3k a month is my budget"
        )
        execution = agent.handle_user_message("yes")

        self.assertEqual(confirmation.state, "execution_confirmation_requested")
        self.assertEqual(agent.current_intent.max_price, 3000)
        self.assertIsNone(agent.current_intent.min_price)
        self.assertIsNone(agent.current_intent.bedrooms)
        self.assertEqual(runner.call_args.kwargs["providers"], ("ohana", "rentalsource"))
        self.assertEqual(execution.state, "executed")
        self.assertEqual(len(agent.latest_execution_result.records), 2)
        self.assertEqual(len(ranker.call_args.args[2]), 2)

    def test_execute_command_repeats_agent_led_confirmation(self) -> None:
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
            readiness_evaluator=ready_readiness,
            listing_ranker=fake_listing_ranker,
            max_listings=5,
        )

        agent.handle_user_message("I need an apartment in Boston")
        confirmation = agent.handle_user_message("execute")

        self.assertEqual(confirmation.state, "execution_confirmation_requested")
        self.assertIn("RentalSource", confirmation.message)
        self.assertIn("Want me to run it?", confirmation.message)
        runner.assert_not_called()

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
            readiness_evaluator=ready_readiness,
        )

        agent.handle_user_message("I need an apartment in Boston")
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
            readiness_evaluator=ready_readiness,
            listing_ranker=fake_listing_ranker,
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
            ),
            readiness_evaluator=ready_readiness,
        )

        agent.handle_user_message("I need an apartment in Boston")
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
