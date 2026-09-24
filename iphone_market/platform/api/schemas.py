from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=256)


class RegisterRequest(LoginRequest):
    display_name: str = Field(min_length=1, max_length=120)


class StaffUserCreate(LoginRequest):
    display_name: str = Field(min_length=1, max_length=120)
    roles: list[str] = Field(
        default_factory=lambda: ["operator"],
        min_length=1,
    )


class UserPublic(BaseModel):
    id: str
    email: str
    display_name: str
    roles: list[str]
    status: str
    created_at: datetime
    last_login_at: datetime | None = None


class PrincipalPublic(BaseModel):
    subject: str
    roles: list[str]
    internal: bool
    user_id: str | None = None
    email: str | None = None
    auth_method: str


class SessionPublic(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserPublic


class MerchantCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=120)
    merchant_type: str = Field(default="business", max_length=24)
    owner_user_id: str | None = None
    commission_rate_bps: int = Field(default=1000, ge=0, le=5000)
    status: str = Field(default="pending", max_length=24)


class MerchantPublic(BaseModel):
    id: str
    owner_user_id: str | None = None
    merchant_type: str
    legal_name: str
    display_name: str
    status: str
    commission_rate_bps: int
    created_at: datetime


class InventoryItemCreate(BaseModel):
    merchant_id: str
    phone_variant_id: str
    sku: str = Field(min_length=1, max_length=80)
    condition_grade: str = Field(default="B", max_length=16)
    battery_health_pct: int | None = Field(default=None, ge=0, le=100)
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    cost_hkd: float | None = Field(default=None, ge=0)
    status: str = Field(default="intake", max_length=24)


class QuickSellerListingCreate(BaseModel):
    merchant_id: str
    phone_variant_id: str
    condition_grade: str = Field(default="B", max_length=16)
    price_hkd: float = Field(gt=0)
    battery_health_pct: int | None = Field(default=None, ge=0, le=100)
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=10000)
    warranty_days: int = Field(default=30, ge=0, le=3650)
    images: list[str] = Field(default_factory=list)


class InventoryItemPublic(BaseModel):
    id: str
    merchant_id: str
    phone_variant_id: str
    sku: str
    model: str
    storage_gb: int
    storage_label: str
    condition_grade: str
    battery_health_pct: int | None = None
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    cost_hkd: float | None = None
    status: str
    listing_id: str | None = None
    created_at: datetime


class SellerListingCreate(BaseModel):
    merchant_id: str
    inventory_item_id: str
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    price_hkd: float = Field(gt=0)
    warranty_days: int = Field(default=0, ge=0, le=3650)
    inspection_report: dict[str, Any] = Field(default_factory=dict)
    images: list[str] = Field(default_factory=list)
    slug: str | None = Field(default=None, max_length=180)


class StoreMerchantPublic(BaseModel):
    id: str
    display_name: str
    type: str


class StoreVariantPublic(BaseModel):
    id: str
    model: str
    generation: int
    family: str
    storage_gb: int
    storage_label: str


class StoreInventoryPublic(BaseModel):
    condition_grade: str
    battery_health_pct: int | None = None
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)


class StoreListingPublic(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    price_hkd: float | None = None
    status: str
    warranty_days: int
    images: list[str] = Field(default_factory=list)
    inspection_report: dict[str, Any] = Field(default_factory=dict)
    published_at: datetime | None = None
    merchant: StoreMerchantPublic
    variant: StoreVariantPublic
    inventory: StoreInventoryPublic


class StoreListingPage(BaseModel):
    items: list[StoreListingPublic]
    total: int
    offset: int
    limit: int


class OrderContactInput(BaseModel):
    recipient_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=5, max_length=40)
    email: str = Field(min_length=3, max_length=320)


class ShippingAddressInput(BaseModel):
    line1: str = Field(min_length=1, max_length=200)
    line2: str = Field(default="", max_length=200)
    district: str = Field(min_length=1, max_length=80)
    region: str = Field(default="香港", min_length=1, max_length=80)
    country: str = Field(default="HK", pattern="^HK$")


class OrderCreateRequest(BaseModel):
    listing_id: str = Field(min_length=1, max_length=180)
    contact: OrderContactInput
    shipping_address: ShippingAddressInput
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class CancelOrderRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class FulfillOrderRequest(BaseModel):
    status: str = Field(pattern="^(processing|shipped)$")
    note: str = Field(default="", max_length=1000)


class RefundCreateRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class OrderEventPublic(BaseModel):
    id: int
    from_status: str | None = None
    to_status: str
    actor: str
    reason: str | None = None
    created_at: datetime


