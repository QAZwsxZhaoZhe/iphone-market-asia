from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from iphone_market import db
from iphone_market.collection import CollectionOptions, collect, normalize_output
from iphone_market.collectors.base import (
    BaseCollector,
    CollectorOutput,
    RawListing,
    VariantCollection,
)
from iphone_market.config import ACTIVE_SOURCE_KEYS, PhoneVariant, SOURCE_BY_KEY
from iphone_market.fx import FxRates


class CollectionIsolationTests(unittest.TestCase):
    def test_default_collection_scope_is_hong_kong_only(self) -> None:
        options = CollectionOptions(run_date="2026-09-20")
        self.assertEqual(options.source_keys, ACTIVE_SOURCE_KEYS)
        self.assertEqual(options.source_keys, ("carousell_hk", "dcfever"))

    def test_repeated_timeouts_stop_after_two_queries(self) -> None:
        class TimeoutCollector(BaseCollector):
            def __init__(self) -> None:
                super().__init__(SOURCE_BY_KEY["mercari_jp"], limit=1)
                self.calls = 0

            def collect_variant(self, _page, _variant):
                self.calls += 1
                raise PlaywrightTimeoutError("Timeout 60000ms exceeded")

        class FakePage:
            def close(self) -> None:
                pass

        class FakeContext:
            def new_page(self):
                return FakePage()

        collector = TimeoutCollector()
        variants = tuple(
            PhoneVariant("iPhone 14 Pro", 14, "Pro", storage)
            for storage in (128, 256, 512, 1024)
        )
        output = collector.collect(FakeContext(), variants)

        self.assertEqual(collector.calls, 2)
        self.assertEqual(len(output.errors), 4)
        self.assertTrue(all("timeout" in error for error in output.errors))

    def test_one_source_failure_does_not_stop_other_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite3"
            rates = FxRates(
                rate_date="2026-09-20",
                cny_per_unit={"CNY": Decimal("1"), "JPY": Decimal("0.05")},
                stale=False,
                source="test",
            )

            class FakeCollector:
                def __init__(self, key: str) -> None:
                    self.key = key

                def collect(self, _context, variants):
                    if self.key == "yahoo_jp":
                        raise RuntimeError("source page changed")
                    return CollectorOutput(
                        source_key=self.key,
                        variants=[
                            VariantCollection(
                                variant=variants[0],
                                listings=[
                                    RawListing(
                                        variant=variants[0],
                                        listing_id="item-1",
                                        title="iPhone 14 Pro 128GB unused",
                                        url="https://example.test/item-1",
                                        price_native=Decimal("90000"),
                                        currency="JPY",
                                    )
                                ],
                            )
                        ],
                    )

            with patch("iphone_market.collection.fetch_or_cache_rates", return_value=rates), patch(
                "iphone_market.collection.create_collector",
                side_effect=lambda key, limit: FakeCollector(key),
            ), patch(
                "iphone_market.collection.persistent_browser",
            ) as browser:
                browser.return_value.__enter__.return_value = object()
                browser.return_value.__exit__.return_value = False
                summary = collect(
                    CollectionOptions(
                        run_date="2026-09-20",
                        source_keys=("mercari_jp", "yahoo_jp"),
                        limit=1,
                        db_path=path,
                    )
                )

            self.assertEqual(summary.status, "partial")
            self.assertEqual({result.source_key for result in summary.source_results}, {"mercari_jp", "yahoo_jp"})
            statuses = {result.source_key: result.status for result in summary.source_results}
            self.assertEqual(statuses["mercari_jp"], "ok")
            self.assertEqual(statuses["yahoo_jp"], "failed")

            conn = db.connect(path)
            rows = conn.execute("SELECT source_key FROM listings").fetchall()
            self.assertEqual([row["source_key"] for row in rows], ["mercari_jp"])
            conn.close()

    def test_normalization_excludes_accessories_and_limits_each_variant(self) -> None:
        variant = PhoneVariant("iPhone 14 Pro", 14, "Pro", 128)
        output = CollectorOutput(
            source_key="mercari_jp",
            variants=[
                VariantCollection(
                    variant=variant,
                    listings=[
                        RawListing(variant, "case-1", "iPhone 14 Pro 128GB case", "https://example.test/1", Decimal("10"), "JPY"),
                        RawListing(variant, "item-1", "iPhone 14 Pro 128GB used", "https://example.test/2", Decimal("80000"), "JPY"),
                        RawListing(variant, "item-1", "iPhone 14 Pro 128GB used duplicate", "https://example.test/3", Decimal("81000"), "JPY"),
                    ],
                )
            ],
        )
        records = normalize_output(output, SOURCE_BY_KEY["mercari_jp"], None, limit=30)
        self.assertEqual([record.listing_id for record in records], ["item-1"])
        self.assertIsNone(records[0].price_cny)

        all_records = normalize_output(
            output,
            SOURCE_BY_KEY["mercari_jp"],
            None,
            limit=30,
            include_rejected=True,
        )
        self.assertEqual(
            [(record.listing_id, record.condition) for record in all_records],
            [("case-1", "accessory"), ("item-1", "used")],
        )
        self.assertEqual(
            all_records[0].raw["quality"]["outcome"],
            "accessory",
        )


if __name__ == "__main__":
    unittest.main()
