from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from ..config import ACTIVE_SOURCE_KEYS, PROJECT_ROOT, ensure_runtime_dirs
from . import repository
from .api.app import create_app
from .celery_app import celery_app
from .database import build_engine, build_session_factory, init_database
from .identity import IdentityError, create_user, ensure_bootstrap_admin
from .ingest import CollectionPipeline
from .object_store import get_object_store
from .services import LegacyImportService, MarketAnalyticsService
from .settings import PlatformSettings, get_settings


LOGGER = logging.getLogger(__name__)


def configure_logging(level: str = "INFO") -> None:
    ensure_runtime_dirs()
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    )
    root.addHandler(handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iphone-platform",
        description="香港二手手机数据聚合平台运维命令",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate", help="执行数据库迁移")
    migrate.add_argument(
        "--revision",
        default="head",
        help="目标 Alembic revision，默认 head",
    )

    subparsers.add_parser("seed", help="写入来源和机型基础数据")

    create_admin = subparsers.add_parser(
        "create-admin",
        help="创建管理員账号，密碼從 BOOTSTRAP_ADMIN_PASSWORD 讀取",
    )
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--name", default="Platform Admin")

    collect_source = subparsers.add_parser(
        "collect-source",
        help="同步采集单个来源",
    )
    collect_source.add_argument("source_key", choices=ACTIVE_SOURCE_KEYS)
    collect_source.add_argument("--date", default=None, help="采集日期 YYYY-MM-DD")
    collect_source.add_argument("--limit", type=int, default=None)
    collect_source.add_argument(
        "--headed",
        action="store_true",
        help="显示采集浏览器窗口",
    )
    collect_source.add_argument("--json", action="store_true")

    collect_all = subparsers.add_parser(
        "collect-all",
        help="按来源隔离执行全部香港采集",
    )
    collect_all.add_argument("--date", default=None, help="采集日期 YYYY-MM-DD")
    collect_all.add_argument("--limit", type=int, default=None)
    collect_all.add_argument(
        "--headed",
        action="store_true",
        help="显示采集浏览器窗口",
    )
    collect_all.add_argument("--json", action="store_true")

    import_legacy = subparsers.add_parser(
        "import-legacy",
        help="把旧 SQLite 数据迁移到平台数据库",
    )
    import_legacy.add_argument(
        "legacy_path",
        nargs="?",
        default=str(PROJECT_ROOT / "data" / "market.sqlite3"),
    )
    import_legacy.add_argument("--limit-runs", type=int, default=None)
    import_legacy.add_argument("--json", action="store_true")

    refresh_valuations = subparsers.add_parser(
        "refresh-valuations",
        help="重算并保存全部在售机型的估值",
    )
    refresh_valuations.add_argument("--lookback-days", type=int, default=45)

    serve = subparsers.add_parser("serve", help="启动 FastAPI 服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    worker = subparsers.add_parser("worker", help="启动 Celery 采集 Worker")
    worker.add_argument(
        "--queue",
        action="append",
        default=None,
        help="队列名，可重复传入；默认 collection,maintenance",
    )
    worker.add_argument("--concurrency", type=int, default=1)
    worker.add_argument("--loglevel", default="INFO")

    beat = subparsers.add_parser("beat", help="启动 Celery Beat 调度器")
    beat.add_argument("--loglevel", default="INFO")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging()
    try:
        if args.command == "migrate":
            return _migrate(args.revision)
        if args.command == "seed":
            return _seed()
        if args.command == "create-admin":
            return _create_admin(args.email, args.name)
        if args.command == "collect-source":
            return _collect_source(args)
        if args.command == "collect-all":
            return _collect_all(args)
        if args.command == "import-legacy":
            return _import_legacy(args)
        if args.command == "refresh-valuations":
            return _refresh_valuations(args.lookback_days)
        if args.command == "serve":
            _serve(args.host, args.port, args.reload)
            return 0
        if args.command == "worker":
            return _worker(args.queue, args.concurrency, args.loglevel)
        if args.command == "beat":
            return _beat(args.loglevel)
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130
    except Exception as exc:
        LOGGER.exception("命令执行失败")
        print(f"错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    parser.error("未知命令")
    return 2


def _migrate(revision: str) -> int:
    settings = get_settings()
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        settings.database_url.replace("%", "%%"),
    )
    command.upgrade(config, revision)
    print(f"数据库已迁移到 {revision}")
    return 0


def _seed() -> int:
    settings = get_settings()
    engine = build_engine(settings)
    try:
        if settings.auto_create_schema:
            init_database(engine)
        session_factory = build_session_factory(engine)
        with session_factory() as session:
            repository.ensure_reference_data(session)
            ensure_bootstrap_admin(session, settings)
            session.commit()
    finally:
        engine.dispose()
    print("来源和机型基础数据已写入")
    return 0


def _create_admin(email: str, name: str) -> int:
    settings = get_settings()
    if not settings.bootstrap_admin_password:
        print(
            "錯誤：請先設定 BOOTSTRAP_ADMIN_PASSWORD",
            file=sys.stderr,
        )
        return 1
    engine = build_engine(settings)
    try:
        if settings.auto_create_schema:
            init_database(engine)
        session_factory = build_session_factory(engine)
        with session_factory() as session:
            try:
                user = create_user(
                    session,
                    email=email,
                    password=settings.bootstrap_admin_password,
                    display_name=name,
                    roles=("admin",),
                )
            except IdentityError as exc:
                print(f"錯誤：{exc}", file=sys.stderr)
                return 1
            session.commit()
    finally:
        engine.dispose()
    print(f"管理員已建立：{user.email}")
    return 0


def _collect_source(args) -> int:
    settings = get_settings()
    pipeline = _pipeline(settings)
    result = pipeline.collect_source(
        args.source_key,
        run_date=args.date,
        limit=args.limit or settings.collection_limit,
        headless=not args.headed,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(
            f"{result['source_key']}: {result['status']}，"
            f"{result['listing_count']} 条"
        )
        if result.get("error"):
            print(f"错误：{result['error']}")
    return 0 if result["status"] in {"ok", "partial"} else 1


def _collect_all(args) -> int:
    settings = get_settings()
    pipeline = _pipeline(settings)
    results = []
    for source_key in ACTIVE_SOURCE_KEYS:
        try:
            result = pipeline.collect_source(
                source_key,
                run_date=args.date,
                limit=args.limit or settings.collection_limit,
                headless=not args.headed,
            )
        except Exception as exc:
            LOGGER.exception("来源采集失败：%s", source_key)
            result = {
                "source_key": source_key,
                "status": "failed",
                "listing_count": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(result)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        for result in results:
            print(
                f"{result['source_key']}: {result['status']}，"
                f"{result['listing_count']} 条"
            )
            if result.get("error"):
                print(f"  错误：{result['error']}")
    return 0 if any(item["status"] in {"ok", "partial"} for item in results) else 1


def _import_legacy(args) -> int:
    settings = get_settings()
    engine = build_engine(settings)
    try:
        if settings.auto_create_schema:
            init_database(engine)
        session_factory = build_session_factory(engine)
        service = LegacyImportService(settings, get_object_store(settings))
        with session_factory() as session:
            result = service.import_sqlite(
                session,
                Path(args.legacy_path),
                limit_runs=args.limit_runs,
            )
            session.commit()
    finally:
        engine.dispose()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "旧数据导入完成："
            f"{result['runs']} 次运行，{result['source_runs']} 条来源记录，"
            f"{result['listings']} 条商品观测"
        )
    return 0


def _refresh_valuations(lookback_days: int) -> int:
    settings = get_settings()
    engine = build_engine(settings)
    try:
        if settings.auto_create_schema:
            init_database(engine)
        session_factory = build_session_factory(engine)
        with session_factory() as session:
            count = MarketAnalyticsService(settings).refresh_valuations(
                session,
                lookback_days=lookback_days,
            )
            session.commit()
    finally:
        engine.dispose()
    print(f"已保存 {count} 个机型估值")
    return 0


def _serve(host: str, port: int, reload: bool) -> None:
    if reload:
        uvicorn.run(
            "iphone_market.platform.api.app:app",
            host=host,
            port=port,
            reload=True,
        )
        return
    uvicorn.run(create_app(get_settings()), host=host, port=port)


def _worker(
    queues: list[str] | None,
    concurrency: int,
    loglevel: str,
) -> int:
    selected_queues = ",".join(queues or ["collection", "maintenance"])
    argv = [
        "worker",
        f"--queues={selected_queues}",
        f"--concurrency={max(1, int(concurrency))}",
        f"--loglevel={loglevel.upper()}",
    ]
    celery_app.worker_main(argv)
    return 0


def _beat(loglevel: str) -> int:
    celery_app.start(
        argv=[
            "beat",
            f"--loglevel={loglevel.upper()}",
            "--schedule",
            str(PROJECT_ROOT / "data" / "celerybeat-schedule"),
        ]
    )
    return 0


def _pipeline(settings: PlatformSettings) -> CollectionPipeline:
    engine = build_engine(settings)
    if settings.auto_create_schema:
        init_database(engine)
    return CollectionPipeline(settings, build_session_factory(engine))


if __name__ == "__main__":
    raise SystemExit(main())
