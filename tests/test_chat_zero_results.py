from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.housing_agent.interactive_agent import InteractiveHousingAgent
from src.housing_agent.types import HousingSearchIntent


class ChatZeroResultsTests(unittest.TestCase):
    def test_zero_results_suggests_specific_price_relaxation(self) -> None:
        agent = InteractiveHousingAgent()
        agent.current_intent = HousingSearchIntent(location="Boston, MA", max_price=1800)
        result = SimpleNamespace(
            provider_results=[],
            records=[],
            excluded_records=[],
            exclusion_counts={"max_price": 3},
            errors={},
        )

        rendered = agent.render_execution_result(result)

        self.assertIn("retry at $2,150", rendered)
        self.assertIn("under $1,800", rendered)


if __name__ == "__main__":
    unittest.main()
