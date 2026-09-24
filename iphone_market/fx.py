from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Mapping

import requests

from .config import PROXY_URL


FX_URL = "https://open.er-api.com/v6/latest/CNY"
SUPPORTED_CURRENCIES = ("CNY", "SGD", "HKD", "JPY")


@dataclass(frozen=True)
class FxRates:
    rate_date: str
    cny_per_unit: Mapping[str, Decimal]
    stale: bool
    source: str

    def to_cny(self, amount: Decimal | None, currency: str) -> Decimal | None:
        if amount is None:
            return None
        rate = self.cny_per_unit.get(currency)
        if rate is None:
            raise KeyError(f"Missing FX rate for {currency}")
        return (amount * rate).quantize(Decimal("0.01"))


def rates_from_api_payload(payload: dict, fallback_date: str) -> FxRates:
    if payload.get("base_code") not in (None, "CNY"):
        raise ValueError("Exchange-rate payload does not use CNY as its base currency")
    rates = payload.get("rates") or {}
    cny_per_unit: dict[str, Decimal] = {"CNY": Decimal("1")}
    for currency in ("SGD", "HKD", "JPY"):
        units_per_cny = rates.get(currency)
        if units_per_cny is None:
            continue
        try:
            cny_per_unit[currency] = Decimal("1") / Decimal(str(units_per_cny))
        except (InvalidOperation, ZeroDivisionError):
            continue
    if len(cny_per_unit) < len(SUPPORTED_CURRENCIES):
        raise ValueError("Exchange-rate payload is missing a required currency")
    update_value = payload.get("time_last_update_utc")
    try:
        rate_date = parsedate_to_datetime(str(update_value)).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        rate_date = fallback_date
    return FxRates(
        rate_date=rate_date,
        cny_per_unit=cny_per_unit,
        stale=False,
        source="open.er-api.com",
    )


def load_cached_rates(conn: sqlite3.Connection) -> FxRates | None:
    row = conn.execute(
        "SELECT rate_date, rates_json, source FROM fx_rates ORDER BY rate_date DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    import json

    rates = json.loads(row["rates_json"])
    return FxRates(
        rate_date=row["rate_date"],
        cny_per_unit={key: Decimal(str(value)) for key, value in rates.items()},
        stale=True,
        source=row["source"],
    )


def fetch_or_cache_rates(conn: sqlite3.Connection, timeout: int = 15) -> FxRates:
    try:
        rates = fetch_latest_rates(timeout=timeout)
        import json

        conn.execute(
            """
            INSERT INTO fx_rates(rate_date, rates_json, source, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(rate_date) DO UPDATE SET
                rates_json=excluded.rates_json,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (
                rates.rate_date,
                json.dumps({key: str(value) for key, value in rates.cny_per_unit.items()}),
                rates.source,
            ),
        )
        conn.commit()
        return rates
    except Exception:
        cached = load_cached_rates(conn)
        if cached is None:
            raise
        return cached


def fetch_latest_rates(timeout: int = 15) -> FxRates:
    proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
    response = requests.get(FX_URL, timeout=timeout, proxies=proxies)
    response.raise_for_status()
    return rates_from_api_payload(response.json(), date.today().isoformat())
