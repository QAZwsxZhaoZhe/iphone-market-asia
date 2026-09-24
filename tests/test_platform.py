from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from iphone_market import db as legacy_db
from iphone_market.collectors.base import (
    CollectorOutput,
    RawListing,
    VariantCollection,
)
from iphone_market.config import PHONE_VARIANTS, SOURCE_BY_KEY
from iphone_market.models import ListingRecord
from iphone_market.platform import models, repository
from iphone_market.platform.api.app import create_app
from iphone_market.platform.database import (
    build_engine,
    build_session_factory,
    init_database,
)
from iphone_market.platform.identity import create_user, hash_session_token
from iphone_market.platform.ingest import CollectionPipeline
from iphone_market.platform.object_store import LocalObjectStore
from iphone_market.platform.search import ListingSearchIndex
from iphone_market.platform.services import (
    LegacyImportService,
    MarketAnalyticsService,
)
from iphone_market.platform.settings import PlatformSettings


def _settings(tmp_path: Path, **overrides) -> PlatformSettings:
    values = {
        "database_url": f"sqlite:///{(tmp_path / 'platform.sqlite3').as_posix()}",
        "object_store_local_dir": str(tmp_path / "raw"),
        "auto_create_schema": True,
        "environment": "test",
    }
    values.update(overrides)
    return PlatformSettings(**values)


def _record(
    listing_id: str,
    *,
    source_key: str = "dcfever",
    model: str = "iPhone 14 Pro",
    storage_gb: int = 128,
    price: str = "5000",
    title: str | None = None,
    district: str = "旺角",
    status: str = "active",
    condition: str = "used",
) -> SimpleNamespace:
    return SimpleNamespace(
        source_key=source_key,
        source_name=SOURCE_BY_KEY[source_key].name,
        market="香港",
        listing_id=listing_id,
        title=title or f"{model} {storage_gb}GB used {listing_id}",
        url=f"https://example.test/{source_key}/{listing_id}",
        model=model,
        generation=int(model.split()[1]),
        family="Pro Max" if "Pro Max" in model else "Pro",
        storage_gb=storage_gb,
        condition=condition,
        listing_status=status,
        price_native=Decimal(price),
        currency="HKD",
        location=district,
        fx_date="2026-09-24",
        raw={"seller_phone": "12345678", "html": "<html>private</html>"},
    )


