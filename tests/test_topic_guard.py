from __future__ import annotations

import json
import unittest

from src.housing_agent.topic_guard import (
    TOPIC_GUARD_SYSTEM_PROMPT,
    build_topic_guard_messages,
    evaluate_message_topic,
    topic_result_from_mapping,
)
from src.housing_agent.types import HousingSearchIntent


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


class TopicGuardTests(unittest.TestCase):
    def test_build_topic_guard_messages_are_execution_neutral(self) -> None:
        messages = build_topic_guard_messages(
            "under 1800",
            current_intent=HousingSearchIntent(location="Boston, MA"),
            transcript=[{"role": "user", "content": "I need an apartment"}],
            today="2026-04-28",
        )

        self.assertIn("housing-message topic guard", messages[0]["content"])
        self.assertIn("answers a previous rental-housing follow-up", TOPIC_GUARD_SYSTEM_PROMPT)
        self.assertNotIn("scrape", messages[0]["content"].lower())
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["latest_user_message"], "under 1800")
        self.assertEqual(payload["current_intent"]["location"], "Boston, MA")

    def test_evaluate_message_topic_parses_off_topic_response(self) -> None:
        client = FakeJsonClient(
            {
                "is_on_topic": False,
                "confidence": "high",
                "reasoning_summary": "The message asks for cooking help.",
            }
        )

        result = evaluate_message_topic("give me a pancake recipe", client=client)

        self.assertFalse(result.is_on_topic)
        self.assertEqual(result.confidence, "high")
        self.assertIn("cooking", result.reasoning_summary)
        self.assertEqual(client.calls[0]["temperature"], 0.0)
        self.assertEqual(client.calls[0]["max_tokens"], 500)

    def test_topic_result_defaults_to_on_topic_for_missing_boolean(self) -> None:
        result = topic_result_from_mapping({"confidence": "medium"})

        self.assertTrue(result.is_on_topic)
        self.assertEqual(result.confidence, "medium")


if __name__ == "__main__":
    unittest.main()
