from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..database import build_engine, build_session_factory, init_database
from ..identity import ensure_bootstrap_admin
from ..ingest import CollectionPipeline
from ..object_store import get_object_store
from ..repository import ensure_reference_data
from ..search import ListingSearchIndex
from ..settings import PlatformSettings, get_settings
from .routes import internal_router, public_router


LOGGER = logging.getLogger(__name__)


def create_app(settings: PlatformSettings | None = None) -> FastAPI:
    selected_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(selected_settings)
        if selected_settings.auto_create_schema:
            init_database(engine)
        session_factory = build_session_factory(engine)
        if selected_settings.auto_create_schema or not selected_settings.is_sqlite:
            with session_factory() as session:
                ensure_reference_data(session)
                ensure_bootstrap_admin(session, selected_settings)
                session.commit()
        app.state.settings = selected_settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.object_store = get_object_store(selected_settings)
        app.state.search_index = ListingSearchIndex(selected_settings)
        app.state.pipeline = CollectionPipeline(
            selected_settings,
            session_factory,
            object_store=app.state.object_store,
            search_index=app.state.search_index,
        )
        try:
            configure_observability(app, selected_settings)
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=selected_settings.api_title,
        version=selected_settings.api_version,
        lifespan=lifespan,
        docs_url="/docs" if selected_settings.environment != "production" else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(selected_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Platform-Key"],
    )
    app.include_router(public_router)
    app.include_router(internal_router)
    return app


def configure_observability(
    app: FastAPI,
    settings: PlatformSettings,
) -> None:
    if not settings.otel_exporter_otlp_endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": "iphone-market-api"})
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=settings.otel_exporter_otlp_endpoint,
                )
            )
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    except ImportError:
        LOGGER.warning("OTel 已配置但依赖未安装，跳过 API 链路追踪")


app = create_app()
