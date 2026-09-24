from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from iphone_market.config import PHONE_VARIANTS
from iphone_market.platform import repository
from iphone_market.platform.api.app import create_app
from iphone_market.platform.identity import create_user
from iphone_market.platform.settings import PlatformSettings


class SellerFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        tmp_path = Path(self.temp_dir.name)
        self.settings = PlatformSettings(
            database_url=(
                f"sqlite:///{(tmp_path / 'seller.sqlite3').as_posix()}"
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
        with self.client.app.state.session_factory() as session:
            create_user(
                session,
                email="seller@example.test",
                password="seller-password",
                display_name="Seller",
                roles=("buyer",),
            )
            create_user(
                session,
                email="other-seller@example.test",
                password="other-seller-password",
                display_name="Other Seller",
                roles=("buyer",),
            )
            create_user(
                session,
                email="buyer@example.test",
                password="buyer-password",
                display_name="Buyer",
                roles=("buyer",),
            )
            create_user(
                session,
                email="operator@example.test",
                password="operator-password",
                display_name="Operator",
                roles=("operator",),
            )
            session.commit()

        self.seller_headers = self._login(
            "seller@example.test",
            "seller-password",
        )
        self.other_seller_headers = self._login(
            "other-seller@example.test",
            "other-seller-password",
        )
        self.buyer_headers = self._login(
            "buyer@example.test",
            "buyer-password",
        )
        self.operator_headers = self._login(
            "operator@example.test",
            "operator-password",
        )
        variant = PHONE_VARIANTS[0]
        self.variant_id = repository.variant_id(
            variant.model,
            variant.storage_gb,
        )

    def _login(self, email: str, password: str) -> dict[str, str]:
        response = self.client.post(
            "/v1/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def _apply(self, headers: dict[str, str], display_name: str) -> dict:
        response = self.client.post(
            "/v1/seller/apply",
            headers=headers,
            json={
                "legal_name": f"{display_name} Limited",
                "display_name": display_name,
                "merchant_type": "business",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _approve(self, merchant_id: str) -> dict:
        response = self.client.post(
            f"/internal/v1/merchants/{merchant_id}/status",
            headers=self.operator_headers,
            json={"status": "active"},
        )
        self.assertEqual(response.status_code, 200, response.text)
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

    def test_public_seller_onboarding_listing_order_and_ownership(self) -> None:
        profile = self.client.get(
            "/v1/seller/profile",
            headers=self.seller_headers,
        )
        self.assertEqual(profile.status_code, 200)
        self.assertIsNone(profile.json())

        merchant = self._apply(self.seller_headers, "Seller Store")
        self.assertEqual(merchant["status"], "pending")
        self.assertEqual(merchant["commission_rate_bps"], 1000)

        principal = self.client.get(
            "/v1/auth/me",
            headers=self.seller_headers,
        )
        self.assertEqual(principal.status_code, 200)
        self.assertIn("buyer", principal.json()["roles"])
        self.assertIn("merchant", principal.json()["roles"])

        pending_listing = self.client.post(
            "/v1/seller/listings/quick",
            headers=self.seller_headers,
            json={
                "phone_variant_id": self.variant_id,
                "condition_grade": "A",
                "price_hkd": 4999,
            },
        )
        self.assertEqual(pending_listing.status_code, 422)

        active_merchant = self._approve(merchant["id"])
        self.assertEqual(active_merchant["status"], "active")

        listing_response = self.client.post(
            "/v1/seller/listings/quick",
            headers=self.seller_headers,
            json={
                "merchant_id": "attempted-override",
                "phone_variant_id": self.variant_id,
                "condition_grade": "A",
                "price_hkd": 4999,
                "battery_health_pct": 91,
            },
        )
        self.assertEqual(listing_response.status_code, 201, listing_response.text)
        listing = listing_response.json()
        self.assertEqual(listing["status"], "active")
        self.assertEqual(listing["merchant"]["id"], merchant["id"])

        own_listings = self.client.get(
            "/v1/seller/listings",
            headers=self.seller_headers,
        )
        self.assertEqual(own_listings.status_code, 200)
        self.assertEqual([item["id"] for item in own_listings.json()], [listing["id"]])

        other_merchant = self._apply(
            self.other_seller_headers,
            "Other Seller Store",
        )
        self._approve(other_merchant["id"])
        other_listings = self.client.get(
            "/v1/seller/listings",
            headers=self.other_seller_headers,
        )
        self.assertEqual(other_listings.status_code, 200)
        self.assertEqual(other_listings.json(), [])

        order_response = self.client.post(
            "/v1/store/orders",
            headers={
                **self.buyer_headers,
                "Idempotency-Key": "seller-flow-order-1",
            },
            json={
                "listing_id": listing["id"],
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
            },
        )
        self.assertEqual(order_response.status_code, 201, order_response.text)
        order = order_response.json()

        intent_response = self.client.post(
            f"/v1/orders/{order['id']}/payment-intent",
            headers=self.buyer_headers,
        )
        self.assertEqual(intent_response.status_code, 200, intent_response.text)
        intent = intent_response.json()
        webhook_payload = {
            "id": "evt-seller-flow-1",
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
        raw, webhook_headers = self._signed_webhook(webhook_payload)
        webhook = self.client.post(
            "/v1/payments/mock/webhook",
            headers=webhook_headers,
            content=raw,
        )
        self.assertEqual(webhook.status_code, 200, webhook.text)

        seller_orders = self.client.get(
            "/v1/seller/orders",
            headers=self.seller_headers,
        )
        self.assertEqual(seller_orders.status_code, 200, seller_orders.text)
        self.assertEqual([item["id"] for item in seller_orders.json()], [order["id"]])
        self.assertEqual(
            seller_orders.json()[0]["contact"]["phone"],
            "61234567",
        )

        other_fulfillment = self.client.post(
            f"/v1/seller/orders/{order['id']}/fulfill",
            headers=self.other_seller_headers,
            json={"status": "processing", "note": "not mine"},
        )
        self.assertEqual(other_fulfillment.status_code, 422)

        processing = self.client.post(
            f"/v1/seller/orders/{order['id']}/fulfill",
            headers=self.seller_headers,
            json={"status": "processing", "note": "packing"},
        )
        self.assertEqual(processing.status_code, 200, processing.text)
        self.assertEqual(processing.json()["status"], "processing")

        shipped = self.client.post(
            f"/v1/seller/orders/{order['id']}/fulfill",
            headers=self.seller_headers,
            json={"status": "shipped", "note": "SF Express"},
        )
        self.assertEqual(shipped.status_code, 200, shipped.text)
        self.assertEqual(shipped.json()["status"], "shipped")

        internal_seller_access = self.client.get(
            "/v1/seller/profile",
            headers=self.operator_headers,
        )
        self.assertEqual(internal_seller_access.status_code, 403)

        suspended = self.client.post(
            f"/internal/v1/merchants/{merchant['id']}/status",
            headers=self.operator_headers,
            json={"status": "suspended"},
        )
        self.assertEqual(suspended.status_code, 200, suspended.text)
        self.assertEqual(suspended.json()["status"], "suspended")
        self.assertEqual(
            self.client.get("/v1/store/listings").json()["total"],
            0,
        )

        blocked_after_suspension = self.client.post(
            "/v1/seller/listings/quick",
            headers=self.seller_headers,
            json={
                "phone_variant_id": self.variant_id,
                "condition_grade": "B",
                "price_hkd": 4599,
            },
        )
        self.assertEqual(blocked_after_suspension.status_code, 422)


if __name__ == "__main__":
    unittest.main()
