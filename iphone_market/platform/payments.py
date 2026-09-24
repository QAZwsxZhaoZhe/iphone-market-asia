from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import models
from .identity import roles_for_user
from .settings import PlatformSettings


ORDER_STATUSES = {
    "pending_payment",
    "paid",
    "processing",
    "shipped",
    "completed",
    "cancelled",
    "refund_pending",
    "refunded",
}
REFUNDABLE_STATUSES = {"paid", "processing", "shipped", "completed"}
FULFILLMENT_STATUSES = {"processing", "shipped"}
MONEY = Decimal("0.01")


class OrderError(ValueError):
    pass


class PaymentVerificationError(OrderError):
    pass


class PaymentProviderError(OrderError):
    pass


@dataclass(frozen=True)
class ProviderIntent:
    reference: str
    status: str
    checkout_url: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ProviderRefund:
    reference: str
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class WebhookEvent:
    provider_event_id: str
    event_type: str
    order_id: str | None
    payment_intent_id: str | None
    provider_reference: str | None
    refund_reference: str | None
    status: str
    payload: dict[str, Any]


class PaymentProvider(Protocol):
    key: str

    def create_intent(self, order: models.Order) -> ProviderIntent:
        ...

    def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookEvent:
        ...

    def create_refund(
        self,
        refund: models.Refund,
        payment_intent: models.PaymentIntent,
    ) -> ProviderRefund:
        ...


