from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import time
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from iphone_market.config import PHONE_VARIANTS
from iphone_market.platform import commerce, models, payments, repository
from iphone_market.platform.api.app import create_app
from iphone_market.platform.identity import create_user
from iphone_market.platform.settings import PlatformSettings


class OrderFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        tmp_path = Path(self.temp_dir.name)
        self.settings = PlatformSettings(
            database_url=(
                f"sqlite:///{(tmp_path / 'orders.sqlite3').as_posix()}"
            ),
            object_store_local_dir=str(tmp_path / "raw"),
            auto_create_schema=True,
            environment="test",
            auth_mode="api_key",
            api_key="test-key",
            payment_provider="mock",
            payment_webhook_secret="test-webhook-secret",
            payment_return_url="http://127.0.0.1:3000/account/orders",
        )
        self.client = self.enterContext(TestClient(create_app(self.settings)))
        session_factory = self.client.app.state.session_factory
        variant = PHONE_VARIANTS[0]
        with session_factory() as session:
            buyer = create_user(
                session,
                email="buyer@example.test",
                password="buyer-password",
                display_name="Buyer",
                roles=("buyer",),
            )
            second_buyer = create_user(
                session,
                email="buyer2@example.test",
                password="buyer2-password",
                display_name="Second Buyer",
                roles=("buyer",),
            )
            create_user(
                session,
                email="operator@example.test",
                password="operator-password",
                display_name="Operator",
                roles=("operator",),
            )
            merchant = commerce.create_merchant(
                session,
                legal_name="HK Certified Devices Limited",
                display_name="香港認證手機",
                merchant_type="business",
                commission_rate_bps=1000,
                status="active",
            )
            inventory = commerce.create_inventory_item(
                session,
                merchant_id=merchant.id,
                phone_variant_id=repository.variant_id(
                    variant.model,
                    variant.storage_gb,
                ),
                sku="ORDER-TEST-0001",
                condition_grade="A",
                battery_health_pct=91,
                cost_hkd=Decimal("4200"),
                status="available",
            )
            listing = commerce.create_seller_listing(
                session,
                merchant_id=merchant.id,
                inventory_item_id=inventory.id,
                title="iPhone 14 Pro 128GB 認證二手",
                description="測試訂單商品",
                price_hkd=Decimal("5299"),
                warranty_days=30,
                images=[],
            )
            listing = commerce.publish_seller_listing(session, listing.id)
            session.commit()
            self.buyer_id = buyer.id
            self.second_buyer_id = second_buyer.id
            self.merchant_id = merchant.id
            self.inventory_id = inventory.id
            self.listing_id = listing.id

        self.buyer_headers = self._login(
            "buyer@example.test",
            "buyer-password",
        )
        self.second_buyer_headers = self._login(
            "buyer2@example.test",
            "buyer2-password",
        )
        self.operator_headers = self._login(
            "operator@example.test",
            "operator-password",
        )

    def _login(self, email: str, password: str) -> dict[str, str]:
        response = self.client.post(
            "/v1/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def _order_payload(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "contact": {
                "recipient_name": "Chan Tai Man",
                "phone": "61234567",
                "email": "buyer@example.test",
            },
            "shipping_address": {
                "line1": "1 Example Road",
                "line2": "Flat A",
                "district": "油尖旺",
                "region": "九龍",
                "country": "HK",
            },
        }

    def _create_order(self, key: str = "order-key-0001") -> dict:
        response = self.client.post(
            "/v1/store/orders",
            headers={**self.buyer_headers, "Idempotency-Key": key},
            json=self._order_payload(),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _signed_webhook(
        self,
        payload: dict,
    ) -> tuple[bytes, dict[str, str]]:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(
            self.settings.payment_webhook_secret.encode("utf-8"),
            raw,
            hashlib.sha256,
        ).hexdigest()
        return raw, {
            "Content-Type": "application/json",
            "X-Payment-Signature": signature,
        }

    def test_order_idempotency_double_sell_ownership_and_cancellation(self) -> None:
        order = self._create_order()
        self.assertEqual(order["status"], "pending_payment")
        self.assertEqual(order["item_price_hkd"], 5299.0)
        self.assertEqual(order["commission_hkd"], 529.9)
        self.assertEqual(order["merchant_net_hkd"], 4769.1)

        repeated = self._create_order()
        self.assertEqual(repeated["id"], order["id"])
        self.assertEqual(repeated["order_number"], order["order_number"])

        double_sell = self.client.post(
            "/v1/store/orders",
            headers={
                **self.second_buyer_headers,
                "Idempotency-Key": "order-key-0002",
            },
            json=self._order_payload(),
        )
        self.assertEqual(double_sell.status_code, 409)

        other_buyer = self.client.get(
            f"/v1/orders/{order['id']}",
            headers=self.second_buyer_headers,
        )
        self.assertEqual(other_buyer.status_code, 404)

        cancelled = self.client.post(
            f"/v1/orders/{order['id']}/cancel",
            headers=self.buyer_headers,
            json={"reason": "changed_mind"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")

        session_factory = self.client.app.state.session_factory
        with session_factory() as session:
            inventory = session.get(models.InventoryItem, self.inventory_id)
            listing = session.get(models.SellerListing, self.listing_id)
            self.assertEqual(inventory.status, "available")
            self.assertEqual(listing.status, "active")
            self.assertEqual(
                session.query(models.Order)
                .filter(models.Order.buyer_user_id == self.buyer_id)
                .count(),
                1,
            )

        payment_intent = self.client.post(
            f"/v1/orders/{order['id']}/payment-intent",
            headers=self.buyer_headers,
        )
        self.assertEqual(payment_intent.status_code, 422)

    def test_payment_webhook_settlement_ledger_and_refund(self) -> None:
        order = self._create_order()
        intent_response = self.client.post(
            f"/v1/orders/{order['id']}/payment-intent",
            headers=self.buyer_headers,
        )
        self.assertEqual(intent_response.status_code, 200, intent_response.text)
        intent = intent_response.json()
        self.assertEqual(intent["provider"], "mock")
        self.assertIn("/v1/payments/mock/checkout/", intent["checkout_url"])

        invalid = self.client.post(
            "/v1/payments/mock/webhook",
            headers={
                "Content-Type": "application/json",
                "X-Payment-Signature": "invalid",
            },
            content=b"{}",
        )
        self.assertEqual(invalid.status_code, 401)

        webhook_payload = {
            "id": "evt-payment-1",
            "type": "payment.succeeded",
            "data": {
                "object": {
                    "id": intent["provider_reference"],
                    "order_id": order["id"],
                    "payment_intent_id": intent["id"],
                    "amount": order["total_hkd"],
                    "currency": "HKD",
                }
            },
        }
        raw, headers = self._signed_webhook(webhook_payload)
        first = self.client.post(
            "/v1/payments/mock/webhook",
            headers=headers,
            content=raw,
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["duplicate"])
        second = self.client.post(
            "/v1/payments/mock/webhook",
            headers=headers,
            content=raw,
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["duplicate"])

        paid = self.client.get(
            f"/v1/orders/{order['id']}",
            headers=self.buyer_headers,
        )
        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.json()["status"], "paid")

        processing = self.client.post(
            f"/internal/v1/orders/{order['id']}/fulfill",
            headers=self.operator_headers,
            json={"status": "processing", "note": "packing"},
        )
        self.assertEqual(processing.status_code, 200, processing.text)
        shipped = self.client.post(
            f"/internal/v1/orders/{order['id']}/fulfill",
            headers=self.operator_headers,
            json={"status": "shipped", "note": "SF Express"},
        )
        self.assertEqual(shipped.status_code, 200, shipped.text)

        completed = self.client.post(
            f"/v1/orders/{order['id']}/confirm-receipt",
            headers=self.buyer_headers,
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        completed_payload = completed.json()
        self.assertEqual(completed_payload["status"], "completed")
        self.assertEqual(completed_payload["settlement"]["status"], "pending")
        self.assertEqual(
            completed_payload["settlement"]["net_hkd"],
            4769.1,
        )

        ledger = self.client.get(
            "/internal/v1/ledger",
            headers=self.operator_headers,
        )
        self.assertEqual(ledger.status_code, 200, ledger.text)
        self.assertEqual(len(ledger.json()), 2)
        self._assert_balanced(ledger.json())

        refund = self.client.post(
            f"/internal/v1/orders/{order['id']}/refund",
            headers={
                **self.operator_headers,
                "Idempotency-Key": "refund-key-0001",
            },
            json={"reason": "item not as described"},
        )
        self.assertEqual(refund.status_code, 200, refund.text)
        self.assertEqual(refund.json()["status"], "succeeded")

        refund_again = self.client.post(
            f"/internal/v1/orders/{order['id']}/refund",
            headers={
                **self.operator_headers,
                "Idempotency-Key": "refund-key-0001",
            },
            json={"reason": "item not as described"},
        )
        self.assertEqual(refund_again.status_code, 200)
        self.assertEqual(refund_again.json()["id"], refund.json()["id"])

        refunded = self.client.get(
            f"/v1/orders/{order['id']}",
            headers=self.buyer_headers,
        )
        self.assertEqual(refunded.status_code, 200)
        self.assertEqual(refunded.json()["status"], "refunded")

        ledger_after_refund = self.client.get(
            "/internal/v1/ledger",
            headers=self.operator_headers,
        )
        self.assertEqual(len(ledger_after_refund.json()), 3)
        self._assert_balanced(ledger_after_refund.json())

        with self.client.app.state.session_factory() as session:
            self.assertEqual(session.query(models.PaymentEvent).count(), 1)
            self.assertEqual(session.query(models.Refund).count(), 1)
            inventory = session.get(models.InventoryItem, self.inventory_id)
            listing = session.get(models.SellerListing, self.listing_id)
            self.assertEqual(inventory.status, "reserved")
            self.assertEqual(listing.status, "reserved")

        restocked = self.client.post(
            f"/internal/v1/orders/{order['id']}/restock",
            headers=self.operator_headers,
        )
        self.assertEqual(restocked.status_code, 200, restocked.text)
        restocked_payload = restocked.json()
        self.assertEqual(restocked_payload["status"], "refunded")
        self.assertTrue(
            any(
                event["reason"] == "return_received_restocked"
                for event in restocked_payload["events"]
            )
        )

        restocked_again = self.client.post(
            f"/internal/v1/orders/{order['id']}/restock",
            headers=self.operator_headers,
        )
        self.assertEqual(restocked_again.status_code, 200, restocked_again.text)
        self.assertEqual(restocked_again.json()["id"], order["id"])

        with self.client.app.state.session_factory() as session:
            inventory = session.get(models.InventoryItem, self.inventory_id)
            listing = session.get(models.SellerListing, self.listing_id)
            self.assertEqual(inventory.status, "available")
            self.assertEqual(listing.status, "active")

    def _assert_balanced(self, journals: list[dict]) -> None:
        for journal in journals:
            debit = sum(entry["debit_hkd"] for entry in journal["entries"])
            credit = sum(entry["credit_hkd"] for entry in journal["entries"])
            self.assertAlmostEqual(debit, credit, places=2)

    def test_production_rejects_mock_payment_provider(self) -> None:
        with self.assertRaisesRegex(ValueError, "PAYMENT_PROVIDER"):
            PlatformSettings(
                environment="production",
                database_url=(
                    "postgresql+psycopg://iphone_market:password"
                    "@127.0.0.1:5432/iphone_market"
                ),
                auth_mode="api_key",
                api_key="a" * 40,
                payment_provider="mock",
                payment_webhook_secret="b" * 40,
                payment_return_url="https://example.test/account/orders",
            )

    def test_stripe_checkout_contract_uses_payment_intent_for_webhook_and_refund(
        self,
    ) -> None:
        order = self._create_order("stripe-order-key-0001")
        stripe_settings = replace(
            self.settings,
            payment_provider="stripe",
            payment_api_key="sk_test_contract",
            payment_webhook_secret="whsec_contract",
        )
        checkout_response = Mock()
        checkout_response.raise_for_status.return_value = None
        checkout_response.json.return_value = {
            "id": "cs_test_contract",
            "url": "https://checkout.stripe.test/session",
            "status": "open",
            "livemode": False,
        }

        with patch(
            "iphone_market.platform.payments.httpx.request",
            return_value=checkout_response,
        ):
            with self.client.app.state.session_factory() as session:
                intent = payments.create_payment_intent(
                    session,
                    stripe_settings,
                    buyer_user_id=self.buyer_id,
                    order_id=order["id"],
                )
                session.commit()
                self.assertEqual(
                    intent.provider_reference,
                    "cs_test_contract",
                )
                self.assertEqual(
                    intent.metadata_json["checkout_session_id"],
                    "cs_test_contract",
                )

        webhook_payload = {
            "id": "evt_stripe_contract",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_contract",
                    "client_reference_id": order["id"],
                    "payment_intent": "pi_test_contract",
                    "payment_status": "paid",
                }
            },
        }
        raw = json.dumps(
            webhook_payload,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = hmac.new(
            stripe_settings.payment_webhook_secret.encode("utf-8"),
            timestamp.encode("ascii") + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        with self.client.app.state.session_factory() as session:
            event, duplicate = payments.process_webhook(
                session,
                stripe_settings,
                provider_key="stripe",
                raw_body=raw,
                headers={
                    "Stripe-Signature": f"t={timestamp},v1={signature}",
                },
            )
            session.commit()
            self.assertFalse(duplicate)
            self.assertEqual(event.status, "processed")
            paid_order = session.get(models.Order, order["id"])
            self.assertEqual(paid_order.status, "paid")
            self.assertEqual(
                paid_order.payment_intent.provider_reference,
                "pi_test_contract",
            )

        refund_response = Mock()
        refund_response.raise_for_status.return_value = None
        refund_response.json.return_value = {
            "id": "re_test_contract",
            "status": "succeeded",
            "livemode": False,
        }
        with patch(
            "iphone_market.platform.payments.httpx.request",
            return_value=refund_response,
        ) as request_mock:
            with self.client.app.state.session_factory() as session:
                refund = payments.request_refund(
                    session,
                    stripe_settings,
                    order_id=order["id"],
                    idempotency_key="stripe-refund-key-0001",
                    reason="contract test",
                    actor="operator@example.test",
                )
                session.commit()
                self.assertEqual(refund.status, "succeeded")
                request_data = request_mock.call_args.kwargs["data"]
                self.assertIn(
                    ("payment_intent", "pi_test_contract"),
                    request_data,
                )


if __name__ == "__main__":
    unittest.main()
