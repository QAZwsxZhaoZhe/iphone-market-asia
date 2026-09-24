from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from .settings import get_settings


settings = get_settings()

celery_app = Celery(
    "iphone_market",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["iphone_market.platform.tasks"],
)
celery_app.conf.update(
    timezone="Asia/Hong_Kong",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    beat_schedule={
        "daily-hong-kong-collection": {
            "task": "iphone_market.collect_all_sources",
            "schedule": crontab(
                hour=settings.schedule_hour_hong_kong,
                minute=settings.schedule_minute_hong_kong,
            ),
        },
        "hourly-platform-maintenance": {
            "task": "iphone_market.maintenance",
            "schedule": crontab(minute=20),
        },
    },
)
