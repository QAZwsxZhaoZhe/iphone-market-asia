from __future__ import annotations

from urllib.parse import quote_plus

from playwright.sync_api import Page

from ..config import PhoneVariant
from ..normalization import detect_listing_status, listing_id_from_url, parse_price
from .base import BaseCollector, RawListing


class YahooAuctionsCollector(BaseCollector):
    def collect_variant(self, page: Page, variant: PhoneVariant) -> list[RawListing]:
        encoded = quote_plus(variant.query)
        url = (
            "https://auctions.yahoo.co.jp/search/search"
            f"?p={encoded}&va={encoded}"
        )
        self.load(page, url, wait_ms=1_500)
        cards = page.locator("li.Product")
        results: list[RawListing] = []
        seen: set[str] = set()
        for index in range(min(cards.count(), self.limit * 4)):
            card = cards.nth(index)
            anchor = card.locator("a.Product__imageLink")
            if not anchor.count():
                continue
            href = self.attr(anchor.first, "href")
            title = self.attr(anchor.first, "data-auction-title")
            auction_id = self.attr(anchor.first, "data-auction-id")
            price_text = self.attr(anchor.first, "data-auction-price")
            listing_id = auction_id or listing_id_from_url(self.spec.key, href)
            if not href or not title or listing_id in seen:
                continue
            item_url = self.absolute_url(href)
            price = parse_price(price_text, self.spec.currency)
            if price is None or price <= 0:
                continue
            card_text = self.text(card)
            results.append(
                RawListing(
                    variant=variant,
                    listing_id=listing_id,
                    title=title,
                    url=item_url,
                    price_native=price,
                    currency=self.spec.currency,
                    location="日本",
                    listing_status=detect_listing_status(card_text),
                    raw={
                        "card_text": card_text,
                        "auction_id": auction_id,
                        "query": variant.query,
                    },
                )
            )
            seen.add(listing_id)
        return results
