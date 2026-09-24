from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ListingRecord:
    source_key: str
    source_name: str
    market: str
    listing_id: str
    title: str
    url: str
    model: str
    generation: int
    family: str
    storage_gb: int | None
    condition: str
    listing_status: str
    price_native: Decimal | None
    currency: str
    price_cny: Decimal | None
    fx_date: str | None
    location: str | None
    raw: dict[str, Any]

    def to_db_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["price_native"] = float(self.price_native) if self.price_native is not None else None
        values["price_cny"] = float(self.price_cny) if self.price_cny is not None else None
        values["raw_json"] = values.pop("raw")
        return values


@dataclass(frozen=True)
class CollectionResult:
    source_key: str
    status: str
    listing_count: int
    query_count: int
    error: str | None = None


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    run_date: str
    status: str
    total_listings: int
    source_results: tuple[CollectionResult, ...]
