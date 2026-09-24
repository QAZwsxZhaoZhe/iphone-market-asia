from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator
from uuid import uuid4

from celery import Task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import Engine

from ..config import ACTIVE_SOURCE_KEYS
from . import repository
from .celery_app import celery_app
from .database import build_engine, build_session_factory
from .ingest import CollectionPipeline
from .object_store import get_object_store
from .settings import get_settings


LOGGER = logging.getLogger(__name__)
_FALLBACK_BROWSER_LOCK = threading.Lock()


class BrowserSlotsBusy(RuntimeError):
    pass


class SourceCollectionFailed(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _engine() -> Engine:
    return build_engine(get_settings())


@lru_cache(maxsize=1)
def _session_factory():
    return build_session_factory(_engine())


@lru_cache(maxsize=1)
def _pipeline() -> CollectionPipeline:
    return CollectionPipeline(get_settings(), _session_factory())


class DeadLetterTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        try:
            with _session_factory()() as session:
                session.add(
                    repository.models.DeadLetterTask(
                        task_id=str(task_id),
                        task_name=self.name,
                        args_json=list(args),
                        kwargs_json=dict(kwargs),
                        error=f"{type(exc).__name__}: {exc}"[:4000],
                        retry_count=int(getattr(self.request, "retries", 0) or 0),
                    )
                )
                session.commit()
        except Exception:
            LOGGER.exception("记录死信任务失败：task_id=%s", task_id)


@contextmanager
def browser_slot() -> Iterator[None]:
    settings = get_settings()
    token = uuid4().hex
    key = None
    fallback_acquired = False
    try:
        import redis

        client = redis.Redis.from_url(settings.celery_broker_url, decode_responses=True)
        for index in range(max(1, settings.browser_max_concurrency)):
            candidate = f"iphone-market:browser-slot:{index}"
            if client.set(candidate, token, nx=True, ex=7200):
                key = candidate
                break
        if key is None:
            raise BrowserSlotsBusy("浏览器并发槽已满")
    except ImportError:
        if not _FALLBACK_BROWSER_LOCK.acquire(blocking=False):
            raise BrowserSlotsBusy("本机浏览器并发槽已满") from None
        fallback_acquired = True
    except BrowserSlotsBusy:
        raise
    except Exception as exc:
        LOGGER.warning("Redis 浏览器并发控制不可用，回退单进程锁：%s", exc)
        if not _FALLBACK_BROWSER_LOCK.acquire(blocking=False):
            raise BrowserSlotsBusy("本机浏览器并发槽已满") from None
        fallback_acquired = True

    try:
        yield
    finally:
        if key is not None:
            try:
                import redis

                client = redis.Redis.from_url(
                    settings.celery_broker_url,
                    decode_responses=True,
                )
                if client.get(key) == token:
                    client.delete(key)
            except Exception:
                LOGGER.warning("释放 Redis 浏览器并发槽失败", exc_info=True)
        if fallback_acquired:
            _FALLBACK_BROWSER_LOCK.release()


@celery_app.task(
    bind=True,
    base=DeadLetterTask,
    name="iphone_market.collect_source",
    max_retries=get_settings().collection_max_retries,
)
def collect_source_task(
    self,
    source_key: str,
    run_date: str | None = None,
    limit: int | None = None,
) -> dict:
    settings = get_settings()
    selected_limit = limit or settings.collection_limit
    try:
        with browser_slot():
            result = _pipeline().collect_source(
                source_key,
                run_date=run_date,
                limit=selected_limit,
                headless=True,
                external_run_id=f"{run_date or 'today'}:{uuid4().hex}",
            )
        if result["status"] == "failed":
            raise SourceCollectionFailed(result.get("error") or "来源采集失败")
        return result
    except BrowserSlotsBusy as exc:
        countdown = max(10, settings.collection_retry_backoff_seconds // 2)
        raise self.retry(exc=exc, countdown=countdown)
    except SourceCollectionFailed as exc:
        countdown = settings.collection_retry_backoff_seconds * (
            2 ** int(self.request.retries)
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            raise
    except Exception as exc:
        countdown = settings.collection_retry_backoff_seconds * (
            2 ** int(self.request.retries)
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            raise


@celery_app.task(
    name="iphone_market.collect_all_sources",
    ignore_result=True,
)
def collect_all_sources_task(run_date: str | None = None) -> list[str]:
    task_ids = []
    for source_key in ACTIVE_SOURCE_KEYS:
        result = collect_source_task.apply_async(
            args=(source_key, run_date),
            queue="collection",
        )
        task_ids.append(result.id)
    return task_ids


@celery_app.task(
    name="iphone_market.maintenance",
    ignore_result=True,
)
def maintenance_task() -> dict[str, int]:
    settings = get_settings()
    object_store = get_object_store(settings)
    output = {
        "stale_listings": 0,
        "clusters": 0,
        "alerts": 0,
        "expired_captures": 0,
    }
    with _session_factory()() as session:
        output["stale_listings"] = repository.mark_stale_listings(
            session,
            stale_hours=settings.listing_stale_hours,
        )
        output["clusters"] = repository.rebuild_clusters(session)
        rows = repository.expired_raw_captures(session)
        for capture in rows:
            try:
                object_store.delete(capture.storage_uri)
            finally:
                session.delete(capture)
        output["expired_captures"] = len(rows)
        session.flush()
        from .services import MarketAnalyticsService

        analytics = MarketAnalyticsService(settings)
        output["valuations"] = analytics.refresh_valuations(session)
        output["alerts"] = analytics.evaluate_alerts(session)
        session.commit()
    return output
