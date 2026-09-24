from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import db
from .ai import (
    estimate_valuation,
    feedback_metrics,
    find_opportunities,
    list_feedback,
    normalize_storage_gb,
    record_feedback,
)
from .analytics import grouped_metrics, median_change, price_metrics
from .config import (
    ACTIVE_MARKET_ORDER,
    ACTIVE_SOURCE_BY_KEY,
    ACTIVE_SOURCE_KEYS,
    DB_PATH,
    DEFAULT_DASHBOARD_HOST,
    DEFAULT_DASHBOARD_PORT,
)
from .redaction import redact_sensitive


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def dashboard_data(
    db_path=DB_PATH,
    *,
    selected_date: str | None = None,
    market: str | None = None,
    model: str | None = None,
    storage_gb: int | None = None,
    source_key: str | None = None,
    listing_status: str = "active",
    include_raw: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    db.init_db(db_path)
    conn = db.connect(db_path)
    dates = _available_dates(conn)
    run_date = selected_date or (dates[0] if dates else None)
    if run_date not in dates and dates:
        run_date = dates[0]
    selected_market = (
        market if market in ACTIVE_MARKET_ORDER else ACTIVE_MARKET_ORDER[0]
    )
    selected_source = source_key if source_key in ACTIVE_SOURCE_BY_KEY else None

    rows: list = []
    previous_rows: list = []
    total = 0
    page_rows: list = []
    if run_date:
        all_rows = db.listing_rows(
            conn,
            run_date,
            market=selected_market,
            model=model,
            storage_gb=storage_gb,
            source_key=selected_source,
            include_excluded=include_raw,
            include_inactive=listing_status != "active",
        )
        all_rows = _active_rows(all_rows)
        if listing_status == "sold":
            all_rows = [row for row in all_rows if row["listing_status"] == "sold"]
        elif listing_status == "active":
            all_rows = [row for row in all_rows if row["listing_status"] == "active"]
        rows = all_rows
        total = len(rows)
        page_rows = rows[offset : offset + limit]

        previous_date = db.previous_date(conn, run_date)
        if previous_date:
            previous_rows = db.listing_rows(
                conn,
                previous_date,
                market=selected_market,
                model=model,
                storage_gb=storage_gb,
                source_key=selected_source,
                include_excluded=False,
                include_inactive=False,
            )
            previous_rows = _active_rows(previous_rows)

    metrics = price_metrics(rows)
    previous_metrics = price_metrics(previous_rows) if previous_rows else None
    metrics["previous_median"] = (
        previous_metrics.get("median") if previous_metrics else None
    )
    metrics["median_change"] = median_change(metrics, previous_metrics)

    filter_options = _filter_options(conn, run_date)
    run = db.latest_run_for_date(conn, run_date) if run_date else None
    source_rows = db.source_results(conn, int(run["id"])) if run else []
    health_by_key = {row["source_key"]: row for row in source_rows}
    source_health = []
    for key in ACTIVE_SOURCE_KEYS:
        row = health_by_key.get(key)
        source_health.append(
            {
                "source_key": key,
                "source_name": ACTIVE_SOURCE_BY_KEY[key].name,
                "market": ACTIVE_SOURCE_BY_KEY[key].market,
                "status": row["status"] if row else "missing",
                "listing_count": row["listing_count"] if row else 0,
                "query_count": row["query_count"] if row else 0,
                "error": redact_sensitive(row["error"] if row else None),
                "finished_at": row["finished_at"] if row else None,
            }
        )

    result = {
        "run": {
            "run_id": run["id"] if run else None,
            "run_date": run_date,
            "status": run["status"] if run else "no_data",
            "started_at": run["started_at"] if run else None,
            "finished_at": run["finished_at"] if run else None,
            "metadata": json.loads(run["metadata_json"] or "{}") if run else {},
        },
        "filters": {
            "dates": dates,
            "markets": filter_options["markets"],
            "models": filter_options["models"],
            "storages": filter_options["storages"],
            "sources": filter_options["sources"],
            "selected": {
                "date": run_date,
                "market": selected_market,
                "model": model,
                "storage_gb": storage_gb,
                "source_key": selected_source,
                "listing_status": listing_status,
                "include_raw": include_raw,
            },
        },
        "metrics": metrics,
        "groups": _group_payload(rows, previous_rows),
        "source_health": source_health,
        "listings": [_listing_payload(row) for row in page_rows],
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        },
    }
    conn.close()
    return result


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], db_path: Path):
        self.db_path = db_path
        super().__init__(address, DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(DASHBOARD_HTML)
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/data":
            try:
                params = parse_qs(parsed.query)
                payload = dashboard_data(
                    self.server.db_path,
                    selected_date=_first(params, "date"),
                    market=_first(params, "market"),
                    model=_first(params, "model"),
                    storage_gb=_int_or_none(_first(params, "storage")),
                    source_key=_first(params, "source"),
                    listing_status=_first(params, "status") or "active",
                    include_raw=_first(params, "raw") == "1",
                    limit=min(max(_int_or_none(_first(params, "limit")) or 100, 1), 500),
                    offset=max(_int_or_none(_first(params, "offset")) or 0, 0),
                )
                self._send_json(payload)
            except Exception as exc:
                self._send_json(
                    {"error": f"{type(exc).__name__}: {exc}"},
                    status=500,
                )
            return
        if parsed.path == "/api/ai/valuation":
            try:
                params = parse_qs(parsed.query)
                model = _first(params, "model")
                storage_value = _first(params, "storage")
                if not model or not storage_value:
                    self._send_json(
                        {"error": "model 和 storage 为必填参数"},
                        status=400,
                    )
                    return
                payload = estimate_valuation(
                    model=model,
                    storage_gb=normalize_storage_gb(storage_value),
                    market=_first(params, "market") or "香港",
                    as_of_date=_first(params, "date"),
                    lookback_days=_bounded_int(
                        _first(params, "lookback_days"),
                        default=45,
                        minimum=1,
                        maximum=365,
                    ),
                    target_margin_pct=_bounded_float(
                        _first(params, "margin"),
                        default=12.0,
                        minimum=0,
                        maximum=40,
                    ),
                    db_path=self.server.db_path,
                )
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json(
                    {"error": f"{type(exc).__name__}: {exc}"},
                    status=500,
                )
            return
        if parsed.path == "/api/ai/opportunities":
            try:
                params = parse_qs(parsed.query)
                model = _first(params, "model")
                storage_value = _first(params, "storage")
                if not model or not storage_value:
                    self._send_json(
                        {"error": "model 和 storage 为必填参数"},
                        status=400,
                    )
                    return
                payload = find_opportunities(
                    model=model,
                    storage_gb=normalize_storage_gb(storage_value),
                    market=_first(params, "market") or "香港",
                    as_of_date=_first(params, "date"),
                    limit=_bounded_int(
                        _first(params, "limit"),
                        default=10,
                        minimum=1,
                        maximum=100,
                    ),
                    fee_pct=_bounded_float(
                        _first(params, "fee_pct"),
                        default=12.0,
                        minimum=0,
                        maximum=40,
                    ),
                    db_path=self.server.db_path,
                )
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json(
                    {"error": f"{type(exc).__name__}: {exc}"},
                    status=500,
                )
            return
        if parsed.path == "/api/ai/feedback/metrics":
            try:
                params = parse_qs(parsed.query)
                payload = feedback_metrics(
                    market=_first(params, "market"),
                    model=_first(params, "model"),
                    storage_gb=_optional_storage(_first(params, "storage")),
                    db_path=self.server.db_path,
                )
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json(
                    {"error": f"{type(exc).__name__}: {exc}"},
                    status=500,
                )
            return
        if parsed.path == "/api/ai/feedback":
            try:
                params = parse_qs(parsed.query)
                payload = list_feedback(
                    market=_first(params, "market"),
                    model=_first(params, "model"),
                    storage_gb=_optional_storage(_first(params, "storage")),
                    outcome=_first(params, "outcome"),
                    limit=_bounded_int(
                        _first(params, "limit"),
                        default=100,
                        minimum=1,
                        maximum=1000,
                    ),
                    db_path=self.server.db_path,
                )
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json(
                    {"error": f"{type(exc).__name__}: {exc}"},
                    status=500,
                )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/ai/feedback":
            self.send_error(404)
            return
        try:
            body = self._read_json()
            if not isinstance(body, dict):
                raise ValueError("请求体必须是 JSON 对象")
            payload = record_feedback(
                model=_required_text(body, "model"),
                storage_gb=_required_text(body, "storage"),
                market=body.get("market") or "香港",
                source_key=body.get("source_key") or body.get("source"),
                listing_id=body.get("listing_id"),
                valuation_date=body.get("valuation_date") or body.get("date"),
                decision=_required_text(body, "decision"),
                outcome=body.get("outcome") or "pending",
                decision_price_cny=body.get("decision_price_cny"),
                actual_purchase_cny=body.get("actual_purchase_cny"),
                actual_sale_cny=body.get("actual_sale_cny"),
                fees_cny=body.get("fees_cny") or 0,
                repair_cost_cny=body.get("repair_cost_cny") or 0,
                estimated_fair_cny=body.get("estimated_fair_cny"),
                fair_low_cny=body.get("fair_low_cny"),
                fair_high_cny=body.get("fair_high_cny"),
                suggested_purchase_cny=body.get("suggested_purchase_cny"),
                confidence_level=body.get("confidence_level"),
                notes=body.get("notes") or "",
                metadata=body.get("metadata") or {},
                auto_estimate=body.get("auto_estimate", True) is not False,
                db_path=self.server.db_path,
            )
            self._send_json(payload, status=201)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json(
                {"error": f"{type(exc).__name__}: {exc}"},
                status=500,
            )

    def log_message(self, format: str, *args) -> None:
        return

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length 无效") from exc
        if length <= 0:
            raise ValueError("请求体不能为空")
        if length > 1_000_000:
            raise ValueError("请求体不能超过 1MB")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体不是有效的 UTF-8 JSON") from exc


def serve(
    host: str = DEFAULT_DASHBOARD_HOST,
    port: int = DEFAULT_DASHBOARD_PORT,
    db_path: Path = DB_PATH,
) -> None:
    server = DashboardServer((host, port), db_path)
    thread = threading.Thread(target=server.serve_forever, name="iphone-market-dashboard")
    thread.daemon = True
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def _available_dates(conn) -> list[str]:
    source_placeholders = ",".join("?" for _ in ACTIVE_SOURCE_KEYS)
    market_placeholders = ",".join("?" for _ in ACTIVE_MARKET_ORDER)
    rows = conn.execute(
        f"""
        SELECT value FROM (
            SELECT cr.run_date AS value
            FROM collection_runs AS cr
            WHERE EXISTS (
                SELECT 1
                FROM source_runs AS sr
                WHERE sr.run_id = cr.id
                  AND sr.source_key IN ({source_placeholders})
            )
            UNION
            SELECT DISTINCT collected_date AS value
            FROM listings
            WHERE source_key IN ({source_placeholders})
              AND market IN ({market_placeholders})
        )
        ORDER BY value DESC
        LIMIT 180
        """,
        (
            *ACTIVE_SOURCE_KEYS,
            *ACTIVE_SOURCE_KEYS,
            *ACTIVE_MARKET_ORDER,
        ),
    ).fetchall()
    return [row["value"] for row in rows if row["value"]]


def _active_rows(rows):
    return [
        row
        for row in rows
        if row["market"] in ACTIVE_MARKET_ORDER
        and row["source_key"] in ACTIVE_SOURCE_BY_KEY
    ]


def _filter_options(conn, run_date: str | None) -> dict[str, list]:
    if not run_date:
        return {
            "markets": list(ACTIVE_MARKET_ORDER),
            "models": [],
            "storages": [],
            "sources": [
                {"key": key, "name": ACTIVE_SOURCE_BY_KEY[key].name}
                for key in ACTIVE_SOURCE_KEYS
            ],
        }
    source_placeholders = ",".join("?" for _ in ACTIVE_SOURCE_KEYS)
    model_rows = conn.execute(
        f"SELECT DISTINCT model, generation, family FROM listings "
        f"WHERE collected_date=? AND source_key IN ({source_placeholders}) "
        "ORDER BY generation, family",
        (run_date, *ACTIVE_SOURCE_KEYS),
    ).fetchall()
    models = [row["model"] for row in model_rows]
    storages = [
        row[0]
        for row in conn.execute(
            f"SELECT DISTINCT storage_gb FROM listings "
            f"WHERE collected_date=? AND source_key IN ({source_placeholders}) "
            "AND storage_gb IS NOT NULL ORDER BY storage_gb",
            (run_date, *ACTIVE_SOURCE_KEYS),
        )
    ]
    source_keys = [
        row[0]
        for row in conn.execute(
            f"SELECT DISTINCT source_key FROM listings "
            f"WHERE collected_date=? AND source_key IN ({source_placeholders})",
            (run_date, *ACTIVE_SOURCE_KEYS),
        )
    ]
    for key in ACTIVE_SOURCE_KEYS:
        if key not in source_keys:
            source_keys.append(key)
    sources = [
        {"key": key, "name": ACTIVE_SOURCE_BY_KEY[key].name}
        for key in ACTIVE_SOURCE_KEYS
        if key in source_keys
    ]
    return {
        "markets": list(ACTIVE_MARKET_ORDER),
        "models": models,
        "storages": storages,
        "sources": sources,
    }


def _group_payload(rows, previous_rows=None) -> list[dict]:
    key_names = ("market", "model", "storage_gb", "source_key")
    groups = grouped_metrics(rows, key_names)
    previous_groups = grouped_metrics(previous_rows or [], key_names)
    previous_by_key = {
        tuple(item.get(name) for name in key_names): item for item in previous_groups
    }
    names = {key: ACTIVE_SOURCE_BY_KEY[key].name for key in ACTIVE_SOURCE_KEYS}
    for item in groups:
        key = tuple(item.get(name) for name in key_names)
        item["median_change"] = median_change(item, previous_by_key.get(key))
        item["source_name"] = names.get(item["source_key"], item["source_key"])
        item["storage_label"] = _storage_label(item["storage_gb"])
    return groups


def _listing_payload(row) -> dict:
    return {
        "id": row["id"],
        "source_key": row["source_key"],
        "source_name": row["source_name"],
        "market": row["market"],
        "title": row["title"],
        "url": row["url"],
        "model": row["model"],
        "storage_gb": row["storage_gb"],
        "storage_label": _storage_label(row["storage_gb"]),
        "condition": row["condition"],
        "listing_status": row["listing_status"],
        "price_native": row["price_native"],
        "currency": row["currency"],
        "price_cny": row["price_cny"],
        "fx_date": row["fx_date"],
        "location": row["location"],
        "seen_at": row["seen_at"],
    }


def _storage_label(storage_gb: int | None) -> str:
    if storage_gb == 1024:
        return "1TB"
    if storage_gb == 2048:
        return "2TB"
    return f"{storage_gb}GB" if storage_gb else "-"


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"{key} 为必填参数")
    return str(value).strip()


