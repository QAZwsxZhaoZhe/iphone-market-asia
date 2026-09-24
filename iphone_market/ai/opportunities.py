from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import db
from ..config import ACTIVE_MARKET_ORDER, ACTIVE_SOURCE_KEYS, DB_PATH
from .valuation import (
    confidence_weight,
    estimate_valuation,
    liquidity_weight,
    normalize_model,
    normalize_storage_gb,
)


DEFAULT_FEE_PCT = 12.0


def find_opportunities(
    *,
    model: str,
    storage_gb: int | str,
    market: str = ACTIVE_MARKET_ORDER[0],
    as_of_date: str | None = None,
    limit: int = 10,
    fee_pct: float = DEFAULT_FEE_PCT,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any]:
    normalized_model = normalize_model(model)
    normalized_storage = normalize_storage_gb(storage_gb)
    if limit < 1 or limit > 100:
        raise ValueError("limit 必须在 1 到 100 之间")
    if fee_pct < 0 or fee_pct > 40:
        raise ValueError("fee_pct 必须在 0 到 40 之间")

    valuation = estimate_valuation(
        model=normalized_model,
        storage_gb=normalized_storage,
        market=market,
        as_of_date=as_of_date,
        db_path=db_path,
    )
    if valuation["status"] != "ok":
        return {
            "status": valuation["status"],
            "market": market,
            "model": normalized_model,
            "storage_gb": normalized_storage,
            "as_of_date": valuation.get("as_of_date"),
            "valuation": valuation,
            "candidates": [],
            "warnings": valuation.get("warnings", []),
        }

    target_date = valuation["as_of_date"]
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        rows = [
            row
            for row in db.listing_rows(
                conn,
                target_date,
                market=market,
                model=normalized_model,
                storage_gb=normalized_storage,
                include_excluded=False,
                include_inactive=False,
            )
            if row["source_key"] in ACTIVE_SOURCE_KEYS
        ]
    finally:
        conn.close()

    fair = valuation["fair_range_cny"]
    median = float(fair["mid"])
    p25 = float(fair["low"])
    confidence = valuation["confidence"]
    score_confidence = confidence_weight(confidence["level"])
    score_liquidity = liquidity_weight(int(valuation["sample_count"]))
    candidates = []
    for row in rows:
        price = float(row["price_cny"]) if row["price_cny"] is not None else None
        if price is None or price <= 0 or median <= 0:
            continue
        gross_spread = median - price
        estimated_net_spread = median * (1 - fee_pct / 100) - price
        discount_pct = gross_spread / median * 100
        raw_score = max(0.0, discount_pct) * 1.8
        score = min(100.0, raw_score * score_confidence * score_liquidity)
        risk_flags = []
        if price < p25 * 0.5:
            risk_flags.append("价格显著低于正常区间，可能是解析错误、故障机或引流信息")
            score = 0.0
        if estimated_net_spread <= 0:
            risk_flags.append("扣除预估费用后没有正利润空间")
            score = 0.0
        priority = (
            "high"
            if score >= 60 and not risk_flags
            else "medium"
            if score >= 35
            else "watch"
        )
        candidates.append(
            {
                "listing_id": row["listing_id"],
                "source_key": row["source_key"],
                "source_name": row["source_name"],
                "title": row["title"],
                "url": row["url"],
                "price_native": row["price_native"],
                "currency": row["currency"],
                "price_cny": round(price, 2),
                "estimated_fair_value_cny": round(median, 2),
                "estimated_gross_spread_cny": round(gross_spread, 2),
                "estimated_net_spread_cny": round(estimated_net_spread, 2),
                "discount_pct": round(discount_pct, 2),
                "opportunity_score": round(score, 1),
                "priority": priority,
                "risk_flags": risk_flags,
                "seen_at": row["seen_at"],
            }
        )
    candidates.sort(
        key=lambda item: (item["opportunity_score"], item["estimated_net_spread_cny"]),
        reverse=True,
    )
    candidates = [item for item in candidates if item["opportunity_score"] > 0]
    return {
        "status": "ok",
        "market": market,
        "model": normalized_model,
        "storage_gb": normalized_storage,
        "as_of_date": target_date,
        "fee_pct": fee_pct,
        "valuation": valuation,
        "candidates": candidates[:limit],
        "warnings": [
            "机会评分只用于排序，不构成自动收购建议。",
            "买入前必须核验商品真实性、成色、电池、保修和卖家信用。",
            "费用比例当前为配置值，接入真实平台费和物流费后应重新回测。",
        ],
    }
