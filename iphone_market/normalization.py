from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

from .config import PhoneVariant


BOX_ONLY_TERMS = (
    "box only",
    "empty box",
    "空盒",
    "淨盒",
    "净盒",
    "僅盒",
    "只有盒",
    "只賣盒",
    "只卖盒",
    "盒only",
    "盒 only",
)

ACCESSORY_TERMS = (
    "手机壳",
    "保護殼",
    "保护壳",
    "壳",
    "case",
    "cover",
    "screen protector",
    "保护膜",
    "保護膜",
    "钢化膜",
    "鋼化膜",
    "充电器",
    "充電器",
    "charger",
    "cable",
    "数据线",
    "數據線",
    "airpods",
    "earbuds",
    "配件",
    "ケース",
    "カバー",
    "フィルム",
    "保護ガラス",
    "充電器",
    "ケーブル",
    "バッテリーのみ",
    "battery only",
    "lens",
)

BROKEN_TERMS = (
    "broken",
    "faulty",
    "parts",
    "part only",
    "for parts",
    "cracked",
    "crack",
    "dead",
    "no power",
    "water damage",
    "icloud locked",
    "activation lock",
    "撞",
    "凹",
    "故障",
    "损坏",
    "損壞",
    "拆修",
    "拆机",
    "拆機",
    "零件",
    "不能用",
    "不能开機",
    "不能开机",
    "屏幕碎",
    "螢幕碎",
    "液晶割れ",
    "画面割れ",
    "画面破損",
    "ジャンク",
    "部品取り",
    "故障品",
    "起動しない",
)

NEW_TERMS = (
    "brand new",
    "sealed",
    "unopened",
    "未拆",
    "未開封",
    "未开封",
    "全新",
    "新品",
    "未使用",
    "未使用品",
)

WANTED_TERMS = (
    "征求",
    "徵求",
    "求购",
    "求購",
    "收购",
    "收購",
    "want to buy",
    "looking for",
    "buying",
    "wanted",
    "高價收",
    "高价收",
    "誠收",
    "诚收",
    "收購",
    "收购",
    "收機",
    "收机",
    "收iphone",
    "收 iphone",
    "回收機",
    "回收机",
    "求む",
    "探しています",
    "買取",
)

RENTAL_TERMS = (
    "出租",
    "租借",
    "rental",
    "for rent",
    "レンタル",
)

SOLD_TERMS = (
    "sold",
    "已售",
    "已出售",
    "売り切れ",
    "sold out",
    "落札",
    "終了",
    "ended",
)

SAFE_BROKEN_TERMS = (
    "無壞",
    "冇壞",
    "沒壞",
    "没坏",
    "未壞",
    "未坏",
    "沒有壞",
    "没有坏",
    "沒壞機",
    "冇壞機",
    "无故障",
    "無故障",
    "沒有故障",
)

MIN_PLAUSIBLE_NATIVE_PRICE = {
    "HKD": Decimal("500"),
    "SGD": Decimal("100"),
    "JPY": Decimal("5000"),
    "CNY": Decimal("500"),
}


@dataclass(frozen=True)
class ListingQuality:
    outcome: str
    score: float
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "score": self.score,
            "reasons": list(self.reasons),
        }


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").replace("\u00a0", " ").strip()