def _optional_storage(value: str | None) -> int | None:
    return normalize_storage_gb(value) if value else None


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _bounded_int(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = default if value is None else int(value)
    except ValueError as exc:
        raise ValueError("整数参数格式无效") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"参数必须在 {minimum} 到 {maximum} 之间")
    return parsed


def _bounded_float(
    value: str | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = default if value is None else float(value)
    except ValueError as exc:
        raise ValueError("数值参数格式无效") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"参数必须在 {minimum} 到 {maximum} 之间")
    return parsed


DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>香港二手 iPhone 价格看板</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-2: #edf2f7;
      --text: #172033;
      --muted: #60708a;
      --border: #d8e0e9;
      --primary: #1e40af;
      --primary-soft: #e8edff;
      --accent: #b45309;
      --ok: #147a52;
      --ok-soft: #e5f6ee;
      --warn: #9a5b00;
      --warn-soft: #fff3d6;
      --danger: #b42318;
      --danger-soft: #feeceb;
      --shadow: 0 1px 2px rgba(23, 32, 51, .06);
      --radius: 8px;
    }
    * { box-sizing: border-box; }
    html { background: var(--bg); }
    body {
      margin: 0;
      color: var(--text);
      background: var(--bg);
      font-family: "Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
      font-size: 15px;
      line-height: 1.5;
    }
    button, select, input { font: inherit; }
    button, select, a { -webkit-tap-highlight-color: transparent; }
    a { color: var(--primary); }
    .app-header {
      background: #111c33;
      color: #fff;
      border-bottom: 1px solid #273653;
    }
    .header-inner {
      width: min(1500px, calc(100% - 40px));
      margin: 0 auto;
      min-height: 108px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
      padding: 18px 0;
    }
    .eyebrow {
      color: #aebbd3;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    h1 {
      font-size: 26px;
      line-height: 1.2;
      margin: 4px 0 6px;
      letter-spacing: 0;
    }
    .header-copy {
      color: #c8d2e3;
      margin: 0;
      font-size: 14px;
    }
    .run-meta {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 12px;
      flex-wrap: wrap;
    }
    .run-pill {
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      padding: 6px 10px;
      border: 1px solid #43506c;
      border-radius: 999px;
      background: #172541;
      color: #e8edf7;
      white-space: nowrap;
      font-size: 13px;
    }
    .icon-button {
      min-height: 40px;
      min-width: 40px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 8px 12px;
      border: 1px solid #52617f;
      border-radius: var(--radius);
      color: #fff;
      background: #223252;
      cursor: pointer;
      transition: background .18s ease, border-color .18s ease;
    }
    .icon-button:hover { background: #2e4167; border-color: #7180a0; }
    .icon-button:focus-visible, select:focus-visible, input:focus-visible, a:focus-visible {
      outline: 3px solid #93b4ff;
      outline-offset: 2px;
    }
    main {
      width: min(1500px, calc(100% - 40px));
      margin: 0 auto 48px;
    }
    .filter-band {
      margin-top: 20px;
      padding: 14px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .filter-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(130px, 1fr)) auto;
      gap: 12px;
      align-items: end;
    }
    .field label {
      display: block;
      margin-bottom: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    select, input[type="text"] {
      width: 100%;
      min-height: 42px;
      border: 1px solid #c8d2df;
      border-radius: 6px;
      padding: 8px 10px;
      color: var(--text);
      background: #fff;
    }
    .raw-toggle {
      min-height: 42px;
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
      white-space: nowrap;
      padding: 0 4px;
    }
    .raw-toggle input { width: 18px; height: 18px; accent-color: var(--primary); }
    .alert {
      display: none;
      margin-top: 14px;
      border: 1px solid #f1b4ae;
      border-radius: var(--radius);
      padding: 11px 13px;
      color: #7a271a;
      background: var(--danger-soft);
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(6, minmax(130px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }
    .metric {
      min-height: 102px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow);
      padding: 14px;
    }
    .metric-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .metric-value {
      margin-top: 10px;
      font-family: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 22px;
      font-weight: 700;
      white-space: nowrap;
    }
    .metric-note {
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      min-height: 18px;
    }
    .ai-kpi-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 12px;
    }
    .ai-kpi {
      min-width: 0;
      min-height: 112px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow);
      padding: 14px;
    }
    .ai-kpi-wide { grid-column: 1 / -1; }
    .ai-kpi-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .ai-kpi-value {
      margin-top: 9px;
      font-family: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 20px;
      font-weight: 700;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .ai-kpi-note {
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
      overflow-wrap: anywhere;
    }
    .ai-detail-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr);
      gap: 12px;
      margin-top: 12px;
    }
    .ai-panel {
      min-width: 0;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .ai-panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 11px 13px;
      border-bottom: 1px solid var(--border);
      background: #f8fafc;
    }
    .ai-panel h3 {
      margin: 0;
      font-size: 14px;
      letter-spacing: 0;
    }
    .ai-panel-body {
      min-width: 0;
      padding: 4px 13px 12px;
    }
    .ai-empty {
      padding: 22px 4px;
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    .ai-empty strong {
      display: block;
      margin-bottom: 4px;
      color: var(--text);
    }
    .opportunity-item {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
      padding: 11px 0;
      border-bottom: 1px solid #e8edf3;
    }
    .opportunity-item:last-child { border-bottom: 0; }
    .opportunity-title {
      min-width: 0;
      color: var(--text);
      font-weight: 600;
      line-height: 1.35;
      text-decoration: none;
      overflow-wrap: anywhere;
    }
    .opportunity-title:hover { color: var(--primary); text-decoration: underline; }
    .opportunity-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 5px 10px;
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .opportunity-score {
      min-width: 72px;
      text-align: right;
    }
    .opportunity-score strong {
      display: block;
      font-family: "Cascadia Mono", Consolas, monospace;
      font-size: 18px;
    }
    .opportunity-score span {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 11px;
    }
    .ai-stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px 16px;
      padding: 10px 0 4px;
    }
    .ai-stat-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .ai-stat-value {
      margin-top: 3px;
      font-family: "Cascadia Mono", Consolas, monospace;
      font-size: 16px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .ai-recommendation {
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid #e8edf3;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    .positive { color: var(--danger); }
    .negative { color: var(--ok); }
    .section {
      margin-top: 20px;
    }
    .section-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 9px;
    }
    h2 {
      margin: 0;
      font-size: 17px;
      letter-spacing: 0;
    }
    .section-note {
      color: var(--muted);
      font-size: 13px;
    }
    .health-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
    }
    .health-item {
      min-width: 0;
      min-height: 104px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      padding: 12px;
      box-shadow: var(--shadow);
    }
    .health-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
    }
    .health-name {
      min-width: 0;
      font-weight: 700;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .health-market {
      color: var(--muted);
      font-size: 12px;
      margin-top: 3px;
    }
    .status-chip {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .status-ok { color: var(--ok); background: var(--ok-soft); }
    .status-partial, .status-running { color: var(--warn); background: var(--warn-soft); }
    .status-failed, .status-missing { color: var(--danger); background: var(--danger-soft); }
    .health-count {
      margin-top: 12px;
      font-family: "Cascadia Mono", Consolas, monospace;
      font-size: 13px;
    }
    .health-error {
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .table-shell {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .table-scroll { overflow-x: auto; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      color: #4f5e74;
      background: #edf1f6;
      text-align: left;
      font-size: 12px;
      font-weight: 700;
      padding: 10px 11px;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    td {
      padding: 10px 11px;
      border-bottom: 1px solid #e8edf3;
      vertical-align: top;
    }
    tbody tr:hover { background: #f8fafc; }
    tbody tr:last-child td { border-bottom: 0; }
    .listing-title {
      display: inline-flex;
      align-items: flex-start;
      gap: 5px;
      min-width: 230px;
      max-width: 440px;
      line-height: 1.35;
      font-weight: 600;
      text-decoration: none;
    }
    .listing-title:hover { text-decoration: underline; }
    .external-icon { flex: 0 0 auto; margin-top: 3px; }
    .subtle { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .money {
      font-family: "Cascadia Mono", Consolas, monospace;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }
    .empty {
      padding: 42px 18px;
      text-align: center;
      color: var(--muted);
    }
    .empty strong {
      display: block;
      color: var(--text);
      font-size: 16px;
      margin-bottom: 5px;
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 11px 12px;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 13px;
    }
    .pager-actions { display: flex; gap: 8px; }
    .pager button {
      min-height: 36px;
      padding: 6px 11px;
      border: 1px solid #c8d2df;
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      cursor: pointer;
    }
    .pager button:hover:not(:disabled) { background: var(--surface-2); }
    .pager button:disabled { opacity: .45; cursor: not-allowed; }
    .skeleton {
      display: inline-block;
      min-width: 54px;
      height: 16px;
      border-radius: 4px;
      background: #e4e9f0;
      animation: pulse 1.2s ease-in-out infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: .6; }
      50% { opacity: 1; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
    }
    @media (max-width: 1180px) {
      .filter-grid { grid-template-columns: repeat(3, minmax(140px, 1fr)); }
      .metrics { grid-template-columns: repeat(3, minmax(140px, 1fr)); }
      .ai-kpi-grid { grid-template-columns: repeat(2, minmax(160px, 1fr)); }
      .ai-detail-grid { grid-template-columns: minmax(0, 1fr); }
      .health-grid { grid-template-columns: repeat(3, minmax(150px, 1fr)); }
    }
    @media (max-width: 720px) {
      .header-inner, main { width: min(100% - 24px, 1500px); }
      .header-inner { align-items: flex-start; flex-direction: column; padding: 18px 0; }
      .run-meta { justify-content: flex-start; }
      h1 { font-size: 22px; }
      .filter-grid { grid-template-columns: 1fr 1fr; }
      .metrics { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      .ai-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .ai-detail-grid { grid-template-columns: minmax(0, 1fr); }
      .health-grid { grid-template-columns: minmax(0, 1fr); }
      .wide { grid-column: 1 / -1; }
      thead { display: none; }
      table, tbody, tr, td { display: block; width: 100%; }
      tbody tr { padding: 10px 12px; border-bottom: 1px solid var(--border); }
      tbody tr:last-child { border-bottom: 0; }
      td {
        display: grid;
        grid-template-columns: 94px minmax(0, 1fr);
        gap: 8px;
        border: 0;
        padding: 5px 0;
      }
      td::before {
        content: attr(data-label);
        color: var(--muted);
        font-size: 12px;
        font-weight: 700;
      }
      .listing-title { min-width: 0; max-width: none; }
      .table-scroll { overflow: visible; }
    }
    @media (max-width: 440px) {
      .filter-grid, .metrics, .ai-kpi-grid, .ai-stat-grid { grid-template-columns: 1fr; }
      .wide { grid-column: auto; }
      .opportunity-item { grid-template-columns: minmax(0, 1fr); }
      .opportunity-score { text-align: left; }
    }
  </style>
</head>
<body>
  <header class="app-header">
    <div class="header-inner">
      <div>
        <div class="eyebrow">本地采集</div>
        <h1>香港二手 iPhone 价格看板</h1>
        <p class="header-copy">Carousell HK 与 DCFever 的公开在售与可见状态数据</p>
      </div>
      <div class="run-meta">
        <span class="run-pill" id="run-meta">正在读取运行状态...</span>
        <button class="icon-button" id="refresh-button" type="button" aria-label="刷新数据">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 12A9 9 0 0 1 18.5 5.8L21 8"/><path d="M3 16v-4h4"/><path d="M21 8V4h-4"/></svg>
          刷新
        </button>
      </div>
    </div>
  </header>
  <main>
    <section class="filter-band" aria-label="数据筛选">
      <form class="filter-grid" id="filter-form">
        <div class="field">
          <label for="date-filter">日期</label>
          <select id="date-filter" name="date"></select>
        </div>
        <div class="field">
          <label for="market-filter">市场</label>
          <select id="market-filter" name="market"><option value="">全部市场</option></select>
        </div>
        <div class="field">
          <label for="model-filter">机型</label>
          <select id="model-filter" name="model"><option value="">全部机型</option></select>
        </div>
        <div class="field">
          <label for="storage-filter">容量</label>
          <select id="storage-filter" name="storage"><option value="">全部容量</option></select>
        </div>
        <div class="field">
          <label for="source-filter">来源</label>
          <select id="source-filter" name="source"><option value="">全部来源</option></select>
        </div>
        <div class="field">
          <label for="status-filter">列表状态</label>
          <select id="status-filter" name="status">
            <option value="active">在售</option>
            <option value="sold">已售或已结束</option>
            <option value="all">全部状态</option>
          </select>
        </div>
        <label class="raw-toggle wide" for="raw-filter">
          <input type="checkbox" id="raw-filter" name="raw">
          包含非默认条件记录
        </label>
      </form>
    </section>
    <div class="alert" id="error-alert" role="alert"></div>

    <section class="metrics" aria-label="价格指标">
      <div class="metric"><div class="metric-label">有效样本</div><div class="metric-value" id="metric-count"><span class="skeleton"></span></div><div class="metric-note" id="metric-count-note"></div></div>
      <div class="metric"><div class="metric-label">最低价</div><div class="metric-value" id="metric-min"><span class="skeleton"></span></div><div class="metric-note">人民币换算</div></div>
      <div class="metric"><div class="metric-label">P25</div><div class="metric-value" id="metric-p25"><span class="skeleton"></span></div><div class="metric-note">第一四分位数</div></div>
      <div class="metric"><div class="metric-label">中位数</div><div class="metric-value" id="metric-median"><span class="skeleton"></span></div><div class="metric-note" id="metric-median-note"></div></div>
      <div class="metric"><div class="metric-label">P75</div><div class="metric-value" id="metric-p75"><span class="skeleton"></span></div><div class="metric-note">第三四分位数</div></div>
      <div class="metric"><div class="metric-label">最高价</div><div class="metric-value" id="metric-max"><span class="skeleton"></span></div><div class="metric-note">人民币换算</div></div>
    </section>

    <section class="section" aria-label="AI 估值与机会">
      <div class="section-head">
        <h2>AI 估值与机会</h2>
        <div class="section-note" id="ai-note">选择机型和容量后生成</div>
      </div>
      <div class="ai-kpi-grid" id="ai-valuation"></div>
      <div class="ai-detail-grid">
        <div class="ai-panel">
          <div class="ai-panel-head">
            <h3>优先机会</h3>
            <span class="section-note" id="ai-opportunity-count"></span>
          </div>
          <div class="ai-panel-body" id="ai-opportunities"></div>
        </div>
        <div class="ai-panel">
          <div class="ai-panel-head">
            <h3>反馈验收</h3>
            <span class="status-chip status-partial" id="ai-feedback-status">待选择</span>
          </div>
          <div class="ai-panel-body" id="ai-feedback"></div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>来源运行状态</h2>
        <div class="section-note" id="source-note">按最近一次对应日期的采集运行展示</div>
      </div>
      <div class="health-grid" id="health-grid"></div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>市场、机型与容量统计</h2>
        <div class="section-note" id="group-note"></div>
      </div>
      <div class="table-shell">
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>市场</th><th>机型</th><th>容量</th><th>来源</th><th>数量</th>
                <th>最低价</th><th>P25</th><th>中位数</th><th>环比</th><th>P75</th><th>最高价</th>
              </tr>
            </thead>
            <tbody id="group-body"></tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>商品列表</h2>
        <div class="section-note" id="listing-note">默认仅显示可正常使用的在售二手机</div>
      </div>
      <div class="table-shell">
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>标题</th><th>来源</th><th>机型</th><th>状态</th>
                <th>原币价格</th><th>人民币</th><th>位置</th><th>采集时间</th>
              </tr>
            </thead>
            <tbody id="listing-body"></tbody>
          </table>
        </div>
        <div class="pager">
          <span id="pager-text">-</span>
          <div class="pager-actions">
            <button id="prev-page" type="button">上一页</button>
            <button id="next-page" type="button">下一页</button>
          </div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const state = {
      data: null,
      offset: 0,
      limit: 100,
      aiRequestId: 0,
      filtersReady: false
    };
    const el = id => document.getElementById(id);

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      })[char]);
    }

    function cny(value) {
      if (value === null || value === undefined) return "-";
      return "¥" + Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    }

    function cnyChange(value) {
      if (value === null || value === undefined) return "-";
      const formatted = cny(Math.abs(Number(value)));
      if (value > 0) return `+${formatted}`;
      if (value < 0) return `-${formatted}`;
      return formatted;
    }

    function nativePrice(value, currency) {
      if (value === null || value === undefined) return "-";
      const formatted = Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
      return `${currency} ${formatted}`;
    }

    function statusLabel(value) {
      return ({ ok: "正常", partial: "部分失败", failed: "失败", running: "运行中", missing: "未运行" })[value] || value;
    }

    function statusClass(value) {
      if (value === "ok") return "status-ok";
      if (value === "partial" || value === "running") return "status-partial";
      return "status-failed";
    }

    function storageLabel(value) {
      if (value === 1024) return "1TB";
      if (value === 2048) return "2TB";
      return value ? value + "GB" : "-";
    }

    function setUrlState(values = readFilters()) {
      const params = new URLSearchParams();
      Object.entries(values).forEach(([key, value]) => {
        if (value !== "" && value !== false && value !== null) params.set(key, String(value));
      });
      history.replaceState(null, "", location.pathname + (params.toString() ? "?" + params.toString() : ""));
    }

    function readFilters() {
      return {
        date: el("date-filter").value,
        market: el("market-filter").value,
        model: el("model-filter").value,
        storage: el("storage-filter").value,
        source: el("source-filter").value,
        status: el("status-filter").value,
        raw: el("raw-filter").checked ? "1" : ""
      };
    }

    function restoreFilters() {
      const params = new URLSearchParams(location.search);
      return {
        date: params.get("date") || "",
        market: params.get("market") || "",
        model: params.get("model") || "",
        storage: params.get("storage") || "",
        source: params.get("source") || "",
        status: params.get("status") || "active",
        raw: params.get("raw") === "1"
      };
    }

    function setOptions(select, values, placeholder, selected) {
      const previous = selected ?? select.value;
      select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` +
        values.map(item => {
          const value = typeof item === "object" ? item.key : item;
          const label = typeof item === "object" ? item.name : (typeof item === "number" ? storageLabel(item) : item);
          return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
        }).join("");
      select.value = previous || "";
      if (select.value !== String(previous || "")) select.value = "";
    }

    function ensureSelectedOption(select, value, label) {
      if (value === null || value === undefined || value === "") return;
      const stringValue = String(value);
      if (!Array.from(select.options).some(option => option.value === stringValue)) {
        select.insertAdjacentHTML(
          "beforeend",
          `<option value="${escapeHtml(stringValue)}">${escapeHtml(label || stringValue)}</option>`
        );
      }
      select.value = stringValue;
    }

    function renderFilterOptions(payload) {
      const saved = restoreFilters();
      const filters = payload.filters;
      setOptions(el("date-filter"), filters.dates, "暂无日期", saved.date || filters.selected.date || "");
      setOptions(el("market-filter"), filters.markets, "全部市场", saved.market || filters.selected.market || "");
      setOptions(el("model-filter"), filters.models, "全部机型", saved.model || filters.selected.model || "");
      setOptions(el("storage-filter"), filters.storages, "全部容量", saved.storage || filters.selected.storage_gb || "");
      ensureSelectedOption(
        el("model-filter"),
        saved.model || filters.selected.model,
        saved.model || filters.selected.model
      );
      ensureSelectedOption(
        el("storage-filter"),
        saved.storage || filters.selected.storage_gb,
        storageLabel(Number(saved.storage || filters.selected.storage_gb))
      );
      setOptions(el("source-filter"), filters.sources, "全部来源", saved.source || filters.selected.source_key || "");
      el("status-filter").value = saved.status || filters.selected.listing_status || "active";
      el("raw-filter").checked = saved.raw || filters.selected.include_raw;
    }

    function renderMetrics(metrics) {
      el("metric-count").textContent = Number(metrics.count || 0).toLocaleString("zh-CN");
      el("metric-min").textContent = cny(metrics.min);
      el("metric-p25").textContent = cny(metrics.p25);
      el("metric-median").textContent = cny(metrics.median);
      el("metric-p75").textContent = cny(metrics.p75);
      el("metric-max").textContent = cny(metrics.max);
      el("metric-count-note").textContent = metrics.count ? "当前筛选条件下" : "暂无可用价格";
      const change = metrics.median_change;
      const note = el("metric-median-note");
      note.className = "metric-note";
      if (change === null || change === undefined) {
        note.textContent = "暂无环比基准";
      } else {
        const sign = change > 0 ? "+" : "";
        note.textContent = `环比 ${sign}${Number(change).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
        note.classList.add(change > 0 ? "positive" : change < 0 ? "negative" : "");
      }
    }

    function aiKpi(label, value, note, className = "") {
      return `<div class="ai-kpi ${className}">
        <div class="ai-kpi-label">${escapeHtml(label)}</div>
        <div class="ai-kpi-value">${escapeHtml(value)}</div>
        <div class="ai-kpi-note">${escapeHtml(note || "")}</div>
      </div>`;
    }

    function formatPct(value) {
      if (value === null || value === undefined) return "-";
      return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + "%";
    }

    function confidenceLabel(value) {
      return ({ high: "高", medium: "中", low: "低", none: "不足" })[value] || "未知";
    }

    function confidenceClass(value) {
      if (value === "high") return "status-ok";
      if (value === "medium") return "status-partial";
      return "status-failed";
    }

    function feedbackStatusLabel(value) {
      return ({
        usable: "可比较",
        exploratory: "探索中",
        insufficient_data: "样本不足"
      })[value] || "未知";
    }

    function feedbackStatusClass(value) {
      if (value === "usable") return "status-ok";
      if (value === "exploratory") return "status-partial";
      return "status-failed";
    }

    function renderAiEmpty(message, detail = "") {
      el("ai-note").textContent = detail || "选择机型和容量后生成";
      el("ai-valuation").innerHTML = aiKpi("等待筛选", message, detail, "ai-kpi-wide");
      el("ai-opportunity-count").textContent = "";
      el("ai-opportunities").innerHTML = `<div class="ai-empty"><strong>${escapeHtml(message)}</strong>${escapeHtml(detail)}</div>`;
      el("ai-feedback-status").className = "status-chip status-partial";
      el("ai-feedback-status").textContent = "待评估";
      el("ai-feedback").innerHTML = `<div class="ai-empty">真实收购和转售结果会在这里累计，样本不足时不会给出准确率结论。</div>`;
    }

    function renderAiLoading() {
      el("ai-note").textContent = "正在计算当前机型容量...";
      const skeleton = `<div class="ai-kpi"><div class="ai-kpi-label"><span class="skeleton"></span></div><div class="ai-kpi-value"><span class="skeleton"></span></div><div class="ai-kpi-note"><span class="skeleton"></span></div></div>`;
      el("ai-valuation").innerHTML = skeleton.repeat(4);
      el("ai-opportunity-count").textContent = "计算中";
      el("ai-opportunities").innerHTML = `<div class="ai-empty"><strong>正在扫描机会</strong>按当前同款估值计算净差额和排序。</div>`;
      el("ai-feedback-status").className = "status-chip status-partial";
      el("ai-feedback-status").textContent = "读取中";
      el("ai-feedback").innerHTML = `<div class="ai-empty">正在读取真实成交反馈。</div>`;
    }

    function renderAiValuation(payload, error) {
      if (error) {
        el("ai-note").textContent = "估值暂不可用";
        el("ai-valuation").innerHTML = aiKpi("估值状态", "暂不可用", error.message, "ai-kpi-wide");
        return;
      }
      if (!payload || payload.status !== "ok") {
        const reason = (payload?.warnings || [])[0] || payload?.confidence?.reason || "当前筛选下没有足够样本。";
        el("ai-note").textContent = payload?.model
          ? `${payload.market || "香港"} · ${payload.model} ${payload.storage_label || ""} · ${payload.as_of_date || "-"}`
          : "估值暂不可用";
        el("ai-valuation").innerHTML = aiKpi(
          "样本不足",
          "暂不估算",
          reason,
          "ai-kpi-wide"
        );
        return;
      }
      const fair = payload.fair_range_cny;
      const guidance = payload.guidance_cny;
      const confidence = payload.confidence || {};
      const nativeRange = payload.fair_range_native
        ? `${nativePrice(payload.fair_range_native.low, payload.fair_range_native.currency)} - ${nativePrice(payload.fair_range_native.high, payload.fair_range_native.currency)}`
        : "人民币为统一比较口径";
      const rejected = Number(payload.rejected_outliers || 0);
      const confidenceNote = `${Number(payload.sample_count || 0)} 条样本${rejected ? ` · 剔除 ${rejected} 条极端价` : ""} · ${confidence.reason || ""}`;
      el("ai-note").textContent = `${payload.market} · ${payload.model} ${payload.storage_label} · ${payload.as_of_date} · 近 ${payload.lookback_days} 天`;
      el("ai-valuation").innerHTML = [
        aiKpi(
          "合理区间",
          `${cny(fair.low)} - ${cny(fair.high)}`,
          `${cny(fair.mid)} 中位 · ${nativeRange}`
        ),
        aiKpi(
          "建议收购上限",
          cny(guidance.suggested_purchase_max),
          `按 ${Number(guidance.target_margin_pct || 0).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}% 目标毛利`
        ),
        aiKpi(
          "转售参考",
          cny(guidance.suggested_resale),
          "按同款有效样本中位价估计"
        ),
        aiKpi(
          "置信度",
          confidenceLabel(confidence.level),
          confidenceNote
        )
      ].join("");
    }

    function renderAiOpportunities(payload, error) {
      const body = el("ai-opportunities");
      if (error) {
        el("ai-opportunity-count").textContent = "";
        body.innerHTML = `<div class="ai-empty"><strong>机会扫描暂不可用</strong>${escapeHtml(error.message)}</div>`;
        return;
      }
      const candidates = payload?.candidates || [];
      if (!payload || payload.status !== "ok") {
        el("ai-opportunity-count").textContent = "0 个";
        const reason = (payload?.warnings || [])[0] || "当前估值样本不足。";
        body.innerHTML = `<div class="ai-empty"><strong>暂不扫描机会</strong>${escapeHtml(reason)}</div>`;
        return;
      }
      el("ai-opportunity-count").textContent = `${candidates.length.toLocaleString("zh-CN")} 个`;
      if (!candidates.length) {
        body.innerHTML = `<div class="ai-empty"><strong>没有正收益机会</strong>当前在售价加上预估费用后，没有低于估值中位的有效商品。</div>`;
        return;
      }
      const priorityLabels = { high: "高优先", medium: "可跟进", watch: "观察" };
      body.innerHTML = candidates.slice(0, 5).map(item => {
        const risks = (item.risk_flags || []).length
          ? `<div class="opportunity-meta">${item.risk_flags.map(flag => `<span>${escapeHtml(flag)}</span>`).join("")}</div>`
          : "";
        return `<div class="opportunity-item">
          <div>
            <a class="opportunity-title" href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
            <div class="opportunity-meta">
              <span>${escapeHtml(item.source_name)}</span>
              <span>${nativePrice(item.price_native, item.currency)}</span>
              <span>净差额 ${cnyChange(item.estimated_net_spread_cny)}</span>
            </div>
            ${risks}
          </div>
          <div class="opportunity-score">
            <strong>${Number(item.opportunity_score || 0).toFixed(0)}</strong>
            <span>${escapeHtml(priorityLabels[item.priority] || item.priority)}</span>
          </div>
        </div>`;
      }).join("");
    }

    function renderAiFeedback(payload, error) {
      const status = el("ai-feedback-status");
      if (error) {
        status.className = "status-chip status-failed";
        status.textContent = "读取失败";
        el("ai-feedback").innerHTML = `<div class="ai-empty"><strong>反馈数据暂不可用</strong>${escapeHtml(error.message)}</div>`;
        return;
      }
      const evaluation = payload?.evaluation || {};
      const profit = payload?.profit || {};
      const evaluationStatus = evaluation.status || "insufficient_data";
      status.className = `status-chip ${feedbackStatusClass(evaluationStatus)}`;
      status.textContent = feedbackStatusLabel(evaluationStatus);
      const sampleCount = Number(evaluation.sold_with_valuation || 0);
      const minimumSamples = Number(evaluation.minimum_samples_for_usable || 30);
      el("ai-feedback").innerHTML = `
        <div class="ai-stat-grid">
          <div><div class="ai-stat-label">成交估值样本</div><div class="ai-stat-value">${sampleCount.toLocaleString("zh-CN")} / ${minimumSamples}</div></div>
          <div><div class="ai-stat-label">MAPE</div><div class="ai-stat-value">${formatPct(evaluation.mape_pct)}</div></div>
          <div><div class="ai-stat-label">平均绝对误差</div><div class="ai-stat-value">${cny(evaluation.mean_absolute_error_cny)}</div></div>
          <div><div class="ai-stat-label">区间覆盖率</div><div class="ai-stat-value">${formatPct(evaluation.fair_range_coverage_pct)}</div></div>
          <div><div class="ai-stat-label">累计净利润</div><div class="ai-stat-value">${cny(profit.total_net_profit_cny)}</div></div>
          <div><div class="ai-stat-label">中位 ROI</div><div class="ai-stat-value">${formatPct(profit.median_roi_pct)}</div></div>
        </div>
        <div class="ai-recommendation">${escapeHtml(payload?.recommendation || "继续录入真实收购和转售结果后再评估。")}</div>`;
    }

    async function fetchJson(path) {
      const response = await fetch(path, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      return payload;
    }

    async function loadAi() {
      const filters = readFilters();
      if (!filters.model || !filters.storage) {
        state.aiRequestId += 1;
        renderAiEmpty("请先选择机型和容量", "AI 估值需要明确的机型和容量，才能匹配同款样本。");
        return;
      }
      const requestId = ++state.aiRequestId;
      const market = filters.market || "香港";
      const params = new URLSearchParams({
        date: filters.date,
        market,
        model: filters.model,
        storage: filters.storage
      });
      const query = params.toString();
      renderAiLoading();
      const [valuationResult, opportunityResult, feedbackResult] = await Promise.allSettled([
        fetchJson("/api/ai/valuation?" + query),
        fetchJson("/api/ai/opportunities?" + query),
        fetchJson("/api/ai/feedback/metrics?" + query)
      ]);
      if (requestId !== state.aiRequestId) return;
      renderAiValuation(
        valuationResult.status === "fulfilled" ? valuationResult.value : null,
        valuationResult.status === "rejected" ? valuationResult.reason : null
      );
      renderAiOpportunities(
        opportunityResult.status === "fulfilled" ? opportunityResult.value : null,
        opportunityResult.status === "rejected" ? opportunityResult.reason : null
      );
      renderAiFeedback(
        feedbackResult.status === "fulfilled" ? feedbackResult.value : null,
        feedbackResult.status === "rejected" ? feedbackResult.reason : null
      );
    }

    function renderRunMeta(run) {
      const status = statusLabel(run.status);
      const finished = run.finished_at ? new Date(run.finished_at).toLocaleString("zh-CN", { hour12: false }) : "-";
      el("run-meta").textContent = `${run.run_date || "无日期"} · ${status} · ${finished}`;
    }

    function renderHealth(items) {
      el("health-grid").innerHTML = items.map(item => {
        const error = item.error ? `<div class="health-error" title="${escapeHtml(item.error)}">${escapeHtml(item.error)}</div>` : "";
        return `<article class="health-item">
          <div class="health-top">
            <div><div class="health-name">${escapeHtml(item.source_name)}</div><div class="health-market">${escapeHtml(item.market)}</div></div>
            <span class="status-chip ${statusClass(item.status)}">${escapeHtml(statusLabel(item.status))}</span>
          </div>
          <div class="health-count">${Number(item.listing_count || 0).toLocaleString("zh-CN")} 条 / ${Number(item.query_count || 0)} 查询</div>
          ${error}
        </article>`;
      }).join("");
    }

    function renderGroups(items) {
      const body = el("group-body");
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="11"><div class="empty"><strong>没有匹配的分组数据</strong>调整日期、市场或机型筛选后重试。</div></td></tr>`;
        return;
      }
      body.innerHTML = items.map(item => `<tr>
        <td data-label="市场">${escapeHtml(item.market)}</td>
        <td data-label="机型">${escapeHtml(item.model)}</td>
        <td data-label="容量">${escapeHtml(item.storage_label)}</td>
        <td data-label="来源">${escapeHtml(item.source_name)}</td>
        <td data-label="数量">${Number(item.count || 0).toLocaleString("zh-CN")}</td>
        <td data-label="最低价" class="money">${cny(item.min)}</td>
        <td data-label="P25" class="money">${cny(item.p25)}</td>
        <td data-label="中位数" class="money">${cny(item.median)}</td>
        <td data-label="环比" class="money ${item.median_change > 0 ? "positive" : item.median_change < 0 ? "negative" : ""}">${cnyChange(item.median_change)}</td>
        <td data-label="P75" class="money">${cny(item.p75)}</td>
        <td data-label="最高价" class="money">${cny(item.max)}</td>
      </tr>`).join("");
      el("group-note").textContent = `${items.length.toLocaleString("zh-CN")} 个统计分组`;
    }

    function renderListings(payload) {
      const items = payload.listings;
      const body = el("listing-body");
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="8"><div class="empty"><strong>没有匹配的商品</strong>尝试清除筛选或启用“包含非默认条件记录”。</div></td></tr>`;
      } else {
        body.innerHTML = items.map(item => {
          const statusText = item.listing_status === "sold" ? "已售/结束" : "在售";
          const conditionText = item.condition === "used" ? "" : ` · ${escapeHtml(item.condition)}`;
          return `<tr>
            <td data-label="标题">
              <a class="listing-title" href="${escapeHtml(item.url)}" target="_blank" rel="noopener">
                <span>${escapeHtml(item.title)}</span>
                <svg class="external-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>
              </a>
              <div class="subtle">${escapeHtml(item.market)}${conditionText}</div>
            </td>
            <td data-label="来源">${escapeHtml(item.source_name)}</td>
            <td data-label="机型">${escapeHtml(item.model)}<div class="subtle">${escapeHtml(item.storage_label)}</div></td>
            <td data-label="状态"><span class="status-chip ${item.listing_status === "sold" ? "status-partial" : "status-ok"}">${statusText}</span></td>
            <td data-label="原币价格" class="money">${nativePrice(item.price_native, item.currency)}</td>
            <td data-label="人民币" class="money">${cny(item.price_cny)}</td>
            <td data-label="位置">${escapeHtml(item.location || "-")}</td>
            <td data-label="采集时间">${escapeHtml(item.seen_at ? new Date(item.seen_at).toLocaleString("zh-CN", { hour12: false }) : "-")}</td>
          </tr>`;
        }).join("");
      }
      const pager = payload.pagination;
      const start = pager.total ? state.offset + 1 : 0;
      const end = Math.min(state.offset + state.limit, pager.total);
      el("pager-text").textContent = `显示 ${start}-${end} / ${pager.total} 条`;
      el("prev-page").disabled = state.offset <= 0;
      el("next-page").disabled = !pager.has_more;
      el("listing-note").textContent = el("raw-filter").checked
        ? "包含非默认条件记录，原始状态仍按采集结果展示"
        : "默认仅显示可正常使用的在售二手机";
    }

    async function loadData({ resetOffset = false } = {}) {
      if (resetOffset) state.offset = 0;
      const values = state.filtersReady ? readFilters() : restoreFilters();
      setUrlState(values);
      const params = new URLSearchParams();
      Object.entries(values).forEach(([key, value]) => {
        if (value !== "" && value !== false && value !== null) params.set(key, String(value));
      });
      params.set("limit", String(state.limit));
      params.set("offset", String(state.offset));
      el("error-alert").style.display = "none";
      el("refresh-button").disabled = true;
      try {
        const response = await fetch("/api/data?" + params.toString(), { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        state.data = payload;
        if (resetOffset) {
          renderFilterOptions(payload);
          state.filtersReady = true;
        }
        renderRunMeta(payload.run);
        renderMetrics(payload.metrics);
        renderHealth(payload.source_health);
        renderGroups(payload.groups);
        renderListings(payload);
        if (resetOffset) loadAi();
      } catch (error) {
        el("error-alert").textContent = "读取失败：" + error.message;
        el("error-alert").style.display = "block";
      } finally {
        el("refresh-button").disabled = false;
      }
    }

    el("filter-form").addEventListener("change", () => loadData({ resetOffset: true }));
    el("filter-form").addEventListener("submit", event => { event.preventDefault(); loadData({ resetOffset: true }); });
    el("refresh-button").addEventListener("click", () => loadData({ resetOffset: true }));
    el("prev-page").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadData(); });
    el("next-page").addEventListener("click", () => { state.offset += state.limit; loadData(); });
    loadData({ resetOffset: true });
  </script>
</body>
</html>
"""
