from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..analytics import percentile
from ..config import PHONE_VARIANTS
from . import models, repository
from .object_store import ObjectStore
from .regions import HONG_KONG_DISTRICTS
from .settings import PlatformSettings


VALID_VARIANTS = {(item.model, item.storage_gb) for item in PHONE_VARIANTS}


class LegacyImportService:
    def __init__(
        self,
        settings: PlatformSettings,
        object_store: ObjectStore | None = None,
    ) -> None:
        self.settings = settings
        self.object_store = object_store

    def import_sqlite(
        self,
        session: Session,
        legacy_path: Path | str,
        *,
        limit_runs: int | None = None,
    ) -> dict[str, int]:
        path = Path(legacy_path)
        if not path.is_file():
            raise FileNotFoundError(f"旧数据库不存在：{path}")

        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            hkd_per_cny = _latest_hkd_per_cny(conn)
            run_query = "SELECT * FROM collection_runs ORDER BY id"
            if limit_runs:
                run_query += " DESC LIMIT ?"
                run_rows = list(
                    reversed(conn.execute(run_query, (int(limit_runs),)).fetchall())
                )
            else:
                run_rows = conn.execute(run_query).fetchall()

            imported_runs = 0
            imported_sources = 0
            imported_listings = 0
            run_dates = {int(row["id"]): row["run_date"] for row in run_rows}
            for run_row in run_rows:
                source_rows = conn.execute(
                    "SELECT * FROM source_runs WHERE run_id=? ORDER BY id",
                    (run_row["id"],),
                ).fetchall()
                for source_row in source_rows:
                    repository.upsert_source_run(
                        session,
                        source_key=source_row["source_key"],
                        external_run_id=str(run_row["id"]),
                        status=source_row["status"],
                        started_at=_parse_datetime(source_row["started_at"]),
                        finished_at=_parse_datetime(source_row["finished_at"]),
                        listing_count=int(source_row["listing_count"] or 0),
                        query_count=int(source_row["query_count"] or 0),
                        error=source_row["error"],
                        metadata={"legacy_run_date": run_row["run_date"]},
                    )
                    imported_sources += 1
                imported_runs += 1

            listing_rows = conn.execute(
                """
                SELECT listings.*, collection_runs.run_date
                FROM listings
                JOIN collection_runs ON collection_runs.id = listings.run_id
                ORDER BY listings.id
                """
            ).fetchall()
            for row in listing_rows:
                if limit_runs and int(row["run_id"]) not in run_dates:
                    continue
                raw = _json_object(row["raw_json"])
                observed_at = _parse_datetime(
                    row["seen_at"]
                    or f"{row['collected_date']}T00:00:00+08:00"
                )
                raw_ref = None
                if self.object_store is not None:
                    key = _raw_capture_key(row["source_key"], row["listing_id"], observed_at)
                    stored = self.object_store.put_json(
                        key,
                        {
                            "legacy_listing_id": row["id"],
                            "source_key": row["source_key"],
                            "source_listing_id": row["listing_id"],
                            "seen_at": observed_at.isoformat(),
                            "raw": raw,
                        },
                    )
                    raw_ref = stored.uri
                    session.add(
                        models.RawCapture(
                            source_key=row["source_key"],
                            listing_id=None,
                            captured_at=observed_at,
                            storage_uri=stored.uri,
                            sha256=stored.sha256,
                            size_bytes=stored.size_bytes,
                            content_type=stored.content_type,
                            expires_at=observed_at
                            + timedelta(
                                days=self.settings.raw_capture_retention_days
                            ),
                            metadata_json={
                                "retention_policy": "raw_capture_short_lived",
                            },
                        )
                    )
                repository.upsert_listing(
                    session,
                    _LegacyListing(
                        row,
                        run_dates.get(int(row["run_id"])),
                        hkd_per_cny=hkd_per_cny,
                    ),
                    observed_at=observed_at,
                    raw_ref=raw_ref,
                )
                imported_listings += 1
            session.flush()
            return {
                "runs": imported_runs,
                "source_runs": imported_sources,
                "listings": imported_listings,
            }
        finally:
            conn.close()


