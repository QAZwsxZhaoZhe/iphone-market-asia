from __future__ import annotations

import json
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .. import db
from ..config import ACTIVE_MARKET_ORDER, ACTIVE_SOURCE_KEYS, DB_PATH
from .valuation import estimate_valuation, normalize_model, normalize_storage_gb


DECISIONS = ("buy", "watch", "skip")
OUTCOMES = ("pending", "purchased", "sold", "rejected", "lost", "not_sold")


def record_feedback(
    *,
    model: str,
    storage_gb: int | str,
    decision: str,
    outcome: str = "pending",
    market: str = ACTIVE_MARKET_ORDER[0],
    source_key: str | None = None,
    listing_id: str | None = None,
    valuation_date: str | None = None,
    decision_price_cny: float | None = None,
    actual_purchase_cny: float | None = None,
    actual_sale_cny: float | None = None,
    fees_cny: float = 0.0,
    repair_cost_cny: float = 0.0,
    estimated_fair_cny: float | None = None,
    fair_low_cny: float | None = None,
    fair_high_cny: float | None = None,
    suggested_purchase_cny: float | None = None,
    confidence_level: str | None = None,
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    auto_estimate: bool = True,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any]:
    normalized_model = normalize_model(model)
    normalized_storage = normalize_storage_gb(storage_gb)
    selected_market = str(market).strip()
    selected_decision = str(decision).strip().lower()
    selected_outcome = str(outcome).strip().lower()
    selected_source = _optional_text(source_key)
    selected_listing_id = _optional_text(listing_id)

    if selected_market not in ACTIVE_MARKET_ORDER:
        raise ValueError(f"不支持的市场：{selected_market}")
    if selected_decision not in DECISIONS:
        raise ValueError(f"decision 必须是：{', '.join(DECISIONS)}")
    if selected_outcome not in OUTCOMES:
        raise ValueError(f"outcome 必须是：{', '.join(OUTCOMES)}")
    if selected_source and selected_source not in ACTIVE_SOURCE_KEYS:
        raise ValueError(f"不支持的来源：{selected_source}")
    if selected_listing_id and not selected_source:
        raise ValueError("填写 listing_id 时必须同时填写 source_key")

    target_date = _parse_date(valuation_date or date.today().isoformat())
    decision_price = _amount(decision_price_cny, "decision_price_cny")
    purchase_price = _amount(actual_purchase_cny, "actual_purchase_cny")
    sale_price = _amount(actual_sale_cny, "actual_sale_cny")
    fees = _amount(fees_cny, "fees_cny", default=0.0) or 0.0
    repair = _amount(repair_cost_cny, "repair_cost_cny", default=0.0) or 0.0
    fair_value = _amount(estimated_fair_cny, "estimated_fair_cny")
    fair_low = _amount(fair_low_cny, "fair_low_cny")
    fair_high = _amount(fair_high_cny, "fair_high_cny")
    suggested_purchase = _amount(
        suggested_purchase_cny,
        "suggested_purchase_cny",
    )
    selected_confidence = _optional_text(confidence_level)

    if selected_outcome == "purchased" and purchase_price is None:
        raise ValueError("outcome=purchased 时必须填写 actual_purchase_cny")
    if selected_outcome == "sold":
        if purchase_price is None or purchase_price <= 0:
            raise ValueError("outcome=sold 时必须填写大于 0 的 actual_purchase_cny")
        if sale_price is None or sale_price <= 0:
            raise ValueError("outcome=sold 时必须填写大于 0 的 actual_sale_cny")
    if fair_low is not None and fair_high is not None and fair_low > fair_high:
        raise ValueError("fair_low_cny 不能高于 fair_high_cny")

    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        if auto_estimate and fair_value is None:
            valuation = estimate_valuation(
                model=normalized_model,
                storage_gb=normalized_storage,
                market=selected_market,
                as_of_date=target_date,
                db_path=db_path,
            )
            if valuation["status"] == "ok":
                fair_value = float(valuation["fair_range_cny"]["mid"])
                fair_low = float(valuation["fair_range_cny"]["low"])
                fair_high = float(valuation["fair_range_cny"]["high"])
                suggested_purchase = float(
                    valuation["guidance_cny"]["suggested_purchase_max"]
                )
                selected_confidence = valuation["confidence"]["level"]

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        cursor = conn.execute(
            """
            INSERT INTO valuation_feedback(
                created_at, updated_at, market, model, storage_gb,
                source_key, listing_id, valuation_date, estimated_fair_cny,
                fair_low_cny, fair_high_cny, suggested_purchase_cny,
                confidence_level, decision, decision_price_cny, outcome,
                actual_purchase_cny, actual_sale_cny, fees_cny, repair_cost_cny,
                notes, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                selected_market,
                normalized_model,
                normalized_storage,
                selected_source,
                selected_listing_id,
                target_date,
                fair_value,
                fair_low,
                fair_high,
                suggested_purchase,
                selected_confidence,
                selected_decision,
                decision_price,
                selected_outcome,
                purchase_price,
                sale_price,
                fees,
                repair,
                str(notes or "").strip(),
                json.dumps(metadata or {}, ensure_ascii=False, default=str),
            ),
        )
        record_id = int(cursor.lastrowid)
        row = conn.execute(
            "SELECT * FROM valuation_feedback WHERE id=?",
            (record_id,),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "record": _record_payload(row)}


def list_feedback(
    *,
    market: str | None = None,
    model: str | None = None,
    storage_gb: int | str | None = None,
    outcome: str | None = None,
    limit: int = 100,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit 必须在 1 到 1000 之间")
    normalized_model = normalize_model(model) if model else None
    normalized_storage = normalize_storage_gb(storage_gb) if storage_gb else None
    selected_market = _optional_text(market)
    selected_outcome = _optional_text(outcome)
    if selected_market and selected_market not in ACTIVE_MARKET_ORDER:
        raise ValueError(f"不支持的市场：{selected_market}")
    if selected_outcome and selected_outcome not in OUTCOMES:
        raise ValueError(f"outcome 必须是：{', '.join(OUTCOMES)}")

    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        conditions: list[str] = []
        params: list[Any] = []
        if selected_market:
            conditions.append("market=?")
            params.append(selected_market)
        if normalized_model:
            conditions.append("model=?")
            params.append(normalized_model)
        if normalized_storage is not None:
            conditions.append("storage_gb=?")
            params.append(normalized_storage)
        if selected_outcome:
            conditions.append("outcome=?")
            params.append(selected_outcome)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = list(
            conn.execute(
                f"SELECT * FROM valuation_feedback {where} ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        )
    finally:
        conn.close()
    return {
        "status": "ok",
        "count": len(rows),
        "records": [_record_payload(row) for row in rows],
    }


def feedback_metrics(
    *,
    market: str | None = None,
    model: str | None = None,
    storage_gb: int | str | None = None,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any]:
    payload = list_feedback(
        market=market,
        model=model,
        storage_gb=storage_gb,
        limit=1000,
        db_path=db_path,
    )
    records = payload["records"]
    outcome_counts = {value: 0 for value in OUTCOMES}
    decision_counts = {value: 0 for value in DECISIONS}
    absolute_errors: list[float] = []
    percentage_errors: list[float] = []
    signed_errors: list[float] = []
    coverage_checks: list[bool] = []
    profits: list[float] = []
    roi_values: list[float] = []
    confidence_groups: dict[str, dict[str, list[float]]] = {
        level: {"absolute_errors": [], "percentage_errors": []}
        for level in ("high", "medium", "low")
    }

    for record in records:
        outcome = record["outcome"]
        decision = record["decision"]
        if outcome in outcome_counts:
            outcome_counts[outcome] += 1
        if decision in decision_counts:
            decision_counts[decision] += 1

        estimate = record["estimated_fair_cny"]
        actual_sale = record["actual_sale_cny"]
        if estimate is not None and actual_sale is not None and actual_sale > 0:
            signed_error = float(estimate) - float(actual_sale)
            absolute_error = abs(signed_error)
            percentage_error = absolute_error / float(actual_sale) * 100
            signed_errors.append(signed_error)
            absolute_errors.append(absolute_error)
            percentage_errors.append(percentage_error)
            confidence = record.get("confidence_level")
            if confidence in confidence_groups:
                confidence_groups[confidence]["absolute_errors"].append(
                    absolute_error
                )
                confidence_groups[confidence]["percentage_errors"].append(
                    percentage_error
                )
            low = record.get("fair_low_cny")
            high = record.get("fair_high_cny")
            if low is not None and high is not None:
                coverage_checks.append(float(low) <= float(actual_sale) <= float(high))

        purchase = record["actual_purchase_cny"]
        if (
            outcome == "sold"
            and purchase is not None
            and actual_sale is not None
        ):
            landed_cost = (
                float(purchase)
                + float(record["fees_cny"] or 0)
                + float(record["repair_cost_cny"] or 0)
            )
            profit = float(actual_sale) - landed_cost
            profits.append(profit)
            if landed_cost > 0:
                roi_values.append(profit / landed_cost * 100)

    sold_with_valuation = len(absolute_errors)
    evaluation_status = (
        "usable"
        if sold_with_valuation >= 30
        else "exploratory"
        if sold_with_valuation >= 10
        else "insufficient_data"
    )
    return {
        "status": "ok",
        "market": market,
        "model": model,
        "storage_gb": storage_gb,
        "record_count": len(records),
        "outcome_counts": outcome_counts,
        "decision_counts": decision_counts,
        "evaluation": {
            "status": evaluation_status,
            "sold_with_valuation": sold_with_valuation,
            "minimum_samples_for_usable": 30,
            "mean_absolute_error_cny": _round_or_none(_mean(absolute_errors)),
            "median_absolute_error_cny": _round_or_none(
                _median(absolute_errors)
            ),
            "mape_pct": _round_or_none(_mean(percentage_errors)),
            "mdape_pct": _round_or_none(_median(percentage_errors)),
            "mean_bias_cny": _round_or_none(_mean(signed_errors)),
            "median_bias_cny": _round_or_none(_median(signed_errors)),
            "fair_range_coverage_pct": _round_or_none(
                _mean(coverage_checks) * 100 if coverage_checks else None
            ),
            "coverage_sample_count": len(coverage_checks),
            "by_confidence": {
                level: {
                    "sold_with_valuation": len(values["absolute_errors"]),
                    "mape_pct": _round_or_none(
                        _mean(values["percentage_errors"])
                    ),
                    "mdape_pct": _round_or_none(
                        _median(values["percentage_errors"])
                    ),
                }
                for level, values in confidence_groups.items()
            },
        },
        "profit": {
            "sold_with_cost": len(profits),
            "total_net_profit_cny": _round_or_none(sum(profits)),
            "median_net_profit_cny": _round_or_none(_median(profits)),
            "median_roi_pct": _round_or_none(_median(roi_values)),
        },
        "recommendation": _recommendation(evaluation_status),
    }


def _record_payload(row) -> dict[str, Any]:
    payload = {key: row[key] for key in row.keys()}
    try:
        payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
    except json.JSONDecodeError:
        payload["metadata"] = {}
    return payload


def _parse_date(value: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError("date 必须是 YYYY-MM-DD") from exc


def _amount(
    value: float | int | str | None,
    name: str,
    *,
    default: float | None = None,
) -> float | None:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    if parsed < 0:
        raise ValueError(f"{name} 不能小于 0")
    return parsed


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mean(values: list) -> float | None:
    return float(statistics.fmean(values)) if values else None


def _median(values: list) -> float | None:
    return float(statistics.median(values)) if values else None


def _round_or_none(value: float | None) -> float | None:
    return round(float(value), 2) if value is not None else None


def _recommendation(status: str) -> str:
    if status == "usable":
        return "样本达到可用门槛，可以开始比较模型版本并回测定价。"
    if status == "exploratory":
        return "已能观察误差方向，但样本仍少，暂不据此自动调价。"
    return "真实成交样本不足 10 条，继续录入收购和转售结果后再评估。"
