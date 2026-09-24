from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from . import db
from .browser import BrowserLaunchError, persistent_browser
from .collectors import create_collector
from .collectors.base import CollectorOutput, RawListing
from .config import (
    ACTIVE_SOURCE_KEYS,
    DB_PATH,
    PHONE_VARIANTS,
    SOURCE_BY_KEY,
    SOURCE_KEYS,
    SourceSpec,
    ensure_runtime_dirs,
)
from .fx import FxRates, fetch_or_cache_rates
from .models import CollectionResult, ListingRecord, RunSummary
from .normalization import (
    MIN_PLAUSIBLE_NATIVE_PRICE,
    classify_listing_quality,
    is_valid_variant,
    listing_id_from_url,
)
from .redaction import redact_sensitive

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionOptions:
    run_date: str
    source_keys: tuple[str, ...] = ACTIVE_SOURCE_KEYS
    limit: int = 30
    headless: bool = True
    db_path: Path | str = DB_PATH


def normalize_output(
    output: CollectorOutput,
    spec: SourceSpec,
    rates: FxRates | None,
    limit: int,
    *,
    include_rejected: bool = False,
) -> list[ListingRecord]:
    records: list[ListingRecord] = []
    seen_ids: set[str] = set()
    for result in output.variants:
        accepted = 0
        for raw in result.listings:
            record = normalize_listing(raw, spec, rates)
            if record is None or record.listing_id in seen_ids:
                continue
            if record.condition == "used":
                if accepted >= limit:
                    continue
                accepted += 1
            elif not include_rejected:
                continue
            seen_ids.add(record.listing_id)
            records.append(record)
    return records


def normalize_listing(
    raw: RawListing,
    spec: SourceSpec,
    rates: FxRates | None,
) -> ListingRecord | None:
    title = raw.title.strip()
    if not title or not raw.url or raw.price_native is None or raw.price_native <= 0:
        return None
    if not is_valid_variant(title, raw.variant):
        return None
    quality = classify_listing_quality(
        title,
        price_native=raw.price_native,
        currency=raw.currency,
    )

    price_cny: Decimal | None
    if raw.currency == "CNY":
        price_cny = raw.price_native.quantize(Decimal("0.01"))
    elif rates is None:
        price_cny = None
    else:
        try:
            price_cny = rates.to_cny(raw.price_native, raw.currency)
        except KeyError:
            price_cny = None

    listing_id = raw.listing_id or listing_id_from_url(spec.key, raw.url, title)
    return ListingRecord(
        source_key=spec.key,
        source_name=spec.name,
        market=spec.market,
        listing_id=listing_id,
        title=title,
        url=raw.url,
        model=raw.variant.model,
        generation=raw.variant.generation,
        family=raw.variant.family,
        storage_gb=raw.variant.storage_gb,
        condition=quality.outcome,
        listing_status=raw.listing_status,
        price_native=raw.price_native,
        currency=raw.currency,
        price_cny=price_cny,
        fx_date=rates.rate_date if rates else None,
        location=raw.location,
    raw={
        **raw.raw,
        "variant_query": raw.variant.query,
        "source_listing_id": listing_id,
        "quality": {
            **quality.as_dict(),
            "price_floor_native": (
                str(MIN_PLAUSIBLE_NATIVE_PRICE.get(raw.currency.upper()))
                if raw.currency.upper() in MIN_PLAUSIBLE_NATIVE_PRICE
                else None
            ),
        },
        "fx_stale": rates.stale if rates else None,
        "fx_source": rates.source if rates else None,
    },
)


