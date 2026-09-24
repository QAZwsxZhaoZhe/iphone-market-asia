from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from iphone_market import db
from iphone_market.models import CollectionResult, ListingRecord


def _record(listing_id: str, title: str, date_value: str, price: str) -> ListingRecord:
    return ListingRecord(
        source_key="mercari_jp",
        source_name="Mercari JP",
        market="日本",
        listing_id=listing_id,
        title=title,
        url=f"https://example.test/{listing_id}",
        model="iPhone 14 Pro",
        generation=14,
        family="Pro",
        storage_gb=128,
        condition="used",
        listing_status="active",
        price_native=Decimal(price),
        currency="JPY",
        price_cny=Decimal("1000"),
        fx_date=date_value,
        location="日本",
        raw={"date": date_value},
    )


class DatabaseTests(unittest.TestCase):
    def test_interrupted_runs_are_closed_before_next_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)
            run_id = db.start_run(conn, "2026-09-20")
            db.start_source_run(conn, run_id, "mercari_jp", "日本")
            conn.commit()

            self.assertEqual(db.recover_interrupted_runs(conn), 1)
            conn.commit()

            run = db.latest_run(conn)
            source = db.source_results(conn, run_id)[0]
            self.assertEqual(run["status"], "failed")
            self.assertIsNotNone(run["finished_at"])
            self.assertEqual(source["status"], "failed")
            self.assertIn("interrupted", source["error"])
            conn.close()

    def test_history_is_preserved_across_daily_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)
            run_one = db.start_run(conn, "2026-09-19")
            db.insert_listings(conn, run_one, "2026-09-19", [_record("item-1", "iPhone 14 Pro 128GB", "2026-09-19", "90000")])
            run_two = db.start_run(conn, "2026-09-20")
            db.insert_listings(conn, run_two, "2026-09-20", [_record("item-1", "iPhone 14 Pro 128GB", "2026-09-20", "85000")])
            conn.commit()

            rows = conn.execute(
                "SELECT collected_date, price_native FROM listings WHERE listing_id='item-1' ORDER BY collected_date"
            ).fetchall()
            self.assertEqual([row["collected_date"] for row in rows], ["2026-09-19", "2026-09-20"])
            self.assertEqual([row["price_native"] for row in rows], [90000.0, 85000.0])
            conn.close()

    def test_same_day_rerun_uses_latest_source_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)
            first_run = db.start_run(conn, "2026-09-20")
            db.start_source_run(conn, first_run, "mercari_jp", "日本")
            db.insert_listings(
                conn,
                first_run,
                "2026-09-20",
                [_record("item-1", "iPhone 14 Pro 128GB", "2026-09-20", "90000")],
            )
            db.finish_source_run(conn, first_run, CollectionResult("mercari_jp", "ok", 1, 1))
            db.finish_run(conn, first_run, "ok")

            second_run = db.start_run(conn, "2026-09-20")
            db.start_source_run(conn, second_run, "mercari_jp", "日本")
            db.insert_listings(
                conn,
                second_run,
                "2026-09-20",
                [_record("item-1", "iPhone 14 Pro 128GB", "2026-09-20", "85000")],
            )
            db.finish_source_run(conn, second_run, CollectionResult("mercari_jp", "ok", 1, 1))
            db.finish_run(conn, second_run, "ok")
            conn.commit()

            rows = db.listing_rows(conn, "2026-09-20")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["price_native"], 85000.0)
            conn.close()

    def test_source_failure_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)
            run_id = db.start_run(conn, "2026-09-20")
            db.start_source_run(conn, run_id, "dcfever", "香港")
            db.finish_source_run(
                conn,
                run_id,
                CollectionResult("dcfever", "failed", 0, 1, "blocked: verification"),
            )
            db.finish_run(conn, run_id, "failed")
            conn.commit()
            row = db.source_results(conn, run_id)[0]
            self.assertEqual(row["status"], "failed")
            self.assertIn("verification", row["error"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
