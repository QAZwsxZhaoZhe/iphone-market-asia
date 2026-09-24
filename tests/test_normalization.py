from __future__ import annotations

import unittest
from decimal import Decimal

from iphone_market.config import PhoneVariant
from iphone_market.normalization import (
    classify_condition,
    classify_listing_quality,
    detect_listing_status,
    detect_model,
    detect_storage,
    is_valid_variant,
    listing_id_from_url,
    parse_api_price,
    parse_price,
)


class PriceParsingTests(unittest.TestCase):
    def test_common_currency_formats(self) -> None:
        self.assertEqual(parse_price("HK$6,000", "HKD"), Decimal("6000"))
        self.assertEqual(parse_price("S$ 1,234.50", "SGD"), Decimal("1234.50"))
        self.assertEqual(parse_price("¥111,111", "JPY"), Decimal("111111"))
        self.assertEqual(parse_price("1.2万", "JPY"), Decimal("12000"))
        self.assertEqual(parse_price("￥7,999", "CNY"), Decimal("7999"))

    def test_rejects_conflicting_currency(self) -> None:
        self.assertIsNone(parse_price("NT$35,000", "HKD"))
        self.assertIsNone(parse_price("US$999", "SGD"))

    def test_prefers_expected_currency_in_mixed_text(self) -> None:
        self.assertEqual(
            parse_price("NT$35,000 (S$1,200)", "SGD"),
            Decimal("1200"),
        )
        self.assertEqual(
            parse_price("US$999 / HK$5,800", "HKD"),
            Decimal("5800"),
        )

    def test_shopee_scaled_api_price(self) -> None:
        self.assertEqual(parse_api_price(123456789), Decimal("1234.57"))
        self.assertEqual(parse_api_price(129900), Decimal("129900"))


class IdentificationTests(unittest.TestCase):
    def test_storage_labels(self) -> None:
        self.assertEqual(detect_storage("iPhone 16 Pro 256GB"), 256)
        self.assertEqual(detect_storage("iPhone 15 Pro Max 1TB"), 1024)
        self.assertEqual(detect_storage("iPhone 17 Pro Max 2T"), 2048)
        self.assertIsNone(detect_storage("iPhone 16 Pro"))

    def test_model_aliases(self) -> None:
        self.assertEqual(detect_model("Apple iPhone 16 Pro Max 512G"), ("iPhone 16 Pro Max", 16, "Pro Max"))
        self.assertEqual(detect_model("苹果 15 Pro 256GB"), ("iPhone 15 Pro", 15, "Pro"))
        self.assertEqual(detect_model("16 PM 1TB"), ("iPhone 16 Pro Max", 16, "Pro Max"))

    def test_variant_match_requires_model_and_storage(self) -> None:
        variant = PhoneVariant("iPhone 16 Pro", 16, "Pro", 256)
        self.assertTrue(is_valid_variant("iPhone 16 Pro 256GB used", variant))
        self.assertFalse(is_valid_variant("iPhone 16 Pro 128GB used", variant))
        self.assertFalse(is_valid_variant("iPhone 16 Pro Max 256GB used", variant))


class ConditionAndIdTests(unittest.TestCase):
    def test_condition_exclusions(self) -> None:
        self.assertEqual(classify_condition("iPhone 16 Pro phone case"), "accessory")
        self.assertEqual(classify_condition("iPhone 16 Pro faulty for parts"), "broken")
        self.assertEqual(classify_condition("want to buy iPhone 16 Pro"), "wanted")
        self.assertEqual(classify_condition("iPhone 16 Pro rental"), "rental")
        self.assertEqual(classify_condition("iPhone 16 Pro brand new sealed"), "new")
        self.assertEqual(classify_condition("iPhone 16 Pro 256GB used"), "used")
        self.assertEqual(
            classify_condition("(Box only)Apple iPhone 14 Pro Max Space Black 256GB"),
            "box_only",
        )
        self.assertEqual(
            classify_condition("Apple iPhone 14 Pro Max Deep Purple 128GB BOX ONLY"),
            "box_only",
        )
        self.assertEqual(
            classify_condition("收iPhone 15 Pro Max 256GB"),
            "wanted",
        )
        self.assertEqual(
            classify_condition(
                "iPhone 14 Pro 256GB",
                price_native=Decimal("50"),
                currency="HKD",
            ),
            "suspicious_low",
        )
        self.assertEqual(
            classify_condition("iPhone 14 Pro 256GB 無壞 有盒"),
            "used",
        )

    def test_quality_classifier_explains_rejection(self) -> None:
        quality = classify_listing_quality(
            "BOX ONLY iPhone 14 Pro Max 256GB",
            price_native=Decimal("60"),
            currency="HKD",
        )
        self.assertEqual(quality.outcome, "box_only")
        self.assertGreaterEqual(quality.score, 0.9)
        self.assertTrue(any("盒" in reason for reason in quality.reasons))

    def test_listing_status(self) -> None:
        self.assertEqual(detect_listing_status("SOLD"), "sold")
        self.assertEqual(detect_listing_status("available now"), "active")

    def test_listing_ids_are_stable_for_query_urls(self) -> None:
        self.assertEqual(
            listing_id_from_url("dcfever", "https://www.dcfever.com/trading/view.php?id=11166861"),
            "11166861",
        )
        self.assertEqual(
            listing_id_from_url("goofish_sz", "https://www.goofish.com/item?id=123456789"),
            "123456789",
        )
        self.assertEqual(
            listing_id_from_url(
                "carousell_hk",
                "https://www.carousell.com.hk/p/iphone-14-pro-128gb-1463568810/"
                "?t-id=abc&t-tap_index=0",
            ),
            "1463568810",
        )


if __name__ == "__main__":
    unittest.main()