class MarketAnalyticsService:
    def __init__(self, settings: PlatformSettings) -> None:
        self.settings = settings

    def valuation(
        self,
        session: Session,
        *,
        model: str,
        storage_gb: int,
        lookback_days: int = 45,
        target_margin_pct: float | None = None,
    ) -> dict[str, Any]:
        _validate_variant(model, storage_gb)
        margin = (
            self.settings.target_margin_pct
            if target_margin_pct is None
            else float(target_margin_pct)
        )
        if lookback_days < 1 or lookback_days > 365:
            raise ValueError("lookback_days 必须在 1 到 365 之间")
        if margin < 0 or margin > 40:
            raise ValueError("target_margin_pct 必须在 0 到 40 之间")

        rows = repository.comparable_prices(
            session,
            model=model,
            storage_gb=storage_gb,
            lookback_days=lookback_days,
        )
        filtered, rejected = _remove_outliers(rows)
        if len(filtered) < 3:
            return {
                "status": "insufficient_data",
                "method": "hk_comparable_median_v1",
                "market": "香港",
                "model": model,
                "storage_gb": storage_gb,
                "storage_label": repository.storage_label(storage_gb),
                "lookback_days": lookback_days,
                "sample_count": len(filtered),
                "rejected_outliers": rejected,
                "confidence": {
                    "level": "none",
                    "score": 0.0,
                    "reason": "去重后的同款同容量有效样本少于 3 条。",
                },
                "fair_range_hkd": None,
                "guidance_hkd": None,
                "comparables": [],
                "warnings": ["当前样本不足，不生成估值。"],
            }

        prices = [float(row.price_hkd) for row in filtered]
        low = percentile(prices, 0.25) or 0.0
        median = percentile(prices, 0.5) or 0.0
        high = percentile(prices, 0.75) or 0.0
        dispersion = (high - low) / median if median > 0 else 1.0
        confidence_level, confidence_score, reason = _confidence(
            len(filtered),
            dispersion,
        )
        suggested_purchase = low * (1 - margin / 100)
        warnings = [
            "估值基于公开在售要价，不代表真实成交价。",
            "交易前仍需核验成色、电池、保修、激活锁和维修史。",
        ]
        if rejected:
            warnings.append(f"已排除 {rejected} 条极端或疑似错误价格。")
        return {
            "status": "ok",
            "method": "hk_comparable_median_v1",
            "market": "香港",
            "model": model,
            "storage_gb": storage_gb,
            "storage_label": repository.storage_label(storage_gb),
            "lookback_days": lookback_days,
            "sample_count": len(filtered),
            "rejected_outliers": rejected,
            "confidence": {
                "level": confidence_level,
                "score": confidence_score,
                "reason": reason,
            },
            "fair_range_hkd": {
                "low": round(low, 2),
                "mid": round(median, 2),
                "high": round(high, 2),
            },
            "guidance_hkd": {
                "suggested_purchase_max": round(suggested_purchase, 2),
                "suggested_resale": round(median, 2),
                "target_margin_pct": round(margin, 2),
            },
            "dispersion_pct": round(dispersion * 100, 2),
            "comparables": [
                repository._listing_payload(item)
                for item in sorted(
                    filtered,
                    key=lambda item: abs(float(item.price_hkd) - median),
                )[:8]
            ],
            "warnings": warnings,
        }

    def opportunities(
        self,
        session: Session,
        *,
        model: str,
        storage_gb: int,
        limit: int = 20,
        fee_pct: float | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise ValueError("limit 必须在 1 到 100 之间")
        selected_fee = (
            self.settings.opportunity_fee_pct
            if fee_pct is None
            else float(fee_pct)
        )
        if selected_fee < 0 or selected_fee > 40:
            raise ValueError("fee_pct 必须在 0 到 40 之间")
        valuation = self.valuation(
            session,
            model=model,
            storage_gb=storage_gb,
        )
        if valuation["status"] != "ok":
            return {
                "status": valuation["status"],
                "market": "香港",
                "model": model,
                "storage_gb": storage_gb,
                "valuation": valuation,
                "candidates": [],
                "warnings": valuation["warnings"],
            }

        rows = repository.active_variant_listings(
            session,
            model=model,
            storage_gb=storage_gb,
        )
        fair = valuation["fair_range_hkd"]
        median = float(fair["mid"])
        p25 = float(fair["low"])
        sample_count = int(valuation["sample_count"])
        confidence_level = valuation["confidence"]["level"]
        confidence_weight = {"high": 1.0, "medium": 0.75, "low": 0.45}.get(
            confidence_level,
            0.25,
        )
        liquidity_weight = min(
            1.0,
            (sample_count and math.log1p(sample_count) / math.log1p(30))
            or 0.0,
        )
        candidates = []
        for row in rows:
            price = float(row.price_hkd or 0)
            if price <= 0 or median <= 0:
                continue
            gross_spread = median - price
            net_spread = median * (1 - selected_fee / 100) - price
            discount_pct = gross_spread / median * 100
            score = min(
                100.0,
                max(0.0, discount_pct)
                * 1.8
                * confidence_weight
                * liquidity_weight,
            )
            risks: list[str] = []
            if price < p25 * 0.5:
                risks.append("价格显著低于正常区间，需排除故障机或错误解析")
                score = 0.0
            if net_spread <= 0:
                risks.append("扣除预估费用后没有正利润空间")
                score = 0.0
            if score <= 0:
                continue
            payload = repository._listing_payload(row)
            payload.update(
                {
                    "estimated_fair_value_hkd": round(median, 2),
                    "estimated_gross_spread_hkd": round(gross_spread, 2),
                    "estimated_net_spread_hkd": round(net_spread, 2),
                    "discount_pct": round(discount_pct, 2),
                    "opportunity_score": round(score, 1),
                    "priority": (
                        "high"
                        if score >= 60 and not risks
                        else "medium"
                        if score >= 35
                        else "watch"
                    ),
                    "risk_flags": risks,
                }
            )
            candidates.append(payload)
        candidates.sort(
            key=lambda item: (
                item["opportunity_score"],
                item["estimated_net_spread_hkd"],
            ),
            reverse=True,
        )
        return {
            "status": "ok",
            "market": "香港",
            "model": model,
            "storage_gb": storage_gb,
            "fee_pct": selected_fee,
            "valuation": valuation,
            "candidates": candidates[:limit],
            "warnings": [
                "机会评分只用于排序，不构成自动收购建议。",
                "费用比例当前为配置值，接入真实平台费和物流费后应重新校准。",
            ],
        }

    def market_summary(
        self,
        session: Session,
        *,
        model: str | None = None,
        storage_gb: int | None = None,
        district: str | None = None,
        source_key: str | None = None,
    ) -> dict[str, Any]:
        stmt = (
            select(models.Listing)
            .join(models.Listing.variant)
            .options(
                joinedload(models.Listing.variant),
                joinedload(models.Listing.source),
            )
            .where(
                models.Listing.condition == "used",
                models.Listing.listing_status == "active",
                models.Listing.is_public.is_(True),
                repository.public_hk_scope_clause(),
                models.Listing.price_hkd.is_not(None),
                models.Listing.price_hkd > 0,
            )
        )
        if model:
            stmt = stmt.where(models.PhoneVariant.model == model)
        if storage_gb is not None:
            stmt = stmt.where(models.PhoneVariant.storage_gb == storage_gb)
        if district:
            stmt = stmt.where(models.Listing.district == district)
        if source_key:
            stmt = stmt.where(models.Listing.source_key == source_key)
        rows = list(session.scalars(stmt).unique())
        return _summary_payload(
            rows,
            filters={
                "model": model,
                "storage_gb": storage_gb,
                "district": district,
                "source_key": source_key,
            },
        )

    def evaluate_alerts(self, session: Session, *, limit: int = 1000) -> int:
        watchlists = list(
            session.scalars(
                select(models.Watchlist).where(models.Watchlist.active.is_(True))
            )
        )
        created = 0
        for watchlist in watchlists:
            filters = dict(watchlist.filter_json or {})
            page = repository.list_listings(
                session,
                **{
                    key: filters.get(key)
                    for key in (
                        "query",
                        "model",
                        "storage_gb",
                        "district",
                        "source_key",
                        "min_price",
                        "max_price",
                    )
                },
                condition="used",
                listing_status="active",
                limit=min(limit, 100),
            )
            for listing_payload in page["items"]:
                exists = session.scalar(
                    select(models.Alert.id).where(
                        models.Alert.watchlist_id == watchlist.id,
                        models.Alert.listing_id == listing_payload["id"],
                        models.Alert.alert_type == "watchlist_match",
                    )
                )
                if exists:
                    continue
                session.add(
                    models.Alert(
                        watchlist_id=watchlist.id,
                        listing_id=listing_payload["id"],
                        alert_type="watchlist_match",
                        status=(
                            "pending"
                            if (watchlist.notification_json or {}).get("enabled")
                            else "recorded"
                        ),
                        payload={
                            "title": listing_payload["title"],
                            "price_hkd": listing_payload["price_hkd"],
                        },
                    )
                )
                created += 1
        session.flush()
        return created

    def refresh_valuations(
        self,
        session: Session,
        *,
        lookback_days: int = 45,
    ) -> int:
        variants = list(
            session.scalars(
                select(models.PhoneVariant)
                .join(models.Listing)
                .where(
                    models.Listing.condition == "used",
                    models.Listing.listing_status == "active",
                    models.Listing.is_public.is_(True),
                    models.Listing.price_hkd.is_not(None),
                    models.Listing.price_hkd > 0,
                )
                .distinct()
                .order_by(models.PhoneVariant.model, models.PhoneVariant.storage_gb)
            )
        )
        count = 0
        for variant in variants:
            payload = self.valuation(
                session,
                model=variant.model,
                storage_gb=variant.storage_gb,
                lookback_days=lookback_days,
            )
            payload["as_of_date"] = repository.utc_now().date().isoformat()
            repository.save_valuation(session, payload)
            count += 1
        return count


def _summary_payload(
    rows: Sequence[models.Listing],
    *,
    filters: Mapping[str, Any],
) -> dict[str, Any]:
    prices = [float(row.price_hkd) for row in rows if row.price_hkd is not None]
    district_groups = _group_metrics(rows, lambda row: row.district or "未標示")
    variant_groups = _group_metrics(
        rows,
        lambda row: (
            f"{row.variant.model}:{row.variant.storage_gb}"
            if row.variant
            else "unknown"
        ),
    )
    source_groups = _group_metrics(
        rows,
        lambda row: row.source_key,
    )
    supply_by_district = [
        {
            "district": district,
            "count": district_groups.get(district, {}).get("count", 0),
        }
        for district in HONG_KONG_DISTRICTS
    ]
    return {
        "as_of": repository.utc_now(),
        "filters": dict(filters),
        "metrics": _metrics(prices),
        "source_count": len({row.source_key for row in rows}),
        "district_coverage": len(
            {row.district for row in rows if row.district in HONG_KONG_DISTRICTS}
        ),
        "supply_by_district": supply_by_district,
        "by_district": [
            {"key": key, **metrics} for key, metrics in district_groups.items()
        ],
        "by_variant": [
            {"key": key, **metrics} for key, metrics in variant_groups.items()
        ],
        "by_source": [
            {"key": key, **metrics} for key, metrics in source_groups.items()
        ],
    }


def _group_metrics(
    rows: Sequence[models.Listing],
    key_fn,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.price_hkd is not None:
            grouped[str(key_fn(row))].append(float(row.price_hkd))
    return {key: _metrics(values) for key, values in grouped.items()}


def _metrics(values: Sequence[float]) -> dict[str, Any]:
    prices = [float(value) for value in values]
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


def _remove_outliers(
    rows: Sequence[models.Listing],
) -> tuple[list[models.Listing], int]:
    retained = list(rows)
    rejected_total = 0
    for _ in range(3):
        prices = [float(row.price_hkd) for row in retained]
        median = percentile(prices, 0.5)
        if median is None or median <= 0 or len(retained) < 8:
            break
        deviations = [abs(price - median) for price in prices]
        mad = percentile(deviations, 0.5) or 0.0
        scale = 1.4826 * mad
        if scale <= 0:
            low = percentile(prices, 0.25) or 0.0
            high = percentile(prices, 0.75) or 0.0
            scale = (high - low) / 1.349
        if scale <= 0:
            break
        lower = max(0.01, median - 3 * scale)
        upper = median + 3 * scale
        next_rows = [
            row for row in retained if lower <= float(row.price_hkd) <= upper
        ]
        if len(next_rows) == len(retained):
            break
        rejected_total += len(retained) - len(next_rows)
        retained = next_rows
    return retained, rejected_total


def _confidence(sample_count: int, dispersion: float) -> tuple[str, float, str]:
    if sample_count >= 20 and dispersion <= 0.35:
        return "high", 0.9, "样本量充足，同款价格集中。"
    if sample_count >= 8 and dispersion <= 0.6:
        return "medium", 0.7, "样本量可用，但价格存在一定离散。"
    if sample_count >= 5 and dispersion <= 0.8:
        return "medium", 0.55, "样本量偏少，建议人工复核。"
    return "low", 0.35, "样本量不足或价格波动较大。"


def _validate_variant(model: str, storage_gb: int) -> None:
    if (model, int(storage_gb)) not in VALID_VARIANTS:
        raise ValueError(f"{model} 不支持 {repository.storage_label(storage_gb)}")


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return repository.utc_now()
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return repository.as_utc(parsed) or repository.utc_now()


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _raw_capture_key(
    source_key: str,
    source_listing_id: str,
    observed_at: datetime,
) -> str:
    digest = hashlib.sha1(source_listing_id.encode("utf-8")).hexdigest()[:20]
    return (
        f"{source_key}/{observed_at:%Y/%m/%d}/"
        f"{observed_at:%H%M%S}-{digest}.json"
    )


class _LegacyListing:
    def __init__(
        self,
        row: sqlite3.Row,
        collected_date: str | None = None,
        *,
        hkd_per_cny: Decimal | None = None,
    ) -> None:
        self.source_key = row["source_key"]
        self.source_name = row["source_name"]
        self.market = row["market"]
        self.listing_id = row["listing_id"]
        self.title = row["title"]
        self.url = row["url"]
        self.model = row["model"]
        self.generation = row["generation"]
        self.family = row["family"]
        self.storage_gb = row["storage_gb"]
        self.condition = row["condition"]
        self.listing_status = row["listing_status"]
        self.price_native = (
            Decimal(str(row["price_native"])) if row["price_native"] is not None else None
        )
        self.currency = row["currency"]
        self.price_cny = (
            Decimal(str(row["price_cny"])) if row["price_cny"] is not None else None
        )
        self.price_hkd = _legacy_hkd_price(
            self.currency,
            self.price_native,
            self.price_cny,
            hkd_per_cny=hkd_per_cny,
        )
        self.fx_date = row["fx_date"]
        self.location = row["location"]
        self.raw = _json_object(row["raw_json"])
        self.collected_date = row["collected_date"] or collected_date
        self.seen_at = row["seen_at"]


def _legacy_hkd_price(
    currency: str,
    price_native: Decimal | None,
    price_cny: Decimal | None,
    *,
    hkd_per_cny: Decimal | None,
) -> Decimal | None:
    if currency == "HKD":
        return price_native
    if price_cny is None or hkd_per_cny is None:
        return None
    return (price_cny * hkd_per_cny).quantize(Decimal("0.01"))


def _latest_hkd_per_cny(conn: sqlite3.Connection) -> Decimal | None:
    try:
        row = conn.execute(
            "SELECT rates_json FROM fx_rates ORDER BY rate_date DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    try:
        rates = json.loads(row["rates_json"])
        hkd_per_cny = Decimal(str(rates["HKD"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if hkd_per_cny <= 0:
        return None
    return Decimal("1") / hkd_per_cny