class MockPaymentProvider:
    key = "mock"

    def __init__(self, settings: PlatformSettings) -> None:
        self.settings = settings

    def create_intent(self, order: models.Order) -> ProviderIntent:
        reference = f"mockpi_{uuid.uuid4().hex}"
        signature = mock_checkout_signature(reference, self.settings)
        checkout_url = (
            f"{self.settings.public_base_url.rstrip('/')}"
            f"/v1/payments/mock/checkout/{reference}"
            f"?signature={signature}"
        )
        return ProviderIntent(
            reference=reference,
            status="requires_payment",
            checkout_url=checkout_url,
            metadata={"mode": "development"},
        )

    def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookEvent:
        signature = _header(headers, "x-payment-signature")
        expected = hmac.new(
            self.settings.payment_webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not signature or not secrets.compare_digest(signature, expected):
            raise PaymentVerificationError("支付回调签名无效")
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaymentVerificationError("支付回调格式无效") from exc
        return _normalize_webhook_event(self.key, payload)

    def create_refund(
        self,
        refund: models.Refund,
        payment_intent: models.PaymentIntent,
    ) -> ProviderRefund:
        del payment_intent
        return ProviderRefund(
            reference=f"mockrf_{uuid.uuid4().hex}",
            status="succeeded",
            metadata={"mode": "development", "refund_id": refund.id},
        )


class StripePaymentProvider:
    """Stripe Checkout adapter.

    This adapter is intentionally thin: Stripe remains the merchant of record
    for card collection and merchant payouts, while this platform owns order
    state, callback deduplication, refunds and the internal ledger.
    """

    key = "stripe"

    def __init__(self, settings: PlatformSettings) -> None:
        self.settings = settings
        if not settings.payment_api_key:
            raise PaymentProviderError("PAYMENT_API_KEY 未配置")
        if not settings.payment_webhook_secret:
            raise PaymentProviderError("PAYMENT_WEBHOOK_SECRET 未配置")

    def create_intent(self, order: models.Order) -> ProviderIntent:
        amount = _money(order.total_hkd)
        return_url = _append_query(
            self.settings.payment_return_url,
            {"order": order.id, "status": "paid"},
        )
        cancel_url = _append_query(
            self.settings.payment_return_url,
            {"order": order.id, "status": "cancelled"},
        )
        payload = [
            ("mode", "payment"),
            ("client_reference_id", order.id),
            ("success_url", return_url),
            ("cancel_url", cancel_url),
            ("line_items[0][quantity]", "1"),
            ("line_items[0][price_data][currency]", "hkd"),
            (
                "line_items[0][price_data][unit_amount]",
                str(_to_minor_units(amount)),
            ),
            (
                "line_items[0][price_data][product_data][name]",
                f"Order {order.order_number}",
            ),
            ("metadata[order_id]", order.id),
            ("metadata[order_number]", order.order_number),
            ("payment_intent_data[metadata][order_id]", order.id),
            (
                "payment_intent_data[metadata][order_number]",
                order.order_number,
            ),
        ]
        response = self._request(
            "POST",
            "/v1/checkout/sessions",
            data=payload,
            idempotency_key=f"payment:{order.id}",
        )
        checkout_session_id = str(response.get("id") or "")
        reference = (
            _provider_object_id(response.get("payment_intent"))
            or checkout_session_id
        )
        checkout_url = response.get("url")
        if not reference or not checkout_url:
            raise PaymentProviderError("支付服務未返回有效結帳連結")
        return ProviderIntent(
            reference=reference,
            status=str(response.get("status") or "requires_payment"),
            checkout_url=str(checkout_url),
            metadata={
                "livemode": bool(response.get("livemode")),
                "checkout_session_id": checkout_session_id,
            },
        )

    def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookEvent:
        signature = _header(headers, "stripe-signature")
        if not signature:
            raise PaymentVerificationError("缺少 Stripe-Signature")
        values = {}
        for item in signature.split(","):
            key, _, value = item.partition("=")
            values.setdefault(key.strip(), []).append(value.strip())
        timestamp = values.get("t", [""])[0]
        signatures = values.get("v1", [])
        if not timestamp or not signatures:
            raise PaymentVerificationError("Stripe 签名格式无效")
        try:
            signed_at = int(timestamp)
        except ValueError as exc:
            raise PaymentVerificationError("Stripe 签名时间无效") from exc
        if abs(int(time.time()) - signed_at) > 300:
            raise PaymentVerificationError("Stripe 回调已过期")
        expected = hmac.new(
            self.settings.payment_webhook_secret.encode("utf-8"),
            timestamp.encode("ascii") + b"." + raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not any(
            secrets.compare_digest(candidate, expected)
            for candidate in signatures
        ):
            raise PaymentVerificationError("Stripe 回调签名无效")
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaymentVerificationError("Stripe 回调格式无效") from exc
        return _normalize_webhook_event(self.key, payload)

    def create_refund(
        self,
        refund: models.Refund,
        payment_intent: models.PaymentIntent,
    ) -> ProviderRefund:
        response = self._request(
            "POST",
            "/v1/refunds",
            data=[
                ("payment_intent", payment_intent.provider_reference),
                ("amount", str(_to_minor_units(_money(refund.amount_hkd)))),
                ("metadata[order_id]", refund.order_id),
                ("metadata[refund_id]", refund.id),
            ],
            idempotency_key=f"refund:{refund.id}",
        )
        reference = str(response.get("id") or "")
        if not reference:
            raise PaymentProviderError("支付服務未返回退款編號")
        return ProviderRefund(
            reference=reference,
            status=str(response.get("status") or "pending"),
            metadata={"livemode": bool(response.get("livemode"))},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: list[tuple[str, str]],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.settings.payment_api_base_url}{path}",
                data=data,
                headers={
                    "Authorization": f"Bearer {self.settings.payment_api_key}",
                    "Idempotency-Key": idempotency_key,
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PaymentProviderError(
                f"支付服務請求失敗：{type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict):
            raise PaymentProviderError("支付服務回應格式無效")
        return payload


def get_payment_provider(settings: PlatformSettings) -> PaymentProvider:
    provider = settings.payment_provider.strip().lower()
    if provider == "mock":
        return MockPaymentProvider(settings)
    if provider == "stripe":
        return StripePaymentProvider(settings)
    raise PaymentProviderError(f"不支持的支付服務：{provider}")


def place_order(
    session: Session,
    *,
    buyer_user_id: str,
    listing_id: str,
    idempotency_key: str,
    contact: dict[str, Any],
    shipping_address: dict[str, Any],
) -> models.Order:
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 120:
        raise OrderError("Idempotency-Key 長度必須介於 8 和 120")
    buyer = session.get(models.User, buyer_user_id)
    if buyer is None or buyer.status != "active":
        raise OrderError("買家帳戶不存在或已停用")

    existing = session.scalar(
        select(models.Order)
        .options(*_order_load_options(), joinedload(models.Order.events))
        .where(
            models.Order.buyer_user_id == buyer_user_id,
            models.Order.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing

    listing = session.scalar(
        select(models.SellerListing)
        .where(
            (models.SellerListing.id == listing_id)
            | (models.SellerListing.slug == listing_id)
        )
        .with_for_update()
    )
    if listing is None or listing.status != "active":
        raise OrderError("商品目前不可購買")
    item = session.scalar(
        select(models.InventoryItem)
        .where(models.InventoryItem.id == listing.inventory_item_id)
        .with_for_update()
    )
    merchant = session.get(models.Merchant, listing.merchant_id)
    if item is None or merchant is None:
        raise OrderError("商品資料不完整")
    if merchant.status != "active":
        raise OrderError("商家目前無法交易")
    if item.status != "available" or listing.status != "active":
        raise OrderError("商品已被其他買家保留")

    item_price = _money(listing.price_hkd)
    commission_rate = int(merchant.commission_rate_bps)
    commission = _money(item_price * Decimal(commission_rate) / Decimal(10000))
    shipping_fee = _money(0)
    total = _money(item_price + shipping_fee)
    merchant_net = _money(total - commission)
    if merchant_net < 0:
        raise OrderError("佣金設定導致商家結算金額小於零")

    order = models.Order(
        id=str(uuid.uuid4()),
        order_number=_order_number(),
        buyer_user_id=buyer.id,
        merchant_id=merchant.id,
        seller_listing_id=listing.id,
        inventory_item_id=item.id,
        status="pending_payment",
        payment_status="pending",
        fulfillment_status="unfulfilled",
        currency="HKD",
        item_price_hkd=item_price,
        shipping_fee_hkd=shipping_fee,
        total_hkd=total,
        commission_rate_bps=commission_rate,
        commission_hkd=commission,
        merchant_net_hkd=merchant_net,
        idempotency_key=key,
        contact_json=_clean_contact(contact),
        shipping_address_json=_clean_address(shipping_address),
    )
    item.status = "reserved"
    listing.status = "reserved"
    session.add(order)
    session.flush()
    _record_order_event(
        session,
        order,
        from_status=None,
        to_status="pending_payment",
        actor=f"buyer:{buyer.id}",
        reason="buyer_placed_order",
    )
    session.flush()
    return order


def get_buyer_order(
    session: Session,
    *,
    buyer_user_id: str,
    order_id: str,
) -> models.Order | None:
    return session.scalar(
        _order_query().where(
            models.Order.id == order_id,
            models.Order.buyer_user_id == buyer_user_id,
        )
    )


def list_buyer_orders(
    session: Session,
    *,
    buyer_user_id: str,
    limit: int = 100,
) -> list[models.Order]:
    return list(
        session.scalars(
            _order_query()
            .where(models.Order.buyer_user_id == buyer_user_id)
            .order_by(models.Order.created_at.desc())
            .limit(max(1, min(limit, 200)))
        ).unique()
    )


def list_internal_orders(
    session: Session,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[models.Order]:
    stmt = _order_query().order_by(models.Order.created_at.desc())
    if status:
        stmt = stmt.where(models.Order.status == status)
    return list(session.scalars(stmt.limit(max(1, min(limit, 500)))).unique())


def cancel_order(
    session: Session,
    *,
    buyer_user_id: str,
    order_id: str,
    reason: str,
) -> models.Order:
    order = get_buyer_order(
        session,
        buyer_user_id=buyer_user_id,
        order_id=order_id,
    )
    if order is None:
        raise OrderError("訂單不存在")
    if order.status == "cancelled":
        return order
    if order.status != "pending_payment":
        raise OrderError("只有待付款訂單可以取消")
    _release_order_reservation(session, order)
    previous = order.status
    order.status = "cancelled"
    order.payment_status = "cancelled"
    order.cancelled_at = _utc_now()
    order.cancellation_reason = reason.strip()[:1000] or "buyer_cancelled"
    if order.payment_intent is not None:
        order.payment_intent.status = "cancelled"
    _record_order_event(
        session,
        order,
        from_status=previous,
        to_status="cancelled",
        actor=f"buyer:{buyer_user_id}",
        reason=order.cancellation_reason,
    )
    session.flush()
    return order


def create_payment_intent(
    session: Session,
    settings: PlatformSettings,
    *,
    buyer_user_id: str,
    order_id: str,
) -> models.PaymentIntent:
    order = session.scalar(
        select(models.Order)
        .options(joinedload(models.Order.payment_intent))
        .where(
            models.Order.id == order_id,
            models.Order.buyer_user_id == buyer_user_id,
        )
        .with_for_update()
    )
    if order is None:
        raise OrderError("訂單不存在")
    if order.payment_intent is not None:
        if order.status == "cancelled":
            raise OrderError("已取消訂單不能付款")
        return order.payment_intent
    if order.status != "pending_payment" or order.payment_status != "pending":
        raise OrderError("訂單目前不能建立付款")

    provider = get_payment_provider(settings)
    result = provider.create_intent(order)
    intent = models.PaymentIntent(
        id=str(uuid.uuid4()),
        order_id=order.id,
        provider=provider.key,
        provider_reference=result.reference,
        status=result.status,
        amount_hkd=_money(order.total_hkd),
        currency="HKD",
        checkout_url=result.checkout_url,
        idempotency_key=f"payment:{order.id}",
        metadata_json=result.metadata,
    )
    session.add(intent)
    _record_order_event(
        session,
        order,
        from_status=order.status,
        to_status=order.status,
        actor=f"buyer:{buyer_user_id}",
        reason="payment_intent_created",
    )
    session.flush()
    order.payment_intent = intent
    return intent


def process_webhook(
    session: Session,
    settings: PlatformSettings,
    *,
    provider_key: str,
    raw_body: bytes,
    headers: Mapping[str, str],
) -> tuple[models.PaymentEvent, bool]:
    if provider_key != settings.payment_provider:
        raise PaymentVerificationError("支付回調來源與目前支付服務不符")
    provider = get_payment_provider(settings)
    event = provider.verify_webhook(raw_body, headers)
    existing = session.scalar(
        select(models.PaymentEvent).where(
            models.PaymentEvent.provider == provider_key,
            models.PaymentEvent.provider_event_id == event.provider_event_id,
        )
    )
    if existing is not None and existing.status == "processed":
        return existing, True

    resolved_order, resolved_intent, resolved_refund = _resolve_event_resources(
        session,
        provider_key,
        event,
    )
    payment_event = existing or models.PaymentEvent(
        provider=provider_key,
        provider_event_id=event.provider_event_id,
        event_type=event.event_type,
        payload=event.payload,
    )
    payment_event.order_id = resolved_order.id if resolved_order else None
    payment_event.payment_intent_id = resolved_intent.id if resolved_intent else None
    payment_event.status = "processing"
    payment_event.error = None
    if existing is None:
        session.add(payment_event)
        session.flush()

    try:
        _apply_webhook_event(
            session,
            event=event,
            order=resolved_order,
            intent=resolved_intent,
            refund=resolved_refund,
        )
        payment_event.status = "processed"
        payment_event.processed_at = _utc_now()
    except Exception as exc:
        payment_event.status = "failed"
        payment_event.error = str(exc)[:2000]
        raise
    session.flush()
    return payment_event, existing is not None


def fulfill_order(
    session: Session,
    *,
    order_id: str,
    target_status: str,
    actor: str,
    note: str = "",
) -> models.Order:
    if target_status not in FULFILLMENT_STATUSES:
        raise OrderError("履約狀態必須是 processing 或 shipped")
    order = session.scalar(
        select(models.Order)
        .where(models.Order.id == order_id)
        .with_for_update()
    )
    if order is None:
        raise OrderError("訂單不存在")
    allowed = (
        {"paid", "processing"}
        if target_status == "shipped"
        else {"paid"}
    )
    if order.status not in allowed:
        raise OrderError("目前訂單狀態不能執行此履約操作")
    previous = order.status
    order.status = target_status
    order.fulfillment_status = target_status
    if target_status == "shipped":
        order.fulfilled_at = _utc_now()
    _record_order_event(
        session,
        order,
        from_status=previous,
        to_status=target_status,
        actor=actor,
        reason=note.strip()[:1000] or "merchant_fulfilled",
    )
    session.flush()
    return order


def restock_refunded_order(
    session: Session,
    *,
    order_id: str,
    actor: str,
) -> models.Order:
    order = session.scalar(
        select(models.Order)
        .where(models.Order.id == order_id)
        .with_for_update()
    )
    if order is None:
        raise OrderError("訂單不存在")
    if order.status != "refunded":
        raise OrderError("只有已退款訂單可以將庫存歸位")
    already_restocked = session.scalar(
        select(models.OrderEvent.id).where(
            models.OrderEvent.order_id == order.id,
            models.OrderEvent.reason == "return_received_restocked",
        )
    )
    if already_restocked is not None:
        return order

    listing = session.scalar(
        select(models.SellerListing)
        .where(models.SellerListing.id == order.seller_listing_id)
        .with_for_update()
    )
    item = session.scalar(
        select(models.InventoryItem)
        .where(models.InventoryItem.id == order.inventory_item_id)
        .with_for_update()
    )
    if (
        listing is None
        or item is None
        or listing.status != "reserved"
        or item.status != "reserved"
    ):
        raise OrderError("此訂單目前沒有可歸位的庫存預留")

    listing.status = "active"
    item.status = "available"
    _record_order_event(
        session,
        order,
        from_status="refunded",
        to_status="refunded",
        actor=actor,
        reason="return_received_restocked",
    )
    session.flush()
    return order


def confirm_receipt(
    session: Session,
    *,
    buyer_user_id: str,
    order_id: str,
) -> models.Order:
    order = session.scalar(
        select(models.Order)
        .options(joinedload(models.Order.settlement))
        .where(
            models.Order.id == order_id,
            models.Order.buyer_user_id == buyer_user_id,
        )
        .with_for_update()
    )
    if order is None:
        raise OrderError("訂單不存在")
    if order.status == "completed":
        return order
    if order.status != "shipped":
        raise OrderError("商品尚未標記為已發貨")
    previous = order.status
    order.status = "completed"
    order.completed_at = _utc_now()
    if order.settlement is None:
        order.settlement = models.MerchantSettlement(
            id=str(uuid.uuid4()),
            merchant_id=order.merchant_id,
            order_id=order.id,
            status="pending",
            gross_hkd=_money(order.total_hkd),
            commission_hkd=_money(order.commission_hkd),
            net_hkd=_money(order.merchant_net_hkd),
        )
        _record_settlement_journal(session, order)
    _record_order_event(
        session,
        order,
        from_status=previous,
        to_status="completed",
        actor=f"buyer:{buyer_user_id}",
        reason="buyer_confirmed_receipt",
    )
    session.flush()
    return order


def request_refund(
    session: Session,
    settings: PlatformSettings,
    *,
    order_id: str,
    idempotency_key: str,
    reason: str,
    actor: str,
) -> models.Refund:
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 120:
        raise OrderError("Idempotency-Key 長度必須介於 8 和 120")
    order = session.scalar(
        select(models.Order)
        .options(
            joinedload(models.Order.payment_intent),
            joinedload(models.Order.settlement),
        )
        .where(models.Order.id == order_id)
        .with_for_update()
    )
    if order is None:
        raise OrderError("訂單不存在")
    existing = session.scalar(
        select(models.Refund).where(
            models.Refund.order_id == order.id,
            models.Refund.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing
    if order.status in {"refunded", "refund_pending"}:
        raise OrderError("訂單已進入退款流程")
    if order.status not in REFUNDABLE_STATUSES:
        raise OrderError("目前訂單狀態不能退款")
    intent = order.payment_intent
    if intent is None or intent.status not in {"succeeded", "paid", "complete"}:
        raise OrderError("訂單尚無可退款的支付")

    previous = order.status
    refund = models.Refund(
        id=str(uuid.uuid4()),
        order_id=order.id,
        payment_intent_id=intent.id,
        provider=settings.payment_provider,
        status="requested",
        amount_hkd=_money(order.total_hkd),
        currency="HKD",
        reason=reason.strip()[:2000] or "operator_refund",
        idempotency_key=key,
        metadata_json={"previous_order_status": previous},
    )
    session.add(refund)
    order.status = "refund_pending"
    _record_order_event(
        session,
        order,
        from_status=previous,
        to_status="refund_pending",
        actor=actor,
        reason=refund.reason,
    )
    session.flush()
    try:
        result = get_payment_provider(settings).create_refund(refund, intent)
    except PaymentProviderError:
        order.status = previous
        order.fulfillment_status = _fulfillment_for_status(previous)
        refund.status = "failed"
        refund.processed_at = _utc_now()
        raise
    refund.provider_reference = result.reference
    refund.metadata_json = {**refund.metadata_json, **result.metadata}
    refund.status = _normalized_refund_status(result.status)
    if refund.status == "succeeded":
        _finalize_refund(session, order, refund)
    session.flush()
    return refund


def list_ledger_journals(
    session: Session,
    *,
    order_id: str | None = None,
    limit: int = 100,
) -> list[models.LedgerJournal]:
    stmt = (
        select(models.LedgerJournal)
        .options(
            joinedload(models.LedgerJournal.entries).joinedload(
                models.LedgerEntry.account
            )
        )
        .order_by(models.LedgerJournal.created_at.desc())
    )
    if order_id:
        stmt = stmt.where(models.LedgerJournal.order_id == order_id)
    return list(session.scalars(stmt.limit(max(1, min(limit, 500)))).unique())


def order_payload(
    order: models.Order,
    *,
    include_buyer: bool = False,
    include_events: bool = True,
) -> dict[str, Any]:
    listing = order.seller_listing
    item = order.inventory_item
    variant = item.variant if item is not None else None
    payload: dict[str, Any] = {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "fulfillment_status": order.fulfillment_status,
        "currency": order.currency,
        "item_price_hkd": _float(order.item_price_hkd),
        "shipping_fee_hkd": _float(order.shipping_fee_hkd),
        "total_hkd": _float(order.total_hkd),
        "commission_rate_bps": order.commission_rate_bps,
        "commission_hkd": _float(order.commission_hkd),
        "merchant_net_hkd": _float(order.merchant_net_hkd),
        "contact": order.contact_json,
        "shipping_address": order.shipping_address_json,
        "merchant": {
            "id": order.merchant_id,
            "display_name": order.merchant.display_name,
        },
        "item": {
            "listing_id": listing.id,
            "slug": listing.slug,
            "title": listing.title,
            "image": listing.images[0] if listing.images else None,
            "model": variant.model if variant else None,
            "storage_label": variant.storage_label if variant else None,
            "condition_grade": item.condition_grade if item else None,
        },
        "payment_intent": (
            payment_intent_payload(order.payment_intent)
            if order.payment_intent
            else None
        ),
        "refund": (
            refund_payload(order.refunds[-1])
            if order.refunds
            else None
        ),
        "settlement": (
            settlement_payload(order.settlement)
            if order.settlement
            else None
        ),
        "paid_at": order.paid_at,
        "fulfilled_at": order.fulfilled_at,
        "completed_at": order.completed_at,
        "cancelled_at": order.cancelled_at,
        "refunded_at": order.refunded_at,
        "cancellation_reason": order.cancellation_reason,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }
    if include_buyer:
        payload["buyer"] = {
            "id": order.buyer_user_id,
            "email": order.buyer.email if order.buyer else None,
            "display_name": order.buyer.display_name if order.buyer else None,
            "roles": list(roles_for_user(order.buyer)) if order.buyer else [],
            "status": order.buyer.status if order.buyer else "unknown",
            "created_at": order.buyer.created_at if order.buyer else order.created_at,
            "last_login_at": (
                order.buyer.last_login_at if order.buyer else None
            ),
        }
    if include_events:
        payload["events"] = [
            {
                "id": row.id,
                "from_status": row.from_status,
                "to_status": row.to_status,
                "actor": row.actor,
                "reason": row.reason,
                "created_at": row.created_at,
            }
            for row in order.events
        ]
    return payload


def payment_intent_payload(intent: models.PaymentIntent) -> dict[str, Any]:
    return {
        "id": intent.id,
        "provider": intent.provider,
        "provider_reference": intent.provider_reference,
        "status": intent.status,
        "amount_hkd": _float(intent.amount_hkd),
        "currency": intent.currency,
        "checkout_url": intent.checkout_url,
        "created_at": intent.created_at,
        "completed_at": intent.completed_at,
    }


def refund_payload(refund: models.Refund) -> dict[str, Any]:
    return {
        "id": refund.id,
        "status": refund.status,
        "amount_hkd": _float(refund.amount_hkd),
        "currency": refund.currency,
        "reason": refund.reason,
        "provider": refund.provider,
        "provider_reference": refund.provider_reference,
        "requested_at": refund.requested_at,
        "processed_at": refund.processed_at,
    }


def settlement_payload(settlement: models.MerchantSettlement) -> dict[str, Any]:
    return {
        "id": settlement.id,
        "status": settlement.status,
        "gross_hkd": _float(settlement.gross_hkd),
        "commission_hkd": _float(settlement.commission_hkd),
        "net_hkd": _float(settlement.net_hkd),
        "provider_reference": settlement.provider_reference,
        "created_at": settlement.created_at,
        "paid_at": settlement.paid_at,
    }


def journal_payload(journal: models.LedgerJournal) -> dict[str, Any]:
    return {
        "id": journal.id,
        "order_id": journal.order_id,
        "event_type": journal.event_type,
        "memo": journal.memo,
        "created_at": journal.created_at,
        "entries": [
            {
                "id": entry.id,
                "account_code": entry.account.code,
                "account_name": entry.account.name,
                "account_type": entry.account.account_type,
                "merchant_id": entry.account.merchant_id,
                "debit_hkd": _float(entry.debit_hkd),
                "credit_hkd": _float(entry.credit_hkd),
            }
            for entry in journal.entries
        ],
    }


def mock_checkout_signature(
    reference: str,
    settings: PlatformSettings,
) -> str:
    return hmac.new(
        settings.payment_webhook_secret.encode("utf-8"),
        f"mock-checkout:{reference}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_mock_checkout(
    settings: PlatformSettings,
    *,
    reference: str,
    signature: str,
) -> None:
    expected = mock_checkout_signature(reference, settings)
    if not signature or not secrets.compare_digest(signature, expected):
        raise PaymentVerificationError("模擬支付簽名無效")
    if settings.environment in {"production", "prod"}:
        raise PaymentVerificationError("Production 不允許模擬支付")


def complete_mock_payment(
    session: Session,
    settings: PlatformSettings,
    *,
    reference: str,
) -> models.Order:
    intent = session.scalar(
        select(models.PaymentIntent)
        .options(joinedload(models.PaymentIntent.order))
        .where(
            models.PaymentIntent.provider == "mock",
            models.PaymentIntent.provider_reference == reference,
        )
        .with_for_update()
    )
    if intent is None:
        raise OrderError("付款請求不存在")
    event = WebhookEvent(
        provider_event_id=f"mock_checkout:{intent.id}",
        event_type="payment.succeeded",
        order_id=intent.order_id,
        payment_intent_id=intent.id,
        provider_reference=intent.provider_reference,
        refund_reference=None,
        status="succeeded",
        payload={
            "id": f"mock_checkout:{intent.id}",
            "type": "payment.succeeded",
            "data": {
                "object": {
                    "id": intent.provider_reference,
                    "order_id": intent.order_id,
                    "payment_intent_id": intent.id,
                    "amount": _float(intent.amount_hkd),
                    "currency": intent.currency,
                }
            },
        },
    )
    existing = session.scalar(
        select(models.PaymentEvent).where(
            models.PaymentEvent.provider == "mock",
            models.PaymentEvent.provider_event_id == event.provider_event_id,
        )
    )
    if existing is None:
        payment_event = models.PaymentEvent(
            provider="mock",
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            order_id=intent.order_id,
            payment_intent_id=intent.id,
            payload=event.payload,
            status="processing",
        )
        session.add(payment_event)
    else:
        payment_event = existing
    _apply_webhook_event(
        session,
        event=event,
        order=intent.order,
        intent=intent,
        refund=None,
    )
    payment_event.status = "processed"
    payment_event.processed_at = _utc_now()
    session.flush()
    return intent.order


def _resolve_event_resources(
    session: Session,
    provider_key: str,
    event: WebhookEvent,
) -> tuple[
    models.Order | None,
    models.PaymentIntent | None,
    models.Refund | None,
]:
    order = session.get(models.Order, event.order_id) if event.order_id else None
    intent = (
        session.get(models.PaymentIntent, event.payment_intent_id)
        if event.payment_intent_id
        else None
    )
    refund = None
    if event.refund_reference:
        refund = session.scalar(
            select(models.Refund).where(
                models.Refund.provider == provider_key,
                models.Refund.provider_reference == event.refund_reference,
            )
        )
    if intent is None and event.provider_reference:
        intent = session.scalar(
            select(models.PaymentIntent).where(
                models.PaymentIntent.provider == provider_key,
                models.PaymentIntent.provider_reference
                == event.provider_reference,
            )
        )
    if intent is None and order is not None:
        intent = order.payment_intent
    if refund is None and event.order_id and event.refund_reference:
        refund = session.scalar(
            select(models.Refund).where(
                models.Refund.order_id == event.order_id,
                models.Refund.provider_reference == event.refund_reference,
            )
        )
    if intent is not None and order is None:
        order = intent.order
    if refund is not None and order is None:
        order = refund.order
    return order, intent, refund


def _apply_webhook_event(
    session: Session,
    *,
    event: WebhookEvent,
    order: models.Order | None,
    intent: models.PaymentIntent | None,
    refund: models.Refund | None,
) -> None:
    if order is None:
        raise OrderError("支付回調找不到對應訂單")
    if event.event_type.startswith("refund"):
        if refund is None:
            refund = order.refunds[-1] if order.refunds else None
        if refund is None:
            raise OrderError("支付回調找不到對應退款")
        refund.provider_reference = (
            refund.provider_reference or event.refund_reference
        )
        refund.status = _normalized_refund_status(event.status)
        if refund.status == "succeeded":
            _finalize_refund(session, order, refund)
        elif refund.status == "failed":
            previous = str(
                refund.metadata_json.get("previous_order_status") or "paid"
            )
            order.status = previous
            refund.processed_at = _utc_now()
            _record_order_event(
                session,
                order,
                from_status="refund_pending",
                to_status=previous,
                actor=f"provider:{refund.provider}",
                reason="refund_failed",
            )
        return

    successful = (
        event.status in {"succeeded", "paid", "complete"}
        or event.event_type.endswith(".succeeded")
    )
    if not successful:
        if intent is not None:
            intent.status = event.status or "failed"
        order.payment_status = "failed"
        _record_order_event(
            session,
            order,
            from_status=order.status,
            to_status=order.status,
            actor=f"provider:{order.payment_intent.provider if order.payment_intent else 'psp'}",
            reason="payment_failed",
        )
        return
    if intent is None:
        intent = order.payment_intent
    if intent is None:
        raise OrderError("支付回調找不到付款請求")
    if (
        event.provider_reference
        and intent.provider_reference != event.provider_reference
    ):
        intent.metadata_json = {
            **intent.metadata_json,
            "initial_provider_reference": intent.provider_reference,
        }
        intent.provider_reference = event.provider_reference
    if order.payment_status == "paid":
        return
    previous = order.status
    intent.status = "succeeded"
    intent.completed_at = _utc_now()
    order.payment_status = "paid"
    order.paid_at = _utc_now()
    if order.status == "pending_payment":
        order.status = "paid"
    _ensure_payment_journal(session, order)
    _record_order_event(
        session,
        order,
        from_status=previous,
        to_status=order.status,
        actor=f"provider:{intent.provider}",
        reason="payment_succeeded",
    )
    session.flush()


def _finalize_refund(
    session: Session,
    order: models.Order,
    refund: models.Refund,
) -> None:
    if order.status == "refunded":
        refund.status = "succeeded"
        return
    previous = order.status
    refund.status = "succeeded"
    refund.processed_at = _utc_now()
    order.status = "refunded"
    order.payment_status = "refunded"
    order.refunded_at = _utc_now()
    if order.settlement is not None and order.settlement.status == "pending":
        order.settlement.status = "cancelled"
    _ensure_refund_journal(session, order, refund)
    _record_order_event(
        session,
        order,
        from_status=previous,
        to_status="refunded",
        actor=f"provider:{refund.provider}",
        reason="refund_succeeded",
    )


def _ensure_payment_journal(
    session: Session,
    order: models.Order,
) -> models.LedgerJournal | None:
    amount = _money(order.total_hkd)
    if amount <= 0:
        return None
    cash = _ensure_account(
        session,
        code="psp_cash",
        name="PSP held cash",
        account_type="asset",
    )
    held = _ensure_account(
        session,
        code="buyer_funds_held",
        name="Buyer funds held",
        account_type="liability",
    )
    return _ensure_journal(
        session,
        order_id=order.id,
        event_type="payment_captured",
        idempotency_key=f"payment:{order.id}",
        memo=f"Payment captured for {order.order_number}",
        entries=[
            (cash, amount, Decimal("0.00")),
            (held, Decimal("0.00"), amount),
        ],
    )


def _record_settlement_journal(
    session: Session,
    order: models.Order,
) -> models.LedgerJournal:
    held = _ensure_account(
        session,
        code="buyer_funds_held",
        name="Buyer funds held",
        account_type="liability",
    )
    merchant_payable = _ensure_merchant_payable_account(session, order.merchant_id)
    commission = _ensure_account(
        session,
        code="platform_commission_revenue",
        name="Platform commission revenue",
        account_type="revenue",
    )
    return _ensure_journal(
        session,
        order_id=order.id,
        event_type="merchant_settlement_created",
        idempotency_key=f"settlement:{order.id}",
        memo=f"Settlement created for {order.order_number}",
        entries=[
            (held, _money(order.total_hkd), Decimal("0.00")),
            (
                merchant_payable,
                Decimal("0.00"),
                _money(order.merchant_net_hkd),
            ),
            (
                commission,
                Decimal("0.00"),
                _money(order.commission_hkd),
            ),
        ],
    )


def _ensure_refund_journal(
    session: Session,
    order: models.Order,
    refund: models.Refund,
) -> models.LedgerJournal:
    cash = _ensure_account(
        session,
        code="psp_cash",
        name="PSP held cash",
        account_type="asset",
    )
    amount = _money(refund.amount_hkd)
    if order.settlement is None:
        held = _ensure_account(
            session,
            code="buyer_funds_held",
            name="Buyer funds held",
            account_type="liability",
        )
        entries = [
            (held, amount, Decimal("0.00")),
            (cash, Decimal("0.00"), amount),
        ]
    else:
        merchant_payable = _ensure_merchant_payable_account(
            session,
            order.merchant_id,
        )
        commission = _ensure_account(
            session,
            code="platform_commission_revenue",
            name="Platform commission revenue",
            account_type="revenue",
        )
        entries = [
            (
                merchant_payable,
                _money(order.merchant_net_hkd),
                Decimal("0.00"),
            ),
            (
                commission,
                _money(order.commission_hkd),
                Decimal("0.00"),
            ),
            (cash, Decimal("0.00"), amount),
        ]
    return _ensure_journal(
        session,
        order_id=order.id,
        event_type="refund_succeeded",
        idempotency_key=f"refund:{refund.id}",
        memo=f"Refund completed for {order.order_number}",
        entries=entries,
    )


def _ensure_account(
    session: Session,
    *,
    code: str,
    name: str,
    account_type: str,
    merchant_id: str | None = None,
) -> models.LedgerAccount:
    account = session.scalar(
        select(models.LedgerAccount).where(models.LedgerAccount.code == code)
    )
    if account is not None:
        return account
    account = models.LedgerAccount(
        id=str(uuid.uuid4()),
        code=code,
        name=name,
        account_type=account_type,
        currency="HKD",
        merchant_id=merchant_id,
    )
    session.add(account)
    session.flush()
    return account


def _ensure_merchant_payable_account(
    session: Session,
    merchant_id: str,
) -> models.LedgerAccount:
    return _ensure_account(
        session,
        code=f"merchant_payable:{merchant_id}",
        name="Merchant settlement payable",
        account_type="liability",
        merchant_id=merchant_id,
    )


def _ensure_journal(
    session: Session,
    *,
    order_id: str,
    event_type: str,
    idempotency_key: str,
    memo: str,
    entries: list[tuple[models.LedgerAccount, Decimal, Decimal]],
) -> models.LedgerJournal:
    existing = session.scalar(
        select(models.LedgerJournal).where(
            models.LedgerJournal.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing
    total_debit = sum((entry[1] for entry in entries), Decimal("0.00"))
    total_credit = sum((entry[2] for entry in entries), Decimal("0.00"))
    if _money(total_debit) != _money(total_credit):
        raise OrderError("Ledger journal is not balanced")
    journal = models.LedgerJournal(
        id=str(uuid.uuid4()),
        order_id=order_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        memo=memo,
    )
    session.add(journal)
    session.flush()
    for account, debit, credit in entries:
        if _money(debit) == 0 and _money(credit) == 0:
            continue
        session.add(
            models.LedgerEntry(
                journal_id=journal.id,
                account_id=account.id,
                debit_hkd=_money(debit),
                credit_hkd=_money(credit),
            )
        )
    session.flush()
    return journal


def _record_order_event(
    session: Session,
    order: models.Order,
    *,
    from_status: str | None,
    to_status: str,
    actor: str,
    reason: str | None,
) -> None:
    session.add(
        models.OrderEvent(
            order_id=order.id,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            reason=reason,
        )
    )


def _release_order_reservation(session: Session, order: models.Order) -> None:
    listing = session.scalar(
        select(models.SellerListing)
        .where(models.SellerListing.id == order.seller_listing_id)
        .with_for_update()
    )
    item = session.scalar(
        select(models.InventoryItem)
        .where(models.InventoryItem.id == order.inventory_item_id)
        .with_for_update()
    )
    if listing is not None and listing.status == "reserved":
        listing.status = "active"
    if item is not None and item.status == "reserved":
        item.status = "available"


def _normalize_webhook_event(
    provider_key: str,
    payload: dict[str, Any],
) -> WebhookEvent:
    event_id = str(payload.get("id") or "").strip()
    event_type = str(payload.get("type") or "").strip()
    if not event_id or not event_type:
        raise PaymentVerificationError("支付回調缺少事件編號或類型")
    data = payload.get("data")
    obj = data.get("object") if isinstance(data, dict) else None
    if not isinstance(obj, dict):
        obj = payload
    metadata = obj.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    refund_reference = (
        str(obj.get("id"))
        if event_type.startswith("refund") or obj.get("object") == "refund"
        else None
    )
    status = str(
        obj.get("status")
        or obj.get("payment_status")
        or _status_from_event_type(event_type)
    ).lower()
    provider_reference = _provider_object_id(obj.get("payment_intent")) or (
        None if refund_reference else _provider_object_id(obj.get("id"))
    )
    return WebhookEvent(
        provider_event_id=event_id,
        event_type=event_type,
        order_id=_optional_string(
            metadata.get("order_id")
            or obj.get("order_id")
            or obj.get("client_reference_id")
        ),
        payment_intent_id=_optional_string(
            metadata.get("payment_intent_id") or obj.get("payment_intent_id")
        ),
        provider_reference=provider_reference,
        refund_reference=refund_reference,
        status=status,
        payload=payload,
    )


def _status_from_event_type(event_type: str) -> str:
    suffix = event_type.rsplit(".", 1)[-1]
    if suffix in {"succeeded", "paid", "complete", "failed", "cancelled"}:
        return suffix
    return "processing" if event_type.startswith("refund") else "succeeded"


def _normalized_refund_status(status: str) -> str:
    value = status.strip().lower()
    if value in {"succeeded", "success", "paid"}:
        return "succeeded"
    if value in {"failed", "cancelled", "canceled"}:
        return "failed"
    return "processing"


def _fulfillment_for_status(status: str) -> str:
    if status == "completed":
        return "shipped"
    if status in {"paid", "processing", "shipped"}:
        return status
    return "unfulfilled"


def _order_query():
    return select(models.Order).options(
        *_order_load_options(),
        joinedload(models.Order.events),
        joinedload(models.Order.refunds),
        joinedload(models.Order.settlement),
    )


def _order_load_options():
    return (
        joinedload(models.Order.buyer),
        joinedload(models.Order.merchant),
        joinedload(models.Order.seller_listing),
        joinedload(models.Order.inventory_item).joinedload(
            models.InventoryItem.variant
        ),
        joinedload(models.Order.payment_intent),
    )


def _clean_contact(value: dict[str, Any]) -> dict[str, str]:
    return {
        "recipient_name": str(value.get("recipient_name") or "").strip()[:120],
        "phone": str(value.get("phone") or "").strip()[:40],
        "email": str(value.get("email") or "").strip().lower()[:320],
    }


def _clean_address(value: dict[str, Any]) -> dict[str, str]:
    return {
        "line1": str(value.get("line1") or "").strip()[:200],
        "line2": str(value.get("line2") or "").strip()[:200],
        "district": str(value.get("district") or "").strip()[:80],
        "region": str(value.get("region") or "香港").strip()[:80],
        "country": "HK",
    }


def _order_number() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"HK{stamp}{secrets.token_hex(4).upper()}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    selected = str(value).strip()
    return selected or None


def _provider_object_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _optional_string(value.get("id"))
    return _optional_string(value)


def _append_query(url: str, values: dict[str, str]) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(values)}"


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _to_minor_units(value: Decimal) -> int:
    return int((_money(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _float(value: Any) -> float:
    return float(_money(value))
