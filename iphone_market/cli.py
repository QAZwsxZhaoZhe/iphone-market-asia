from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import webbrowser
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__, db
from .ai import (
    DECISIONS,
    OUTCOMES,
    estimate_valuation,
    feedback_metrics,
    find_opportunities,
    list_feedback,
    normalize_storage_gb,
    record_feedback,
)
from .browser import BrowserLaunchError, persistent_browser
from .collection import CollectionOptions, collect
from .config import (
    ACTIVE_MARKET_ORDER,
    ACTIVE_SOURCE_KEYS,
    DB_PATH,
    DEFAULT_DASHBOARD_HOST,
    DEFAULT_DASHBOARD_PORT,
    DEFAULT_LIMIT,
    LOG_DIR,
    PROJECT_ROOT,
    SOURCE_BY_KEY,
    ensure_runtime_dirs,
)
from .dashboard import port_available, serve
from .report import generate_report
from .scheduler import (
    SCHEDULE_TASK_NAME,
    ScheduleInfo,
    SchedulerError,
    install_schedule,
    remove_schedule,
    run_schedule_now,
    show_schedule,
)
from .status import status_snapshot


def configure_logging(verbose: bool = False) -> None:
    ensure_runtime_dirs()
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler = RotatingFileHandler(
        LOG_DIR / "collector.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    )
    root.addHandler(file_handler)
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG if verbose else logging.INFO)
        console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(console)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iphone-market",
        description="香港二手 iPhone 每日采集与本地看板",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="打开香港来源的人工登录或验证页面")
    login.add_argument(
        "--source",
        default="all",
        choices=("all", *ACTIVE_SOURCE_KEYS),
        help="要打开的香港来源，默认全部",
    )

    collect_parser = subparsers.add_parser("collect", help="执行一次香港采集")
    collect_parser.add_argument("--date", default=date.today().isoformat())
    collect_parser.add_argument(
        "--source",
        action="append",
        choices=ACTIVE_SOURCE_KEYS,
        help="只采集指定的香港来源，可重复传入",
    )
    collect_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    collect_parser.add_argument(
        "--headed",
        action="store_true",
        help="显示采集浏览器窗口",
    )
    collect_parser.add_argument(
        "--start-dashboard",
        action="store_true",
        help="采集完成后在端口空闲时隐藏启动看板",
    )
    collect_parser.add_argument("--dashboard-port", type=int, default=DEFAULT_DASHBOARD_PORT)

    dashboard = subparsers.add_parser("dashboard", help="启动本地看板")
    dashboard.add_argument("--host", default=DEFAULT_DASHBOARD_HOST)
    dashboard.add_argument("--port", type=int, default=DEFAULT_DASHBOARD_PORT)
    dashboard.add_argument("--open", action="store_true", help="启动后在默认浏览器打开")

    status = subparsers.add_parser("status", help="查看最近运行状态")
    status.add_argument("--json", action="store_true", help="输出 JSON")

    valuation = subparsers.add_parser("valuation", help="按同款可比样本估算二手 iPhone 价格")
    _add_ai_arguments(valuation)
    valuation.add_argument(
        "--margin",
        type=float,
        default=12.0,
        help="建议收购价预留的毛利空间百分比，默认 12",
    )
    valuation.add_argument("--json", action="store_true", help="输出 JSON")

    opportunities = subparsers.add_parser("opportunities", help="按估值偏差发现潜在收购机会")
    _add_ai_arguments(opportunities)
    opportunities.add_argument("--limit", type=int, default=10, help="最多返回多少条，默认 10")
    opportunities.add_argument(
        "--fee-pct",
        type=float,
        default=12.0,
        help="转售平台费和物流费用的预估百分比，默认 12",
    )
    opportunities.add_argument("--json", action="store_true", help="输出 JSON")

    feedback = subparsers.add_parser("feedback", help="记录真实收购转售并评估 AI 估值")
    feedback_subparsers = feedback.add_subparsers(
        dest="feedback_command",
        required=True,
    )
    feedback_add = feedback_subparsers.add_parser("add", help="新增一条业务反馈")
    _add_feedback_variant_arguments(feedback_add)
    feedback_add.add_argument(
        "--source",
        choices=ACTIVE_SOURCE_KEYS,
        help="来源平台；如果同时提供 listing-id，可关联原始商品",
    )
    feedback_add.add_argument("--listing-id", help="平台商品 ID")
    feedback_add.add_argument(
        "--decision",
        required=True,
        choices=DECISIONS,
        help="当时的决策：buy、watch 或 skip",
    )
    feedback_add.add_argument(
        "--outcome",
        default="pending",
        choices=OUTCOMES,
        help="后续结果，默认 pending",
    )
    feedback_add.add_argument("--decision-price", type=float, help="决策时商品要价 CNY")
    feedback_add.add_argument("--purchase-price", type=float, help="实际收购价 CNY")
    feedback_add.add_argument("--sale-price", type=float, help="实际转售价 CNY")
    feedback_add.add_argument("--fees", type=float, default=0.0, help="平台及物流费用 CNY")
    feedback_add.add_argument("--repair-cost", type=float, default=0.0, help="维修成本 CNY")
    feedback_add.add_argument("--estimated-fair", type=float, help="人工指定合理价 CNY")
    feedback_add.add_argument("--fair-low", type=float, help="人工指定合理区间下限 CNY")
    feedback_add.add_argument("--fair-high", type=float, help="人工指定合理区间上限 CNY")
    feedback_add.add_argument(
        "--suggested-purchase",
        type=float,
        help="人工指定建议收购上限 CNY",
    )
    feedback_add.add_argument(
        "--confidence",
        choices=("high", "medium", "low", "none"),
        help="预估置信度；默认从当时估值自动带入",
    )
    feedback_add.add_argument("--notes", default="", help="备注")
    feedback_add.add_argument(
        "--no-auto-valuation",
        action="store_false",
        dest="auto_estimate",
        default=True,
        help="不自动调用当前可比估值",
    )
    feedback_add.add_argument("--json", action="store_true", help="输出 JSON")

    feedback_list = feedback_subparsers.add_parser("list", help="查看业务反馈")
    _add_feedback_filter_arguments(feedback_list, include_outcome=True)
    feedback_list.add_argument("--limit", type=int, default=100)
    feedback_list.add_argument("--json", action="store_true", help="输出 JSON")

    feedback_metrics_parser = feedback_subparsers.add_parser(
        "metrics",
        help="查看估值误差和真实利润",
    )
    _add_feedback_filter_arguments(feedback_metrics_parser, include_outcome=False)
    feedback_metrics_parser.add_argument("--json", action="store_true", help="输出 JSON")

    schedule = subparsers.add_parser("schedule", help="管理香港采集的 Windows 定时任务")
    schedule_subparsers = schedule.add_subparsers(dest="schedule_command", required=True)
    schedule_install = schedule_subparsers.add_parser("install", help="创建每日 08:00 任务")
    schedule_install.add_argument("--time", default="08:00", help="每日启动时间 HH:MM")
    schedule_subparsers.add_parser("show", help="显示任务详情")
    schedule_subparsers.add_parser("remove", help="删除任务")
    schedule_subparsers.add_parser("run", help="立即运行任务")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    try:
        if args.command == "login":
            return _login(args.source)
        if args.command == "collect":
            return _collect(args)
        if args.command == "dashboard":
            return _dashboard(args.host, args.port, args.open)
        if args.command == "status":
            return _status(args.json)
        if args.command == "valuation":
            return _valuation(args)
        if args.command == "opportunities":
            return _opportunities(args)
        if args.command == "feedback":
            return _feedback(args)
        if args.command == "schedule":
            return _schedule(args)
    except (ValueError, BrowserLaunchError, SchedulerError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logging.getLogger(__name__).exception("命令执行失败：%s", exc)
        print(f"错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130
    parser.error("未知命令")
    return 2


def _login(source_key: str) -> int:
    keys = (
        [key for key in ACTIVE_SOURCE_KEYS if SOURCE_BY_KEY[key].requires_login]
        if source_key == "all"
        else [source_key]
    )
    if not keys:
        print("没有需要人工登录的来源。")
        return 0
    with persistent_browser(headless=False) as context:
        pages = []
        for key in keys:
            spec = SOURCE_BY_KEY[key]
            page = context.new_page()
            target = spec.login_url or spec.base_url
            try:
                page.goto(target, wait_until="domcontentloaded")
            except Exception as exc:
                print(f"{spec.name}: 打开失败，{exc}")
            pages.append((spec, page))
        print("已打开以下来源。请在浏览器中完成人工登录或安全验证：")
        for spec, _page in pages:
            print(f"  - {spec.name} ({spec.market}): {spec.login_url or spec.base_url}")
        print("不会读取、导出或保存密码和 Cookie。")
        input("完成所有登录和验证后，回到此终端按 Enter 关闭浏览器...")
    return 0


def _collect(args) -> int:
    run_date = date.fromisoformat(args.date).isoformat()
    source_keys = tuple(args.source or ACTIVE_SOURCE_KEYS)
    if args.limit < 1 or args.limit > 200:
        raise ValueError("--limit 必须在 1 到 200 之间")
    summary = collect(
        CollectionOptions(
            run_date=run_date,
            source_keys=source_keys,
            limit=args.limit,
            headless=not args.headed,
        )
    )
    report_path = generate_report(run_date)
    print(f"采集完成：{summary.status}，共写入 {summary.total_listings} 条")
    for result in summary.source_results:
        message = f"  - {SOURCE_BY_KEY[result.source_key].name}: {result.status} ({result.listing_count} 条)"
        if result.error:
            message += f"，{result.error}"
        print(message)
    print(f"日报：{report_path}")

    if args.start_dashboard:
        started = start_dashboard_background(args.dashboard_port)
        if started:
            print(f"看板已启动：http://127.0.0.1:{args.dashboard_port}")
        else:
            print(f"端口 {args.dashboard_port} 已占用，沿用现有看板。")
    return 0 if summary.status in {"ok", "partial"} else 1


def _dashboard(host: str, port: int, open_browser: bool) -> int:
    if not port_available(host, port):
        url = f"http://{host}:{port}"
        print(f"看板已在运行：{url}")
        if open_browser:
            webbrowser.open(url)
        return 0
    url = f"http://{host}:{port}"
    print(f"看板：{url}")
    if open_browser:
        webbrowser.open(url)
    serve(host=host, port=port)
    return 0


def _status(as_json: bool) -> int:
    snapshot = status_snapshot()
    if as_json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
        return 0
    run = snapshot.get("latest_run")
    if not run:
        print("尚未执行采集。")
        return 0
    print(
        f"最近运行：{run['run_date']}，状态 {snapshot['status']}，"
        f"开始 {run['started_at']}，结束 {run['finished_at'] or '-'}"
    )
    for item in snapshot["sources"]:
        print(
            f"  - {item['source_name']}（{item['market']}）：{item['status']}，"
            f"{item.get('listing_count', 0)} 条"
            + (f"，{item['error']}" if item.get("error") else "")
        )
    return 0


def _add_ai_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", required=True, help="例如 iPhone 17 Pro Max")
    parser.add_argument("--storage", required=True, type=_storage_value, help="例如 256GB、1TB")
    parser.add_argument(
        "--market",
        default=ACTIVE_MARKET_ORDER[0],
        choices=ACTIVE_MARKET_ORDER,
        help="市场，当前默认香港",
    )
    parser.add_argument("--date", default=None, help="估值基准日期 YYYY-MM-DD")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=45,
        help="可比样本回溯天数，默认 45",
    )


def _add_feedback_variant_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", required=True, help="例如 iPhone 17 Pro Max")
    parser.add_argument("--storage", required=True, type=_storage_value, help="例如 256GB、1TB")
    parser.add_argument(
        "--market",
        default=ACTIVE_MARKET_ORDER[0],
        choices=ACTIVE_MARKET_ORDER,
        help="市场，当前默认香港",
    )
    parser.add_argument(
        "--valuation-date",
        default=None,
        help="估值基准日期 YYYY-MM-DD，默认今天",
    )


def _add_feedback_filter_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_outcome: bool,
) -> None:
    parser.add_argument("--model", help="例如 iPhone 17 Pro Max")
    parser.add_argument("--storage", type=_storage_value, help="例如 256GB、1TB")
    parser.add_argument(
        "--market",
        choices=ACTIVE_MARKET_ORDER,
        help="市场，当前仅香港",
    )
    if include_outcome:
        parser.add_argument("--outcome", choices=OUTCOMES, help="按结果过滤")


