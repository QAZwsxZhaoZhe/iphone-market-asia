from __future__ import annotations

import json
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

from iphone_market import db
from iphone_market.config import ACTIVE_SOURCE_KEYS
from iphone_market.dashboard import DashboardServer, dashboard_data
from iphone_market.models import CollectionResult, ListingRecord
from iphone_market.report import generate_report


def _listing(source_key: str, market: str, listing_id: str, date_value: str, price: str, status: str = "active") -> ListingRecord:
    return ListingRecord(
        source_key=source_key,
        source_name=source_key,
        market=market,
        listing_id=listing_id,
        title="iPhone 14 Pro 128GB used",
        url=f"https://example.test/{listing_id}",
        model="iPhone 14 Pro",
        generation=14,
        family="Pro",
        storage_gb=128,
        condition="used",
        listing_status=status,
        price_native=Decimal(price),
        currency="JPY",
        price_cny=Decimal(price),
        fx_date=date_value,
        location=market,
        raw={"fx_stale": False},
    )


class ReportAndDashboardTests(unittest.TestCase):
    def test_feedback_http_api_records_and_reports_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            server = DashboardServer(("127.0.0.1", 0), path)
            thread = threading.Thread(target=server.serve_forever)
            thread.daemon = True
            thread.start()
            try:
                port = server.server_address[1]
                request = Request(
                    f"http://127.0.0.1:{port}/api/ai/feedback",
                    data=json.dumps(
                        {
                            "model": "iPhone 17 Pro",
                            "storage": "256GB",
                            "market": "香港",
                            "decision": "buy",
                            "outcome": "sold",
                            "actual_purchase_cny": 5000,
                            "actual_sale_cny": 6000,
                            "fees_cny": 100,
                            "estimated_fair_cny": 6200,
                            "fair_low_cny": 5900,
                            "fair_high_cny": 6500,
                            "suggested_purchase_cny": 5400,
                            "confidence_level": "high",
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    created = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 201)
                self.assertEqual(created["record"]["outcome"], "sold")

                with urlopen(
                    f"http://127.0.0.1:{port}/api/ai/feedback/metrics",
                    timeout=5,
                ) as response:
                    metrics = json.loads(response.read().decode("utf-8"))
                self.assertEqual(metrics["record_count"], 1)
                self.assertEqual(
                    metrics["evaluation"]["sold_with_valuation"],
                    1,
                )
                self.assertEqual(
                    metrics["profit"]["total_net_profit_cny"],
                    900.0,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_failure_is_visible_in_report_and_dashboard_with_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            report_dir = Path(temp_dir) / "reports"
            db.init_db(path)
            conn = db.connect(path)
            run_id = db.start_run(conn, "2026-09-20")
            db.start_source_run(conn, run_id, "carousell_hk", "香港")
            db.finish_source_run(
                conn,
                run_id,
                CollectionResult("carousell_hk", "failed", 0, 1, "blocked: verification"),
            )
            db.start_source_run(conn, run_id, "dcfever", "香港")
            db.finish_source_run(conn, run_id, CollectionResult("dcfever", "ok", 1, 1))
            db.start_source_run(conn, run_id, "mercari_jp", "日本")
            db.finish_source_run(conn, run_id, CollectionResult("mercari_jp", "ok", 1, 1))
            db.insert_listings(
                conn,
                run_id,
                "2026-09-20",
                [
                    _listing("dcfever", "香港", "hk-1", "2026-09-20", "1000"),
                    _listing("mercari_jp", "日本", "jp-1", "2026-09-20", "2000"),
                ],
            )
            db.finish_run(conn, run_id, "partial")
            conn.commit()
            conn.close()

            report_path = generate_report("2026-09-20", db_path=path, report_dir=report_dir)
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("blocked: verification", report_text)
            self.assertIn("Carousell HK", report_text)
            self.assertIn("DCFever", report_text)
            self.assertNotIn("Mercari JP", report_text)

            payload = dashboard_data(path, selected_date="2026-09-20")
            self.assertEqual(payload["metrics"]["count"], 1)
            self.assertEqual(payload["pagination"]["total"], 1)
            self.assertEqual(
                tuple(item["source_key"] for item in payload["source_health"]),
                ACTIVE_SOURCE_KEYS,
            )
            carousell_health = next(
                item
                for item in payload["source_health"]
                if item["source_key"] == "carousell_hk"
            )
            self.assertEqual(carousell_health["status"], "failed")

            empty = dashboard_data(path, selected_date="2026-09-20", model="iPhone 17 Pro Max")
            self.assertEqual(empty["metrics"]["count"], 0)
            self.assertEqual(empty["pagination"]["total"], 0)

    def test_listing_status_filter_and_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)
            run_id = db.start_run(conn, "2026-09-20")
            db.start_source_run(conn, run_id, "dcfever", "香港")
            db.insert_listings(
                conn,
                run_id,
                "2026-09-20",
                [
                    _listing("dcfever", "香港", "a", "2026-09-20", "1000"),
                    _listing("dcfever", "香港", "b", "2026-09-20", "2000"),
                    _listing("dcfever", "香港", "c", "2026-09-20", "3000", "sold"),
                ],
            )
            db.finish_source_run(conn, run_id, CollectionResult("dcfever", "ok", 3, 1))
            db.finish_run(conn, run_id, "ok")
            conn.commit()
            conn.close()

            active = dashboard_data(path, selected_date="2026-09-20", limit=1)
            self.assertEqual(active["pagination"]["total"], 2)
            self.assertTrue(active["pagination"]["has_more"])
            sold = dashboard_data(path, selected_date="2026-09-20", listing_status="sold")
            self.assertEqual(sold["pagination"]["total"], 1)
            self.assertEqual(sold["listings"][0]["listing_status"], "sold")

    def test_group_median_change_uses_same_group_on_previous_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)

            previous_run = db.start_run(conn, "2026-09-19")
            db.start_source_run(conn, previous_run, "carousell_hk", "香港")
            db.insert_listings(
                conn,
                previous_run,
                "2026-09-19",
                [
                    _listing("carousell_hk", "香港", "old-a", "2026-09-19", "1000"),
                    _listing("carousell_hk", "香港", "old-b", "2026-09-19", "2000"),
                    _listing("carousell_hk", "香港", "old-c", "2026-09-19", "3000"),
                ],
            )
            db.finish_source_run(conn, previous_run, CollectionResult("carousell_hk", "ok", 3, 1))
            db.finish_run(conn, previous_run, "ok")

            current_run = db.start_run(conn, "2026-09-20")
            db.start_source_run(conn, current_run, "carousell_hk", "香港")
            db.insert_listings(
                conn,
                current_run,
                "2026-09-20",
                [
                    _listing("carousell_hk", "香港", "new-a", "2026-09-20", "1200"),
                    _listing("carousell_hk", "香港", "new-b", "2026-09-20", "2200"),
                    _listing("carousell_hk", "香港", "new-c", "2026-09-20", "3200"),
                ],
            )
            db.finish_source_run(conn, current_run, CollectionResult("carousell_hk", "ok", 3, 1))
            db.finish_run(conn, current_run, "ok")
            conn.commit()
            conn.close()

            payload = dashboard_data(path, selected_date="2026-09-20")
            group = payload["groups"][0]
            self.assertEqual(group["median"], 2200)
            self.assertEqual(group["median_change"], 200)

            first_day = dashboard_data(path, selected_date="2026-09-19")
            self.assertIsNone(first_day["groups"][0]["median_change"])


if __name__ == "__main__":
    unittest.main()
