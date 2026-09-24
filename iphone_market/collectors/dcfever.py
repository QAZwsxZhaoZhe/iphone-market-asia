from __future__ import annotations

from urllib.parse import quote_plus

from playwright.sync_api import Page

from ..config import PhoneVariant
from ..normalization import detect_listing_status, listing_id_from_url
from .base import BaseCollector, RawListing


class DcfeverCollector(BaseCollector):
    def collect_variant(self, page: Page, variant: PhoneVariant) -> list[RawListing]:
        url = (
            "https://www.dcfever.com/trading/search.php"
            f"?form_action=search_action&keyword={quote_plus(variant.query)}"
        )
        self.load_html_request(page, url)
        cards = page.locator('a[href*="view.php?id="]')
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
            title = self.first_text(card, (".trade_title",))
            alt_title = self.first_attr(card, ("img",), "alt")
            if alt_title and (not title or title.endswith("...") or len(alt_title) > len(title)):
                title = alt_title
            price_text = self.first_text(card, (".price", '[class*="price"]'))
            price = self.price_from_text(price_text, self.spec.currency)
            if not title or price is None:
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
                    location="香港",
                    listing_status=detect_listing_status(card_text),
                    raw={"card_text": card_text, "query": variant.query},
                )
            )
            seen.add(listing_id)
        return results
