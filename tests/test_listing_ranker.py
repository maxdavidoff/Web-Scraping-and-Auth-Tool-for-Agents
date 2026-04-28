from __future__ import annotations

import json
import unittest

from src.housing_agent.listing_ranker import (
    build_listing_ranker_messages,
    rank_listings,
    ranking_from_mapping,
)
from src.housing_agent.types import HousingSearchIntent, SearchReadiness


class FakeJsonClient:
    model = "fake-mistral"

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = []

    def complete_json(self, messages, *, temperature=0.0, max_tokens=1200):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        return json.dumps(self.response)


class ListingRankerTests(unittest.TestCase):
    def test_build_listing_ranker_messages_are_provider_execution_neutral(self) -> None:
        messages = build_listing_ranker_messages(
            HousingSearchIntent(location="Boston, MA", max_price=1800),
            SearchReadiness(ready_to_search=True, ready_to_recommend=True),
            [{"title": "Studio", "price": "$1,700"}],
        )

        self.assertIn("Do not invent facts", messages[0]["content"])
        self.assertNotIn("run_ohana_search", messages[0]["content"])
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["intent"]["location"], "Boston, MA")
        self.assertEqual(payload["records"][0]["title"], "Studio")

    def test_listing_ranker_prompt_states_prices_are_monthly(self) -> None:
        """Regression: ranker used to multiply $X/mo by sublet length and over-exclude."""
        messages = build_listing_ranker_messages(
            HousingSearchIntent(location="Philadelphia, PA", max_price=1800),
            SearchReadiness(ready_to_search=True),
            [{"title": "Room", "price": "$1,650/mo"}],
        )
        prompt = messages[0]["content"]
        self.assertIn("MONTHLY", prompt)
        self.assertIn("Do NOT multiply", prompt)
        self.assertIn("timing signal, not a budget multiplier", prompt)

    def test_listing_ranker_prompt_narrows_price_exclusion_rule(self) -> None:
        """Regression: ranker invented 'per month vs per room' as an exclusion reason."""
        messages = build_listing_ranker_messages(
            HousingSearchIntent(location="Philadelphia, PA", max_price=1800),
            SearchReadiness(ready_to_search=True),
            [{"title": "Room", "price": "$1,650/mo"}],
        )
        prompt = messages[0]["content"]
        self.assertIn("ONLY price-based reason to exclude", prompt)
        self.assertIn("Do not exclude a listing for \"price basis mismatch\"", prompt)
        self.assertIn("needs_verification", prompt)

    def test_rank_listings_parses_recommended_needs_verification_and_excluded(self) -> None:
        fake = FakeJsonClient(
            {
                "recommended": [
                    {
                        "listing_id": "ok-1",
                        "title": "Private room near campus",
                        "url": "https://example.com/ok",
                        "fit_score": 92,
                        "matched_constraints": ["Boston", "under budget"],
                        "missing_info": [],
                        "concerns": [],
                        "why_it_fits": "Matches the hard constraints.",
                        "provider": "ohana",
                    }
                ],
                "needs_verification": [
                    {
                        "listing_id": "maybe-1",
                        "title": "Apartment with missing availability",
                        "fit_score": 61,
                        "matched_constraints": ["Boston"],
                        "missing_info": ["availability"],
                        "concerns": [],
                        "why_it_fits": "Promising but availability is unknown.",
                    }
                ],
                "excluded": [
                    {
                        "listing_id": "bad-1",
                        "title": "Too expensive",
                        "fit_score": 10,
                        "matched_constraints": ["Boston"],
                        "missing_info": [],
                        "concerns": ["violates max budget"],
                        "why_it_fits": "Does not satisfy the max price.",
                    }
                ],
                "overall_summary": "One listing is a strong fit.",
                "followup_suggestions": ["Verify lease dates."],
            }
        )

        result = rank_listings(
            HousingSearchIntent(location="Boston, MA", max_price=1800),
            SearchReadiness(ready_to_search=True, ready_to_recommend=True),
            [{"listing_id": "ok-1", "title": "Private room near campus"}],
            client=fake,
        )

        self.assertEqual(result.recommended[0].fit_score, 92)
        self.assertEqual(result.needs_verification[0].missing_info, ("availability",))
        self.assertEqual(result.excluded[0].concerns, ("violates max budget",))
        self.assertEqual(result.followup_suggestions, ("Verify lease dates.",))

    def test_ranking_from_mapping_clamps_scores_and_preserves_missing_info(self) -> None:
        result = ranking_from_mapping(
            {
                "recommended": [{"title": "Impossible score", "fit_score": 900}],
                "needs_verification": [{"title": "Unknown rent", "missing_info": ["price", "availability"]}],
                "excluded": [{"title": "Hard fail", "fit_score": -5, "concerns": ["wrong city"]}],
            }
        )

        self.assertEqual(result.recommended[0].fit_score, 100)
        self.assertEqual(result.needs_verification[0].missing_info, ("price", "availability"))
        self.assertEqual(result.excluded[0].fit_score, 0)

    def test_no_records_returns_empty_result_without_model_call(self) -> None:
        fake = FakeJsonClient({"recommended": []})

        result = rank_listings(
            HousingSearchIntent(location="Boston, MA"),
            SearchReadiness(ready_to_search=True),
            [],
            client=fake,
        )

        self.assertEqual(result.recommended, ())
        self.assertEqual(fake.calls, [])
        self.assertIn("No listings", result.overall_summary)


if __name__ == "__main__":
    unittest.main()
