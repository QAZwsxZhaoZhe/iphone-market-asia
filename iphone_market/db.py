from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

from .models import CollectionResult, ListingRecord


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES collection_runs(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    market TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    listing_count INTEGER NOT NULL DEFAULT 0,
    query_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    UNIQUE(run_id, source_key)
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES collection_runs(id) ON DELETE CASCADE,
    collected_date TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_name TEXT NOT NULL,
    market TEXT NOT NULL,
    listing_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    model TEXT NOT NULL,
    generation INTEGER NOT NULL,
    family TEXT NOT NULL,
    storage_gb INTEGER,
    condition TEXT NOT NULL,
    listing_status TEXT NOT NULL,
    price_native REAL,
    currency TEXT NOT NULL,
    price_cny REAL,
    fx_date TEXT,
    location TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(run_id, source_key, listing_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_date ON listings(collected_date);
CREATE INDEX IF NOT EXISTS idx_listings_model ON listings(model);
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source_key);

CREATE TABLE IF NOT EXISTS fx_rates (
    rate_date TEXT PRIMARY KEY,
    rates_json TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS valuation_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    market TEXT NOT NULL,
    model TEXT NOT NULL,
    storage_gb INTEGER NOT NULL,
    source_key TEXT,
    listing_id TEXT,
    valuation_date TEXT,
    estimated_fair_cny REAL,
    fair_low_cny REAL,
    fair_high_cny REAL,
    suggested_purchase_cny REAL,
    confidence_level TEXT,
    decision TEXT NOT NULL,
    decision_price_cny REAL,
    outcome TEXT NOT NULL DEFAULT 'pending',
    actual_purchase_cny REAL,
    actual_sale_cny REAL,
    fees_cny REAL NOT NULL DEFAULT 0,
    repair_cost_cny REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_feedback_variant
ON valuation_feedback(market, model, storage_gb);

CREATE INDEX IF NOT EXISTS idx_feedback_outcome
ON valuation_feedback(outcome);

CREATE INDEX IF NOT EXISTS idx_feedback_listing
ON valuation_feedback(source_key, listing_id);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def start_run(conn: sqlite3.Connection, run_date: str, metadata: dict[str, Any] | None = None) -> int:
    cursor = conn.execute(
        """
        INSERT INTO collection_runs(run_date, started_at, status, metadata_json)
        VALUES (?, ?, 'running', ?)
        """,
        (run_date, datetime.now().astimezone().isoformat(timespec="seconds"), json.dumps(metadata or {}, ensure_ascii=False)),
    )
    return int(cursor.lastrowid)


def start_source_run(conn: sqlite3.Connection, run_id: int, source_key: str, market: str) -> None:
    conn.execute(
        """
        INSERT INTO source_runs(run_id, source_key, market, started_at, status)
        VALUES (?, ?, ?, ?, 'running')
        ON CONFLICT(run_id, source_key) DO UPDATE SET
            started_at=excluded.started_at,
            status='running',
            error=NULL
        """,
        (run_id, source_key, market, datetime.now().astimezone().isoformat(timespec="seconds")),
    )


def finish_source_run(conn: sqlite3.Connection, run_id: int, result: CollectionResult) -> None:
    conn.execute(
        """
        UPDATE source_runs
        SET finished_at=?, status=?, listing_count=?, query_count=?, error=?
        WHERE run_id=? AND source_key=?
        """,
        (
            datetime.now().astimezone().isoformat(timespec="seconds"),
            result.status,
            result.listing_count,
            result.query_count,
            result.error,
            run_id,
            result.source_key,
        ),
    )


def finish_run(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    conn.execute(
        "UPDATE collection_runs SET finished_at=?, status=? WHERE id=?",
        (datetime.now().astimezone().isoformat(timespec="seconds"), status, run_id),
    )


def recover_interrupted_runs(conn: sqlite3.Connection) -> int:
    finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
    source_cursor = conn.execute(
        """
        UPDATE source_runs
        SET finished_at=?, status='failed',
            error=COALESCE(error, 'interrupted: 上次采集未正常结束')
        WHERE status='running'
        """,
        (finished_at,),
    )
    run_cursor = conn.execute(
        """
        UPDATE collection_runs
        SET finished_at=?, status='failed',
            metadata_json=json_set(
                CASE
                    WHEN json_valid(metadata_json) THEN metadata_json
                    ELSE '{}'
                END,
                '$.interrupted',
                json('true')
            )
        WHERE status='running'
        """,
        (finished_at,),
    )
    return run_cursor.rowcount


def update_run_metadata(conn: sqlite3.Connection, run_id: int, metadata: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE collection_runs SET metadata_json=? WHERE id=?",
        (json.dumps(metadata, ensure_ascii=False), run_id),
    )


def insert_listings(conn: sqlite3.Connection, run_id: int, collected_date: str, records: Sequence[ListingRecord]) -> int:
    if not records:
        return 0
    seen_at = datetime.now().astimezone().isoformat(timespec="seconds")
    inserted = 0
    for record in records:
        row = record.to_db_dict()
        conn.execute(
            """
            INSERT INTO listings(
                run_id, collected_date, seen_at, source_key, source_name, market,
                listing_id, title, url, model, generation, family, storage_gb,
                condition, listing_status, price_native, currency, price_cny,
                fx_date, location, raw_json
            ) VALUES (
                :run_id, :collected_date, :seen_at, :source_key, :source_name, :market,
                :listing_id, :title, :url, :model, :generation, :family, :storage_gb,
                :condition, :listing_status, :price_native, :currency, :price_cny,
                :fx_date, :location, :raw_json
            )
            ON CONFLICT(run_id, source_key, listing_id) DO UPDATE SET
                seen_at=excluded.seen_at,
                title=excluded.title,
                price_native=excluded.price_native,
                price_cny=excluded.price_cny,
                listing_status=excluded.listing_status,
                raw_json=excluded.raw_json
            """,
            {
                **row,
                "run_id": run_id,
                "collected_date": collected_date,
                "seen_at": seen_at,
                "raw_json": json.dumps(row["raw_json"], ensure_ascii=False, default=str),
            },
        )
        inserted += 1
    return inserted


def latest_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM collection_runs ORDER BY id DESC LIMIT 1").fetchone()


def latest_run_for_date(conn: sqlite3.Connection, run_date: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM collection_runs WHERE run_date=? ORDER BY id DESC LIMIT 1",
        (run_date,),
    ).fetchone()


def source_results(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM source_runs WHERE run_id=? ORDER BY market, source_key",
            (run_id,),
        ).fetchall()
    )


def available_dates(conn: sqlite3.Connection, limit: int = 90) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT collected_date FROM listings ORDER BY collected_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [row[0] for row in rows]


def listing_rows(
    conn: sqlite3.Connection,
    run_date: str | None = None,
    market: str | None = None,
    model: str | None = None,
    storage_gb: int | None = None,
    source_key: str | None = None,
    include_excluded: bool = False,
    include_inactive: bool = False,
) -> list[sqlite3.Row]:
    target_date = run_date or (available_dates(conn, 1) or [None])[0]
    if target_date is None:
        return []
    conditions = [
        "l.collected_date=?",
        """
        l.run_id = (
            SELECT sr.run_id
            FROM source_runs AS sr
            JOIN collection_runs AS cr ON cr.id = sr.run_id
            WHERE sr.source_key = l.source_key
              AND cr.run_date = l.collected_date
            ORDER BY sr.id DESC
            LIMIT 1
        )
        """,
    ]
    params: list[Any] = [target_date]
    if market:
        conditions.append("l.market=?")
        params.append(market)
    if model:
        conditions.append("l.model=?")
        params.append(model)
    if storage_gb is not None:
        conditions.append("l.storage_gb=?")
        params.append(storage_gb)
    if source_key:
        conditions.append("l.source_key=?")
        params.append(source_key)
    if not include_excluded:
        conditions.append("l.condition='used'")
    if not include_inactive:
        conditions.append("l.listing_status='active'")
    sql = (
        f"SELECT l.* FROM listings AS l WHERE {' AND '.join(conditions)} "
        "ORDER BY l.price_cny IS NULL, l.price_cny, l.seen_at DESC"
    )
    return list(conn.execute(sql, params).fetchall())


def previous_date(conn: sqlite3.Connection, current_date: str) -> str | None:
    row = conn.execute(
        """
        SELECT max(l.collected_date)
        FROM listings AS l
        WHERE l.collected_date < ?
          AND l.run_id = (
              SELECT sr.run_id
              FROM source_runs AS sr
              JOIN collection_runs AS cr ON cr.id = sr.run_id
              WHERE sr.source_key = l.source_key
                AND cr.run_date = l.collected_date
              ORDER BY sr.id DESC
              LIMIT 1
          )
        """,
        (current_date,),
    ).fetchone()
    return row[0] if row and row[0] else None
