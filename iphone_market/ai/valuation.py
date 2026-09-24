from __future__ import annotations

import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .. import db
from ..analytics import percentile
from ..config import ACTIVE_MARKET_ORDER, ACTIVE_SOURCE_KEYS, DB_PATH, PHONE_VARIANTS
from ..fx import load_cached_rates


DEFAULT_LOOKBACK_DAYS = 45
DEFAULT_TARGET_MARGIN_PCT = 12.0
MODEL_METHOD = "comparable_median_v1"

_VALID_VARIANTS = {(item.model, item.storage_gb) for item in PHONE_VARIANTS}
_CURRENCY_BY_MARKET = {"香港": "HKD", "新加坡": "SGD", "日本": "JPY", "深圳": "CNY"}


def normalize_model(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", str(value).lower())
    if compact.startswith("iphone"):
        compact = compact[6:]
    match = re.fullmatch(r"(1[4-7])(pro|promax)", compact)
    if match is None:
        raise ValueError("机型必须是 iPhone 14/15/16/17 的 Pro 或 Pro Max")
    generation, family_key = match.groups()
    family = "Pro Max" if family_key == "promax" else "Pro"
    return f"iPhone {generation} {family}"


def normalize_storage_gb(value: int | str) -> int:
    raw = str(value).strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)(gb|g|tb|t)?", raw)
    if match is None:
        raise ValueError("容量格式无效，支持 256GB、512GB、1TB、2TB")
    amount = int(match.group(1))
    unit = match.group(2) or ""
    if unit in {"tb", "t"} and amount in {1, 2}:
        return amount * 1024
    if amount in {128, 256, 512, 1024, 2048}:
        return amount
    raise ValueError("容量必须是 128GB、256GB、512GB、1TB 或 2TB")


def estimate_valuation(
    *,
    model: str,
    storage_gb: int | str,
    market: str = ACTIVE_MARKET_ORDER[0],
    as_of_date: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    target_margin_pct: float = DEFAULT_TARGET_MARGIN_PCT,
    comparable_limit: int = 8,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any]:
    normalized_model = normalize_model(model)
    normalized_storage = normalize_storage_gb(storage_gb)
    if (normalized_model, normalized_storage) not in _VALID_VARIANTS:
        raise ValueError(f"{normalized_model} 不支持该容量")
    if market not in _CURRENCY_BY_MARKET:
        raise ValueError(f"不支持的市场：{market}")
    if lookback_days < 1 or lookback_days > 365:
        raise ValueError("lookback_days 必须在 1 到 365 之间")
    if target_margin_pct < 0 or target_margin_pct > 40:
        raise ValueError("target_margin_pct 必须在 0 到 40 之间")

    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        target_date = as_of_date or _latest_active_date(conn, market)
        if target_date is None:
            return _empty_result(
                status="no_data",
                model=normalized_model,
                storage_gb=normalized_storage,
                market=market,
                message="数据库中没有可用于估值的香港在售样本。",
            )

        cutoff_date = (
            date.fromisoformat(target_date) - timedelta(days=lookback_days)
        ).isoformat()
        rows = _historical_comparables(
            conn,
            market=market,
            model=normalized_model,
            storage_gb=normalized_storage,
            cutoff_date=cutoff_date,
            target_date=target_date,
        )
        if not rows:
            return {
                **_empty_result(
                    status="insufficient_data",
                    model=normalized_model,
                    storage_gb=normalized_storage,
                    market=market,
                    message="没有找到同款、同容量的有效二手机样本。",
                ),
                "as_of_date": target_date,
                "lookback_days": lookback_days,
            }

        filtered_rows, rejected_count = _remove_price_outliers(rows)
        if len(filtered_rows) < 3:
            return {
                **_empty_result(
                    status="insufficient_data",
                    model=normalized_model,
                    storage_gb=normalized_storage,
                    market=market,
                    message="去除异常价格后，同款有效样本少于 3 条。",
                ),
                "as_of_date": target_date,
                "lookback_days": lookback_days,
                "sample_count": len(filtered_rows),
                "rejected_outliers": rejected_count,
            }

        prices = [float(row["price_cny"]) for row in filtered_rows]
        p25 = percentile(prices, 0.25) or 0.0
        median = percentile(prices, 0.5) or 0.0
        p75 = percentile(prices, 0.75) or 0.0
        dispersion = (p75 - p25) / median if median > 0 else 1.0
        confidence_level, confidence_score, confidence_reason = _confidence(
            len(filtered_rows), dispersion
        )
        suggested_purchase = p25 * (1 - target_margin_pct / 100)
        fx_payload, native_range, native_guidance = _native_currency_payload(
            conn,
            market=market,
            fair_range=(p25, median, p75),
            suggested_purchase=suggested_purchase,
            suggested_resale=median,
        )
        warnings = [
            "估值基于公开在售要价，不代表已经成交。",
            "结果用于辅助判断，交易前仍需核验成色、电池、保修和维修史。",
        ]
        if rejected_count:
            warnings.append(f"已排除 {rejected_count} 条极端或疑似错误价格。")
        if confidence_level == "low":
            warnings.append("当前样本量或价格离散度不足，置信度较低。")

        return {
            "status": "ok",
            "method": MODEL_METHOD,
            "market": market,
            "model": normalized_model,
            "storage_gb": normalized_storage,
            "storage_label": _storage_label(normalized_storage),
            "as_of_date": target_date,
            "lookback_days": lookback_days,
            "sample_count": len(filtered_rows),
            "rejected_outliers": rejected_count,
            "confidence": {
                "level": confidence_level,
                "score": confidence_score,
                "reason": confidence_reason,
            },
            "fair_range_cny": {
                "low": round(p25, 2),
                "mid": round(median, 2),
                "high": round(p75, 2),
            },
            "guidance_cny": {
                "suggested_purchase_max": round(suggested_purchase, 2),
                "suggested_resale": round(median, 2),
                "target_margin_pct": round(target_margin_pct, 2),
            },
            "fair_range_native": native_range,
            "guidance_native": native_guidance,
            "dispersion_pct": round(dispersion * 100, 2),
            "fx": fx_payload,
            "comparables": [
                _comparable_payload(row)
                for row in sorted(
                    filtered_rows,
                    key=lambda item: abs(float(item["price_cny"]) - median),
                )[: max(1, min(comparable_limit, 20))]
            ],
            "warnings": warnings,
        }
    finally:
        conn.close()


