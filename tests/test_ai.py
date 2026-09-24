from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from iphone_market import db
from iphone_market.ai import (
    estimate_valuation,
    feedback_metrics,
    find_opportunities,
    list_feedback,
    normalize_model,
    normalize_storage_gb,
    record_feedback,
)
from iphone_market.models import CollectionResult, ListingRecord


def _listing(price: str, listing_id: str, collected_date: str = "2026-09-23") -> ListingRecord:
    return ListingRecord(
        source_key="dcfever",
        source_name="DCFever",
        market="香港",
        listing_id=listing_id,
        title=f"iPhone 14 Pro 128GB used {listing_id}",
        url=f"https://example.test/{listing_id}",
        model="iPhone 14 Pro",
        generation=14,
        family="Pro",
        storage_gb=128,
        condition="used",
        listing_status="active",
        price_native=Decimal(price),
        currency="HKD",
        price_cny=Decimal(price),
        fx_date=collected_date,
        location="香港",
        raw={},
    )


class AiValuationTests(unittest.TestCase):
    def test_normalizes_model_and_storage(self) -> None:
        self.assertEqual(normalize_model("iphone 17 promax"), "iPhone 17 Pro Max")
        self.assertEqual(normalize_model("iPhone 15 Pro"), "iPhone 15 Pro")
        self.assertEqual(normalize_storage_gb("1TB"), 1024)
        self.assertEqual(normalize_storage_gb("2048GB"), 2048)

    def test_valuation_removes_outliers_and_builds_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)
            run_id = db.start_run(conn, "2026-09-23")
            db.start_source_run(conn, run_id, "dcfever", "香港")
            db.insert_listings(
                conn,
                run_id,
                "2026-09-23",
                [
                    _listing("2000", "a"),
                    _listing("2100", "b"),
                    _listing("2200", "c"),
                    _listing("2300", "d"),
                    _listing("2400", "e"),
                    _listing("2500", "f"),
                    _listing("0.5", "bad-low"),
                    _listing("100000", "bad-high"),
                ],
            )
            db.finish_source_run(conn, run_id, CollectionResult("dcfever", "ok", 8, 1))
            db.finish_run(conn, run_id, "ok")
            conn.execute(
                """
                INSERT INTO fx_rates(rate_date, rates_json, source, updated_at)
                VALUES ('2026-09-23', '{"CNY": "1", "HKD": "1.1"}', 'test', 'now')
                """
            )
            conn.commit()
            conn.close()

            result = estimate_valuation(
                model="iPhone 14 Pro",
                storage_gb=128,
                db_path=path,
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["sample_count"], 6)
            self.assertEqual(result["rejected_outliers"], 2)
            self.assertEqual(result["fair_range_cny"]["mid"], 2250.0)
            self.assertAlmostEqual(
                result["guidance_cny"]["suggested_purchase_max"],
                1870.0,
                places=2,
            )
            self.assertEqual(result["fair_range_native"]["currency"], "HKD")
            self.assertAlmostEqual(
                result["fair_range_native"]["mid"],
                2045.45,
                places=2,
            )

            opportunities = find_opportunities(
                model="iPhone 14 Pro",
                storage_gb=128,
                fee_pct=0,
                db_path=path,
            )
            self.assertEqual(opportunities["status"], "ok")
            self.assertTrue(opportunities["candidates"])
            self.assertEqual(
                opportunities["candidates"][0]["price_cny"],
                2000.0,
            )

    def test_insufficient_data_returns_explicit_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            result = estimate_valuation(
                model="iPhone 17 Pro Max",
                storage_gb="2TB",
                db_path=path,
            )
            self.assertEqual(result["status"], "no_data")
            self.assertEqual(result["sample_count"], 0)

    def test_rejects_invalid_variant(self) -> None:
        with self.assertRaises(ValueError):
            estimate_valuation(
                model="iPhone 15 Pro Max",
                storage_gb="128GB",
            )

    def test_feedback_records_estimate_and_actual_profit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)
            run_id = db.start_run(conn, "2026-09-23")
            db.start_source_run(conn, run_id, "dcfever", "香港")
            db.insert_listings(
                conn,
                run_id,
                "2026-09-23",
                [
                    _listing("2000", "a"),
                    _listing("2100", "b"),
                    _listing("2200", "c"),
                    _listing("2300", "d"),
                    _listing("2400", "e"),
                    _listing("2500", "f"),
                ],
            )
            db.finish_source_run(
                conn,
                run_id,
                CollectionResult("dcfever", "ok", 6, 1),
            )
            db.finish_run(conn, run_id, "ok")
            conn.commit()
            conn.close()

            recorded = record_feedback(
                model="iPhone 14 Pro",
                storage_gb=128,
                decision="buy",
                outcome="sold",
                source_key="dcfever",
                listing_id="a",
                valuation_date="2026-09-23",
                actual_purchase_cny=2000,
                actual_sale_cny=2500,
                fees_cny=50,
                repair_cost_cny=100,
                db_path=path,
            )
            self.assertEqual(recorded["status"], "ok")
            self.assertEqual(
                recorded["record"]["estimated_fair_cny"],
                2250.0,
            )
            self.assertEqual(
                recorded["record"]["suggested_purchase_cny"],
                1870.0,
            )

            listed = list_feedback(
                model="iPhone 14 Pro",
                storage_gb=128,
                db_path=path,
            )
            self.assertEqual(listed["count"], 1)

            metrics = feedback_metrics(
                model="iPhone 14 Pro",
                storage_gb=128,
                db_path=path,
            )
            self.assertEqual(metrics["evaluation"]["sold_with_valuation"], 1)
            self.assertEqual(
                metrics["evaluation"]["mean_absolute_error_cny"],
                250.0,
            )
            self.assertEqual(metrics["evaluation"]["mape_pct"], 10.0)
            self.assertEqual(metrics["profit"]["total_net_profit_cny"], 350.0)
            self.assertAlmostEqual(
                metrics["profit"]["median_roi_pct"],
                16.28,
                places=2,
            )

    def test_feedback_sold_requires_actual_costs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            with self.assertRaises(ValueError):
                record_feedback(
                    model="iPhone 14 Pro",
                    storage_gb=128,
                    decision="buy",
                    outcome="sold",
                    actual_sale_cny=2500,
                    db_path=path,
                )


if __name__ == "__main__":
    unittest.main()
