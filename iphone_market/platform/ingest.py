from __future__ import annotations

import hashlib
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..browser import persistent_browser
from ..collection import normalize_output
from ..collectors import create_collector
from ..collectors.base import CollectorOutput
from ..config import PHONE_VARIANTS, SOURCE_BY_KEY, SourceSpec
from ..fx import FxRates, fetch_latest_rates
from ..redaction import redact_sensitive
from . import models, repository
from .object_store import ObjectStore, get_object_store
from .search import ListingSearchIndex
from .settings import PlatformSettings


LOGGER = logging.getLogger(__name__)


class CollectionPipeline:
    def __init__(
        self,
        settings: PlatformSettings,
        session_factory: sessionmaker[Session],
        *,
        object_store: ObjectStore | None = None,
        search_index: ListingSearchIndex | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.object_store = object_store or get_object_store(settings)
        self.search_index = search_index or ListingSearchIndex(settings)

    def collect_source(
        self,
        source_key: str,
        *,
        run_date: str | None = None,
        limit: int = 30,
        headless: bool = True,
        external_run_id: str | None = None,
    ) -> dict[str, Any]:
        if source_key not in SOURCE_BY_KEY:
            raise ValueError(f"未知来源：{source_key}")
        selected_date = run_date or date.today().isoformat()
        selected_run_id = external_run_id or uuid4().hex
        started_at = repository.utc_now()
        self._record_run(
            source_key=source_key,
            external_run_id=selected_run_id,
            status="running",
            started_at=started_at,
            metadata={"run_date": selected_date, "limit": limit},
        )

        spec = SOURCE_BY_KEY[source_key]
        rates = self._load_rates(spec)
        output: CollectorOutput | None = None
        records = []
        try:
            with persistent_browser(headless=headless) as context:
                collector = create_collector(source_key, limit)
                output = collector.collect(context, PHONE_VARIANTS)
            records = normalize_output(output, spec, rates, limit)
            result = self.ingest_records(
                records,
                spec=spec,
                observed_at=repository.utc_now(),
                run_date=selected_date,
            )
            status = _source_status(output, len(records))
            error = _source_error(output)
            finished_at = repository.utc_now()
            with self.session_factory() as session:
                repository.upsert_source_run(
                    session,
                    source_key=source_key,
                    external_run_id=selected_run_id,
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    listing_count=result["listings"],
                    query_count=output.query_count,
                    error=error,
                    metadata={
                        "run_date": selected_date,
                        "limit": limit,
                        "snapshots": result["snapshots"],
                        "raw_captures": result["raw_captures"],
                        "upserted": result["upserted"],
                    },
                )
                session.commit()
            return {
                "source_key": source_key,
                "external_run_id": selected_run_id,
                "status": status,
                "listing_count": result["listings"],
                "query_count": output.query_count,
                "error": error,
            }
        except Exception as exc:
            message = redact_sensitive(f"{type(exc).__name__}: {exc}")[:2000]
            with self.session_factory() as session:
                repository.upsert_source_run(
                    session,
                    source_key=source_key,
                    external_run_id=selected_run_id,
                    status="failed",
                    started_at=started_at,
                    finished_at=repository.utc_now(),
                    listing_count=len(records),
                    query_count=len(PHONE_VARIANTS),
                    error=message,
                    metadata={"run_date": selected_date, "limit": limit},
                )
                session.commit()
            raise

    def ingest_records(
        self,
        records: list[Any],
        *,
        spec: SourceSpec,
        observed_at: datetime,
        run_date: str,
    ) -> dict[str, int]:
        result = {"listings": 0, "snapshots": 0, "raw_captures": 0, "upserted": 0}
        indexed_ids: list[int] = []
        with self.session_factory() as session:
            for record in records:
                capture = self._store_raw_capture(record, observed_at=observed_at)
                listing, snapshot_created = repository.upsert_listing_observation(
                    session,
                    record,
                    observed_at=observed_at,
                    raw_ref=capture.uri,
                    metadata={"run_date": run_date},
                )
                if capture.size_bytes:
                    existing_capture = session.scalar(
                        select(models.RawCapture.id).where(
                            models.RawCapture.storage_uri == capture.uri
                        )
                    )
                    if existing_capture is None:
                        session.add(
                            models.RawCapture(
                                source_key=spec.key,
                                listing_id=listing.id,
                                captured_at=observed_at,
                                storage_uri=capture.uri,
                                sha256=capture.sha256,
                                size_bytes=capture.size_bytes,
                                content_type=capture.content_type,
                                expires_at=observed_at
                                + timedelta(
                                    days=self.settings.raw_capture_retention_days
                                ),
                                metadata_json={
                                    "source_listing_id": listing.source_listing_id,
                                    "retention_policy": "raw_capture_short_lived",
                                },
                            )
                        )
                        result["raw_captures"] += 1
                indexed_ids.append(listing.id)
                result["listings"] += 1
                result["upserted"] += 1
                result["snapshots"] += int(snapshot_created)
            session.commit()
            for listing_id in indexed_ids:
                self.search_index.index_listing(session, listing_id)
        return result

    def _store_raw_capture(self, record: Any, *, observed_at: datetime):
        digest = hashlib.sha1(
            f"{record.source_key}|{record.listing_id}|{observed_at.isoformat()}".encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        key = (
            f"{record.source_key}/{observed_at:%Y/%m/%d}/"
            f"{observed_at:%H%M%S}-{digest}.json"
        )
        return self.object_store.put_json(
            key,
            {
                "source_key": record.source_key,
                "source_listing_id": record.listing_id,
                "observed_at": observed_at.isoformat(),
                "title": record.title,
                "url": record.url,
                "price_native": str(record.price_native),
                "currency": record.currency,
                "raw": record.raw,
            },
        )

    def _record_run(
        self,
        *,
        source_key: str,
        external_run_id: str,
        status: str,
        started_at: datetime,
        metadata: dict[str, Any],
    ) -> None:
        with self.session_factory() as session:
            repository.upsert_source_run(
                session,
                source_key=source_key,
                external_run_id=external_run_id,
                status=status,
                started_at=started_at,
                metadata=metadata,
            )
            session.commit()

    @staticmethod
    def _load_rates(spec: SourceSpec) -> FxRates | None:
        if spec.currency == "CNY":
            return None
        try:
            return fetch_latest_rates()
        except Exception as exc:
            LOGGER.warning("汇率获取失败，原币数据仍会保留：%s", exc)
            return None


def _source_status(output: CollectorOutput, accepted_count: int) -> str:
    if output.successful_query_count == 0:
        return "failed"
    if output.errors or output.successful_query_count < output.query_count:
        return "partial"
    if accepted_count == 0:
        return "partial"
    return "ok"


def _source_error(output: CollectorOutput) -> str | None:
    if not output.errors and output.successful_query_count == output.query_count:
        return None
    counts = Counter(output.errors)
    details = []
    for message, count in counts.items():
        compact = " ".join(message.split())
        details.append(compact if count == 1 else f"{compact} [x{count}]")
    return redact_sensitive("；".join(details))[:2000] or None
