from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError

from ..config import PhoneVariant, SourceSpec
from ..normalization import normalize_text, parse_price


class SourceAccessError(RuntimeError):
    def __init__(self, message: str, status: str = "blocked") -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RawListing:
    variant: PhoneVariant
    listing_id: str
    title: str
    url: str
    price_native: Decimal | None
    currency: str
    location: str | None = None
    listing_status: str = "active"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class VariantCollection:
    variant: PhoneVariant
    listings: list[RawListing] = field(default_factory=list)
    error: str | None = None


@dataclass
class CollectorOutput:
    source_key: str
    variants: list[VariantCollection]

    @property
    def query_count(self) -> int:
        return len(self.variants)

    @property
    def successful_query_count(self) -> int:
        return sum(1 for result in self.variants if result.error is None)

    @property
    def listings(self) -> list[RawListing]:
        return [listing for result in self.variants for listing in result.listings]

    @property
    def errors(self) -> list[str]:
        return [result.error for result in self.variants if result.error]


class BaseCollector:
    blocked_markers = (
        "enable javascript and cookies to continue",
        "verify you are human",
        "security verification",
        "just a moment",
        "非法访问",
        "安全验证",
        "验证码",
        "请完成验证",
        "アクセスが集中",
        "captcha",
    )
    login_markers = (
        "please log in",
        "please login",
        "log in to continue",
        "请先登录",
        "請先登入",
        "ログインしてください",
    )
    network_error_markers = (
        "net::err_",
        "err_name_not_resolved",
        "err_connection",
        "err_timed_out",
        "err_proxy",
        "econnrefused",
        "econnreset",
        "etimedout",
        "socket hang up",
    )

    def __init__(self, spec: SourceSpec, limit: int = 30) -> None:
        self.spec = spec
        self.limit = limit

    def collect(self, context: BrowserContext, variants: tuple[PhoneVariant, ...]) -> CollectorOutput:
        variant_results: list[VariantCollection] = []
        terminal_error: str | None = None
        consecutive_failures = 0
        for variant in variants:
            if terminal_error is not None:
                variant_results.append(
                    VariantCollection(variant=variant, error=terminal_error)
                )
                continue
            page = context.new_page()
            try:
                listings = self.collect_variant(page, variant)
                variant_results.append(VariantCollection(variant=variant, listings=listings))
                consecutive_failures = 0
            except SourceAccessError as exc:
                message = f"{exc.status}: {exc}"
                variant_results.append(
                    VariantCollection(
                        variant=variant,
                        error=message,
                    )
                )
                if exc.status in {"blocked", "login_required"}:
                    terminal_error = message
            except PlaywrightTimeoutError as exc:
                message = "timeout: 页面加载或列表渲染超时"
                variant_results.append(
                    VariantCollection(
                        variant=variant,
                        error=message,
                    )
                )
                consecutive_failures += 1
                if consecutive_failures >= 2 or self._is_network_error(str(exc)):
                    terminal_error = message
            except Exception as exc:
                message = f"parse_error: {type(exc).__name__}: {exc}"
                variant_results.append(
                    VariantCollection(
                        variant=variant,
                        error=message,
                    )
                )
                if self._is_network_error(str(exc)):
                    consecutive_failures += 1
                    if consecutive_failures >= 2:
                        terminal_error = f"network_error: {exc}"
                else:
                    consecutive_failures = 0
            finally:
                page.close()
        return CollectorOutput(source_key=self.spec.key, variants=variant_results)

    def collect_variant(self, page: Page, variant: PhoneVariant) -> list[RawListing]:
        raise NotImplementedError

    def load(self, page: Page, url: str, *, wait_ms: int = 1200) -> None:
        response = page.goto(url, wait_until="domcontentloaded")
        if response is not None and response.status in {401, 403, 429}:
            raise SourceAccessError(f"HTTP {response.status}", status="blocked")
        page.wait_for_timeout(wait_ms)
        self.assert_page_available(page)

    def load_html_request(
        self,
        page: Page,
        url: str,
        *,
        wait_ms: int = 0,
        timeout_ms: int = 30_000,
    ) -> None:
        """Load a server-rendered page through the browser session without navigation."""
        response = page.context.request.get(url, timeout=timeout_ms)
        if response.status in {401, 403, 429}:
            raise SourceAccessError(f"HTTP {response.status}", status="blocked")
        if not response.ok:
            raise SourceAccessError(f"HTTP {response.status}", status="failed")
        page.set_content(response.text(), wait_until="domcontentloaded")
        if wait_ms:
            page.wait_for_timeout(wait_ms)
        self.assert_page_available(page)

    def assert_page_available(self, page: Page) -> None:
        try:
            text = normalize_text(page.locator("body").inner_text(timeout=5_000)).lower()
        except PlaywrightTimeoutError:
            text = ""
        if any(marker.lower() in text for marker in self.blocked_markers):
            raise SourceAccessError("页面要求验证码或安全检查，请在 login 会话中人工处理", "blocked")
        if any(marker.lower() in text for marker in self.login_markers):
            raise SourceAccessError("登录状态无效，请重新运行 login", "login_required")

    def absolute_url(self, href: str) -> str:
        return urljoin(self.spec.base_url, href)

    def text(self, locator: Locator, default: str = "") -> str:
        try:
            return normalize_text(locator.inner_text(timeout=2_000))
        except Exception:
            return default

    def attr(self, locator: Locator, name: str, default: str = "") -> str:
        try:
            return normalize_text(locator.get_attribute(name, timeout=2_000) or default)
        except Exception:
            return default

    def first_text(self, root: Locator, selectors: tuple[str, ...]) -> str:
        for selector in selectors:
            try:
                nested = root.locator(selector)
                if nested.count():
                    value = self.text(nested.first)
                    if value:
                        return value
            except Exception:
                continue
        return ""

    def first_attr(self, root: Locator, selectors: tuple[str, ...], name: str) -> str:
        for selector in selectors:
            try:
                nested = root.locator(selector)
                if nested.count():
                    value = self.attr(nested.first, name)
                    if value:
                        return value
            except Exception:
                continue
        return ""

    @staticmethod
    def price_from_text(value: str, currency: str) -> Decimal | None:
        text = normalize_text(value)
        currency_pattern = {
            "SGD": r"(?:S\$|SGD)\s*([\d,.]+)",
            "HKD": r"(?:HK\$|HKD)\s*([\d,.]+)",
            "JPY": r"(?:¥|￥|JPY)\s*([\d,.]+)",
            "CNY": r"(?:¥|￥|RMB|CNY)\s*([\d,.]+)",
        }.get(currency)
        if currency_pattern:
            match = re.search(currency_pattern, text, flags=re.IGNORECASE)
            if match:
                return parse_price(match.group(1), currency)
        return parse_price(text, currency)

    @classmethod
    def _is_network_error(cls, message: str) -> bool:
        lowered = message.lower()
        return any(marker in lowered for marker in cls.network_error_markers)
