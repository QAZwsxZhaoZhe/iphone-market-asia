from __future__ import annotations

import base64
import hashlib
import json
import math
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..analytics import percentile
from ..config import PHONE_VARIANTS, SOURCES
from . import models
from .regions import HONG_KONG_DISTRICTS, normalize_district


CONDITIONS = ("used", "new", "broken", "accessory", "wanted", "rental")
LISTING_STATUSES = ("active", "sold", "stale", "removed", "unknown")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def variant_id(model: str, storage_gb: int) -> str:
    return f"{model}:{storage_gb}"


def storage_label(storage_gb: int) -> str:
    if storage_gb == 1024:
        return "1TB"
    if storage_gb == 2048:
        return "2TB"
    return f"{storage_gb}GB"


def normalize_search_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower().strip()
    replacements = str.maketrans(
        {
            "區": "区",
            "東": "东",
            "觀": "观",
            "灣": "湾",
            "黃": "黄",
            "龍": "龙",
            "離": "离",
            "門": "门",
            "荃": "荃",
            "號": "号",
            "臺": "台",
            "台": "台",
        }
    )
    return " ".join(text.translate(replacements).split())


def ensure_reference_data(session: Session) -> None:
    for spec in SOURCES:
        source = session.get(models.Source, spec.key)
        if source is None:
            source = models.Source(
                key=spec.key,
                name=spec.name,
                market=spec.market,
                currency=spec.currency,
                base_url=spec.base_url,
                requires_login=spec.requires_login,
                active=spec.market == "香港",
            )
            session.add(source)
        else:
            source.name = spec.name
            source.market = spec.market
            source.currency = spec.currency
            source.base_url = spec.base_url
            source.requires_login = spec.requires_login
            if spec.market == "香港":
                source.active = True

    for item in PHONE_VARIANTS:
        key = variant_id(item.model, item.storage_gb)
        variant = session.get(models.PhoneVariant, key)
        if variant is None:
            variant = models.PhoneVariant(
                id=key,
                model=item.model,
                generation=item.generation,
                family=item.family,
                storage_gb=item.storage_gb,
                storage_label=item.storage_label,
                aliases=[
                    item.model.lower(),
                    f"{item.generation} {item.family.lower()}",
                    f"{item.model} {item.storage_label}".lower(),
                ],
            )
            session.add(variant)
    session.flush()


