from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import PROJECT_ROOT


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def _as_tuple(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _default_database_url() -> str:
    path = (PROJECT_ROOT / "data" / "platform.sqlite3").resolve()
    return f"sqlite:///{path.as_posix()}"


@dataclass(frozen=True)
class PlatformSettings:
    environment: str = "development"
    database_url: str = ""
    api_title: str = "香港二手手机数据聚合平台"
    api_version: str = "v1"
    session_ttl_hours: int = 336
    allow_public_registration: bool = True
    bootstrap_admin_email: str = ""
    bootstrap_admin_name: str = "Platform Admin"
    bootstrap_admin_password: str = ""
    public_base_url: str = "http://127.0.0.1:8000"
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )
    auth_mode: str = "disabled"
    api_key: str = ""
    auto_create_schema: bool = True
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_roles_claim: str = "roles"
    internal_roles: tuple[str, ...] = ("admin", "operator", "analyst")
    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/1"
    collection_limit: int = 30
    collection_max_retries: int = 3
    collection_retry_backoff_seconds: int = 60
    browser_max_concurrency: int = 2
    schedule_hour_hong_kong: int = 8
    schedule_minute_hong_kong: int = 0
    opensearch_url: str = ""
    opensearch_index: str = "hk-iphone-listings"
    object_store_backend: str = "local"
    object_store_bucket: str = ""
    object_store_local_dir: str = ""
    object_store_endpoint_url: str = ""
    object_store_access_key: str = ""
    object_store_secret_key: str = ""
    object_store_sse: str = "AES256"
    raw_capture_retention_days: int = 30
    listing_stale_hours: int = 36
    default_page_size: int = 30
    max_page_size: int = 100
    target_margin_pct: float = 12.0
    opportunity_fee_pct: float = 12.0
    payment_provider: str = "mock"
    payment_api_key: str = ""
    payment_webhook_secret: str = "development-payment-webhook-secret"
    payment_return_url: str = "http://127.0.0.1:3000/account/orders"
    payment_api_base_url: str = "https://api.stripe.com"
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "environment", self.environment.strip().lower())
        if not self.database_url:
            object.__setattr__(self, "database_url", _default_database_url())
        if not self.object_store_local_dir:
            object.__setattr__(
                self,
                "object_store_local_dir",
                str((PROJECT_ROOT / "data" / "raw-captures").resolve()),
            )
        self._validate_production_settings()

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def _validate_production_settings(self) -> None:
        if self.environment not in {"production", "prod"}:
            return
        if self.is_sqlite:
            raise ValueError("Production 不允許使用 SQLite")
        if self.auth_mode not in {"api_key", "oidc"}:
            raise ValueError("Production AUTH_MODE 必須是 api_key 或 oidc")
        if self.auth_mode == "api_key":
            weak_key = self.api_key.lower() in {
                "",
                "change-me",
                "change-me-before-exposing",
                "replace-with-a-long-random-internal-key",
            }
            if weak_key or len(self.api_key) < 32:
                raise ValueError("Production PLATFORM_API_KEY 必須至少 32 個字元")
        if self.auth_mode == "oidc":
            if not all(
                (
                    self.oidc_issuer,
                    self.oidc_audience,
                    self.oidc_jwks_url,
                )
            ):
                raise ValueError("Production OIDC 必須配置 ISSUER、AUDIENCE 和 JWKS_URL")
        if "*" in self.cors_origins:
            raise ValueError("Production CORS_ORIGINS 不允許使用 *")
        if self.bootstrap_admin_password and len(self.bootstrap_admin_password) < 12:
            raise ValueError("Production 初始管理員密碼必須至少 12 個字元")
        if self.payment_provider == "mock":
            raise ValueError("Production PAYMENT_PROVIDER 不允許使用 mock")
        if not self.payment_webhook_secret:
            raise ValueError("Production PAYMENT_WEBHOOK_SECRET 必須配置")
        if not self.payment_return_url.startswith("https://"):
            raise ValueError("Production PAYMENT_RETURN_URL 必須使用 HTTPS")
        if self.payment_provider == "stripe" and not self.payment_api_key:
            raise ValueError("Production Stripe 必須配置 PAYMENT_API_KEY")

    @classmethod
    def from_env(cls) -> "PlatformSettings":
        return cls(
            environment=os.getenv("APP_ENV", "development").strip().lower(),
            database_url=os.getenv("DATABASE_URL", _default_database_url()),
            api_title=os.getenv("API_TITLE", "香港二手手机数据聚合平台"),
            api_version=os.getenv("API_VERSION", "v1"),
            session_ttl_hours=_as_int(os.getenv("SESSION_TTL_HOURS"), 336),
            allow_public_registration=_as_bool(
                os.getenv("ALLOW_PUBLIC_REGISTRATION"),
                True,
            ),
            bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip(),
            bootstrap_admin_name=os.getenv(
                "BOOTSTRAP_ADMIN_NAME",
                "Platform Admin",
            ).strip(),
            bootstrap_admin_password=os.getenv(
                "BOOTSTRAP_ADMIN_PASSWORD",
                "",
            ),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000"),
            cors_origins=_as_tuple(
                os.getenv("CORS_ORIGINS"),
                ("http://127.0.0.1:3000", "http://localhost:3000"),
            ),
            auth_mode=os.getenv("AUTH_MODE", "disabled").strip().lower(),
            api_key=os.getenv("PLATFORM_API_KEY", ""),
            auto_create_schema=_as_bool(
                os.getenv("AUTO_CREATE_SCHEMA"),
                True,
            ),
            oidc_issuer=os.getenv("OIDC_ISSUER", ""),
            oidc_audience=os.getenv("OIDC_AUDIENCE", ""),
            oidc_jwks_url=os.getenv("OIDC_JWKS_URL", ""),
            oidc_roles_claim=os.getenv("OIDC_ROLES_CLAIM", "roles"),
            internal_roles=_as_tuple(
                os.getenv("INTERNAL_ROLES"),
                ("admin", "operator", "analyst"),
            ),
            celery_broker_url=os.getenv(
                "CELERY_BROKER_URL",
                "redis://127.0.0.1:6379/0",
            ),
            celery_result_backend=os.getenv(
                "CELERY_RESULT_BACKEND",
                "redis://127.0.0.1:6379/1",
            ),
            collection_limit=_as_int(os.getenv("COLLECTION_LIMIT"), 30),
            collection_max_retries=_as_int(
                os.getenv("COLLECTION_MAX_RETRIES"),
                3,
            ),
            collection_retry_backoff_seconds=_as_int(
                os.getenv("COLLECTION_RETRY_BACKOFF_SECONDS"),
                60,
            ),
            browser_max_concurrency=_as_int(
                os.getenv("BROWSER_MAX_CONCURRENCY"),
                2,
            ),
            schedule_hour_hong_kong=_as_int(
                os.getenv("COLLECTION_SCHEDULE_HOUR"),
                8,
            ),
            schedule_minute_hong_kong=_as_int(
                os.getenv("COLLECTION_SCHEDULE_MINUTE"),
                0,
            ),
            opensearch_url=os.getenv("OPENSEARCH_URL", ""),
            opensearch_index=os.getenv(
                "OPENSEARCH_INDEX",
                "hk-iphone-listings",
            ),
            object_store_backend=os.getenv(
                "OBJECT_STORE_BACKEND",
                "local",
            ).strip().lower(),
            object_store_bucket=os.getenv("OBJECT_STORE_BUCKET", ""),
            object_store_local_dir=os.getenv(
                "OBJECT_STORE_LOCAL_DIR",
                str((PROJECT_ROOT / "data" / "raw-captures").resolve()),
            ),
            object_store_endpoint_url=os.getenv("OBJECT_STORE_ENDPOINT_URL", ""),
            object_store_access_key=os.getenv("OBJECT_STORE_ACCESS_KEY", ""),
            object_store_secret_key=os.getenv("OBJECT_STORE_SECRET_KEY", ""),
            object_store_sse=os.getenv("OBJECT_STORE_SSE", "AES256").strip(),
            raw_capture_retention_days=_as_int(
                os.getenv("RAW_CAPTURE_RETENTION_DAYS"),
                30,
            ),
            listing_stale_hours=_as_int(os.getenv("LISTING_STALE_HOURS"), 36),
            default_page_size=_as_int(os.getenv("DEFAULT_PAGE_SIZE"), 30),
            max_page_size=_as_int(os.getenv("MAX_PAGE_SIZE"), 100),
            target_margin_pct=_as_float(os.getenv("TARGET_MARGIN_PCT"), 12.0),
            opportunity_fee_pct=_as_float(
                os.getenv("OPPORTUNITY_FEE_PCT"),
                12.0,
            ),
            payment_provider=os.getenv(
                "PAYMENT_PROVIDER",
                "mock",
            ).strip().lower(),
            payment_api_key=os.getenv("PAYMENT_API_KEY", ""),
            payment_webhook_secret=os.getenv(
                "PAYMENT_WEBHOOK_SECRET",
                "development-payment-webhook-secret",
            ),
            payment_return_url=os.getenv(
                "PAYMENT_RETURN_URL",
                "http://127.0.0.1:3000/account/orders",
            ).strip(),
            payment_api_base_url=os.getenv(
                "PAYMENT_API_BASE_URL",
                "https://api.stripe.com",
            ).rstrip("/"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            otel_exporter_otlp_endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "",
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> PlatformSettings:
    return PlatformSettings.from_env()


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def ensure_storage_dirs(settings: PlatformSettings) -> None:
    if settings.object_store_backend == "local":
        Path(settings.object_store_local_dir).mkdir(parents=True, exist_ok=True)
