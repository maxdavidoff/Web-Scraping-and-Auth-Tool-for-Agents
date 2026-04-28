from __future__ import annotations

import json
import unittest

from src.housing_agent.readiness_evaluator import (
    apply_readiness_guards,
    build_readiness_messages,
    evaluate_search_readiness,
    readiness_from_mapping,
)
from src.housing_agent.types import HousingSearchIntent


class FakeJsonClient:
    model = "fake-mistral"

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = []

    def complete_json(self, messages, *, temperature=0.0, max_tokens=1200):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        return json.dumps(self.response)


class SearchReadinessTests(unittest.TestCase):
    def test_build_readiness_messages_are_execution_neutral(self) -> None:
        messages = build_readiness_messages(
            HousingSearchIntent(location="Philadelphia", max_price=1600),
            transcript=[{"role": "user", "content": "near Penn under 1600"}],
            today="2026-04-28",
        )

        self.assertIn("do not choose providers", messages[0]["content"].lower())
        self.assertIn("do not", messages[0]["content"].lower())
        self.assertNotIn("run_ohana_search", messages[0]["content"])
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["today"], "2026-04-28")
        self.assertEqual(payload["intent"]["location"], "Philadelphia")

    def test_missing_location_is_guarded_even_if_model_says_ready(self) -> None:
        fake = FakeJsonClient(
            {
                "ready_to_search": True,
                "ready_to_recommend": True,
                "confidence": "high",
                "next_action": "execute_search",
                "followup_questions": [],
            }
        )

        readiness = evaluate_search_readiness(
            HousingSearchIntent(max_price=1800, property_types=("Apartment",)),
            client=fake,
            today="2026-04-28",
        )

        self.assertFalse(readiness.ready_to_search)
        self.assertEqual(readiness.next_action, "ask_followup")
        self.assertIn("location", readiness.missing_required_fields)
        self.assertIn("city", readiness.followup_questions[0].lower())

    def test_neighborhood_only_location_asks_for_larger_city(self) -> None:
        guarded = apply_readiness_guards(
            readiness_from_mapping(
                {
                    "ready_to_search": True,
                    "ready_to_recommend": False,
                    "confidence": "medium",
                    "next_action": "plan_search",
                }
            ),
            HousingSearchIntent(location="Cambridge", type_of_places=("Private room",)),
            transcript=[{"role": "user", "content": "private room in Cambridge"}],
        )

        self.assertFalse(guarded.ready_to_search)
        self.assertEqual(guarded.next_action, "ask_followup")
        self.assertIn("larger city", guarded.followup_questions[0].lower())

    def test_neighborhood_preference_followup_is_dropped_for_city_wide_search(self) -> None:
        guarded = apply_readiness_guards(
            readiness_from_mapping(
                {
                    "ready_to_search": False,
                    "ready_to_recommend": False,
                    "confidence": "medium",
                    "next_action": "ask_followup",
                    "missing_required_fields": ["neighborhood preference"],
                    "followup_questions": ["Do you have a preferred neighborhood or area in Boston?"],
                }
            ),
            HousingSearchIntent(location="Boston, MA", max_price=1800, type_of_places=("Private room",)),
            transcript=[{"role": "user", "content": "private room in Boston under 1800"}],
        )

        self.assertTrue(guarded.ready_to_search)
        self.assertEqual(guarded.next_action, "request_confirmation")
        self.assertEqual(guarded.followup_questions, ())

    def test_vague_city_search_asks_provider_routing_question(self) -> None:
        guarded = apply_readiness_guards(
            readiness_from_mapping(
                {
                    "ready_to_search": True,
                    "ready_to_recommend": False,
                    "confidence": "medium",
                    "next_action": "plan_search",
                }
            ),
            HousingSearchIntent(location="Boston, MA", max_price=1800),
            transcript=[{"role": "user", "content": "I need housing in Boston under 1800"}],
        )

        self.assertFalse(guarded.ready_to_search)
        self.assertEqual(guarded.next_action, "ask_followup")
        self.assertIn("multiple roommates", guarded.followup_questions[0])
        self.assertIn("affordable", guarded.followup_questions[0])

    def test_vague_new_york_apartment_can_follow_model_readiness(self) -> None:
        model_readiness = readiness_from_mapping(
            {
                "ready_to_search": True,
                "ready_to_recommend": False,
                "confidence": "medium",
                "next_action": "plan_search",
                "safe_assumptions": ["Treat missing budget and bedrooms as flexible."],
            }
        )

        guarded = apply_readiness_guards(
            model_readiness,
            HousingSearchIntent(location="New York", property_types=("Apartment",), intent_kind="apartment"),
            transcript=[{"role": "user", "content": "I need an apartment in New York"}],
        )

        self.assertTrue(guarded.ready_to_search)
        self.assertFalse(guarded.ready_to_recommend)
        self.assertEqual(guarded.next_action, "request_confirmation")
        self.assertEqual(guarded.followup_questions, ())

    def test_section8_prompt_is_ready_enough_for_affordable_planning(self) -> None:
        model_readiness = readiness_from_mapping(
            {
                "ready_to_search": True,
                "ready_to_recommend": False,
                "confidence": "medium",
                "next_action": "plan_search",
                "reasoning_summary": "Voucher status and location are clear.",
            }
        )

        guarded = apply_readiness_guards(
            model_readiness,
            HousingSearchIntent(location="Boston, MA", section8=True, intent_kind="affordable"),
            transcript=[{"role": "user", "content": "I need Section 8 housing in Boston"}],
        )

        self.assertTrue(guarded.ready_to_search)
        self.assertEqual(guarded.next_action, "request_confirmation")
        self.assertEqual(guarded.followup_questions, ())

    def test_penn_under_1500_can_follow_model_followup(self) -> None:
        guarded = apply_readiness_guards(
            readiness_from_mapping(
                {
                    "ready_to_search": False,
                    "ready_to_recommend": False,
                    "next_action": "ask_followup",
                    "followup_questions": [
                        "Are you looking for a private room, shared room, or an entire place?",
                        "When does the summer program start?",
                    ],
                    "reasoning_summary": "Room type and timing would materially improve the search.",
                }
            ),
            HousingSearchIntent(location="Philadelphia", max_price=1500, campus_or_school="Penn"),
            transcript=[{"role": "user", "content": "I need somewhere near Penn under 1500"}],
        )

        self.assertFalse(guarded.ready_to_search)
        self.assertEqual(len(guarded.followup_questions), 2)
        self.assertIn("private room", guarded.followup_questions[0])

    def test_uncertain_budget_answer_does_not_repeat_budget_question(self) -> None:
        guarded = apply_readiness_guards(
            readiness_from_mapping(
                {
                    "ready_to_search": False,
                    "ready_to_recommend": False,
                    "next_action": "ask_followup",
                    "followup_questions": ["What is your maximum budget per person?"],
                    "reasoning_summary": "Missing budget and room type for a student sublet search.",
                }
            ),
            HousingSearchIntent(location="Philadelphia", campus_or_school="UPenn", intent_kind="student_sublet"),
            transcript=[
                {"role": "user", "content": "What is your maximum budget per person?"},
                {"role": "user", "content": "i dont really know"},
            ],
        )

        self.assertFalse(guarded.ready_to_search)
        self.assertNotIn("budget", " ".join(guarded.followup_questions).lower())
        self.assertIn("private room", guarded.followup_questions[0])

    def test_contradictory_followup_summary_is_cleaned(self) -> None:
        guarded = apply_readiness_guards(
            readiness_from_mapping(
                {
                    "ready_to_search": True,
                    "ready_to_recommend": True,
                    "next_action": "ask_followup",
                    "followup_questions": ["What is your maximum budget per person?"],
                    "reasoning_summary": "All required fields for a student sublet search are provided.",
                }
            ),
            HousingSearchIntent(location="Philadelphia", campus_or_school="UPenn", intent_kind="student_sublet"),
            transcript=[{"role": "user", "content": "summer program at upenn"}],
        )

        self.assertFalse(guarded.ready_to_search)
        self.assertNotIn("All required fields", guarded.reasoning_summary)

    def test_user_explicitly_browsing_permits_broad_search_with_caveat(self) -> None:
        guarded = apply_readiness_guards(
            readiness_from_mapping(
                {
                    "ready_to_search": True,
                    "ready_to_recommend": False,
                    "confidence": "low",
                    "next_action": "plan_search",
                    "safe_assumptions": ["Treat this as a broad browsing search."],
                }
            ),
            HousingSearchIntent(location="New York", property_types=("Apartment",), intent_kind="apartment"),
            transcript=[{"role": "user", "content": "Just browsing, show me options in New York"}],
        )

        self.assertTrue(guarded.ready_to_search)
        self.assertFalse(guarded.ready_to_recommend)
        self.assertEqual(guarded.next_action, "request_confirmation")


if __name__ == "__main__":
    unittest.main()
