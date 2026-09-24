from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote_plus

from playwright.sync_api import Page, Response

from ..config import PhoneVariant
from ..normalization import listing_id_from_url, parse_api_price
from .base import BaseCollector, RawListing, SourceAccessError


class ShopeeCollector(BaseCollector):
    def collect_variant(self, page: Page, variant: PhoneVariant) -> list[RawListing]:
        api_items: list[dict] = []

        def capture_search(response: Response) -> None:
            if "/api/v4/search/search_items" not in response.url:
                return
            try:
                payload = response.json()
            except Exception:
                return
            for wrapper in payload.get("items") or []:
                item = wrapper.get("item_basic") if isinstance(wrapper, dict) else None
                if isinstance(item, dict):
                    api_items.append(item)

        page.on("response", capture_search)
        url = f"{self.spec.base_url}search?keyword={quote_plus(variant.query)}"
        self.load(page, url, wait_ms=3_000)
        page.wait_for_timeout(1_500)

        results = self._parse_api_items(api_items, variant)
        if results:
            return results

        results = self._parse_dom(page, variant)
        if results:
            return results

        body = self.text(page.locator("body")).lower()
        if "log in" in body or "login" in body or "verify" in body:
            raise SourceAccessError("未取得商品列表，请重新运行 login 完成登录或验证", "login_required")
        return []

    def _parse_api_items(self, items: list[dict], variant: PhoneVariant) -> list[RawListing]:
        results: list[RawListing] = []
        seen: set[str] = set()
        for item in items:
            item_id = str(item.get("itemid") or item.get("item_id") or "")
            shop_id = str(item.get("shopid") or item.get("shop_id") or "")
            title = str(item.get("name") or "").strip()
            if not item_id or not title:
                continue
            listing_id = f"{shop_id}-{item_id}" if shop_id else item_id
            if listing_id in seen:
                continue
            price = parse_api_price(
                item.get("price")
                or item.get("price_min")
                or item.get("price_max")
            )
            if price is None:
                continue
            url = f"{self.spec.base_url}product/{shop_id}/{item_id}"
            results.append(
                RawListing(
                    variant=variant,
                    listing_id=listing_id,
                    title=title,
                    url=url,
                    price_native=price,
                    currency=self.spec.currency,
                    location=str(item.get("shop_location") or "") or None,
                    raw={"api_item": item, "query": variant.query},
                )
            )
            seen.add(listing_id)
            if len(results) >= self.limit * 4:
                break
        return results

    def _parse_dom(self, page: Page, variant: PhoneVariant) -> list[RawListing]:
        cards = page.locator('div[data-sqe="item"], .shopee-search-item-result__item')
        results: list[RawListing] = []
        seen: set[str] = set()
        for index in range(min(cards.count(), self.limit * 4)):
            card = cards.nth(index)
            anchor = card.locator('a[href*="-i."]')
            if not anchor.count():
                continue
            href = self.attr(anchor.first, "href")
            if not href:
                continue
            item_url = self.absolute_url(href)
            listing_id = listing_id_from_url(self.spec.key, item_url)
            if listing_id in seen:
                continue
            title = self.first_text(card, ('[data-sqe="name"]', '[class*="name"]', "div"))
            if not title:
                title = self.first_attr(card, ("img",), "alt")
            price_text = self.first_text(
                card,
                ('[data-sqe="price"]', '[class*="price"]', '[class*="Price"]'),
            )
            price = self.price_from_text(price_text, self.spec.currency)
            if not title or price is None:
                continue
            results.append(
                RawListing(
                    variant=variant,
                    listing_id=listing_id,
                    title=title,
                    url=item_url,
                    price_native=Decimal(price),
                    currency=self.spec.currency,
                    raw={"card_text": self.text(card), "query": variant.query},
                )
            )
            seen.add(listing_id)
        return results