class PlatformPipelineTests(unittest.TestCase):
    def test_duplicate_ingestion_is_idempotent_and_history_is_correct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            settings = _settings(tmp_path)
            engine = build_engine(settings)
            init_database(engine)
            session_factory = build_session_factory(engine)
            pipeline = CollectionPipeline(
                settings,
                session_factory,
                object_store=LocalObjectStore(tmp_path / "raw"),
                search_index=ListingSearchIndex(settings),
            )
            observed = datetime(2026, 9, 24, 1, tzinfo=timezone.utc)
            spec = SOURCE_BY_KEY["dcfever"]

            first = pipeline.ingest_records(
                [_record("item-1", price="5000")],
                spec=spec,
                observed_at=observed,
                run_date="2026-09-24",
            )
            second = pipeline.ingest_records(
                [_record("item-1", price="5000")],
                spec=spec,
                observed_at=observed,
                run_date="2026-09-24",
            )
            later = pipeline.ingest_records(
                [_record("item-1", price="4700")],
                spec=spec,
                observed_at=observed + timedelta(days=1),
                run_date="2026-09-25",
            )

            self.assertEqual(first["snapshots"], 1)
            self.assertEqual(first["raw_captures"], 1)
            self.assertEqual(second["snapshots"], 0)
            self.assertEqual(second["raw_captures"], 0)
            self.assertEqual(later["snapshots"], 1)

            with session_factory() as session:
                self.assertEqual(
                    session.query(repository.models.Listing).count(),
                    1,
                )
                self.assertEqual(
                    session.query(repository.models.ListingSnapshot).count(),
                    2,
                )
                listing = session.query(repository.models.Listing).one()
                history = repository.listing_history(session, listing.id)
                self.assertEqual(
                    [float(snapshot.price_hkd) for snapshot in history],
                    [4700.0, 5000.0],
                )
            engine.dispose()

    def test_source_failure_isolated_from_successful_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            settings = _settings(tmp_path)
            engine = build_engine(settings)
            init_database(engine)
            session_factory = build_session_factory(engine)
            pipeline = CollectionPipeline(
                settings,
                session_factory,
                object_store=LocalObjectStore(tmp_path / "raw"),
                search_index=ListingSearchIndex(settings),
            )
            variant = PHONE_VARIANTS[0]

            class FakeCollector:
                def __init__(self, source_key: str) -> None:
                    self.source_key = source_key

                def collect(self, _context, _variants):
                    if self.source_key == "carousell_hk":
                        raise RuntimeError("page changed")
                    return CollectorOutput(
                        source_key=self.source_key,
                        variants=[
                            VariantCollection(
                                variant=variant,
                                listings=[
                                    RawListing(
                                        variant=variant,
                                        listing_id="dcfever-1",
                                        title=(
                                            f"{variant.model} "
                                            f"{variant.storage_label} used"
                                        ),
                                        url="https://example.test/dcfever-1",
                                        price_native=Decimal("5000"),
                                        currency="HKD",
                                    )
                                ],
                            )
                        ],
                    )

            class BrowserContext:
                def __enter__(self):
                    return object()

                def __exit__(self, *_args):
                    return False

            with patch(
                "iphone_market.platform.ingest.persistent_browser",
                return_value=BrowserContext(),
            ), patch(
                "iphone_market.platform.ingest.create_collector",
                side_effect=lambda key, _limit: FakeCollector(key),
            ), patch.object(
                pipeline,
                "_load_rates",
                return_value=None,
            ):
                with self.assertRaises(RuntimeError):
                    pipeline.collect_source(
                        "carousell_hk",
                        run_date="2026-09-24",
                        limit=1,
                    )
                ok = pipeline.collect_source(
                    "dcfever",
                    run_date="2026-09-24",
                    limit=1,
                )

            self.assertEqual(ok["status"], "ok")
            with session_factory() as session:
                runs = repository.recent_runs(session, limit=10)
                statuses = {run.source_key: run.status for run in runs}
                self.assertEqual(statuses["carousell_hk"], "failed")
                self.assertEqual(statuses["dcfever"], "ok")
            engine.dispose()

    def test_legacy_import_converts_cny_history_to_hkd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            legacy_path = tmp_path / "legacy.sqlite3"
            legacy_db.init_db(legacy_path)
            conn = legacy_db.connect(legacy_path)
            run_id = legacy_db.start_run(conn, "2026-09-20")
            legacy_db.start_source_run(conn, run_id, "dcfever", "香港")
            legacy_db.insert_listings(
                conn,
                run_id,
                "2026-09-20",
                [
                    ListingRecord(
                        source_key="dcfever",
                        source_name="DCFever",
                        market="香港",
                        listing_id="legacy-1",
                        title="iPhone 14 Pro 128GB used",
                        url="https://example.test/legacy-1",
                        model="iPhone 14 Pro",
                        generation=14,
                        family="Pro",
                        storage_gb=128,
                        condition="used",
                        listing_status="active",
                        price_native=Decimal("900"),
                        currency="CNY",
                        price_cny=Decimal("900"),
                        fx_date="2026-09-20",
                        location="旺角",
                        raw={},
                    )
                ],
            )
            conn.execute(
                """
                INSERT INTO fx_rates(rate_date, rates_json, source, updated_at)
                VALUES ('2026-09-20', '{"CNY": "1", "HKD": "1.1"}', 'test', 'now')
                """
            )
            conn.commit()
            conn.close()

            settings = _settings(tmp_path)
            engine = build_engine(settings)
            init_database(engine)
            session_factory = build_session_factory(engine)
            with session_factory() as session:
                result = LegacyImportService(
                    settings,
                    LocalObjectStore(tmp_path / "raw"),
                ).import_sqlite(session, legacy_path)
                session.commit()
                listing = session.query(models.Listing).one()
                self.assertEqual(result["listings"], 1)
                self.assertEqual(float(listing.price_native), 900.0)
                self.assertEqual(float(listing.price_hkd), 818.18)
            engine.dispose()


