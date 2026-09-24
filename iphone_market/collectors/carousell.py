from __future__ import annotations

from urllib.parse import quote

from playwright.sync_api import Page

from ..config import PhoneVariant
from ..normalization import detect_listing_status, listing_id_from_url
from .base import BaseCollector, RawListing, SourceAccessError


class CarousellCollector(BaseCollector):
    def collect_variant(self, page: Page, variant: PhoneVariant) -> list[RawListing]:
        query = quote(variant.query)
        url = f"{self.spec.base_url}search/{query}?addRecent=true&canChangeKeyword=true"
        self.load(page, url, wait_ms=2_000)

        cards = page.locator('a[href*="/p/"]')
        if cards.count() == 0:
            body = self.text(page.locator("body")).lower()
            if "log in" in body or "login" in body:
                raise SourceAccessError("未检测到列表且页面提示登录，请重新运行 login", "login_required")
            raise SourceAccessError("未找到列表卡片，可能被安全检查或页面已改版", "blocked")

        results: list[RawListing] = []
        seen: set[str] = set()
        for index in range(min(cards.count(), self.limit * 4)):
            card = cards.nth(index)
            href = self.attr(card, "href")
            if not href:
                continue
            item_url = self.absolute_url(href)
            listing_id = listing_id_from_url(self.spec.key, item_url)
            if listing_id in seen:
                continue

            title = self.first_text(
                card,
                (
                    '[data-testid*="listing-card-title"]',
                    '[class*="title"]',
                    "p",
                    "h3",
                ),
            )
            if not title:
                title = self.first_attr(card, ("img",), "alt")
            if not title:
                title = self._title_from_card_text(self.text(card))
            if not title:
                continue

            price_text = self.first_text(
                card,
                (
                    '[data-testid*="listing-card-price"]',
                    '[class*="price"]',
                    '[class*="Price"]',
                ),
            )
            price = self.price_from_text(price_text or self.text(card), self.spec.currency)
            if price is None or price <= 0:
                continue

            card_text = self.text(card)
            location = self.first_text(
                card,
                (
                    '[data-testid*="listing-card-location"]',
                    '[class*="location"]',
                    '[class*="Location"]',
                ),
            )
            results.append(
                RawListing(
                    variant=variant,
                    listing_id=listing_id,
                    title=title,
                    url=item_url,
                    price_native=price,
                    currency=self.spec.currency,
                    location=location or None,
                    listing_status=detect_listing_status(card_text),
                    raw={"card_text": card_text, "href": href, "query": variant.query},
                )
            )
            seen.add(listing_id)
        return results

    @staticmethod
    def _title_from_card_text(value: str) -> str:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        for line in lines:
            lowered = line.lower()
            if any(symbol in lowered for symbol in ("s$", "sgd", "sold", "sponsored")):
                continue
            if len(line) >= 4:
                return line
        return ""
