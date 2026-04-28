from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.ohana_agent.housing_agent import StudentHousingSearchPlan, run_student_housing_agent
from src.ohana_agent.provider_router import normalize_provider_names


def fake_result(provider: str, records: list[dict], tmpdir: str):
    root = Path(tmpdir)
    return SimpleNamespace(
        records=records,
        raw_output=root / f"{provider}.jsonl",
        csv_output=root / f"{provider}.csv",
        debug_artifacts={"html": root / f"{provider}.html"},
        search_url=f"https://example.com/{provider}",
    )


class HousingProviderRoutingTests(unittest.TestCase):
    def test_provider_name_normalization_accepts_common_aliases(self) -> None:
        self.assertEqual(
            normalize_provider_names(["ohana", "rental source", "affordable housing"]),
            ["ohana", "rentalsource", "affordablehousing"],
        )

    def test_ohana_still_runs_through_main_flow(self) -> None:
        plan = StudentHousingSearchPlan(
            location="Boston, MA",
            providers=["ohana"],
            max_listings=2,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.housing_agent.plan_student_housing_search", return_value=plan):
                with patch("src.ohana_agent.provider_router.run_ohana_search") as run_ohana:
                    run_ohana.return_value = fake_result(
                        "ohana",
                        [{"source": "ohana", "title": "Student sublet", "url": "https://liveohana.ai/listing/1"}],
                        tmpdir,
                    )

                    result = run_student_housing_agent("Find a Boston sublet", summarize=False)

        self.assertEqual(len(result.search.records), 1)
        self.assertEqual(result.search.records[0]["provider"], "ohana")
        self.assertEqual(result.search.provider_results[0].status, "ok")
        run_ohana.assert_called_once()

    def test_rentalsource_can_be_instructed_through_main_flow(self) -> None:
        plan = StudentHousingSearchPlan(
            location="Boston, MA",
            providers=["ohana"],
            max_listings=2,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.housing_agent.plan_student_housing_search", return_value=plan):
                with patch("src.ohana_agent.provider_router.run_rentalsource_search") as run_rentalsource:
                    run_rentalsource.return_value = fake_result(
                        "rentalsource",
                        [
                            {
                                "source": "rentalsource",
                                "title": "Market apartment",
                                "url": "https://www.rentalsource.com/details/1/",
                            }
                        ],
                        tmpdir,
                    )

                    result = run_student_housing_agent(
                        "Find a Boston apartment",
                        providers=["rentalsource"],
                        summarize=False,
                    )

        self.assertEqual(len(result.search.records), 1)
        self.assertEqual(result.search.records[0]["provider"], "rentalsource")
        self.assertEqual(result.search.provider_results[0].provider, "rentalsource")
        run_rentalsource.assert_called_once()

    def test_affordablehousing_can_be_selected_by_plan_through_main_flow(self) -> None:
        plan = StudentHousingSearchPlan(
            location="Boston, MA",
            providers=["affordablehousing"],
            max_listings=2,
            notes=["Student asked for income restricted housing."],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.housing_agent.plan_student_housing_search", return_value=plan):
                with patch("src.ohana_agent.provider_router.run_affordablehousing_search") as run_affordable:
                    run_affordable.return_value = fake_result(
                        "affordablehousing",
                        [
                            {
                                "source": "affordablehousing",
                                "title": "Affordable apartment",
                                "url": "https://www.affordablehousing.com/boston-ma/a-1/",
                            }
                        ],
                        tmpdir,
                    )

                    result = run_student_housing_agent("Find affordable housing in Boston", summarize=False)

        self.assertEqual(len(result.search.records), 1)
        self.assertEqual(result.search.records[0]["provider"], "affordablehousing")
        self.assertEqual(result.search.provider_results[0].status, "ok")
        run_affordable.assert_called_once()

    def test_multi_provider_search_keeps_successes_when_one_empty_and_one_errors(self) -> None:
        plan = StudentHousingSearchPlan(
            location="Boston, MA",
            providers=["ohana", "rentalsource", "affordablehousing"],
            max_listings=2,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.housing_agent.plan_student_housing_search", return_value=plan):
                with patch("src.ohana_agent.provider_router.run_ohana_search") as run_ohana:
                    with patch("src.ohana_agent.provider_router.run_rentalsource_search") as run_rentalsource:
                        with patch("src.ohana_agent.provider_router.run_affordablehousing_search") as run_affordable:
                            run_ohana.return_value = fake_result("ohana", [], tmpdir)
                            run_rentalsource.side_effect = RuntimeError("RentalSource unavailable")
                            run_affordable.return_value = fake_result(
                                "affordablehousing",
                                [{"source": "affordablehousing", "title": "Affordable unit"}],
                                tmpdir,
                            )

                            result = run_student_housing_agent("Search across providers", summarize=False)

        statuses = {provider_result.provider: provider_result.status for provider_result in result.search.provider_results}
        self.assertEqual(statuses["ohana"], "empty")
        self.assertEqual(statuses["rentalsource"], "failed")
        self.assertEqual(statuses["affordablehousing"], "ok")
        self.assertEqual(len(result.search.records), 1)
        self.assertIn("rentalsource", result.search.errors)


if __name__ == "__main__":
    unittest.main()
