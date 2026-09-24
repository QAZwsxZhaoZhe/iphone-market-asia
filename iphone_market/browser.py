from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urlparse

from playwright.sync_api import BrowserContext, Error, sync_playwright

from .config import BROWSER_PROFILE_DIR, CHROME_EXECUTABLE, PROXY_URL


class BrowserLaunchError(RuntimeError):
    pass


@contextmanager
def persistent_browser(
    *,
    headless: bool = True,
    profile_dir: Path = BROWSER_PROFILE_DIR,
    viewport: dict[str, int] | None = None,
) -> Iterator[BrowserContext]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    if CHROME_EXECUTABLE is not None and not CHROME_EXECUTABLE.exists():
        raise BrowserLaunchError(
            f"未找到 Chrome：{CHROME_EXECUTABLE}。请设置 IPHONE_MARKET_CHROME。"
        )

    launch_options = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "locale": "zh-CN",
        "viewport": viewport or {"width": 1440, "height": 1000},
        "accept_downloads": False,
        "args": [
            "--disable-popup-blocking",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }
    if CHROME_EXECUTABLE is not None:
        launch_options["executable_path"] = str(CHROME_EXECUTABLE)
    proxy = proxy_settings()
    if proxy:
        launch_options["proxy"] = proxy

    with sync_playwright() as playwright:
        context: BrowserContext | None = None
        try:
            context = playwright.chromium.launch_persistent_context(**launch_options)
            context.set_default_timeout(45_000)
            context.set_default_navigation_timeout(60_000)
            yield context
        except Error as exc:
            message = str(exc)
            if "ProcessSingleton" in message or "user data directory is already in use" in message:
                raise BrowserLaunchError(
                    "浏览器配置目录正在被占用。请关闭由 login 命令打开的采集浏览器后重试。"
                ) from exc
            raise BrowserLaunchError(f"启动 Chrome 失败：{message}") from exc
        finally:
            if context is not None:
                try:
                    context.close()
                except Error:
                    pass


def proxy_settings() -> dict[str, str] | None:
    if not PROXY_URL:
        return None
    parsed = urlparse(PROXY_URL)
    if parsed.scheme not in {"http", "https", "socks4", "socks5"} or not parsed.hostname:
        raise BrowserLaunchError(
            "IPHONE_MARKET_PROXY_URL 格式无效，应类似 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080。"
        )
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    settings = {"server": server}
    if parsed.username:
        settings["username"] = unquote(parsed.username)
    if parsed.password:
        settings["password"] = unquote(parsed.password)
    return settings