def _storage_value(value: str) -> int:
    try:
        return normalize_storage_gb(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _valuation(args) -> int:
    payload = estimate_valuation(
        model=args.model,
        storage_gb=args.storage,
        market=args.market,
        as_of_date=args.date,
        lookback_days=args.lookback_days,
        target_margin_pct=args.margin,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    if payload["status"] != "ok":
        print(f"暂时无法估值：{payload['confidence']['reason']}")
        return 0
    fair = payload["fair_range_cny"]
    guidance = payload["guidance_cny"]
    print(
        f"{payload['market']} {payload['model']} {payload['storage_label']}"
        f"（{payload['as_of_date']}，{payload['sample_count']} 条可比样本）"
    )
    print(
        "合理价格区间："
        f"{_money(fair['low'])} - {_money(fair['mid'])} - {_money(fair['high'])}"
    )
    print(f"建议收购上限：{_money(guidance['suggested_purchase_max'])}")
    print(f"建议转售参考：{_money(guidance['suggested_resale'])}")
    print(
        f"置信度：{payload['confidence']['level']}"
        f"（{payload['confidence']['reason']}）"
    )
    print(f"离散度：{payload['dispersion_pct']:.2f}%")
    native = payload.get("fair_range_native")
    if native:
        print(
            f"原币价格区间：{native['currency']} "
            f"{native['low']:,.0f} - {native['mid']:,.0f} - {native['high']:,.0f}"
        )
    print(f"已排除异常价格：{payload['rejected_outliers']} 条")
    if payload["comparables"]:
        print("可比样本：")
        for item in payload["comparables"][:5]:
            print(
                f"  - {item['source_name']}: {_money(item['price_cny'])} "
                f"{item['title']}"
            )
    for warning in payload.get("warnings", []):
        print(f"提示：{warning}")
    return 0


def _opportunities(args) -> int:
    payload = find_opportunities(
        model=args.model,
        storage_gb=args.storage,
        market=args.market,
        as_of_date=args.date,
        limit=args.limit,
        fee_pct=args.fee_pct,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    if payload["status"] != "ok":
        print(f"暂时无法评分：{payload['valuation']['confidence']['reason']}")
        return 0
    print(
        f"{payload['market']} {payload['model']} "
        f"{payload['valuation']['storage_label']}，{payload['as_of_date']}"
    )
    if not payload["candidates"]:
        print("当前没有满足条件的候选机会。")
        return 0
    print(
        f"共 {len(payload['candidates'])} 条候选，"
        f"费用率按 {payload['fee_pct']:.1f}% 估算："
    )
    for item in payload["candidates"]:
        risk = f"，风险：{'；'.join(item['risk_flags'])}" if item["risk_flags"] else ""
        print(
            f"  - 评分 {item['opportunity_score']:.1f}，"
            f"要价 {_money(item['price_cny'])}，"
            f"预估净价差 {_money(item['estimated_net_spread_cny'])}，"
            f"{item['title']}{risk}"
        )
    for warning in payload.get("warnings", []):
        print(f"提示：{warning}")
    return 0


def _feedback(args) -> int:
    if args.feedback_command == "add":
        return _feedback_add(args)
    if args.feedback_command == "list":
        return _feedback_list(args)
    if args.feedback_command == "metrics":
        return _feedback_metrics(args)
    return 2


def _feedback_add(args) -> int:
    payload = record_feedback(
        model=args.model,
        storage_gb=args.storage,
        market=args.market,
        source_key=args.source,
        listing_id=args.listing_id,
        valuation_date=args.valuation_date,
        decision=args.decision,
        outcome=args.outcome,
        decision_price_cny=args.decision_price,
        actual_purchase_cny=args.purchase_price,
        actual_sale_cny=args.sale_price,
        fees_cny=args.fees,
        repair_cost_cny=args.repair_cost,
        estimated_fair_cny=args.estimated_fair,
        fair_low_cny=args.fair_low,
        fair_high_cny=args.fair_high,
        suggested_purchase_cny=args.suggested_purchase,
        confidence_level=args.confidence,
        notes=args.notes,
        auto_estimate=args.auto_estimate,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    record = payload["record"]
    print(f"已记录反馈 #{record['id']}：{record['model']} {record['storage_gb']}GB")
    if record["estimated_fair_cny"] is not None:
        print(f"记录时合理价：{_money(record['estimated_fair_cny'])}")
    if record["suggested_purchase_cny"] is not None:
        print(f"记录时建议收购上限：{_money(record['suggested_purchase_cny'])}")
    print(f"决策/结果：{record['decision']} / {record['outcome']}")
    return 0


def _feedback_list(args) -> int:
    payload = list_feedback(
        market=args.market,
        model=args.model,
        storage_gb=args.storage,
        outcome=args.outcome,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    if not payload["records"]:
        print("暂无业务反馈。")
        return 0
    print(f"共 {payload['count']} 条业务反馈：")
    for item in payload["records"]:
        print(
            f"  #{item['id']} {item['model']} {item['storage_gb']}GB "
            f"{item['decision']}/{item['outcome']} "
            f"合理价 {_money(item['estimated_fair_cny'])} "
            f"收购 {_money(item['actual_purchase_cny'])} "
            f"转售 {_money(item['actual_sale_cny'])}"
        )
    return 0


def _feedback_metrics(args) -> int:
    payload = feedback_metrics(
        market=args.market,
        model=args.model,
        storage_gb=args.storage,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    evaluation = payload["evaluation"]
    print(
        f"AI 估值验收状态：{evaluation['status']}，"
        f"已完成估值和成交的样本 {evaluation['sold_with_valuation']} 条"
    )
    print(f"平均绝对误差：{_money(evaluation['mean_absolute_error_cny'])}")
    print(f"中位绝对误差：{_money(evaluation['median_absolute_error_cny'])}")
    mape = evaluation["mape_pct"]
    print(f"MAPE：{mape:.2f}%" if mape is not None else "MAPE：-")
    coverage = evaluation["fair_range_coverage_pct"]
    print(
        f"合理区间覆盖率：{coverage:.2f}%"
        if coverage is not None
        else "合理区间覆盖率：-"
    )
    profit = payload["profit"]
    print(f"真实成交样本：{profit['sold_with_cost']} 条")
    print(f"累计净利润：{_money(profit['total_net_profit_cny'])}")
    print(f"中位净利润：{_money(profit['median_net_profit_cny'])}")
    roi = profit["median_roi_pct"]
    print(f"中位 ROI：{roi:.2f}%" if roi is not None else "中位 ROI：-")
    print(f"建议：{payload['recommendation']}")
    return 0


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"CNY {float(value):,.0f}"


def _schedule(args) -> int:
    if args.schedule_command == "install":
        info = install_schedule(start_time=args.time)
        _print_schedule(info)
    elif args.schedule_command == "show":
        _print_schedule(show_schedule())
    elif args.schedule_command == "remove":
        remove_schedule()
        print("定时任务已删除。")
    elif args.schedule_command == "run":
        run_schedule_now()
        print("定时任务已触发。")
    return 0


def _print_schedule(info: ScheduleInfo) -> None:
    print(f"任务：{info.task_name or SCHEDULE_TASK_NAME}")
    print(f"启动时间：{info.start_boundary}")
    print(f"错过计划后补跑：{'是' if info.start_when_available else '否'}")
    print(f"强制唤醒电脑：{'是' if info.wake_to_run else '否'}")
    print(f"命令：{info.command} {info.arguments}")
    print(f"工作目录：{info.working_directory}")


def start_dashboard_background(port: int) -> bool:
    if not port_available(DEFAULT_DASHBOARD_HOST, port):
        return False
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = str(pythonw if pythonw.exists() else sys.executable)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [
            executable,
            "-m",
            "iphone_market",
            "dashboard",
            "--host",
            DEFAULT_DASHBOARD_HOST,
            "--port",
            str(port),
        ],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    return True