class PlatformApiTests(unittest.TestCase):
    def test_session_registration_login_logout_and_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            settings = _settings(
                tmp_path,
                auth_mode="api_key",
                api_key="test-key",
            )
            with TestClient(create_app(settings)) as client:
                registered = client.post(
                    "/v1/auth/register",
                    json={
                        "email": "Buyer@Example.test",
                        "password": "buyer-password",
                        "display_name": "測試買家",
                    },
                )
                self.assertEqual(registered.status_code, 201)
                registration = registered.json()
                self.assertEqual(registration["user"]["email"], "buyer@example.test")
                self.assertEqual(registration["user"]["roles"], ["buyer"])

                duplicate = client.post(
                    "/v1/auth/register",
                    json={
                        "email": "buyer@example.test",
                        "password": "buyer-password",
                        "display_name": "重複買家",
                    },
                )
                self.assertEqual(duplicate.status_code, 409)

                logged_in = client.post(
                    "/v1/auth/login",
                    json={
                        "email": "buyer@example.test",
                        "password": "buyer-password",
                    },
                )
                self.assertEqual(logged_in.status_code, 200)
                token = logged_in.json()["token"]
                headers = {"Authorization": f"Bearer {token}"}
                principal = client.get("/v1/auth/me", headers=headers)
                self.assertEqual(principal.status_code, 200)
                self.assertFalse(principal.json()["internal"])
                self.assertEqual(principal.json()["auth_method"], "session")

                logged_out = client.post("/v1/auth/logout", headers=headers)
                self.assertEqual(logged_out.status_code, 200)
                self.assertTrue(logged_out.json()["revoked"])
                self.assertEqual(
                    client.get("/v1/auth/me", headers=headers).status_code,
                    401,
                )

                logged_in_again = client.post(
                    "/v1/auth/login",
                    json={
                        "email": "buyer@example.test",
                        "password": "buyer-password",
                    },
                )
                expiring_token = logged_in_again.json()["token"]
                session_factory = client.app.state.session_factory
                with session_factory() as session:
                    auth_session = (
                        session.query(models.AuthSession)
                        .filter(
                            models.AuthSession.token_hash
                            == hash_session_token(expiring_token)
                        )
                        .one()
                    )
                    auth_session.expires_at = (
                        datetime.now(timezone.utc) - timedelta(seconds=1)
                    )
                    session.commit()
                self.assertEqual(
                    client.get(
                        "/v1/auth/me",
                        headers={"Authorization": f"Bearer {expiring_token}"},
                    ).status_code,
                    401,
                )

            closed_settings = _settings(
                tmp_path,
                auth_mode="api_key",
                api_key="test-key",
                allow_public_registration=False,
            )
            with TestClient(create_app(closed_settings)) as client:
                closed = client.post(
                    "/v1/auth/register",
                    json={
                        "email": "closed@example.test",
                        "password": "buyer-password",
                        "display_name": "停用註冊",
                    },
                )
                self.assertEqual(closed.status_code, 403)

    def test_role_boundaries_and_b2c_publish_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            settings = _settings(
                tmp_path,
                auth_mode="api_key",
                api_key="test-key",
            )
            with TestClient(create_app(settings)) as client:
                session_factory = client.app.state.session_factory
                with session_factory() as session:
                    create_user(
                        session,
                        email="buyer@example.test",
                        password="buyer-password",
                        display_name="Buyer",
                        roles=("buyer",),
                    )
                    create_user(
                        session,
                        email="analyst@example.test",
                        password="analyst-password",
                        display_name="Analyst",
                        roles=("analyst",),
                    )
                    create_user(
                        session,
                        email="operator@example.test",
                        password="operator-password",
                        display_name="Operator",
                        roles=("operator",),
                    )
                    session.commit()

                def login(email: str, password: str) -> dict[str, str]:
                    response = client.post(
                        "/v1/auth/login",
                        json={"email": email, "password": password},
                    )
                    self.assertEqual(response.status_code, 200)
                    return {
                        "Authorization": f"Bearer {response.json()['token']}"
                    }

                buyer_headers = login("buyer@example.test", "buyer-password")
                analyst_headers = login(
                    "analyst@example.test",
                    "analyst-password",
                )
                operator_headers = login(
                    "operator@example.test",
                    "operator-password",
                )

                self.assertEqual(
                    client.get(
                        "/internal/v1/inventory",
                        headers=buyer_headers,
                    ).status_code,
                    401,
                )
                self.assertEqual(
                    client.get(
                        "/internal/v1/inventory",
                        headers=analyst_headers,
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    client.post(
                        "/internal/v1/merchants",
                        headers=analyst_headers,
                        json={
                            "legal_name": "Analyst Shop Limited",
                            "display_name": "不應建立",
                            "merchant_type": "business",
                            "commission_rate_bps": 1000,
                            "status": "active",
                        },
                    ).status_code,
                    403,
                )

                meta = client.get("/v1/meta")
                self.assertEqual(meta.status_code, 200)
                variant_id = meta.json()["variants"][0]["id"]
                self.assertTrue(variant_id)

                merchant = client.post(
                    "/internal/v1/merchants",
                    headers=operator_headers,
                    json={
                        "legal_name": "HK Certified Devices Limited",
                        "display_name": "香港認證手機",
                        "merchant_type": "business",
                        "commission_rate_bps": 800,
                        "status": "active",
                    },
                )
                self.assertEqual(merchant.status_code, 201)
                merchant_id = merchant.json()["id"]

                self.assertEqual(
                    client.post(
                        "/internal/v1/users",
                        headers=operator_headers,
                        json={
                            "email": "forbidden-admin@example.test",
                            "password": "forbidden-admin-password",
                            "display_name": "Forbidden Admin",
                            "roles": ["admin"],
                        },
                    ).status_code,
                    403,
                )

                inventory = client.post(
                    "/internal/v1/inventory",
                    headers=operator_headers,
                    json={
                        "merchant_id": merchant_id,
                        "phone_variant_id": variant_id,
                        "sku": "HK-IPHONE-0001",
                        "condition_grade": "A",
                        "battery_health_pct": 91,
                        "repair_history": [],
                        "accessories": ["充電線"],
                        "cost_hkd": 4200,
                        "status": "available",
                    },
                )
                self.assertEqual(inventory.status_code, 201)
                inventory_payload = inventory.json()
                self.assertEqual(inventory_payload["cost_hkd"], 4200)
                inventory_id = inventory_payload["id"]

                created_listing = client.post(
                    "/internal/v1/seller-listings",
                    headers=operator_headers,
                    json={
                        "merchant_id": merchant_id,
                        "inventory_item_id": inventory_id,
                        "title": "iPhone 14 Pro 128GB 認證二手",
                        "description": "已驗機，功能正常。",
                        "price_hkd": 5299,
                        "warranty_days": 30,
                        "inspection_report": {"battery": "正常"},
                        "images": [],
                        "slug": "iphone-14-pro-128-hk-0001",
                    },
                )
                self.assertEqual(created_listing.status_code, 201)
                listing = created_listing.json()
                self.assertEqual(listing["status"], "draft")
                self.assertNotIn("cost_hkd", listing)
                self.assertEqual(
                    client.get(
                        f"/v1/store/listings/{listing['id']}"
                    ).status_code,
                    404,
                )

                published = client.post(
                    f"/internal/v1/seller-listings/{listing['id']}/publish",
                    headers=operator_headers,
                )
                self.assertEqual(published.status_code, 200)
                self.assertEqual(published.json()["status"], "active")
                self.assertIsNotNone(published.json()["published_at"])

                store = client.get("/v1/store/listings")
                self.assertEqual(store.status_code, 200)
                self.assertEqual(store.json()["total"], 1)
                store_item = store.json()["items"][0]
                self.assertNotIn("cost_hkd", store_item)
                self.assertNotIn("inventory_item_id", store_item)

                detail = client.get(
                    "/v1/store/listings/iphone-14-pro-128-hk-0001"
                )
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["id"], listing["id"])
                self.assertNotIn("cost_hkd", detail.json())

                internal_inventory = client.get(
                    "/internal/v1/inventory",
                    headers=operator_headers,
                )
                self.assertEqual(internal_inventory.status_code, 200)
                self.assertEqual(
                    internal_inventory.json()[0]["listing_id"],
                    listing["id"],
                )

                quick_listing = client.post(
                    "/internal/v1/seller-listings/quick",
                    headers=operator_headers,
                    json={
                        "merchant_id": merchant_id,
                        "phone_variant_id": variant_id,
                        "condition_grade": "A",
                        "price_hkd": 4999,
                        "battery_health_pct": 88,
                        "images": ["https://example.test/iphone.jpg"],
                    },
                )
                self.assertEqual(quick_listing.status_code, 201)
                quick_payload = quick_listing.json()
                self.assertEqual(quick_payload["status"], "active")
                self.assertTrue(quick_payload["title"])
                self.assertEqual(
                    quick_payload["inventory"]["battery_health_pct"],
                    88,
                )
                self.assertEqual(
                    quick_payload["images"],
                    ["https://example.test/iphone.jpg"],
                )
                self.assertIsNotNone(quick_payload["published_at"])
                self.assertNotIn("cost_hkd", quick_payload)

                store_after_quick = client.get("/v1/store/listings")
                self.assertEqual(store_after_quick.status_code, 200)
                self.assertEqual(store_after_quick.json()["total"], 2)

                second_quick_listing = client.post(
                    "/internal/v1/seller-listings/quick",
                    headers=operator_headers,
                    json={
                        "merchant_id": merchant_id,
                        "phone_variant_id": variant_id,
                        "condition_grade": "B",
                        "price_hkd": 4599,
                        "battery_health_pct": 84,
                    },
                )
                self.assertEqual(second_quick_listing.status_code, 201)
                inventory_after_quick = client.get(
                    "/internal/v1/inventory",
                    headers=operator_headers,
                )
                quick_skus = [
                    item["sku"]
                    for item in inventory_after_quick.json()
                    if item["listing_id"]
                    in {
                        quick_payload["id"],
                        second_quick_listing.json()["id"],
                    }
                ]
                self.assertEqual(len(quick_skus), 2)
                self.assertEqual(len(set(quick_skus)), 2)
                self.assertEqual(
                    client.get("/v1/store/listings").json()["total"],
                    3,
                )

    def test_production_rejects_weak_auth_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "PLATFORM_API_KEY"):
            PlatformSettings(
                environment="production",
                database_url=(
                    "postgresql+psycopg://iphone_market:password"
                    "@127.0.0.1:5432/iphone_market"
                ),
                auth_mode="api_key",
                api_key="short-key",
            )

    def test_public_api_excludes_inactive_non_hk_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            settings = _settings(tmp_path)
            with TestClient(create_app(settings)) as client:
                pipeline = client.app.state.pipeline
                observed = datetime(2026, 9, 24, 2, tzinfo=timezone.utc)
                pipeline.ingest_records(
                    [_record("hk-1", price="4300")],
                    spec=SOURCE_BY_KEY["dcfever"],
                    observed_at=observed,
                    run_date="2026-09-24",
                )
                pipeline.ingest_records(
                    [_record("jp-1", source_key="mercari_jp", price="3999")],
                    spec=SOURCE_BY_KEY["mercari_jp"],
                    observed_at=observed,
                    run_date="2026-09-24",
                )

                listing_page = client.get("/v1/listings")
                self.assertEqual(listing_page.status_code, 200)
                self.assertEqual(listing_page.json()["total"], 1)
                self.assertEqual(
                    listing_page.json()["items"][0]["source_key"],
                    "dcfever",
                )

                market = client.get("/v1/market/summary")
                self.assertEqual(market.status_code, 200)
                self.assertEqual(market.json()["source_count"], 1)
                self.assertEqual(
                    [group["key"] for group in market.json()["by_source"]],
                    ["dcfever"],
                )

                session_factory = client.app.state.session_factory
                with session_factory() as session:
                    overseas_id = (
                        session.query(models.Listing.id)
                        .filter(models.Listing.source_key == "mercari_jp")
                        .scalar()
                    )
                self.assertEqual(
                    client.get(f"/v1/listings/{overseas_id}").status_code,
                    404,
                )

    def test_public_search_pagination_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            settings = _settings(tmp_path, default_page_size=2)
            with TestClient(create_app(settings)) as client:
                session_factory = client.app.state.session_factory
                spec = SOURCE_BY_KEY["dcfever"]
                pipeline = client.app.state.pipeline
                observed = datetime(2026, 9, 24, 2, tzinfo=timezone.utc)
                pipeline.ingest_records(
                    [
                        _record("a", price="4300", storage_gb=128),
                        _record("b", price="4600", storage_gb=128),
                        _record("c", price="5100", storage_gb=256),
                    ],
                    spec=spec,
                    observed_at=observed,
                    run_date="2026-09-24",
                )

                page = client.get(
                    "/v1/listings",
                    params={
                        "q": "iPhone 14 Pro",
                        "storage_gb": 128,
                        "max_price": 5000,
                        "limit": 1,
                    },
                )
                self.assertEqual(page.status_code, 200)
                payload = page.json()
                self.assertEqual(payload["total"], 2)
                self.assertEqual(len(payload["items"]), 1)
                self.assertIsNotNone(payload["next_cursor"])

                next_page = client.get(
                    "/v1/listings",
                    params={
                        "q": "iPhone 14 Pro",
                        "storage_gb": 128,
                        "cursor": payload["next_cursor"],
                        "limit": 1,
                    },
                )
                self.assertEqual(next_page.status_code, 200)
                self.assertEqual(next_page.json()["total"], 1)

                listing = client.get(f"/v1/listings/{payload['items'][0]['id']}")
                detail = listing.json()
                self.assertNotIn("raw_metadata", detail)
                self.assertNotIn("seller_signals", detail)
                self.assertNotIn("search_text", detail)

    def test_api_key_and_oidc_roles_authorize_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            settings = _settings(
                tmp_path,
                auth_mode="api_key",
                api_key="test-key",
            )
            with TestClient(create_app(settings)) as client:
                self.assertEqual(client.get("/internal/v1/sources").status_code, 401)
                authorized = client.get(
                    "/internal/v1/sources",
                    headers={"X-Platform-Key": "test-key"},
                )
                self.assertEqual(authorized.status_code, 200)

            oidc_settings = _settings(
                tmp_path,
                auth_mode="oidc",
                oidc_jwks_url="https://issuer.test/jwks",
            )
            with TestClient(create_app(oidc_settings)) as client:
                with patch(
                    "iphone_market.platform.api.auth._decode_oidc_token",
                    return_value={"sub": "analyst-1", "roles": ["analyst"]},
                ):
                    self.assertEqual(
                        client.get(
                            "/internal/v1/sources",
                            headers={"Authorization": "Bearer token"},
                        ).status_code,
                        200,
                    )
                    forbidden = client.post(
                        "/internal/v1/clusters/rebuild",
                        headers={"Authorization": "Bearer token"},
                    )
                    self.assertEqual(forbidden.status_code, 403)

                with patch(
                    "iphone_market.platform.api.auth._decode_oidc_token",
                    return_value={"sub": "operator-1", "roles": ["operator"]},
                ):
                    accepted = client.post(
                        "/internal/v1/clusters/rebuild",
                        headers={"Authorization": "Bearer token"},
                    )
                    self.assertEqual(accepted.status_code, 200)

                session_factory = client.app.state.session_factory
                with session_factory() as session:
                    audit = repository.audit_entries(session, limit=1)[0]
                    self.assertEqual(audit.actor, "operator-1")
                    self.assertEqual(audit.action, "clusters.rebuild")

    def test_market_valuation_alerts_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            settings = _settings(tmp_path)
            engine = build_engine(settings)
            init_database(engine)
            session_factory = build_session_factory(engine)
            observed = datetime(2026, 9, 24, 3, tzinfo=timezone.utc)
            with session_factory() as session:
                repository.ensure_reference_data(session)
                for index, (price, district) in enumerate(
                    [
                        ("4000", "旺角"),
                        ("4200", "旺角"),
                        ("4400", "深水埗"),
                        ("4600", "沙田"),
                        ("4800", "灣仔"),
                        ("5000", "中西區"),
                    ],
                    start=1,
                ):
                    repository.upsert_listing_observation(
                        session,
                        _record(
                            f"m-{index}",
                            price=price,
                            district=district,
                        ),
                        observed_at=observed,
                    )
                session.add(
                    models.Watchlist(
                        id="watch-1",
                        name="四千五以下",
                        filter_json={
                            "model": "iPhone 14 Pro",
                            "storage_gb": 128,
                            "max_price": 4500,
                        },
                        notification_json={"enabled": True},
                    )
                )
                session.commit()

                analytics = MarketAnalyticsService(settings)
                valuation = analytics.valuation(
                    session,
                    model="iPhone 14 Pro",
                    storage_gb=128,
                )
                self.assertEqual(valuation["status"], "ok")
                self.assertEqual(valuation["sample_count"], 6)
                self.assertEqual(
                    analytics.refresh_valuations(session),
                    1,
                )
                self.assertEqual(
                    analytics.evaluate_alerts(session),
                    3,
                )
                session.commit()

                self.assertEqual(
                    session.query(models.Valuation).count(),
                    1,
                )
                self.assertEqual(session.query(models.Alert).count(), 3)
                summary = analytics.market_summary(session)
                self.assertEqual(summary["metrics"]["count"], 6)
                self.assertEqual(summary["source_count"], 1)
                self.assertEqual(summary["district_coverage"], 5)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