def _latest_active_date(conn, market: str) -> str | None:
    placeholders = ",".join("?" for _ in ACTIVE_SOURCE_KEYS)
    row = conn.execute(
        f"""
        SELECT max(collected_date)
        FROM listings
        WHERE market=?
          AND source_key IN ({placeholders})
          AND condition='used'
          AND listing_status='active'
          AND price_cny IS NOT NULL
        """,
        (market, *ACTIVE_SOURCE_KEYS),
    ).fetchone()
    return row[0] if row and row[0] else None


def _historical_comparables(
    conn,
    *,
    market: str,
    model: str,
    storage_gb: int,
    cutoff_date: str,
    target_date: str,
) -> list[Any]:
    placeholders = ",".join("?" for _ in ACTIVE_SOURCE_KEYS)
    return list(
        conn.execute(
            f"""
            SELECT l.*
            FROM listings AS l
            JOIN (
                SELECT source_key, listing_id, max(id) AS latest_id
                FROM listings
                WHERE market=?
                  AND source_key IN ({placeholders})
                  AND model=?
                  AND storage_gb=?
                  AND condition='used'
                  AND listing_status='active'
                  AND price_cny IS NOT NULL
                  AND price_cny > 0
                  AND collected_date BETWEEN ? AND ?
                GROUP BY source_key, listing_id
            ) AS latest ON latest.latest_id = l.id
            ORDER BY l.price_cny
            """,
            (
                market,
                *ACTIVE_SOURCE_KEYS,
                model,
                storage_gb,
                cutoff_date,
                target_date,
            ),
        ).fetchall()
    )