def collect(options: CollectionOptions) -> RunSummary:
    ensure_runtime_dirs()
    run_date = date.fromisoformat(options.run_date).isoformat()
    unknown = sorted(set(options.source_keys) - set(SOURCE_KEYS))
    if unknown:
        raise ValueError(f"未知来源：{', '.join(unknown)}")
    if not options.source_keys:
        raise ValueError("至少需要选择一个来源")

    variants = PHONE_VARIANTS
    db.init_db(options.db_path)
    conn = db.connect(options.db_path)
    db.recover_interrupted_runs(conn)
    run_id = db.start_run(
        conn,
        run_date,
        metadata={
            "sources": list(options.source_keys),
            "limit": options.limit,
            "headless": options.headless,
        },
    )
    conn.commit()

    fx_rates: FxRates | None = None
    fx_error: str | None = None
    try:
        fx_rates = fetch_or_cache_rates(conn)
    except Exception as exc:
        fx_error = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("汇率获取失败：%s", fx_error)

    source_results: list[CollectionResult] = []
    try:
        try:
            with persistent_browser(headless=options.headless) as context:
                for source_key in options.source_keys:
                    spec = SOURCE_BY_KEY[source_key]
                    db.start_source_run(conn, run_id, spec.key, spec.market)
                    conn.commit()
                    try:
                        collector = create_collector(source_key, options.limit)
                        LOGGER.info("开始采集 %s（%s）", spec.name, spec.market)
                        output = collector.collect(context, variants)
                        records = normalize_output(
                            output,
                            spec,
                            fx_rates,
                            options.limit,
                            include_rejected=True,
                        )
                        accepted_records = [
                            record
                            for record in records
                            if record.condition == "used"
                        ]
                        db.insert_listings(conn, run_id, run_date, records)
                        status = _source_status(output)
                        error_parts = []
                        if fx_error and spec.currency != "CNY":
                            error_parts.append(f"汇率不可用：{fx_error}")
                        if output.errors:
                            error_parts.append(_summarize_errors(output.errors))
                        if not accepted_records and not output.errors:
                            status = "partial"
                            error_parts.append(
                                "未解析到符合筛选条件的二手机，请检查登录状态、页面结构或搜索词"
                            )
                        result = CollectionResult(
                            source_key=spec.key,
                            status=status,
                            listing_count=len(accepted_records),
                            query_count=output.query_count,
                            error=redact_sensitive("；".join(error_parts))[:2_000] or None,
                        )
                        db.finish_source_run(conn, run_id, result)
                        conn.commit()
                        source_results.append(result)
                        LOGGER.info(
                            "完成 %s：status=%s，listings=%s，queries=%s",
                            spec.name,
                            status,
                            len(accepted_records),
                            output.query_count,
                        )
                    except Exception as exc:
                        conn.rollback()
                        result = CollectionResult(
                            source_key=spec.key,
                            status="failed",
                            listing_count=0,
                            query_count=len(variants),
                            error=redact_sensitive(
                                f"{type(exc).__name__}: {exc}"
                            )[:2_000],
                        )
                        db.finish_source_run(conn, run_id, result)
                        conn.commit()
                        source_results.append(result)
                        LOGGER.exception("采集来源失败：%s", spec.name)
        except BrowserLaunchError as exc:
            LOGGER.error("浏览器启动失败：%s", exc)
            _record_unstarted_sources(
                conn,
                run_id,
                options.source_keys,
                source_results,
                len(variants),
                f"browser_error: {exc}",
            )
        except Exception as exc:
            # A browser-context failure outside a source adapter must not leave
            # the run or its unfinished sources stuck in the running state.
            LOGGER.exception("浏览器会话异常：%s", exc)
            _record_unstarted_sources(
                conn,
                run_id,
                options.source_keys,
                source_results,
                len(variants),
                f"browser_error: {type(exc).__name__}: {exc}",
            )

        run_status = _run_status(source_results)
        db.update_run_metadata(
            conn,
            run_id,
            {
                "sources": list(options.source_keys),
                "limit": options.limit,
                "headless": options.headless,
                "fx_date": fx_rates.rate_date if fx_rates else None,
                "fx_stale": fx_rates.stale if fx_rates else None,
                "fx_error": redact_sensitive(fx_error),
            },
        )
        db.finish_run(conn, run_id, run_status)
        conn.commit()
    finally:
        conn.close()

    total = sum(result.listing_count for result in source_results)
    return RunSummary(
        run_id=run_id,
        run_date=run_date,
        status=run_status,
        total_listings=total,
        source_results=tuple(source_results),
    )


def _record_unstarted_sources(
    conn,
    run_id: int,
    source_keys: tuple[str, ...],
    source_results: list[CollectionResult],
    query_count: int,
    error: str,
) -> None:
    existing = {result.source_key for result in source_results}
    for source_key in source_keys:
        if source_key in existing:
            continue
        spec = SOURCE_BY_KEY[source_key]
        db.start_source_run(conn, run_id, spec.key, spec.market)
        result = CollectionResult(
            source_key=spec.key,
            status="failed",
            listing_count=0,
            query_count=query_count,
            error=redact_sensitive(error)[:2_000],
        )
        db.finish_source_run(conn, run_id, result)
        source_results.append(result)
    conn.commit()


def _source_status(output: CollectorOutput) -> str:
    if output.successful_query_count == 0:
        return "failed"
    if output.errors or output.successful_query_count < output.query_count:
        return "partial"
    return "ok"


def _run_status(results: Sequence[CollectionResult]) -> str:
    if not results:
        return "failed"
    usable = sum(1 for result in results if result.status in {"ok", "partial"})
    if usable == 0:
        return "failed"
    if usable < len(results) or any(result.status != "ok" for result in results):
        return "partial"
    return "ok"


def _summarize_errors(errors: Sequence[str]) -> str:
    counts = Counter(errors)
    parts = []
    for message, count in counts.items():
        compact = " ".join(message.split())
        parts.append(compact if count == 1 else f"{compact} [x{count}]")
    return redact_sensitive("；".join(parts)) or ""


def today_iso() -> str:
    return date.today().isoformat()
