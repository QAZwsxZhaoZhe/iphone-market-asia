from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .settings import PlatformSettings


LOGGER = logging.getLogger(__name__)


class ListingSearchIndex:
    """Optional OpenSearch projection; PostgreSQL remains the source of truth."""

    def __init__(self, settings: PlatformSettings) -> None:
        self.settings = settings
        self.enabled = bool(settings.opensearch_url)
        self._client = None

    def _get_client(self):
        if not self.enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            from opensearchpy import OpenSearch
        except ImportError:
            LOGGER.warning("OpenSearch 已配置但 opensearch-py 未安装，将回退 PostgreSQL")
            self.enabled = False
            return None
        self._client = OpenSearch(
            hosts=[self.settings.opensearch_url],
            use_ssl=self.settings.opensearch_url.startswith("https"),
            verify_certs=True,
            timeout=10,
        )
        return self._client

    def ensure_index(self) -> bool:
        client = self._get_client()
        if client is None:
            return False
        index = self.settings.opensearch_index
        try:
            if client.indices.exists(index):
                return True
            client.indices.create(
                index=index,
                body={
                    "settings": {
                        "index": {"number_of_shards": 1, "number_of_replicas": 0}
                    },
                    "mappings": {
                        "properties": {
                            "id": {"type": "long"},
                            "source_key": {"type": "keyword"},
                            "model": {"type": "keyword"},
                            "family": {"type": "keyword"},
                            "generation": {"type": "integer"},
                            "storage_gb": {"type": "integer"},
                            "district": {"type": "keyword"},
                            "condition": {"type": "keyword"},
                            "listing_status": {"type": "keyword"},
                            "price_hkd": {"type": "double"},
                            "last_seen_at": {"type": "date"},
                            "search_text": {
                                "type": "text",
                                "fields": {"keyword": {"type": "keyword"}},
                            },
                        }
                    },
                },
            )
            return True
        except Exception as exc:
            LOGGER.warning("OpenSearch 索引创建失败，将回退 PostgreSQL：%s", exc)
            return False

    def index_listing(self, session: Session, listing_id: int) -> None:
        client = self._get_client()
        if client is None or not self.ensure_index():
            return
        listing = session.scalar(
            select(models.Listing).where(models.Listing.id == listing_id)
        )
        if listing is None:
            return
        variant = session.get(models.PhoneVariant, listing.phone_variant_id)
        document = {
            "id": listing.id,
            "source_key": listing.source_key,
            "model": variant.model if variant else None,
            "family": variant.family if variant else None,
            "generation": variant.generation if variant else None,
            "storage_gb": variant.storage_gb if variant else None,
            "district": listing.district,
            "condition": listing.condition,
            "listing_status": listing.listing_status,
            "price_hkd": float(listing.price_hkd)
            if listing.price_hkd is not None
            else None,
            "last_seen_at": listing.last_seen_at.isoformat(),
            "search_text": listing.search_text,
        }
        try:
            client.index(
                index=self.settings.opensearch_index,
                id=str(listing.id),
                body=document,
                refresh=False,
            )
        except Exception as exc:
            LOGGER.warning("商品 %s 写入 OpenSearch 失败：%s", listing_id, exc)

    def search_ids(
        self,
        *,
        query: str | None = None,
        model: str | None = None,
        storage_gb: int | None = None,
        district: str | None = None,
        source_key: str | None = None,
        condition: str = "used",
        listing_status: str | None = "active",
        min_price: float | None = None,
        max_price: float | None = None,
        limit: int = 5000,
    ) -> list[int] | None:
        client = self._get_client()
        if client is None or not self.ensure_index():
            return None
        filters: list[dict[str, Any]] = []
        if model:
            filters.append({"term": {"model": model}})
        if storage_gb is not None:
            filters.append({"term": {"storage_gb": int(storage_gb)}})
        if district:
            filters.append({"term": {"district": district}})
        if source_key:
            filters.append({"term": {"source_key": source_key}})
        if condition:
            filters.append({"term": {"condition": condition}})
        if listing_status:
            filters.append({"term": {"listing_status": listing_status}})
        price_range = {
            key: value
            for key, value in (("gte", min_price), ("lte", max_price))
            if value is not None
        }
        if price_range:
            filters.append({"range": {"price_hkd": price_range}})
        must: list[dict[str, Any]] = []
        if query:
            must.append(
                {
                    "multi_match": {
                        "query": query,
                        "fields": ["search_text^3", "model^2", "district"],
                        "lenient": True,
                    }
                }
            )
        body = {
            "size": max(1, min(int(limit), 10000)),
            "_source": False,
            "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filters}},
        }
        try:
            response = client.search(index=self.settings.opensearch_index, body=body)
            return [int(hit["_id"]) for hit in response.get("hits", {}).get("hits", [])]
        except Exception as exc:
            LOGGER.warning("OpenSearch 查询失败，将回退 PostgreSQL：%s", exc)
            return None
