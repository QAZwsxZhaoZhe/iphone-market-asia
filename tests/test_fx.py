from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from iphone_market import db
from iphone_market.fx import rates_from_api_payload


class FxTests(unittest.TestCase):
    def test_normalizes_inverse_rates_and_date(self) -> None:
        rates = rates_from_api_payload(
            {
                "base_code": "CNY",
                "time_last_update_utc": "Sun, 20 Sep 2026 00:02:31 +0000",
                "rates": {"SGD": "0.20", "HKD": "1.10", "JPY": "20"},
            },
            "2026-09-20",
        )
        self.assertEqual(rates.rate_date, "2026-09-20")
        self.assertFalse(rates.stale)
        self.assertEqual(rates.to_cny(Decimal("10"), "SGD"), Decimal("50.00"))
        self.assertEqual(rates.to_cny(Decimal("10"), "HKD").quantize(Decimal("0.01")), Decimal("9.09"))
        self.assertEqual(rates.to_cny(Decimal("100"), "JPY"), Decimal("5.00"))

    def test_rejects_wrong_base_currency(self) -> None:
        with self.assertRaises(ValueError):
            rates_from_api_payload(
                {"base_code": "USD", "rates": {"SGD": 1, "HKD": 1, "JPY": 1}},
                "2026-09-20",
            )

    def test_cached_rates_are_marked_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            db.init_db(path)
            conn = db.connect(path)
            conn.execute(
                """
                INSERT INTO fx_rates(rate_date, rates_json, source, updated_at)
                VALUES ('2026-09-19', '{"CNY": "1", "SGD": "4.8"}', 'test', 'now')
                """
            )
            conn.commit()
            cached = __import__("iphone_market.fx", fromlist=["load_cached_rates"]).load_cached_rates(conn)
            conn.close()
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertTrue(cached.stale)
        self.assertEqual(cached.to_cny(Decimal("10"), "SGD"), Decimal("48.00"))


if __name__ == "__main__":
    unittest.main()
