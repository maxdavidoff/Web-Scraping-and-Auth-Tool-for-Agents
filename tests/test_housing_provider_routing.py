from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.ohana_agent.provider_router import normalize_provider_names, run_provider_searches


def make_plan(**overrides):
    values = {
        "location": "Boston, MA",
        "providers": ["ohana"],
        "movein": None,
        "moveout": None,
        "property_types": None,
        "type_of_places": None,
        "num_bedrooms": None,
        "num_bathrooms": None,
        "min_price": None,
        "max_price": None,
        "pet_policy": None,
        "furnished_status": None,
        "photos": False,
        "verified": False,
        "featured": False,
        "sort": None,
        "page": None,
        "max_listings": 2,
        "notes": None,
        "assumptions": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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

    def test_ohana_runs_through_deterministic_router(self) -> None:
        plan = make_plan(providers=["ohana"])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.provider_router.run_ohana_search") as run_ohana:
                run_ohana.return_value = fake_result(
                    "ohana",
                    [{"source": "ohana", "title": "Student sublet", "url": "https://liveohana.ai/listing/1"}],
                    tmpdir,
                )

                result = run_provider_searches(plan, providers=plan.providers)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["provider"], "ohana")
        self.assertEqual(result.records[0]["coordinates_status"], "not_requested")
        self.assertEqual(result.records[0]["coordinates_source"], "ohana_init_data")
        self.assertEqual(result.provider_results[0].status, "ok")
        run_ohana.assert_called_once()

    def test_rentalsource_can_be_selected_through_deterministic_router(self) -> None:
        plan = make_plan(providers=["rentalsource"])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.provider_router.run_rentalsource_search") as run_rentalsource:
                run_rentalsource.return_value = fake_result(
                    "rentalsource",
                    [
                        {
                            "source": "rentalsource",
                            "title": "Market apartment",
                            "url": "https://www.rentalsource.com/details/1/",
                            "listing_latitude": 42.3,
                            "listing_longitude": -71.0,
                            "listing_location_source": "detail_json_ld",
                        }
                    ],
                    tmpdir,
                )

                result = run_provider_searches(plan, providers=plan.providers)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["provider"], "rentalsource")
        self.assertEqual(result.records[0]["coordinates_status"], "present")
        self.assertEqual(result.records[0]["coordinates_source"], "detail_json_ld")
        self.assertEqual(result.provider_results[0].provider, "rentalsource")
        run_rentalsource.assert_called_once()

    def test_rentalsource_router_passes_full_url_filters_and_reports_them(self) -> None:
        plan = make_plan(
            providers=["rentalsource"],
            property_types=["Apartment"],
            num_bedrooms=2,
            num_bathrooms=1.5,
            min_price=1200,
            max_price=3400,
            pet_policy=["dogs"],
            photos=True,
            verified=True,
            featured=True,
            sort="price-high",
            page=2,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.provider_router.run_rentalsource_search") as run_rentalsource:
                run_rentalsource.return_value = fake_result(
                    "rentalsource",
                    [{"source": "rentalsource", "title": "Filtered apartment"}],
                    tmpdir,
                )

                result = run_provider_searches(plan, providers=plan.providers)

        options = run_rentalsource.call_args.args[0]
        self.assertEqual(options.num_bathrooms, 1.5)
        self.assertTrue(options.pets)
        self.assertTrue(options.photos)
        self.assertTrue(options.verified)
        self.assertTrue(options.featured)
        self.assertEqual(options.sort, "price-high")
        self.assertEqual(options.page, 2)

        provider_result = result.provider_results[0]
        self.assertEqual(provider_result.query_quality["status"], "source_applied")
        self.assertIn("num_bathrooms", provider_result.filter_application["source_applied"])
        self.assertIn("photos", provider_result.filter_application["source_applied"])
        self.assertIn("verified", provider_result.filter_application["source_applied"])
        self.assertIn("featured", provider_result.filter_application["source_applied"])
        self.assertIn("sort", provider_result.filter_application["source_applied"])
        self.assertIn("page", provider_result.filter_application["source_applied"])

    def test_affordablehousing_can_be_selected_through_deterministic_router(self) -> None:
        plan = make_plan(
            providers=["affordablehousing"],
            notes=["Student asked for income restricted housing."],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.provider_router.run_affordablehousing_search") as run_affordable:
                run_affordable.return_value = fake_result(
                    "affordablehousing",
                    [
                        {
                            "source": "affordablehousing",
                            "title": "Affordable apartment",
                            "url": "https://www.affordablehousing.com/boston-ma/a-1/",
                            "listing_detail_status": "ok_no_detail_coordinates",
                        }
                    ],
                    tmpdir,
                )

                result = run_provider_searches(plan, providers=plan.providers)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["provider"], "affordablehousing")
        self.assertEqual(result.records[0]["coordinates_status"], "missing")
        self.assertEqual(result.records[0]["coordinates_source"], "server_side_variables")
        self.assertEqual(result.provider_results[0].status, "ok")
        run_affordable.assert_called_once()

    def test_fetch_listing_api_enables_affordablehousing_detail_enrichment(self) -> None:
        plan = make_plan(providers=["affordablehousing"])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.provider_router.run_affordablehousing_search") as run_affordable:
                run_affordable.return_value = fake_result("affordablehousing", [], tmpdir)

                run_provider_searches(
                    plan,
                    providers=plan.providers,
                    fetch_listing_api=True,
                )

        options = run_affordable.call_args.args[0]
        self.assertTrue(options.fetch_listing_detail)

    def test_affordablehousing_report_does_not_mark_min_price_source_applied(self) -> None:
        plan = make_plan(
            providers=["affordablehousing"],
            min_price=900,
            max_price=1800,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.ohana_agent.provider_router.run_affordablehousing_search") as run_affordable:
                run_affordable.return_value = fake_result(
                    "affordablehousing",
                    [{"source": "affordablehousing", "title": "Affordable unit"}],
                    tmpdir,
                )

                result = run_provider_searches(plan, providers=plan.providers)

        provider_result = result.provider_results[0]
        self.assertIn("max_price", provider_result.filter_application["source_applied"])
        self.assertNotIn("min_price", provider_result.filter_application["source_applied"])
        self.assertIn("min_price", provider_result.filter_application["not_source_applied"])
        self.assertEqual(provider_result.query_quality["status"], "partial")

    def test_multi_provider_search_keeps_successes_when_one_empty_and_one_errors(self) -> None:
        plan = make_plan(providers=["ohana", "rentalsource", "affordablehousing"])

        with tempfile.TemporaryDirectory() as tmpdir:
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

                        result = run_provider_searches(plan, providers=plan.providers)

        statuses = {provider_result.provider: provider_result.status for provider_result in result.provider_results}
        self.assertEqual(statuses["ohana"], "empty")
        self.assertEqual(statuses["rentalsource"], "failed")
        self.assertEqual(statuses["affordablehousing"], "ok")
        self.assertEqual(len(result.records), 1)
        self.assertIn("rentalsource", result.errors)


if __name__ == "__main__":
    unittest.main()