def upsert_listing(
    session: Session,
    record: Any,
    *,
    observed_at: datetime | None = None,
    raw_ref: str | None = None,
    price_hkd: float | Decimal | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> models.Listing:
    listing, _snapshot_created = upsert_listing_observation(
        session,
        record,
        observed_at=observed_at,
        raw_ref=raw_ref,
        price_hkd=price_hkd,
        metadata=metadata,
    )
    return listing


def upsert_listing_observation(
    session: Session,
    record: Any,
    *,
    observed_at: datetime | None = None,
    raw_ref: str | None = None,
    price_hkd: float | Decimal | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[models.Listing, bool]:
    ensure_reference_data(session)
    source_key = str(_value(record, "source_key"))
    source_listing_id = str(_value(record, "listing_id"))
    model = str(_value(record, "model"))
    storage_gb = int(_value(record, "storage_gb"))
    selected_variant_id = variant_id(model, storage_gb)
    if session.get(models.PhoneVariant, selected_variant_id) is None:
        raise ValueError(f"不支持的机型容量：{model} {storage_gb}GB")

    observed = as_utc(observed_at or _datetime_value(record, "seen_at") or utc_now())
    assert observed is not None
    collected_date = str(_value(record, "collected_date", observed.date().isoformat()))
    title = str(_value(record, "title"))
    url = str(_value(record, "url"))
    condition = str(_value(record, "condition", "used"))
    listing_status = str(_value(record, "listing_status", "active"))
    location_raw = _optional_value(record, "location")
    district = normalize_district(location_raw)
    price_native = _decimal_or_none(_value(record, "price_native", None))
    currency = str(_value(record, "currency", "HKD")).upper()
    normalized_hkd = _decimal_or_none(price_hkd)
    if normalized_hkd is None:
        normalized_hkd = _legacy_hkd_price(record, price_native, currency)
    raw = dict(_value(record, "raw", {}) or {})
    raw.update(dict(metadata or {}))
    fx_date = _optional_value(record, "fx_date")

    listing = session.scalar(
        select(models.Listing).where(
            models.Listing.source_key == source_key,
            models.Listing.source_listing_id == source_listing_id,
        )
    )
    search_text = normalize_search_text(
        " ".join(
            [
                title,
                model,
                storage_label(storage_gb),
                source_key,
                district or "",
                location_raw or "",
            ]
        )
    )
    if listing is None:
        listing = models.Listing(
            source_key=source_key,
            source_listing_id=source_listing_id,
            phone_variant_id=selected_variant_id,
            title=title,
            url=url,
            condition=condition,
            listing_status=listing_status,
            district=district,
            location_raw=location_raw,
            first_seen_at=observed,
            last_seen_at=observed,
            price_native=price_native,
            currency=currency,
            price_hkd=normalized_hkd,
            fx_date=fx_date,
            is_public=condition == "used",
            raw_metadata=raw,
            search_text=search_text,
        )
        session.add(listing)
        session.flush()
    else:
        listing.phone_variant_id = selected_variant_id
        listing.title = title
        listing.url = url
        listing.condition = condition
        listing.listing_status = listing_status
        listing.district = district or listing.district
        listing.location_raw = location_raw or listing.location_raw
        listing.price_native = price_native
        listing.currency = currency
        listing.price_hkd = normalized_hkd
        listing.fx_date = fx_date or listing.fx_date
        listing.last_seen_at = max(observed, as_utc(listing.last_seen_at) or observed)
        listing.raw_metadata = {**listing.raw_metadata, **raw}
        listing.search_text = search_text
        listing.is_public = condition == "used"

    observation_key = hashlib.sha1(
        (
            f"{source_key}|{source_listing_id}|{observed.isoformat()}|"
            f"{price_native}|{listing_status}"
        ).encode("utf-8")
    ).hexdigest()
    snapshot = session.scalar(
        select(models.ListingSnapshot).where(
            models.ListingSnapshot.observation_key == observation_key
        )
    )
    snapshot_created = snapshot is None
    if snapshot_created:
        session.add(
            models.ListingSnapshot(
                listing_id=listing.id,
                source_key=source_key,
                observation_key=observation_key,
                collected_date=collected_date,
                observed_at=observed,
                status=listing_status,
                condition=condition,
                district=district,
                price_native=price_native,
                currency=currency,
                price_hkd=normalized_hkd,
                raw_ref=raw_ref,
                metadata_json=raw,
            )
        )
    session.flush()
    return listing, snapshot_created


def upsert_listings(
    session: Session,
    records: Iterable[Any],
    *,
    observed_at: datetime | None = None,
) -> int:
    count = 0
    for record in records:
        upsert_listing(session, record, observed_at=observed_at)
        count += 1
    return count


def upsert_source_run(
    session: Session,
    *,
    source_key: str,
    external_run_id: str,
    status: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    listing_count: int = 0,
    query_count: int = 0,
    error: str | None = None,
    attempt: int = 1,
    metadata: Mapping[str, Any] | None = None,
) -> models.SourceRun:
    ensure_reference_data(session)
    run = session.scalar(
        select(models.SourceRun).where(
            models.SourceRun.source_key == source_key,
            models.SourceRun.external_run_id == external_run_id,
        )
    )
    if run is None:
        run = models.SourceRun(
            source_key=source_key,
            external_run_id=external_run_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            listing_count=listing_count,
            query_count=query_count,
            error=error,
            attempt=attempt,
            metadata_json=dict(metadata or {}),
        )
        session.add(run)
    else:
        run.status = status
        run.started_at = started_at
        run.finished_at = finished_at
        run.listing_count = listing_count
        run.query_count = query_count
        run.error = error
        run.attempt = attempt
        run.metadata_json = {**run.metadata_json, **dict(metadata or {})}

    if status in {"ok", "partial"}:
        source = session.get(models.Source, source_key)
        if source is not None:
            source.last_success_at = finished_at or started_at
    session.flush()
    return run


def list_listings(
    session: Session,
    *,
    query: str | None = None,
    model: str | None = None,
    storage_gb: int | None = None,
    district: str | None = None,
    source_key: str | None = None,
    condition: str = "used",
    listing_status: str | None = "active",
    min_price: float | None = None,
    max_price: float | None = None,
    fresh_within_hours: int | None = None,
    listing_ids: Sequence[int] | None = None,
    include_internal: bool = False,
    cursor: str | None = None,
    limit: int = 30,
    max_limit: int = 100,
) -> dict[str, Any]:
    selected_limit = max(1, min(int(limit), max_limit))
    decoded_cursor = decode_cursor(cursor)
    if decoded_cursor is not None:
        left = (
            select(models.Listing)
            .join(models.PhoneVariant)
            .where(models.Listing.id < decoded_cursor)
        )
    else:
        left = select(models.Listing).join(models.PhoneVariant)

    clause = _listing_filters(
        query=query,
        model=model,
        storage_gb=storage_gb,
        district=district,
        source_key=source_key,
        condition=condition,
        listing_status=listing_status,
        min_price=min_price,
        max_price=max_price,
        fresh_within_hours=fresh_within_hours,
        listing_ids=listing_ids,
        include_internal=include_internal,
    )
    if clause is not None:
        left = left.where(clause)
    left = left.order_by(models.Listing.id.desc()).limit(selected_limit + 1)
    stmt = _with_listing_relations(left)
    rows = list(session.scalars(stmt).unique())
    has_more = len(rows) > selected_limit
    rows = rows[:selected_limit]

    count_left = select(models.Listing).join(models.PhoneVariant)
    if decoded_cursor is not None:
        count_left = count_left.where(models.Listing.id < decoded_cursor)
    if clause is not None:
        count_left = count_left.where(clause)
    total = int(
        session.scalar(
            select(func.count()).select_from(count_left.order_by(None).subquery())
        )
        or 0
    )
    next_cursor = encode_cursor(rows[-1].id) if has_more and rows else None
    return {
        "items": [_listing_payload(row) for row in rows],
        "next_cursor": next_cursor,
        "total": total,
        "limit": selected_limit,
    }


def get_listing(
    session: Session,
    listing_id: int,
    *,
    include_internal: bool = False,
) -> models.Listing | None:
    stmt = select(models.Listing).where(models.Listing.id == listing_id)
    if not include_internal:
        stmt = stmt.where(
            models.Listing.is_public.is_(True),
            models.Listing.condition == "used",
            public_hk_scope_clause(),
        )
    return session.scalar(_with_listing_relations(stmt))


def cluster_id_for_listing(session: Session, listing_id: int) -> int | None:
    return session.scalar(
        select(models.ListingClusterMember.cluster_id).where(
            models.ListingClusterMember.listing_id == listing_id
        )
    )


def listing_history(
    session: Session,
    listing_id: int,
    *,
    limit: int = 180,
) -> list[models.ListingSnapshot]:
    selected_limit = max(1, min(limit, 1000))
    return list(
        session.scalars(
            select(models.ListingSnapshot)
            .where(models.ListingSnapshot.listing_id == listing_id)
            .order_by(models.ListingSnapshot.observed_at.desc())
            .limit(selected_limit)
        )
    )


def source_health(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = as_utc(now or utc_now()) or utc_now()
    sources = list(
        session.scalars(
            select(models.Source)
            .where(models.Source.market == "香港")
            .order_by(models.Source.name)
        )
    )
    output = []
    for source in sources:
        latest_run = session.scalar(
            select(models.SourceRun)
            .where(models.SourceRun.source_key == source.key)
            .order_by(models.SourceRun.started_at.desc(), models.SourceRun.id.desc())
            .limit(1)
        )
        active_count = int(
            session.scalar(
                select(func.count(models.Listing.id)).where(
                    models.Listing.source_key == source.key,
                    models.Listing.listing_status == "active",
                    models.Listing.is_public.is_(True),
                )
            )
            or 0
        )
        success_at = as_utc(source.last_success_at)
        output.append(
            {
                "source_key": source.key,
                "source_name": source.name,
                "market": source.market,
                "active": source.active,
                "status": latest_run.status if latest_run else "missing",
                "listing_count": latest_run.listing_count if latest_run else 0,
                "active_listing_count": active_count,
                "query_count": latest_run.query_count if latest_run else 0,
                "error": latest_run.error if latest_run else None,
                "started_at": latest_run.started_at if latest_run else None,
                "finished_at": latest_run.finished_at if latest_run else None,
                "last_success_at": success_at,
                "freshness_seconds": (
                    max(0, int((current - success_at).total_seconds()))
                    if success_at
                    else None
                ),
                "cadence_seconds": source.cadence_seconds,
            }
        )
    return output


def recent_runs(
    session: Session,
    *,
    source_key: str | None = None,
    limit: int = 50,
) -> list[models.SourceRun]:
    stmt = select(models.SourceRun)
    if source_key:
        stmt = stmt.where(models.SourceRun.source_key == source_key)
    return list(
        session.scalars(
            stmt.order_by(models.SourceRun.started_at.desc()).limit(
                max(1, min(limit, 200))
            )
        )
    )


def recent_valuations(
    session: Session,
    *,
    model: str | None = None,
    storage_gb: int | None = None,
    limit: int = 50,
) -> list[models.Valuation]:
    stmt = select(models.Valuation)
    if model:
        stmt = stmt.where(models.Valuation.model == model)
    if storage_gb is not None:
        stmt = stmt.where(models.Valuation.storage_gb == int(storage_gb))
    return list(
        session.scalars(
            stmt.order_by(
                models.Valuation.as_of_date.desc(),
                models.Valuation.id.desc(),
            ).limit(max(1, min(limit, 200)))
        )
    )


def save_valuation(
    session: Session,
    payload: Mapping[str, Any],
) -> models.Valuation:
    market = str(payload.get("market") or "香港")
    model = str(payload["model"])
    storage_gb = int(payload["storage_gb"])
    as_of_date = str(payload.get("as_of_date") or utc_now().date().isoformat())
    method = str(payload.get("method") or "unknown")
    row = session.scalar(
        select(models.Valuation).where(
            models.Valuation.market == market,
            models.Valuation.model == model,
            models.Valuation.storage_gb == storage_gb,
            models.Valuation.as_of_date == as_of_date,
            models.Valuation.method == method,
        )
    )
    fair = payload.get("fair_range_hkd") or {}
    guidance = payload.get("guidance_hkd") or {}
    confidence = payload.get("confidence") or {}
    values = {
        "status": str(payload.get("status") or "unknown"),
        "fair_low_hkd": _decimal_or_none(fair.get("low")),
        "fair_mid_hkd": _decimal_or_none(fair.get("mid")),
        "fair_high_hkd": _decimal_or_none(fair.get("high")),
        "suggested_purchase_hkd": _decimal_or_none(
            guidance.get("suggested_purchase_max")
        ),
        "suggested_resale_hkd": _decimal_or_none(
            guidance.get("suggested_resale")
        ),
        "confidence_level": str(confidence.get("level") or "none"),
        "sample_count": int(payload.get("sample_count") or 0),
        "payload": _json_safe(dict(payload)),
    }
    if row is None:
        row = models.Valuation(
            market=market,
            model=model,
            storage_gb=storage_gb,
            as_of_date=as_of_date,
            method=method,
            **values,
        )
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return row


def comparable_prices(
    session: Session,
    *,
    model: str,
    storage_gb: int,
    as_of_date: str | None = None,
    lookback_days: int = 45,
) -> list[models.Listing]:
    end_date = (
        datetime.fromisoformat(as_of_date).date()
        if as_of_date
        else (utc_now().date())
    )
    cutoff = end_date - timedelta(days=max(1, lookback_days))
    stmt = (
        select(models.Listing)
        .join(models.PhoneVariant)
        .where(
            models.PhoneVariant.model == model,
            models.PhoneVariant.storage_gb == storage_gb,
            models.Listing.condition == "used",
            models.Listing.listing_status == "active",
            models.Listing.is_public.is_(True),
            public_hk_scope_clause(),
            models.Listing.price_hkd.is_not(None),
            models.Listing.price_hkd > 0,
            models.Listing.last_seen_at >= datetime.combine(
                cutoff,
                datetime.min.time(),
                tzinfo=timezone.utc,
            ),
        )
        .order_by(models.Listing.price_hkd)
    )
    return list(session.scalars(_with_listing_relations(stmt)).unique())


def active_variant_listings(
    session: Session,
    *,
    model: str,
    storage_gb: int,
) -> list[models.Listing]:
    stmt = (
        select(models.Listing)
        .join(models.PhoneVariant)
        .where(
            models.PhoneVariant.model == model,
            models.PhoneVariant.storage_gb == storage_gb,
            models.Listing.condition == "used",
            models.Listing.listing_status == "active",
            models.Listing.is_public.is_(True),
            public_hk_scope_clause(),
            models.Listing.price_hkd.is_not(None),
            models.Listing.price_hkd > 0,
        )
        .order_by(models.Listing.price_hkd)
    )
    return list(session.scalars(_with_listing_relations(stmt)).unique())


def mark_stale_listings(session: Session, *, stale_hours: int = 36) -> int:
    cutoff = utc_now() - timedelta(hours=max(1, stale_hours))
    result = session.execute(
        models.Listing.__table__.update()
        .where(
            models.Listing.listing_status == "active",
            models.Listing.last_seen_at < cutoff,
        )
        .values(listing_status="stale", updated_at=utc_now())
    )
    return int(result.rowcount or 0)


def rebuild_clusters(session: Session) -> int:
    session.execute(delete(models.ListingClusterMember))
    session.execute(delete(models.ListingCluster))
    session.flush()
    listings = list(
        session.scalars(
            select(models.Listing)
            .options(joinedload(models.Listing.variant), joinedload(models.Listing.source))
            .where(
                models.Listing.listing_status == "active",
                models.Listing.is_public.is_(True),
                public_hk_scope_clause(),
                models.Listing.price_hkd.is_not(None),
                models.Listing.price_hkd > 0,
            )
        ).unique()
    )
    buckets: dict[tuple[str, str], list[models.Listing]] = defaultdict(list)
    for listing in listings:
        buckets[(listing.phone_variant_id, listing.district or "unknown")].append(listing)

    cluster_count = 0
    for candidates in buckets.values():
        candidates.sort(key=lambda item: float(item.price_hkd or 0))
        groups: list[list[models.Listing]] = []
        for listing in candidates:
            placed = False
            for group in reversed(groups):
                reference = group[0]
                reference_price = float(reference.price_hkd or 0)
                current_price = float(listing.price_hkd or 0)
                if reference_price <= 0:
                    continue
                if abs(current_price - reference_price) / reference_price > 0.03:
                    continue
                if SequenceMatcher(
                    None,
                    _title_tokens(listing.title),
                    _title_tokens(reference.title),
                ).ratio() < 0.35:
                    continue
                group.append(listing)
                placed = True
                break
            if not placed:
                groups.append([listing])

        for group in groups:
            if len({item.source_key for item in group}) < 2:
                continue
            identity = "|".join(
                sorted(f"{item.source_key}:{item.source_listing_id}" for item in group)
            )
            cluster_key = hashlib.sha1(identity.encode("utf-8")).hexdigest()
            cluster = models.ListingCluster(
                cluster_key=cluster_key,
                reason="same_variant_district_price_window",
            )
            session.add(cluster)
            session.flush()
            for item in group:
                session.add(
                    models.ListingClusterMember(
                        cluster_id=cluster.id,
                        listing_id=item.id,
                    )
                )
            cluster_count += 1
    session.flush()
    return cluster_count


def cluster_memberships(session: Session) -> dict[int, int]:
    return {
        int(listing_id): int(cluster_id)
        for listing_id, cluster_id in session.execute(
            select(
                models.ListingClusterMember.listing_id,
                models.ListingClusterMember.cluster_id,
            )
        )
    }


def record_audit(
    session: Session,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> models.AuditLog:
    item = models.AuditLog(
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=dict(details or {}),
    )
    session.add(item)
    session.flush()
    return item


def audit_entries(session: Session, *, limit: int = 100) -> list[models.AuditLog]:
    return list(
        session.scalars(
            select(models.AuditLog)
            .order_by(models.AuditLog.id.desc())
            .limit(max(1, min(limit, 500)))
        )
    )


def dead_letters(session: Session, *, limit: int = 100) -> list[models.DeadLetterTask]:
    return list(
        session.scalars(
            select(models.DeadLetterTask)
            .order_by(models.DeadLetterTask.id.desc())
            .limit(max(1, min(limit, 500)))
        )
    )


def raw_captures(
    session: Session,
    *,
    listing_id: int | None = None,
    source_key: str | None = None,
    limit: int = 100,
) -> list[models.RawCapture]:
    stmt = select(models.RawCapture)
    if listing_id is not None:
        stmt = stmt.where(models.RawCapture.listing_id == listing_id)
    if source_key:
        stmt = stmt.where(models.RawCapture.source_key == source_key)
    return list(
        session.scalars(
            stmt.order_by(models.RawCapture.id.desc()).limit(
                max(1, min(limit, 500))
            )
        )
    )


def expired_raw_captures(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = 1000,
) -> list[models.RawCapture]:
    current = as_utc(now or utc_now()) or utc_now()
    return list(
        session.scalars(
            select(models.RawCapture)
            .where(
                models.RawCapture.expires_at.is_not(None),
                models.RawCapture.expires_at <= current,
            )
            .order_by(models.RawCapture.expires_at)
            .limit(max(1, min(limit, 5000)))
        )
    )


def encode_cursor(listing_id: int) -> str:
    payload = json.dumps({"id": int(listing_id)}, separators=(",", ":")).encode(
        "utf-8"
    )
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> int | None:
    if not cursor:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        )
        value = int(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ValueError("cursor 无效") from None
    if value < 1:
        raise ValueError("cursor 无效")
    return value


def _with_listing_relations(stmt: Select) -> Select:
    return stmt.options(
        joinedload(models.Listing.source),
        joinedload(models.Listing.variant),
    )


def public_hk_scope_clause():
    return models.Listing.source.has(
        and_(
            models.Source.market == "香港",
            models.Source.active.is_(True),
        )
    )


def _listing_filters(
    *,
    query: str | None,
    model: str | None,
    storage_gb: int | None,
    district: str | None,
    source_key: str | None,
    condition: str,
    listing_status: str | None,
    min_price: float | None,
    max_price: float | None,
    fresh_within_hours: int | None,
    listing_ids: Sequence[int] | None,
    include_internal: bool,
):
    clauses = []
    if not include_internal:
        clauses.extend(
            [
                models.Listing.is_public.is_(True),
                models.Listing.condition == condition,
                public_hk_scope_clause(),
            ]
        )
    elif condition:
        clauses.append(models.Listing.condition == condition)
    if listing_status:
        clauses.append(models.Listing.listing_status == listing_status)
    if model:
        clauses.append(models.PhoneVariant.model == model)
    if storage_gb is not None:
        clauses.append(models.PhoneVariant.storage_gb == storage_gb)
    if district:
        clauses.append(models.Listing.district == district)
    if source_key:
        clauses.append(models.Listing.source_key == source_key)
    if min_price is not None:
        clauses.append(models.Listing.price_hkd >= min_price)
    if max_price is not None:
        clauses.append(models.Listing.price_hkd <= max_price)
    if fresh_within_hours is not None:
        cutoff = utc_now() - timedelta(hours=max(1, fresh_within_hours))
        clauses.append(models.Listing.last_seen_at >= cutoff)
    if listing_ids is not None:
        ids = [int(item) for item in listing_ids]
        clauses.append(models.Listing.id.in_(ids or [-1]))
    if query:
        normalized = normalize_search_text(query)
        pattern = f"%{normalized}%"
        clauses.append(
            or_(
                func.lower(models.Listing.search_text).like(pattern),
                func.lower(models.Listing.title).like(pattern),
                func.lower(models.PhoneVariant.model).like(pattern),
                func.lower(func.coalesce(models.Listing.district, "")).like(pattern),
            )
        )
    if not clauses:
        return None
    return and_(*clauses)


def _listing_payload(
    listing: models.Listing,
    *,
    cluster_id: int | None = None,
) -> dict[str, Any]:
    source = listing.source
    variant = listing.variant
    last_seen = as_utc(listing.last_seen_at)
    freshness_seconds = (
        max(0, int((utc_now() - last_seen).total_seconds()))
        if last_seen
        else None
    )
    return {
        "id": int(listing.id),
        "source_key": listing.source_key,
        "source_name": source.name if source else listing.source_key,
        "source_listing_id": listing.source_listing_id,
        "title": listing.title,
        "url": listing.url,
        "model": variant.model if variant else None,
        "generation": variant.generation if variant else None,
        "family": variant.family if variant else None,
        "storage_gb": variant.storage_gb if variant else None,
        "storage_label": variant.storage_label if variant else None,
        "condition": listing.condition,
        "listing_status": listing.listing_status,
        "district": listing.district,
        "location": listing.location_raw,
        "price_native": _float_or_none(listing.price_native),
        "currency": listing.currency,
        "price_hkd": _float_or_none(listing.price_hkd),
        "fx_date": listing.fx_date,
        "valuation_hkd": _float_or_none(listing.valuation_hkd),
        "valuation_low_hkd": _float_or_none(listing.valuation_low_hkd),
        "valuation_high_hkd": _float_or_none(listing.valuation_high_hkd),
        "valuation_confidence": listing.valuation_confidence,
        "first_seen_at": as_utc(listing.first_seen_at),
        "last_seen_at": last_seen,
        "freshness_seconds": freshness_seconds,
        "is_public": listing.is_public,
        "cluster_id": cluster_id,
    }


def _legacy_hkd_price(
    record: Any,
    price_native: Decimal | None,
    currency: str,
) -> Decimal | None:
    explicit = _decimal_or_none(_value(record, "price_hkd", None))
    if explicit is not None:
        return explicit
    if currency == "HKD":
        return price_native
    price_cny = _decimal_or_none(_value(record, "price_cny", None))
    return price_cny


def _title_tokens(value: str) -> str:
    text = normalize_search_text(value)
    for token in (
        "iphone",
        "apple",
        "pro",
        "max",
        "used",
        "全新",
        "二手",
        "gb",
        "tb",
    ):
        text = text.replace(token, " ")
    return "".join(character for character in text if character.isalnum())


def _value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _optional_value(record: Any, name: str) -> str | None:
    value = _value(record, name, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime_value(record: Any, name: str) -> datetime | None:
    value = _value(record, name, None)
    if value is None:
        return None
    if isinstance(value, datetime):
        return as_utc(value)
    try:
        return as_utc(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


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


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _price_metrics(values: Sequence[float]) -> dict[str, Any]:
    prices = [float(value) for value in values if value is not None]
    if not prices:
        return {
            "count": 0,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "max": None,
        }
    return {
        "count": len(prices),
        "min": round(min(prices), 2),
        "p25": round(percentile(prices, 0.25) or 0.0, 2),
        "median": round(percentile(prices, 0.5) or 0.0, 2),
        "p75": round(percentile(prices, 0.75) or 0.0, 2),
        "max": round(max(prices), 2),
    }
