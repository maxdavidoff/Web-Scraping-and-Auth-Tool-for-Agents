from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from src.housing_agent.intent_extractor import (
    build_intent_messages,
    build_intent_update_messages,
    extract_housing_intent,
    intent_from_mapping,
    parse_json_object,
    update_housing_intent,
)
from src.housing_agent.llm_client import DEFAULT_MISTRAL_MODEL, LLMClientError, MistralChatClient
from src.housing_agent.provider_capabilities import AFFORDABLEHOUSING, OHANA, RENTALSOURCE


class FakeJsonClient:
    model = "fake-mistral"

    def __init__(self, response: str) -> None:
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
        return self.response


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class IntentExtractorTests(unittest.TestCase):
    def test_build_intent_messages_are_provider_neutral_and_reject_empty_request(self) -> None:
        messages = build_intent_messages("furnished room in Boston under 1800", today="2026-04-28")

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Do not choose providers", messages[0]["content"])
        self.assertIn("provider-neutral", messages[0]["content"])
        self.assertNotIn("run_ohana_search", messages[0]["content"])
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["today"], "2026-04-28")
        self.assertEqual(payload["housing_request"], "furnished room in Boston under 1800")

        with self.assertRaises(ValueError):
            build_intent_messages("   ")

    def test_parse_json_object_accepts_raw_json_or_wrapped_json(self) -> None:
        self.assertEqual(parse_json_object('{"location": "Boston, MA"}'), {"location": "Boston, MA"})
        self.assertEqual(
            parse_json_object('Here is the JSON: {"location": "Boston, MA"}'),
            {"location": "Boston, MA"},
        )

    def test_intent_from_mapping_normalizes_types_and_aliases(self) -> None:
        intent = intent_from_mapping(
            {
                "location": "Boston, MA",
                "neighborhoods": ["Back Bay"],
                "avoid_neighborhoods": ["Far commute"],
                "min_price": "$1,000",
                "max_price": "1800",
                "price_basis": "per person",
                "bedrooms": "1",
                "bathrooms": "1.5",
                "property_types": ["Apartment"],
                "type_of_places": "Private room",
                "pet_policy": ["dogs allowed"],
                "furnished_status": ["Furnished"],
                "movein": "2026-06-01",
                "moveout": "2026-08-31",
                "lease_length": "summer",
                "campus_or_school": "Northeastern",
                "commute_target": "campus",
                "max_commute_minutes": "20",
                "roommate_count": "2",
                "required_amenities": ["laundry"],
                "preferred_amenities": ["natural light"],
                "dealbreakers": ["basement"],
                "safety_priority": "high",
                "student_priority": "medium",
                "photos": "true",
                "verified": "yes",
                "section8": "false",
                "flexibility_notes": ["dates can slide"],
                "notes": ["near campus"],
            }
        )

        self.assertEqual(intent.location, "Boston, MA")
        self.assertEqual(intent.neighborhoods, ("Back Bay",))
        self.assertEqual(intent.avoid_neighborhoods, ("Far commute",))
        self.assertEqual(intent.min_price, 1000)
        self.assertEqual(intent.max_price, 1800)
        self.assertEqual(intent.price_basis, "per_person")
        self.assertEqual(intent.bedrooms, 1)
        self.assertEqual(intent.bathrooms, 1.5)
        self.assertEqual(intent.property_types, ("Apartment",))
        self.assertEqual(intent.type_of_places, ("Private room",))
        self.assertTrue(intent.furnished)
        self.assertEqual(intent.move_in_date, "2026-06-01")
        self.assertEqual(intent.move_out_date, "2026-08-31")
        self.assertEqual(intent.lease_length, "summer")
        self.assertEqual(intent.campus_or_school, "Northeastern")
        self.assertEqual(intent.commute_target, "campus")
        self.assertEqual(intent.max_commute_minutes, 20)
        self.assertEqual(intent.roommate_count, 2)
        self.assertEqual(intent.required_amenities, ("laundry",))
        self.assertEqual(intent.preferred_amenities, ("natural light",))
        self.assertEqual(intent.dealbreakers, ("basement",))
        self.assertEqual(intent.safety_priority, "high")
        self.assertEqual(intent.student_priority, "medium")
        self.assertTrue(intent.photos)
        self.assertTrue(intent.verified_listings)
        self.assertFalse(intent.section8)
        self.assertEqual(intent.flexibility_notes, ("dates can slide",))
        self.assertEqual(intent.notes, ("near campus",))

    def test_neighborhood_only_location_is_not_used_as_search_location(self) -> None:
        fake = FakeJsonClient(json.dumps({"location": "Cambridge", "type_of_places": ["Private room"]}))

        result = extract_housing_intent("private room in Cambridge", client=fake, today="2026-04-28")

        self.assertIsNone(result.intent.location)
        self.assertEqual(result.intent.neighborhoods, ("Cambridge",))

    def test_neighborhood_followup_preserves_previous_city_location(self) -> None:
        previous = {"location": "Boston, MA", "type_of_places": ["Private room"], "intent_kind": "student_sublet"}
        fake = FakeJsonClient(
            json.dumps(
                {
                    "location": "Cambridge",
                    "type_of_places": ["Private room"],
                    "intent_kind": "student_sublet",
                }
            )
        )

        result = update_housing_intent(
            previous,
            "I prefer Cambridge",
            client=fake,
            today="2026-04-28",
        )

        self.assertEqual(result.intent.location, "Boston, MA")
        self.assertEqual(result.intent.neighborhoods, ("Cambridge",))

    def test_extract_housing_intent_uses_mocked_mistral_client_and_plans_providers(self) -> None:
        fake = FakeJsonClient(
            json.dumps(
                {
                    "location": "Boston, MA",
                    "max_price": 1800,
                    "bedrooms": 1,
                    "type_of_places": ["Private room"],
                    "furnished": True,
                    "move_in_date": "2026-06-01",
                    "intent_kind": "student_sublet",
                    "notes": ["student wants summer housing near campus"],
                }
            )
        )

        result = extract_housing_intent(
            "I need a furnished private room in Boston under 1800 for June",
            client=fake,
            providers=[OHANA, RENTALSOURCE, AFFORDABLEHOUSING],
            today="2026-04-28",
        )

        self.assertEqual(result.model, "fake-mistral")
        self.assertEqual(result.intent.location, "Boston, MA")
        self.assertEqual(result.intent.max_price, 1800)
        self.assertEqual(result.intent.type_of_places, ("Private room",))
        self.assertEqual(result.query_plan.ranked_provider_names[0], OHANA)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["temperature"], 0.0)

    def test_update_housing_intent_asks_for_full_merged_intent_with_newer_override(self) -> None:
        previous = intent_from_mapping(
            {
                "location": "Boston, MA",
                "max_price": 1800,
                "property_types": ["Apartment"],
                "intent_kind": "general_rental",
            }
        )
        messages = build_intent_update_messages(
            previous,
            "actually make it Philadelphia",
            today="2026-04-28",
        )

        self.assertIn("full merged HousingSearchIntent", messages[0]["content"])
        self.assertIn("Newer user messages override older values", messages[0]["content"])
        self.assertNotIn("run_ohana_search", messages[0]["content"])
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["previous_intent"]["location"], "Boston, MA")
        self.assertEqual(payload["latest_user_message"], "actually make it Philadelphia")

        fake = FakeJsonClient(
            json.dumps(
                {
                    "location": "Philadelphia, PA",
                    "max_price": 1800,
                    "property_types": ["Apartment"],
                    "intent_kind": "general_rental",
                }
            )
        )
        result = update_housing_intent(
            previous,
            "actually make it Philadelphia",
            client=fake,
            today="2026-04-28",
        )

        self.assertEqual(result.intent.location, "Philadelphia, PA")
        self.assertEqual(result.intent.max_price, 1800)

    def test_mistral_client_posts_json_mode_chat_completion_payload(self) -> None:
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"location": "Philadelphia, PA", "max_price": 2000}'
                    }
                }
            ]
        }

        captured = {}

        def fake_urlopen(request, timeout, **kwargs):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            captured["context"] = kwargs.get("context")
            return FakeHTTPResponse(response_payload)

        client = MistralChatClient(
            api_key="test-key",
            model="mistral-small-latest",
            base_url="https://api.mistral.test/v1",
            timeout_seconds=7,
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            content = client.complete_json([{"role": "user", "content": "hello"}])

        self.assertEqual(content, '{"location": "Philadelphia, PA", "max_price": 2000}')
        self.assertEqual(captured["url"], "https://api.mistral.test/v1/chat/completions")
        self.assertEqual(captured["timeout"], 7)
        self.assertIsNotNone(captured["context"])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["payload"]["model"], "mistral-small-latest")
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertFalse(captured["payload"]["stream"])

    def test_mistral_client_reads_key_and_model_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MISTRAL_API_KEY": "env-key",
                "MISTRAL_MODEL": "env-model",
                "MISTRAL_BASE_URL": "https://mistral.example/v1",
            },
        ):
            client = MistralChatClient.from_env()

        self.assertEqual(client.api_key, "env-key")
        self.assertEqual(client.model, "env-model")
        self.assertEqual(client.base_url, "https://mistral.example/v1")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMClientError):
                MistralChatClient.from_env()


@unittest.skipUnless(
    os.getenv("RUN_LIVE_LLM_TESTS") == "1",
    "Set RUN_LIVE_LLM_TESTS=1 to run live Mistral intent extraction tests",
)
class MistralLiveIntentExtractionTests(unittest.TestCase):
    def test_live_mistral_extracts_provider_neutral_intent(self) -> None:
        if not os.getenv("MISTRAL_API_KEY"):
            self.skipTest("MISTRAL_API_KEY is required for live LLM tests")

        result = extract_housing_intent(
            "Find me a furnished private room in Boston under $1800 for June 2026",
            model=os.getenv("MISTRAL_MODEL", DEFAULT_MISTRAL_MODEL),
            providers=[OHANA, RENTALSOURCE, AFFORDABLEHOUSING],
            today="2026-04-28",
        )

        self.assertIsNotNone(result.intent.location)
        self.assertEqual(result.intent.max_price, 1800)
        self.assertTrue(result.intent.furnished)
        self.assertIn(result.query_plan.ranked_provider_names[0], {OHANA, RENTALSOURCE, AFFORDABLEHOUSING})


if __name__ == "__main__":
    unittest.main()
