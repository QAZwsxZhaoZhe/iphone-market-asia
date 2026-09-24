from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_user_status", "status"),
        Index("idx_user_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    merchants: Mapped[list["Merchant"]] = relationship(back_populates="owner")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (Index("idx_user_role_role", "role"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    user: Mapped[User] = relationship(back_populates="roles")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("idx_auth_session_expiry", "expires_at"),
        Index("idx_auth_session_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class Merchant(Base):
    __tablename__ = "merchants"
    __table_args__ = (
        Index("idx_merchant_owner", "owner_user_id"),
        Index("idx_merchant_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    merchant_type: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="business",
    )
    legal_name: Mapped[str] = mapped_column(String(180), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    commission_rate_bps: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1000,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    owner: Mapped[User | None] = relationship(back_populates="merchants")
    inventory_items: Mapped[list["InventoryItem"]] = relationship(
        back_populates="merchant"
    )
    seller_listings: Mapped[list["SellerListing"]] = relationship(
        back_populates="merchant"
    )


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("merchant_id", "sku", name="uq_inventory_merchant_sku"),
        Index("idx_inventory_variant_status", "phone_variant_id", "status"),
        Index("idx_inventory_merchant_status", "merchant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    phone_variant_id: Mapped[str] = mapped_column(
        ForeignKey("phone_variants.id"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    serial_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    condition_grade: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="B",
    )
    battery_health_pct: Mapped[int | None] = mapped_column(Integer)
    repair_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    accessories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cost_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="intake")
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    merchant: Mapped[Merchant] = relationship(back_populates="inventory_items")
    variant: Mapped[PhoneVariant] = relationship()
    listing: Mapped["SellerListing | None"] = relationship(
        back_populates="inventory_item",
        uselist=False,
    )


class SellerListing(Base):
    __tablename__ = "seller_listings"
    __table_args__ = (
        UniqueConstraint(
            "inventory_item_id",
            name="uq_seller_listing_inventory",
        ),
        UniqueConstraint("slug", name="uq_seller_listing_slug"),
        Index("idx_seller_listing_status_price", "status", "price_hkd"),
        Index("idx_seller_listing_merchant", "merchant_id", "status"),
        Index("idx_seller_listing_published", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inventory_item_id: Mapped[str] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(180), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_hkd: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    warranty_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inspection_report: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    images: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    inventory_item: Mapped[InventoryItem] = relationship(back_populates="listing")
    merchant: Mapped[Merchant] = relationship(back_populates="seller_listings")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_number", name="uq_order_number"),
        UniqueConstraint(
            "buyer_user_id",
            "idempotency_key",
            name="uq_order_buyer_idempotency",
        ),
        Index("idx_order_buyer_status", "buyer_user_id", "status"),
        Index("idx_order_merchant_status", "merchant_id", "status"),
        Index("idx_order_listing_status", "seller_listing_id", "status"),
        Index("idx_order_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_number: Mapped[str] = mapped_column(String(32), nullable=False)
    buyer_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    seller_listing_id: Mapped[str] = mapped_column(
        ForeignKey("seller_listings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    inventory_item_id: Mapped[str] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_payment",
    )
    payment_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
    )
    fulfillment_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="unfulfilled",
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="HKD")
    item_price_hkd: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    shipping_fee_hkd: Mapped[float] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=0,
    )
    total_hkd: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    commission_rate_bps: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    commission_hkd: Mapped[float] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=0,
    )
    merchant_net_hkd: Mapped[float] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=0,
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    shipping_address_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    buyer: Mapped[User] = relationship()
    merchant: Mapped[Merchant] = relationship()
    seller_listing: Mapped[SellerListing] = relationship()
    inventory_item: Mapped[InventoryItem] = relationship()
    events: Mapped[list["OrderEvent"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )
    payment_intent: Mapped["PaymentIntent | None"] = relationship(
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )
    refunds: Mapped[list["Refund"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )
    settlement: Mapped["MerchantSettlement | None"] = relationship(
        back_populates="order",
        uselist=False,
    )


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (Index("idx_order_event_order", "order_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(180), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    order: Mapped[Order] = relationship(back_populates="events")


class PaymentIntent(Base):
    __tablename__ = "payment_intents"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_payment_intent_order"),
        UniqueConstraint(
            "provider",
            "provider_reference",
            name="uq_payment_intent_provider_reference",
        ),
        Index("idx_payment_intent_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
    )
    amount_hkd: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="HKD")
    checkout_url: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        unique=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="payment_intent")


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_payment_event_provider_id",
        ),
        Index("idx_payment_event_received", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(180), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"),
    )
    payment_intent_id: Mapped[str | None] = mapped_column(
        ForeignKey("payment_intents.id", ondelete="SET NULL"),
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="processing",
    )
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_refund_order_idempotency",
        ),
        UniqueConstraint(
            "provider",
            "provider_reference",
            name="uq_refund_provider_reference",
        ),
        Index("idx_refund_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    payment_intent_id: Mapped[str] = mapped_column(
        ForeignKey("payment_intents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="requested",
    )
    amount_hkd: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="HKD")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="refunds")
    payment_intent: Mapped[PaymentIntent] = relationship()


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (UniqueConstraint("code", name="uq_ledger_account_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="HKD")
    merchant_id: Mapped[str | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class LedgerJournal(Base):
    __tablename__ = "ledger_journals"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ledger_journal_idempotency"),
        Index("idx_ledger_journal_order", "order_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"),
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    memo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="journal",
        cascade="all, delete-orphan",
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index("idx_ledger_entry_account", "account_id", "created_at"),
        Index("idx_ledger_entry_journal", "journal_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[str] = mapped_column(
        ForeignKey("ledger_journals.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("ledger_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    debit_hkd: Mapped[float] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=0,
    )
    credit_hkd: Mapped[float] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    journal: Mapped[LedgerJournal] = relationship(back_populates="entries")
    account: Mapped[LedgerAccount] = relationship()


class MerchantSettlement(Base):
    __tablename__ = "merchant_settlements"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_merchant_settlement_order"),
        Index("idx_merchant_settlement_status", "status"),
        Index("idx_merchant_settlement_merchant", "merchant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
    )
    gross_hkd: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    commission_hkd: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    net_hkd: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    merchant: Mapped[Merchant] = relationship()
    order: Mapped[Order] = relationship(back_populates="settlement")


class Source(Base):
    __tablename__ = "sources"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    market: Mapped[str] = mapped_column(String(40), nullable=False, default="香港")
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requires_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cadence_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    terms_url: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    listings: Mapped[list["Listing"]] = relationship(back_populates="source")


class PhoneVariant(Base):
    __tablename__ = "phone_variants"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    family: Mapped[str] = mapped_column(String(24), nullable=False)
    storage_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_label: Mapped[str] = mapped_column(String(12), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    listings: Mapped[list["Listing"]] = relationship(back_populates="variant")


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "source_listing_id",
            name="uq_listing_source_identity",
        ),
        Index("idx_listing_status_seen", "listing_status", "last_seen_at"),
        Index("idx_listing_variant_price", "phone_variant_id", "price_hkd"),
        Index("idx_listing_district", "district"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(
        ForeignKey("sources.key"),
        nullable=False,
    )
    source_listing_id: Mapped[str] = mapped_column(String(180), nullable=False)
    phone_variant_id: Mapped[str] = mapped_column(
        ForeignKey("phone_variants.id"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[str] = mapped_column(String(24), nullable=False, default="used")
    listing_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="active",
    )
    district: Mapped[str | None] = mapped_column(String(40))
    location_raw: Mapped[str | None] = mapped_column(Text)
    seller_signals: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price_native: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="HKD")
    price_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    fx_date: Mapped[str | None] = mapped_column(String(10))
    valuation_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    valuation_low_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    valuation_high_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    valuation_confidence: Mapped[str | None] = mapped_column(String(16))
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    source: Mapped[Source] = relationship(back_populates="listings")
    variant: Mapped[PhoneVariant] = relationship(back_populates="listings")
    snapshots: Mapped[list["ListingSnapshot"]] = relationship(
        back_populates="listing",
        cascade="all, delete-orphan",
    )


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"
    __table_args__ = (
        UniqueConstraint("observation_key", name="uq_listing_snapshot_observation"),
        Index("idx_snapshot_listing_seen", "listing_id", "observed_at"),
        Index("idx_snapshot_date", "collected_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_date: Mapped[str] = mapped_column(String(10), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    condition: Mapped[str] = mapped_column(String(24), nullable=False)
    district: Mapped[str | None] = mapped_column(String(40))
    price_native: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    price_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    raw_ref: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    listing: Mapped[Listing] = relationship(back_populates="snapshots")


class SourceRun(Base):
    __tablename__ = "source_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "external_run_id",
            name="uq_source_run_external",
        ),
        Index("idx_source_run_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(
        ForeignKey("sources.key"),
        nullable=False,
    )
    external_run_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    listing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    query_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )


class RawCapture(Base):
    __tablename__ = "raw_captures"
    __table_args__ = (Index("idx_raw_capture_expiry", "expires_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL"),
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="application/json",
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )


class ListingCluster(Base):
    __tablename__ = "listing_clusters"
    __table_args__ = (
        UniqueConstraint("cluster_key", name="uq_listing_cluster_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_key: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    members: Mapped[list["ListingClusterMember"]] = relationship(
        back_populates="cluster",
        cascade="all, delete-orphan",
    )


class ListingClusterMember(Base):
    __tablename__ = "listing_cluster_members"
    __table_args__ = (
        UniqueConstraint("listing_id", name="uq_cluster_member_listing"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("listing_clusters.id", ondelete="CASCADE"),
        nullable=False,
    )
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
    )

    cluster: Mapped[ListingCluster] = relationship(back_populates="members")


class Valuation(Base):
    __tablename__ = "valuations"
    __table_args__ = (
        UniqueConstraint(
            "market",
            "model",
            "storage_gb",
            "as_of_date",
            "method",
            name="uq_valuation_version",
        ),
        Index(
            "idx_valuation_variant_date",
            "model",
            "storage_gb",
            "as_of_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(40), nullable=False, default="香港")
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_date: Mapped[str] = mapped_column(String(10), nullable=False)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    fair_low_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    fair_mid_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    fair_high_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    suggested_purchase_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    suggested_resale_hkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    confidence_level: Mapped[str] = mapped_column(String(16), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filter_json: Mapped[dict[str, Any]] = mapped_column(
        "filters",
        JSON,
        nullable=False,
        default=dict,
    )
    notification_json: Mapped[dict[str, Any]] = mapped_column(
        "notifications",
        JSON,
        nullable=False,
        default=dict,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    alerts: Mapped[list["Alert"]] = relationship(back_populates="watchlist")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("idx_alert_triggered", "triggered_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[str] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"),
        nullable=False,
    )
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    watchlist: Mapped[Watchlist] = relationship(back_populates="alerts")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("idx_audit_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(180), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(180))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DeadLetterTask(Base):
    __tablename__ = "dead_letter_tasks"
    __table_args__ = (Index("idx_dead_letter_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(120), nullable=False)
    task_name: Mapped[str] = mapped_column(String(180), nullable=False)
    args_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    kwargs_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    error: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
