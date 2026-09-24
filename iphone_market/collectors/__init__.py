from __future__ import annotations

from ..config import SOURCE_BY_KEY, SourceSpec
from .base import BaseCollector
from .carousell import CarousellCollector
from .dcfever import DcfeverCollector
from .goofish import GoofishCollector
from .mercari import MercariCollector
from .shopee import ShopeeCollector
from .yahoo_auctions import YahooAuctionsCollector


COLLECTOR_TYPES: dict[str, type[BaseCollector]] = {
    "carousell_sg": CarousellCollector,
    "carousell_hk": CarousellCollector,
    "shopee_sg": ShopeeCollector,
    "dcfever": DcfeverCollector,
    "mercari_jp": MercariCollector,
    "yahoo_jp": YahooAuctionsCollector,
    "goofish_sz": GoofishCollector,
}


def create_collector(source_key: str, limit: int) -> BaseCollector:
    spec: SourceSpec = SOURCE_BY_KEY[source_key]
    collector_type = COLLECTOR_TYPES[source_key]
    return collector_type(spec=spec, limit=limit)


__all__ = ["BaseCollector", "create_collector", "COLLECTOR_TYPES"]