def _remove_price_outliers(rows: list[Any]) -> tuple[list[Any], int]:
    retained = list(rows)
    rejected_total = 0
    for _ in range(3):
        prices = [float(row["price_cny"]) for row in retained]
        median = percentile(prices, 0.5)
        if median is None or median <= 0 or len(retained) < 8:
            break
        deviations = [abs(price - median) for price in prices]
        mad = percentile(deviations, 0.5) or 0.0
        scale = 1.4826 * mad
        if scale <= 0:
            p25 = percentile(prices, 0.25) or 0.0
            p75 = percentile(prices, 0.75) or 0.0
            scale = (p75 - p25) / 1.349
        if scale <= 0:
            break
        lower = max(0.01, median - 3 * scale)
        upper = median + 3 * scale
        next_rows = [
            row for row in retained if lower <= float(row["price_cny"]) <= upper
        ]
        if len(next_rows) == len(retained):
            break
        rejected_total += len(retained) - len(next_rows)
        retained = next_rows
    return retained, rejected_total


def _confidence(
    sample_count: int, dispersion: float
) -> tuple[str, float, str]:
    if sample_count >= 20 and dispersion <= 0.35:
        return "high", 0.9, "样本量充足，同款价格集中。"
    if sample_count >= 8 and dispersion <= 0.6:
        return "medium", 0.7, "样本量可用，但同款价格存在一定离散。"
    if sample_count >= 5 and dispersion <= 0.8:
        return "medium", 0.55, "样本量偏少，建议结合人工检查。"
    return "low", 0.35, "样本量不足或价格波动较大。"


def _native_currency_payload(
    conn,
    *,
    market: str,
    fair_range: tuple[float, float, float],
    suggested_purchase: float,
    suggested_resale: float,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    currency = _CURRENCY_BY_MARKET.get(market)
    if currency is None:
        return {"currency": None, "rate_cny_per_unit": None}, None, None
    if currency == "CNY":
        rate = 1.0
        stale = False
        rate_date = None
    else:
        try:
            rates = load_cached_rates(conn)
        except Exception:
            rates = None
        if rates is None or currency not in rates.cny_per_unit:
            return {
                "currency": currency,
                "rate_cny_per_unit": None,
                "rate_date": None,
                "stale": None,
            }, None, None
        rate = float(rates.cny_per_unit[currency])
        stale = rates.stale
        rate_date = rates.rate_date
    if rate <= 0:
        return {"currency": currency, "rate_cny_per_unit": rate}, None, None
    low, median, high = fair_range
    return (
        {
            "currency": currency,
            "rate_cny_per_unit": round(rate, 6),
            "rate_date": rate_date,
            "stale": stale,
        },
        {
            "currency": currency,
            "low": round(low / rate, 2),
            "mid": round(median / rate, 2),
            "high": round(high / rate, 2),
        },
        {
            "currency": currency,
            "suggested_purchase_max": round(suggested_purchase / rate, 2),
            "suggested_resale": round(suggested_resale / rate, 2),
        },
    )


def _comparable_payload(row) -> dict[str, Any]:
    return {
        "listing_id": row["listing_id"],
        "source_key": row["source_key"],
        "source_name": row["source_name"],
        "title": row["title"],
        "url": row["url"],
        "price_native": row["price_native"],
        "currency": row["currency"],
        "price_cny": round(float(row["price_cny"]), 2),
        "collected_date": row["collected_date"],
        "seen_at": row["seen_at"],
    }


def _empty_result(
    *,
    status: str,
    model: str,
    storage_gb: int,
    market: str,
    message: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "method": MODEL_METHOD,
        "market": market,
        "model": model,
        "storage_gb": storage_gb,
        "storage_label": _storage_label(storage_gb),
        "sample_count": 0,
        "rejected_outliers": 0,
        "fair_range_cny": None,
        "guidance_cny": None,
        "fair_range_native": None,
        "guidance_native": None,
        "confidence": {
            "level": "none",
            "score": 0.0,
            "reason": message,
        },
        "comparables": [],
        "warnings": [message],
    }


def _storage_label(storage_gb: int) -> str:
    if storage_gb == 1024:
        return "1TB"
    if storage_gb == 2048:
        return "2TB"
    return f"{storage_gb}GB"


def confidence_weight(level: str) -> float:
    return {"high": 1.0, "medium": 0.75, "low": 0.45}.get(level, 0.25)


def liquidity_weight(sample_count: int) -> float:
    if sample_count <= 0:
        return 0.0
    return min(1.0, math.log1p(sample_count) / math.log1p(30))
