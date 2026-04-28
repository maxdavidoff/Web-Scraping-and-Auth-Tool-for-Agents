from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.housing_agent.interactive_agent import InteractiveHousingAgent


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "housing_chat_transcripts.json"


class FakeJsonClient:
    model = "fake-mistral"

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)

    def complete_json(self, messages, *, temperature=0.0, max_tokens=1200):
        if not self.responses:
            raise AssertionError("FakeJsonClient response queue is empty")
        return json.dumps(self.responses.pop(0))


def fake_router_result(provider: str):
    record = {
        "provider": provider,
        "title": "Mock listing",
        "price": "$1,800",
        "location": "Mock city",
    }
    provider_result = SimpleNamespace(
        provider=provider,
        status="ok",
        error="",
        search_url=f"https://example.com/{provider}",
        records=[record],
        raw_output=None,
        csv_output=None,
        debug_artifacts={},
    )
    return SimpleNamespace(provider_results=[provider_result], records=[record], errors={})


class HousingChatTranscriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cls.scenarios = json.load(handle)

    def test_agent_led_golden_transcripts(self) -> None:
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["name"]):
                executed_providers: list[str] = []

                def router(*args, **kwargs):
                    provider = kwargs["providers"][0]
                    executed_providers.append(provider)
                    return fake_router_result(provider)

                agent = InteractiveHousingAgent(
                    client=FakeJsonClient(scenario["model_responses"]),
                    runner=Mock(side_effect=router),
                    max_listings=5,
                )

                for turn_spec in scenario["turns"]:
                    turn = agent.handle_user_message(turn_spec["user"])
                    for expected_text in turn_spec.get("agent_should_include", []):
                        self.assertIn(expected_text, turn.message)
                    expected_provider = turn_spec.get("expected_execute_provider")
                    if expected_provider:
                        self.assertEqual(executed_providers[-1], expected_provider)


if __name__ == "__main__":
    unittest.main()