class PaymentIntentPublic(BaseModel):
    id: str
    provider: str
    provider_reference: str
    status: str
    amount_hkd: float
    currency: str
    checkout_url: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class RefundPublic(BaseModel):
    id: str
    status: str
    amount_hkd: float
    currency: str
    reason: str
    provider: str
    provider_reference: str | None = None
    requested_at: datetime
    processed_at: datetime | None = None


class SettlementPublic(BaseModel):
    id: str
    status: str
    gross_hkd: float
    commission_hkd: float
    net_hkd: float
    provider_reference: str | None = None
    created_at: datetime
    paid_at: datetime | None = None


class OrderMerchantPublic(BaseModel):
    id: str
    display_name: str


class OrderItemPublic(BaseModel):
    listing_id: str
    slug: str
    title: str
    image: str | None = None
    model: str | None = None
    storage_label: str | None = None
    condition_grade: str | None = None


class OrderPublic(BaseModel):
    id: str
    order_number: str
    status: str
    payment_status: str
    fulfillment_status: str
    currency: str
    item_price_hkd: float
    shipping_fee_hkd: float
    total_hkd: float
    commission_rate_bps: int
    commission_hkd: float
    merchant_net_hkd: float
    contact: dict[str, Any] = Field(default_factory=dict)
    shipping_address: dict[str, Any] = Field(default_factory=dict)
    merchant: OrderMerchantPublic
    item: OrderItemPublic
    payment_intent: PaymentIntentPublic | None = None
    refund: RefundPublic | None = None
    settlement: SettlementPublic | None = None
    paid_at: datetime | None = None
    fulfilled_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    refunded_at: datetime | None = None
    cancellation_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    events: list[OrderEventPublic] = Field(default_factory=list)


class InternalOrderPublic(OrderPublic):
    buyer: UserPublic


class LedgerEntryPublic(BaseModel):
    id: int
    account_code: str
    account_name: str
    account_type: str
    merchant_id: str | None = None
    debit_hkd: float
    credit_hkd: float


class LedgerJournalPublic(BaseModel):
    id: str
    order_id: str | None = None
    event_type: str
    memo: str
    created_at: datetime
    entries: list[LedgerEntryPublic]


class PaymentWebhookAck(BaseModel):
    event_id: int
    provider_event_id: str
    status: str
    duplicate: bool = False


class ListingPublic(BaseModel):
    id: int
    source_key: str
    source_name: str
    title: str
    url: str
    model: str | None = None
    generation: int | None = None
    family: str | None = None
    storage_gb: int | None = None
    storage_label: str | None = None
    condition: str
    listing_status: str
    district: str | None = None
    location: str | None = None
    price_native: float | None = None
    currency: str
    price_hkd: float | None = None
    fx_date: str | None = None
    valuation_hkd: float | None = None
    valuation_low_hkd: float | None = None
    valuation_high_hkd: float | None = None
    valuation_confidence: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    freshness_seconds: int | None = None
    cluster_id: int | None = None


class ListingPage(BaseModel):
    items: list[ListingPublic]
    next_cursor: str | None = None
    total: int
    limit: int


class SnapshotPublic(BaseModel):
    observed_at: datetime
    collected_date: str
    status: str
    condition: str
    district: str | None = None
    price_native: float | None = None
    currency: str
    price_hkd: float | None = None


class SourceHealthPublic(BaseModel):
    source_key: str
    source_name: str
    market: str
    active: bool
    status: str
    listing_count: int
    active_listing_count: int
    query_count: int
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_success_at: datetime | None = None
    freshness_seconds: int | None = None
    cadence_seconds: int


class SourceRunPublic(BaseModel):
    id: int
    source_key: str
    external_run_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    listing_count: int
    query_count: int
    error: str | None = None
    attempt: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditPublic(BaseModel):
    id: int
    actor: str
    action: str
    resource_type: str
    resource_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DeadLetterPublic(BaseModel):
    id: int
    task_id: str
    task_name: str
    args_json: list[Any]
    kwargs_json: dict[str, Any]
    error: str
    retry_count: int
    created_at: datetime


class RawCapturePublic(BaseModel):
    id: int
    source_key: str
    listing_id: int | None = None
    captured_at: datetime
    storage_uri: str
    sha256: str
    size_bytes: int
    content_type: str
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskAccepted(BaseModel):
    task_id: str
    status: str = "queued"


class ActionAccepted(BaseModel):
    status: str
    detail: str
    count: int | None = None
