from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from . import models
from .identity import IdentityError


MERCHANT_TYPES = {"platform", "business", "individual"}
MERCHANT_STATUSES = {"pending", "active", "suspended", "closed"}
INVENTORY_STATUSES = {
    "intake",
    "inspection",
    "available",
    "reserved",
    "sold",
    "returned",
    "archived",
}
LISTING_STATUSES = {"draft", "active", "reserved", "sold", "archived"}
CONDITION_GRADES = {"A+", "A", "B", "C", "D"}


class CommerceError(ValueError):
    pass


def create_merchant(
    session: Session,
    *,
    legal_name: str,
    display_name: str,
    merchant_type: str = "business",
    owner_user_id: str | None = None,
    commission_rate_bps: int = 1000,
    status: str = "pending",
) -> models.Merchant:
    if merchant_type not in MERCHANT_TYPES:
        raise CommerceError("商家類型無效")
    if status not in MERCHANT_STATUSES:
        raise CommerceError("商家狀態無效")
    if not 0 <= int(commission_rate_bps) <= 5000:
        raise CommerceError("佣金必須介於 0% 和 50% 之間")
    if owner_user_id and session.get(models.User, owner_user_id) is None:
        raise CommerceError("商家擁有人不存在")
    merchant = models.Merchant(
        id=str(uuid.uuid4()),
        owner_user_id=owner_user_id,
        merchant_type=merchant_type,
        legal_name=legal_name.strip()[:180],
        display_name=display_name.strip()[:120],
        status=status,
        commission_rate_bps=int(commission_rate_bps),
    )
    if not merchant.legal_name or not merchant.display_name:
        raise CommerceError("商家名稱不能為空")
    session.add(merchant)
    session.flush()
    return merchant


def get_owned_merchant(
    session: Session,
    *,
    owner_user_id: str,
) -> models.Merchant | None:
    return session.scalar(
        select(models.Merchant)
        .options(joinedload(models.Merchant.owner))
        .where(models.Merchant.owner_user_id == owner_user_id)
        .order_by(models.Merchant.created_at.asc())
        .limit(1)
    )


def apply_merchant(
    session: Session,
    *,
    owner_user_id: str,
    legal_name: str,
    display_name: str,
    merchant_type: str = "business",
) -> models.Merchant:
    existing = get_owned_merchant(session, owner_user_id=owner_user_id)
    if existing is not None:
        return existing
    selected_type = merchant_type.strip().lower()
    if selected_type not in {"business", "individual"}:
        raise CommerceError("公開申請只支援 B2C 商家或個人賣家")
    return create_merchant(
        session,
        legal_name=legal_name,
        display_name=display_name,
        merchant_type=selected_type,
        owner_user_id=owner_user_id,
        status="pending",
    )


def update_merchant_status(
    session: Session,
    *,
    merchant_id: str,
    status: str,
) -> models.Merchant:
    selected_status = status.strip().lower()
    if selected_status not in MERCHANT_STATUSES:
        raise CommerceError("商家狀態無效")
    merchant = session.get(models.Merchant, merchant_id)
    if merchant is None:
        raise CommerceError("商家不存在")
    merchant.status = selected_status
    session.flush()
    return merchant