def parse_price(value: str | int | float | Decimal | None, currency: str = "CNY") -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = normalize_text(str(value))
    text = text.replace("，", ",").replace("。", ".")
    expected = (currency or "").upper()
    patterns = {
        "SGD": r"(?<![A-Za-z0-9])(?:S\$|SGD)\s*([\d,.]+)",
        "HKD": r"(?<![A-Za-z0-9])(?:HK\$|HKD)\s*([\d,.]+)",
        "JPY": r"(?<![A-Za-z0-9])(?:JPY|¥|￥|円)\s*([\d,.]+)",
        "CNY": r"(?<![A-Za-z0-9])(?:RMB|CNY|¥|￥|元)\s*([\d,.]+)",
    }
    conflicts = {
        "SGD": r"\b(?:USD|US\$|TWD|NT\$)\b",
        "HKD": r"\b(?:USD|US\$|TWD|NT\$)\b",
        "JPY": r"\b(?:USD|US\$|SGD|S\$|HKD|HK\$|TWD|NT\$)\b",
        "CNY": r"\b(?:USD|US\$|SGD|S\$|HKD|HK\$|TWD|NT\$)\b",
    }
    raw: str | None = None
    expected_match = re.search(patterns.get(expected, ""), text, flags=re.IGNORECASE)
    if expected_match:
        raw = expected_match.group(1)
    elif re.search(conflicts.get(expected, ""), text, flags=re.IGNORECASE):
        return None

    if raw is None:
        cleaned = re.sub(
            r"(?i)(s\$|hk\$|hkd|sgd|jpy|rmb|cny|usd|us\$|nt\$|twd|¥|￥|円|元)",
            "",
            text,
        )
        match = re.search(r"(?<!\d)(\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)", cleaned)
        if not match:
            return None
        raw = match.group(1)

    raw = raw.replace(",", "").replace(" ", "")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    if "万" in text:
        amount *= Decimal("10000")
    elif "億" in text or "亿" in text:
        amount *= Decimal("100000000")
    return amount


def parse_api_price(value: int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    if parsed <= 0:
        return None
    if parsed > Decimal("1000000"):
        return (parsed / Decimal("100000")).quantize(Decimal("0.01"))
    return parsed


def detect_storage(title: str) -> int | None:
    text = normalize_text(title).lower().replace(" ", "")
    match = re.search(r"(?<!\d)(128|256|512|1024|2048)(gb|g|tb|t)(?!\d)", text)
    if not match:
        match = re.search(r"(?<!\d)(1|2)(tb|t)(?!\d)", text)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit in {"t", "tb"}:
        amount *= 1024
    return amount


def detect_model(title: str) -> tuple[str, int, str] | None:
    text = normalize_text(title).lower()
    text = text.replace("苹果", "iphone").replace("apple", "iphone")
    text = re.sub(r"\biphone\s*", "iphone ", text)
    match = re.search(r"iphone\s*(1[4-7])\s*pro(\s*max)?", text)
    if not match:
        match = re.search(r"\b(1[4-7])\s*pro(\s*max)?\b", text)
    if not match:
        pm_match = re.search(r"\b(1[4-7])\s*pm\b", text)
        if pm_match:
            generation = int(pm_match.group(1))
            return f"iPhone {generation} Pro Max", generation, "Pro Max"
        return None
    generation = int(match.group(1))
    family = "Pro Max" if match.group(2) else "Pro"
    return f"iPhone {generation} {family}", generation, family


def classify_listing_quality(
    title: str,
    *,
    price_native: Decimal | int | float | None = None,
    currency: str | None = None,
) -> ListingQuality:
    """Classify listing intent with weighted, explainable evidence."""
    text = normalize_text(title).lower()
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add_evidence(outcome: str, score: float, reason: str) -> None:
        scores[outcome] = max(scores.get(outcome, 0.0), score)
        outcome_reasons = reasons.setdefault(outcome, [])
        if reason not in outcome_reasons:
            outcome_reasons.append(reason)

    wanted_patterns = (
        r"^\s*(?:收|求|徵|征)\s*(?:iphone|apple|苹果|\d{1,2}\s*pro|一[部台]|機|机)",
        r"(?:高價|高价|誠|诚)?收(?:購|购)?\s*(?:iphone|apple|苹果|\d{1,2}\s*pro|一[部台])",
        r"\b(?:want\s+to\s+buy|looking\s+for|wtb)\b",
    )
    if any(term.lower() in text for term in WANTED_TERMS) or any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in wanted_patterns
    ):
        add_evidence("wanted", 0.96, "标题包含求购或收机表达")

    box_patterns = (
        r"\bbox\s*only\b",
        r"\bempty\s+box\b",
        r"^\s*[\(（]?\s*box\s+only\b",
        r"(?:空|淨|净|僅|只|只有|只賣|只卖|剩)\s*(?:手機|手机|原裝|原装)?盒",
        r"(?<!有)盒\s*(?:only|淨|净)",
    )
    if any(term.lower() in text for term in BOX_ONLY_TERMS) or any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in box_patterns
    ):
        add_evidence("box_only", 0.99, "标题表明仅出售手机盒或包装")

    if any(term.lower() in text for term in RENTAL_TERMS):
        add_evidence("rental", 0.95, "标题包含出租或租赁表达")

    if not any(term in text for term in SAFE_BROKEN_TERMS):
        if any(term.lower() in text for term in BROKEN_TERMS):
            add_evidence("broken", 0.92, "标题包含故障、零件或损坏表达")
        elif "壞" in text or "坏" in text:
            add_evidence("broken", 0.82, "标题包含损坏表达")

    accessory_hit = any(term.lower() in text for term in ACCESSORY_TERMS)
    included_accessory = re.search(
        r"(?:送|有|連|连|全套|包|跟|附).{0,6}(?:配件|ケース|カバー|charger|cable)",
        text,
        flags=re.IGNORECASE,
    )
    if accessory_hit and (included_accessory is None or "only" in text):
        add_evidence("accessory", 0.96, "标题主要描述配件而非手机本体")

    if any(term.lower() in text for term in NEW_TERMS):
        add_evidence("new", 0.90, "标题表明全新、未拆封或未使用")

    minimum = MIN_PLAUSIBLE_NATIVE_PRICE.get((currency or "").upper())
    if price_native is not None and minimum is not None:
        try:
            parsed_price = Decimal(str(price_native))
            if parsed_price < minimum:
                add_evidence(
                    "suspicious_low",
                    0.80,
                    f"原币价格低于最低合理阈值 {minimum}",
                )
        except InvalidOperation:
            pass

    if not scores:
        return ListingQuality("used", 0.50, ())

    priority = (
        "box_only",
        "wanted",
        "rental",
        "broken",
        "accessory",
        "new",
        "suspicious_low",
    )
    outcome = max(
        scores,
        key=lambda item: (scores[item], -priority.index(item)),
    )
    return ListingQuality(
        outcome=outcome,
        score=round(scores[outcome], 2),
        reasons=tuple(reasons.get(outcome, ())),
    )


