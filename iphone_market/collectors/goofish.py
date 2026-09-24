from __future__ import annotations

from urllib.parse import quote_plus

from playwright.sync_api import Page

from ..config import PhoneVariant
from ..normalization import detect_listing_status, listing_id_from_url
from .base import BaseCollector, RawListing, SourceAccessError


class GoofishCollector(BaseCollector):
    def collect_variant(self, page: Page, variant: PhoneVariant) -> list[RawListing]:
        url = f"{self.spec.base_url}search?q={quote_plus(variant.query + ' 深圳')}"
        self.load(page, url, wait_ms=3_500)
        cards = page.locator(
            'a[href*="item?id="], a[href*="/item?"], a[href*="/item/"]'
        )
        if cards.count() == 0:
            body = self.text(page.locator("body"))
            lowered = body.lower()
            if any(term in body for term in ("登录", "登入", "扫码", "验证")) or "login" in lowered:
                raise SourceAccessError("未取得列表，需要登录或完成安全验证", "login_required")
            return []

        results: list[RawListing] = []
        seen: set[str] = set()
        for index in range(min(cards.count(), self.limit * 5)):
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
                    '[class*="title"]',
                    '[class*="Title"]',
                    '[class*="name"]',
                ),
            )
            if not title:
                title = self.first_attr(card, ("img",), "alt")
            if not title:
                title = self._title_from_text(self.text(card))
            price_text = self.first_text(
                card,
                (
                    '[class*="price"]',
                    '[class*="Price"]',
                    '[class*="money"]',
                ),
            )
            price = self.price_from_text(price_text or self.text(card), self.spec.currency)
            if not title or price is None:
                continue
            card_text = self.text(card)
            location = self.first_text(
                card,
                (
                    '[class*="area"]',
                    '[class*="location"]',
                    '[class*="city"]',
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
                    location=location or "深圳",
                    listing_status=detect_listing_status(card_text),
                    raw={"card_text": card_text, "query": variant.query},
                )
            )
            seen.add(listing_id)
        return results

    @staticmethod
    def _title_from_text(value: str) -> str:
        for line in (part.strip() for part in value.splitlines()):
            if len(line) >= 5 and "¥" not in line and "￥" not in line:
                return line
        return ""
