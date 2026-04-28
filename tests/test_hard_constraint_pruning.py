from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.housing_agent.interactive_agent import InteractiveHousingAgent
from src.housing_agent.types import ListingRankingResult, SearchReadiness


class FakeJsonClient:
    model = "fake-mistral"

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)

    def complete_json(self, messages, *, temperature=0.0, max_tokens=1200):
        if "housing-message topic guard" in messages[0].get("content", ""):
            return json.dumps({"is_on_topic": True, "confidence": "high"})
        return json.dumps(self.responses.pop(0))


def ready_readiness(intent, **kwargs):
    return SearchReadiness(
        ready_to_search=True,
        ready_to_recommend=True,
        confidence="high",
        next_action="request_confirmation",
    )


def routed_result(records: list[dict]):
    provider_result = SimpleNamespace(
        provider="rentalsource",
        status="ok",
        error="",
        search_url="https://www.rentalsource.com/boston-ma/",
        records=records,
        excluded_records=[],
        exclusion_counts={},
        raw_output=None,
        csv_output=None,
        debug_artifacts={},
    )
    return SimpleNamespace(provider_results=[provider_result], records=records, excluded_records=[], exclusion_counts={}, errors={})


class HardConstraintPruningTests(unittest.TestCase):
    def test_hard_price_violation_is_excluded_before_ranker(self) -> None:
        records_seen_by_ranker = []

        def ranker(intent, readiness, records, **kwargs):
            records_seen_by_ranker.extend(records)
            return ListingRankingResult(overall_summary="ranked survivors")

        runner = Mock(
            return_value=routed_result(
                [
                    {"title": "Within budget", "price": "$1,900", "raw_text": "Apartment"},
                    {"title": "Too expensive", "price": "$3,500", "raw_text": "Apartment"},
                ]
            )
        )
        agent = InteractiveHousingAgent(
            client=FakeJsonClient(
                [
                    {
                        "location": "Boston, MA",
                        "max_price": 2000,
                        "property_types": ["Apartment"],
                        "intent_kind": "general_rental",
                    }
                ]
            ),
            runner=runner,
            readiness_evaluator=ready_readiness,
            listing_ranker=ranker,
        )

        agent.handle_user_message("apartment in Boston under 2000")
        turn = agent.handle_user_message("yes")

        self.assertEqual(turn.state, "executed")
        self.assertEqual([record["title"] for record in records_seen_by_ranker], ["Within budget"])
        self.assertEqual(agent.latest_listing_ranking.excluded[0].title, "Too expensive")
        self.assertIn("above max", agent.latest_listing_ranking.excluded[0].why_it_fits)


if __name__ == "__main__":
    unittest.main()