def list_merchants(session: Session, *, limit: int = 100) -> list[models.Merchant]:
    return list(
        session.scalars(
            select(models.Merchant)
            .options(joinedload(models.Merchant.owner))
            .order_by(models.Merchant.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    )


def create_inventory_item(
    session: Session,
    *,
    merchant_id: str,
    phone_variant_id: str,
    sku: str,
    condition_grade: str,
    battery_health_pct: int | None = None,
    repair_history: list[dict[str, Any]] | None = None,
    accessories: list[str] | None = None,
    cost_hkd: Decimal | float | None = None,
    status: str = "intake",
) -> models.InventoryItem:
    merchant = session.get(models.Merchant, merchant_id)
    if merchant is None:
        raise CommerceError("商家不存在")
    if session.get(models.PhoneVariant, phone_variant_id) is None:
        raise CommerceError("機型容量不存在")
    if condition_grade not in CONDITION_GRADES:
        raise CommerceError("成色等級無效")
    if status not in INVENTORY_STATUSES:
        raise CommerceError("庫存狀態無效")
    if battery_health_pct is not None and not 0 <= int(battery_health_pct) <= 100:
        raise CommerceError("電池健康度必須介於 0 和 100")
    selected_sku = sku.strip()[:80]
    if not selected_sku:
        raise CommerceError("SKU 不能為空")
    existing = session.scalar(
        select(models.InventoryItem.id).where(
            models.InventoryItem.merchant_id == merchant.id,
            models.InventoryItem.sku == selected_sku,
        )
    )
    if existing:
        raise CommerceError("此商家已有相同 SKU")
    item = models.InventoryItem(
        id=str(uuid.uuid4()),
        merchant_id=merchant.id,
        phone_variant_id=phone_variant_id,
        sku=selected_sku,
        condition_grade=condition_grade,
        battery_health_pct=(
            int(battery_health_pct) if battery_health_pct is not None else None
        ),
        repair_history=list(repair_history or []),
        accessories=list(accessories or []),
        cost_hkd=_decimal_or_none(cost_hkd),
        status=status,
    )
    session.add(item)
    session.flush()
    return item


def list_inventory(
    session: Session,
    *,
    merchant_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[models.InventoryItem]:
    stmt = (
        select(models.InventoryItem)
        .options(
            joinedload(models.InventoryItem.merchant),
            joinedload(models.InventoryItem.variant),
            joinedload(models.InventoryItem.listing),
        )
        .order_by(models.InventoryItem.created_at.desc())
    )
    if merchant_id:
        stmt = stmt.where(models.InventoryItem.merchant_id == merchant_id)
    if status:
        stmt = stmt.where(models.InventoryItem.status == status)
    return list(session.scalars(stmt.limit(max(1, min(limit, 500)))).unique())


def create_seller_listing(
    session: Session,
    *,
    merchant_id: str,
    inventory_item_id: str,
    title: str,
    description: str,
    price_hkd: Decimal | float,
    warranty_days: int = 0,
    inspection_report: dict[str, Any] | None = None,
    images: list[str] | None = None,
    slug: str | None = None,
) -> models.SellerListing:
    merchant = session.get(models.Merchant, merchant_id)
    item = session.get(models.InventoryItem, inventory_item_id)
    if merchant is None or item is None or item.merchant_id != merchant.id:
        raise CommerceError("商家或庫存商品不存在")
    if session.scalar(
        select(models.SellerListing.id).where(
            models.SellerListing.inventory_item_id == item.id
        )
    ):
        raise CommerceError("此庫存商品已有銷售頁")
    selected_price = _decimal_or_none(price_hkd)
    if selected_price is None or selected_price <= 0:
        raise CommerceError("售價必須大於零")
    if int(warranty_days) < 0 or int(warranty_days) > 3650:
        raise CommerceError("保養期必須介於 0 和 3650 日")
    selected_slug = _unique_slug(
        session,
        slug or f"{item.variant.model}-{item.variant.storage_label}",
    )
    listing = models.SellerListing(
        id=str(uuid.uuid4()),
        inventory_item_id=item.id,
        merchant_id=merchant.id,
        slug=selected_slug,
        title=title.strip(),
        description=description.strip(),
        price_hkd=selected_price,
        warranty_days=int(warranty_days),
        inspection_report=dict(inspection_report or {}),
        images=[str(image) for image in (images or [])],
    )
    if not listing.title:
        raise CommerceError("商品標題不能為空")
    session.add(listing)
    session.flush()
    return listing


def quick_create_seller_listing(
    session: Session,
    *,
    merchant_id: str,
    phone_variant_id: str,
    condition_grade: str,
    price_hkd: Decimal | float,
    battery_health_pct: int | None = None,
    title: str = "",
    description: str = "",
    warranty_days: int = 30,
    images: list[str] | None = None,
) -> models.SellerListing:
    merchant = session.get(models.Merchant, merchant_id)
    if merchant is None:
        raise CommerceError("商家不存在")
    if merchant.status != "active":
        raise CommerceError("商家尚未通過審核")
    variant = session.get(models.PhoneVariant, phone_variant_id)
    if variant is None:
        raise CommerceError("機型容量不存在")

    item = create_inventory_item(
        session,
        merchant_id=merchant_id,
        phone_variant_id=phone_variant_id,
        sku=_quick_listing_sku(session, merchant_id),
        condition_grade=condition_grade,
        battery_health_pct=battery_health_pct,
        status="available",
    )
    listing = create_seller_listing(
        session,
        merchant_id=merchant_id,
        inventory_item_id=item.id,
        title=title.strip()
        or f"Apple {variant.model} {variant.storage_label} {condition_grade}級",
        description=description,
        price_hkd=price_hkd,
        warranty_days=warranty_days,
        inspection_report=(
            {"battery_health_pct": int(battery_health_pct)}
            if battery_health_pct is not None
            else {}
        ),
        images=images,
    )
    return publish_seller_listing(session, listing.id)


def list_seller_listings(
    session: Session,
    *,
    merchant_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[models.SellerListing]:
    stmt = _seller_listing_query().order_by(models.SellerListing.created_at.desc())
    if merchant_id:
        stmt = stmt.where(models.SellerListing.merchant_id == merchant_id)
    if status:
        stmt = stmt.where(models.SellerListing.status == status)
    return list(session.scalars(stmt.limit(max(1, min(limit, 500)))).unique())


def publish_seller_listing(
    session: Session,
    listing_id: str,
) -> models.SellerListing:
    listing = session.scalar(
        select(models.SellerListing)
        .options(
            joinedload(models.SellerListing.merchant),
            joinedload(models.SellerListing.inventory_item),
        )
        .where(models.SellerListing.id == listing_id)
    )
    if listing is None:
        raise CommerceError("銷售商品不存在")
    if listing.merchant.status != "active":
        raise CommerceError("商家尚未通過審核")
    if listing.inventory_item.status not in {"available", "reserved"}:
        raise CommerceError("庫存商品尚未完成驗機或不可上架")
    listing.status = "active"
    listing.published_at = datetime.now(timezone.utc)
    if listing.inventory_item.status == "reserved":
        listing.inventory_item.status = "available"
    session.flush()
    return listing


def store_listings(
    session: Session,
    *,
    model: str | None = None,
    storage_gb: int | None = None,
    condition_grade: str | None = None,
    min_price: Decimal | float | None = None,
    max_price: Decimal | float | None = None,
    offset: int = 0,
    limit: int = 30,
) -> tuple[list[models.SellerListing], int]:
    clauses = [
        models.SellerListing.status == "active",
        models.Merchant.status == "active",
    ]
    if model:
        clauses.append(models.PhoneVariant.model == model)
    if storage_gb is not None:
        clauses.append(models.PhoneVariant.storage_gb == int(storage_gb))
    if condition_grade:
        clauses.append(models.InventoryItem.condition_grade == condition_grade)
    if min_price is not None:
        clauses.append(models.SellerListing.price_hkd >= _decimal_or_none(min_price))
    if max_price is not None:
        clauses.append(models.SellerListing.price_hkd <= _decimal_or_none(max_price))
    count_stmt = (
        select(func.count(models.SellerListing.id))
        .join(models.InventoryItem)
        .join(models.PhoneVariant)
        .join(
            models.Merchant,
            models.Merchant.id == models.SellerListing.merchant_id,
        )
        .where(*clauses)
    )
    total = int(session.scalar(count_stmt) or 0)
    stmt = (
        _seller_listing_query()
        .where(*clauses)
        .order_by(models.SellerListing.published_at.desc(), models.SellerListing.id)
        .offset(max(0, offset))
        .limit(max(1, min(limit, 100)))
    )
    return list(session.scalars(stmt).unique()), total


def get_store_listing(
    session: Session,
    listing_id: str,
) -> models.SellerListing | None:
    return session.scalar(
        _seller_listing_query()
        .where(
            or_(
                models.SellerListing.id == listing_id,
                models.SellerListing.slug == listing_id,
            ),
            models.SellerListing.status == "active",
            models.Merchant.status == "active",
        )
    )


def merchant_payload(merchant: models.Merchant) -> dict[str, Any]:
    return {
        "id": merchant.id,
        "owner_user_id": merchant.owner_user_id,
        "merchant_type": merchant.merchant_type,
        "legal_name": merchant.legal_name,
        "display_name": merchant.display_name,
        "status": merchant.status,
        "commission_rate_bps": merchant.commission_rate_bps,
        "created_at": merchant.created_at,
    }


def inventory_payload(item: models.InventoryItem) -> dict[str, Any]:
    variant = item.variant
    return {
        "id": item.id,
        "merchant_id": item.merchant_id,
        "phone_variant_id": item.phone_variant_id,
        "sku": item.sku,
        "model": variant.model,
        "storage_gb": variant.storage_gb,
        "storage_label": variant.storage_label,
        "condition_grade": item.condition_grade,
        "battery_health_pct": item.battery_health_pct,
        "repair_history": item.repair_history,
        "accessories": item.accessories,
        "cost_hkd": _float_or_none(item.cost_hkd),
        "status": item.status,
        "listing_id": item.listing.id if item.listing else None,
        "created_at": item.created_at,
    }


def seller_listing_payload(listing: models.SellerListing) -> dict[str, Any]:
    item = listing.inventory_item
    variant = item.variant
    return {
        "id": listing.id,
        "slug": listing.slug,
        "title": listing.title,
        "description": listing.description,
        "price_hkd": _float_or_none(listing.price_hkd),
        "status": listing.status,
        "warranty_days": listing.warranty_days,
        "images": listing.images,
        "inspection_report": listing.inspection_report,
        "published_at": listing.published_at,
        "merchant": {
            "id": listing.merchant.id,
            "display_name": listing.merchant.display_name,
            "type": listing.merchant.merchant_type,
        },
        "variant": {
            "id": variant.id,
            "model": variant.model,
            "generation": variant.generation,
            "family": variant.family,
            "storage_gb": variant.storage_gb,
            "storage_label": variant.storage_label,
        },
        "inventory": {
            "condition_grade": item.condition_grade,
            "battery_health_pct": item.battery_health_pct,
            "repair_history": item.repair_history,
            "accessories": item.accessories,
        },
    }


def _seller_listing_query():
    return (
        select(models.SellerListing)
        .join(models.SellerListing.inventory_item)
        .join(models.InventoryItem.variant)
        .join(
            models.Merchant,
            models.Merchant.id == models.SellerListing.merchant_id,
        )
        .options(
            joinedload(models.SellerListing.merchant),
            joinedload(models.SellerListing.inventory_item).joinedload(
                models.InventoryItem.variant
            ),
        )
    )


def _unique_slug(session: Session, value: str) -> str:
    base = _slugify(value) or "iphone"
    candidate = base[:150]
    suffix = 2
    while session.scalar(
        select(models.SellerListing.id).where(
            models.SellerListing.slug == candidate
        )
    ):
        candidate = f"{base[:140]}-{suffix}"
        suffix += 1
    return candidate


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return text.strip("-")


def _quick_listing_sku(session: Session, merchant_id: str) -> str:
    while True:
        candidate = f"HK-{uuid.uuid4().hex[:16].upper()}"
        existing = session.scalar(
            select(models.InventoryItem.id).where(
                models.InventoryItem.merchant_id == merchant_id,
                models.InventoryItem.sku == candidate,
            )
        )
        if existing is None:
            return candidate


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None
