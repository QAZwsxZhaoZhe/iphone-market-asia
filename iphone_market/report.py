from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import db
from .analytics import cny, grouped_metrics, median_change, percentile, price_metrics
from .config import (
    ACTIVE_MARKET_ORDER,
    ACTIVE_SOURCE_BY_KEY,
    ACTIVE_SOURCE_KEYS,
    DB_PATH,
    REPORT_DIR,
    SOURCE_BY_KEY,
)
from .redaction import redact_sensitive


STATUS_LABELS = {
    "ok": "正常",
    "partial": "部分失败",
    "failed": "失败",
    "running": "运行中",
    "missing": "未运行",
}


def generate_report(run_date: str, db_path=DB_PATH, report_dir: Path = REPORT_DIR) -> Path:
    db.init_db(db_path)
    conn = db.connect(db_path)
    rows = _active_rows(
        db.listing_rows(
            conn,
            run_date,
            market=ACTIVE_MARKET_ORDER[0],
            include_inactive=False,
        )
    )
    previous = db.previous_date(conn, run_date)
    previous_rows = (
        _active_rows(
            db.listing_rows(
                conn,
                previous,
                market=ACTIVE_MARKET_ORDER[0],
                include_inactive=False,
            )
        )
        if previous
        else []
    )
    run = db.latest_run_for_date(conn, run_date)
    source_rows = db.source_results(conn, int(run["id"])) if run else []

    current_groups = grouped_metrics(rows, ("market", "model", "storage_gb"))
    previous_groups = {
        (item["market"], item["model"], item["storage_gb"]): item
        for item in grouped_metrics(previous_rows, ("market", "model", "storage_gb"))
    }
    source_groups = {
        item["source_key"]: item
        for item in grouped_metrics(rows, ("source_key",))
    }
    status_by_key = {row["source_key"]: row for row in source_rows}
    metadata = json.loads(run["metadata_json"] or "{}") if run else {}
    anomalies = _anomalies(rows)
    fx_dates = sorted({row["fx_date"] for row in rows if row["fx_date"]})
    if metadata.get("fx_date") and metadata["fx_date"] not in fx_dates:
        fx_dates.append(str(metadata["fx_date"]))
    fx_stale = bool(metadata.get("fx_stale")) or _fx_stale(rows)
    missing_fx = sum(
        1
        for row in rows
        if row["currency"] != "CNY" and row["price_native"] is not None and row["price_cny"] is None
    )

    lines = [
        f"# 香港二手 iPhone 日报 - {run_date}",
        "",
        f"- 运行状态：**{STATUS_LABELS.get(run['status'], run['status']) if run else '无运行记录'}**",
        f"- 有效在售样本：**{len(rows)}** 条",
        f"- 汇率日期：{', '.join(fx_dates) if fx_dates else '未知'}",
        f"- 汇率状态：{'最近缓存，可能过期' if fx_stale else '正常'}",
    ]
    if metadata.get("fx_error"):
        lines.append(f"- 汇率告警：{metadata['fx_error']}")
    if missing_fx:
        lines.append(f"- 汇率缺失：{missing_fx} 条非人民币列表未能换算，未计入价格统计。")
    lines.extend(["", "## 来源状态", "", "| 市场 | 来源 | 状态 | 样本 | 查询 | 说明 |", "|---|---|---:|---:|---:|---|"])
    for source_key in ACTIVE_SOURCE_KEYS:
        row = status_by_key.get(source_key)
        source = next((item for item in source_groups.values() if item["source_key"] == source_key), None)
        spec = SOURCE_BY_KEY[source_key]
        status = STATUS_LABELS.get(row["status"] if row else "missing", "未运行")
        error = redact_sensitive(row["error"] if row else None) or ""
        lines.append(
            f"| {spec.market} | {spec.name} | {status} | "
            f"{source['count'] if source else 0} | {row['query_count'] if row else 0} | {_escape(error)} |"
        )

    lines.extend(
        [
            "",
            "## 市场与机型容量",
            "",
            "| 市场 | 机型 | 容量 | 数量 | 最低价 | P25 | 中位数 | P75 | 最高价 | 中位数环比 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in current_groups:
        key = (item["market"], item["model"], item["storage_gb"])
        prev = previous_groups.get(key)
        change = median_change(item, prev)
        lines.append(
            f"| {item['market']} | {item['model']} | {_storage_label(item['storage_gb'])} | "
            f"{item['count']} | {cny(item['min'])} | {cny(item['p25'])} | "
            f"{cny(item['median'])} | {cny(item['p75'])} | {cny(item['max'])} | "
            f"{_change_label(change)} |"
        )
    if not current_groups:
        lines.append("| - | - | - | 0 | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 异常价格",
            "",
            "按同一市场、机型、容量分组，样本不少于 4 条时，标记超出 1.5 倍四分位距的活跃在售列表。",
            "",
        ]
    )
    if anomalies:
        lines.extend(
            [
                "| 市场 | 机型 | 容量 | 价格 | 标题 | 来源 |",
                "|---|---|---:|---:|---|---|",
            ]
        )
        for item in anomalies[:20]:
            lines.append(
                f"| {item['market']} | {item['model']} | {_storage_label(item['storage_gb'])} | "
                f"{cny(item['price_cny'])} | [{_escape(item['title'])}]({item['url']}) | "
                f"{_escape(item['source_name'])} |"
            )
    else:
        lines.append("未发现明显的组内价格异常。")

    missing = [
        _source_name(source_key)
        for source_key in ACTIVE_SOURCE_KEYS
        if not status_by_key.get(source_key) or status_by_key[source_key]["status"] == "failed"
    ]
    lines.extend(["", "## 缺失与告警", ""])
    if missing:
        lines.append(f"- 缺失或失败来源：{', '.join(missing)}")
    partial = [
        _source_name(source_key)
        for source_key in ACTIVE_SOURCE_KEYS
        if status_by_key.get(source_key) and status_by_key[source_key]["status"] == "partial"
    ]
    if partial:
        lines.append(f"- 部分失败来源：{', '.join(partial)}")
    if not missing and not partial:
        lines.append("- 所有纳入来源均完成采集。")
    lines.extend(
        [
            "",
            "> 价格是采集时公开页面上的要价，单位为人民币换算值。未公开成交状态的已售/已结束列表不会混入默认价格统计。",
            "",
        ]
    )

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{run_date}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    conn.close()
    return path


def _anomalies(rows) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        if row["price_cny"] is not None:
            groups[(row["market"], row["model"], row["storage_gb"])].append(row)
    output = []
    for group in groups.values():
        if len(group) < 4:
            continue
        prices = [float(row["price_cny"]) for row in group]
        p25 = percentile(prices, 0.25) or 0
        p75 = percentile(prices, 0.75) or 0
        spread = p75 - p25
        low = p25 - 1.5 * spread
        high = p75 + 1.5 * spread
        for row in group:
            price = float(row["price_cny"])
            if price < low or price > high:
                item = dict(row)
                item["deviation"] = max(low - price, price - high, 0)
                output.append(item)
    output.sort(key=lambda item: item["deviation"], reverse=True)
    return output


def _active_rows(rows):
    return [
        row
        for row in rows
        if row["market"] in ACTIVE_MARKET_ORDER
        and row["source_key"] in ACTIVE_SOURCE_BY_KEY
    ]


def _fx_stale(rows) -> bool:
    for row in rows:
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if raw.get("fx_stale") is True:
            return True
    return False


def _source_name(source_key: str) -> str:
    from .config import SOURCE_BY_KEY

    return SOURCE_BY_KEY[source_key].name


def _storage_label(storage_gb: int | None) -> str:
    if storage_gb == 1024:
        return "1TB"
    if storage_gb == 2048:
        return "2TB"
    return f"{storage_gb}GB" if storage_gb else "-"


def _change_label(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f}"


def _escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
