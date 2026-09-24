from __future__ import annotations

import json
from typing import Any

from . import db
from .config import ACTIVE_SOURCE_BY_KEY, ACTIVE_SOURCE_KEYS, DB_PATH
from .redaction import redact_sensitive


def status_snapshot(db_path=DB_PATH) -> dict[str, Any]:
    db.init_db(db_path)
    conn = db.connect(db_path)
    run = db.latest_run(conn)
    if run is None:
        conn.close()
        return {
            "status": "never_run",
            "latest_run": None,
            "sources": [
                {
                    "source_key": key,
                    "source_name": ACTIVE_SOURCE_BY_KEY[key].name,
                    "market": ACTIVE_SOURCE_BY_KEY[key].market,
                    "status": "not_run",
                }
                for key in ACTIVE_SOURCE_KEYS
            ],
        }

    source_runs = db.source_results(conn, int(run["id"]))
    by_key = {row["source_key"]: row for row in source_runs}
    source_status = []
    for key in ACTIVE_SOURCE_KEYS:
        row = by_key.get(key)
        source_status.append(
            {
                "source_key": key,
                "source_name": ACTIVE_SOURCE_BY_KEY[key].name,
                "market": ACTIVE_SOURCE_BY_KEY[key].market,
                "status": row["status"] if row else "missing",
                "listing_count": row["listing_count"] if row else 0,
                "query_count": row["query_count"] if row else 0,
                "error": redact_sensitive(row["error"] if row else None),
                "started_at": row["started_at"] if row else None,
                "finished_at": row["finished_at"] if row else None,
            }
        )
    conn.close()
    return {
        "status": run["status"],
        "latest_run": {
            "run_id": run["id"],
            "run_date": run["run_date"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "metadata": json.loads(run["metadata_json"] or "{}"),
        },
        "sources": source_status,
    }
