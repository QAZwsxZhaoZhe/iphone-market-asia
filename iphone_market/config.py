from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("IPHONE_MARKET_DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = DATA_DIR / "market.sqlite3"
BROWSER_PROFILE_DIR = DATA_DIR / "chrome-profile"
LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = PROJECT_ROOT / "reports"

_configured_chrome = os.environ.get("IPHONE_MARKET_CHROME", "").strip()
CHROME_EXECUTABLE: Path | None = (
    Path(_configured_chrome)
    if _configured_chrome
    else (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if os.name == "nt"
        else None
    )
)
PROXY_URL = (
    os.environ.get("IPHONE_MARKET_PROXY_URL")
    or os.environ.get("HTTPS_PROXY")
    or os.environ.get("HTTP_PROXY")
    or ""
).strip()

DEFAULT_LIMIT = 30
DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
SCHEDULE_TASK_NAME = "二手iPhone每日采集"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    market: str
    currency: str
    base_url: str
    login_url: str | None = None
    requires_login: bool = False


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        key="carousell_sg",
        name="Carousell SG",
        market="新加坡",
        currency="SGD",
        base_url="https://www.carousell.sg/",
        login_url="https://www.carousell.sg/",
        requires_login=True,
    ),
    SourceSpec(
        key="shopee_sg",
        name="Shopee SG",
        market="新加坡",
        currency="SGD",
        base_url="https://shopee.sg/",
        login_url="https://shopee.sg/buyer/login",
        requires_login=True,
    ),
    SourceSpec(
        key="carousell_hk",
        name="Carousell HK",
        market="香港",
        currency="HKD",
        base_url="https://www.carousell.com.hk/",
        login_url="https://www.carousell.com.hk/",
        requires_login=True,
    ),
    SourceSpec(
        key="dcfever",
        name="DCFever",
        market="香港",
        currency="HKD",
        base_url="https://www.dcfever.com/trading/",
    ),
    SourceSpec(
        key="mercari_jp",
        name="Mercari JP",
        market="日本",
        currency="JPY",
        base_url="https://jp.mercari.com/",
    ),
    SourceSpec(
        key="yahoo_jp",
        name="Yahoo Auctions JP",
        market="日本",
        currency="JPY",
        base_url="https://auctions.yahoo.co.jp/",
    ),
    SourceSpec(
        key="goofish_sz",
        name="闲鱼深圳",
        market="深圳",
        currency="CNY",
        base_url="https://www.goofish.com/",
        login_url="https://www.goofish.com/",
        requires_login=True,
    ),
)

SOURCE_BY_KEY = {source.key: source for source in SOURCES}
SOURCE_KEYS = tuple(source.key for source in SOURCES)
MARKET_ORDER = ("新加坡", "香港", "日本", "深圳")

# 当前业务范围只保留香港。旧来源配置和历史数据继续保留，便于查询和回溯，
# 但所有默认采集、状态展示和报表入口只使用这组活跃来源。
ACTIVE_SOURCE_KEYS = ("carousell_hk", "dcfever")
ACTIVE_SOURCES = tuple(SOURCE_BY_KEY[key] for key in ACTIVE_SOURCE_KEYS)
ACTIVE_SOURCE_BY_KEY = {source.key: source for source in ACTIVE_SOURCES}
ACTIVE_MARKET_ORDER = ("香港",)


@dataclass(frozen=True)
class PhoneVariant:
    model: str
    generation: int
    family: str
    storage_gb: int

    @property
    def query(self) -> str:
        return f"iPhone {self.generation} {self.family} {self.storage_label}"

    @property
    def storage_label(self) -> str:
        if self.storage_gb == 1024:
            return "1TB"
        if self.storage_gb == 2048:
            return "2TB"
        return f"{self.storage_gb}GB"


_CAPACITY_MATRIX: dict[tuple[int, str], tuple[int, ...]] = {
    (14, "Pro"): (128, 256, 512, 1024),
    (14, "Pro Max"): (128, 256, 512, 1024),
    (15, "Pro"): (128, 256, 512, 1024),
    (15, "Pro Max"): (256, 512, 1024),
    (16, "Pro"): (128, 256, 512, 1024),
    (16, "Pro Max"): (256, 512, 1024),
    (17, "Pro"): (256, 512, 1024),
    (17, "Pro Max"): (256, 512, 1024, 2048),
}

PHONE_VARIANTS: tuple[PhoneVariant, ...] = tuple(
    PhoneVariant(
        model=f"iPhone {generation} {family}",
        generation=generation,
        family=family,
        storage_gb=storage_gb,
    )
    for (generation, family), capacities in _CAPACITY_MATRIX.items()
    for storage_gb in capacities
)


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