def classify_condition(
    title: str,
    *,
    price_native: Decimal | int | float | None = None,
    currency: str | None = None,
) -> str:
    return classify_listing_quality(
        title,
        price_native=price_native,
        currency=currency,
    ).outcome


def detect_listing_status(text: str) -> str:
    normalized = normalize_text(text).lower()
    if any(term.lower() in normalized for term in SOLD_TERMS):
        return "sold"
    return "active"


def listing_id_from_url(source_key: str, url: str, fallback: str = "") -> str:
    parsed = urlparse(url)
    if source_key.startswith("carousell"):
        slug = next(
            (segment for segment in reversed(parsed.path.split("/")) if segment),
            "",
        )
        match = re.search(r"-(\d{6,})$", slug)
        if match:
            return match.group(1)
    for key in ("id", "itemId", "item_id"):
        value = parse_qs(parsed.query).get(key)
        if value and re.search(r"[A-Za-z0-9_-]{4,}", value[0]):
            return value[0]
    candidates = [segment for segment in parsed.path.split("/") if segment]
    query_parts = [part for part in parsed.query.split("&") if part]
    for value in reversed(candidates + query_parts):
        match = re.search(r"([A-Za-z0-9_-]{5,})", value)
        if match:
            return match.group(1)
    digest = hashlib.sha1(f"{source_key}|{url}|{fallback}".encode("utf-8")).hexdigest()
    return digest[:20]


def is_valid_variant(title: str, variant: PhoneVariant) -> bool:
    model = detect_model(title)
    if model is None:
        return False
    _, generation, family = model
    storage = detect_storage(title)
    return generation == variant.generation and family == variant.family and storage == variant.storage_gb
