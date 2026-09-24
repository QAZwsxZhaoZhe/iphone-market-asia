from __future__ import annotations

import unicodedata


HONG_KONG_DISTRICTS: tuple[str, ...] = (
    "中西區",
    "灣仔區",
    "東區",
    "南區",
    "油尖旺區",
    "深水埗區",
    "九龍城區",
    "黃大仙區",
    "觀塘區",
    "葵青區",
    "荃灣區",
    "屯門區",
    "元朗區",
    "北區",
    "大埔區",
    "沙田區",
    "西貢區",
    "離島區",
)


DISTRICT_ALIASES: dict[str, tuple[str, ...]] = {
    "中西區": ("中西區", "中西区", "central and western", "central"),
    "灣仔區": ("灣仔區", "湾仔区", "wan chai"),
    "東區": ("東區", "东区", "eastern district", "eastern"),
    "南區": ("南區", "南区", "southern district", "southern"),
    "油尖旺區": ("油尖旺區", "油尖旺区", "yau tsim mong"),
    "深水埗區": ("深水埗區", "深水埗区", "sham shui po"),
    "九龍城區": ("九龍城區", "九龙城区", "kowloon city"),
    "黃大仙區": ("黃大仙區", "黄大仙区", "wong tai sin"),
    "觀塘區": ("觀塘區", "观塘区", "kwun tong"),
    "葵青區": ("葵青區", "葵青区", "kwai tsing"),
    "荃灣區": ("荃灣區", "荃湾区", "tsuen wan"),
    "屯門區": ("屯門區", "屯门区", "tuen mun"),
    "元朗區": ("元朗區", "元朗区", "yuen long"),
    "北區": ("北區", "北区", "north district", "north"),
    "大埔區": ("大埔區", "大埔区", "tai po"),
    "沙田區": ("沙田區", "沙田区", "sha tin"),
    "西貢區": ("西貢區", "西贡区", "sai kung"),
    "離島區": ("離島區", "离岛区", "islands district", "islands"),
}


MTR_DISTRICT_MAP: dict[str, str] = {
    "香港": "中西區",
    "中環": "中西區",
    "金鐘": "中西區",
    "上環": "中西區",
    "西營盤": "中西區",
    "堅尼地城": "中西區",
    "灣仔": "灣仔區",
    "銅鑼灣": "灣仔區",
    "天后": "灣仔區",
    "炮台山": "東區",
    "北角": "東區",
    "鰂魚涌": "東區",
    "太古": "東區",
    "西灣河": "東區",
    "筲箕灣": "東區",
    "柴灣": "東區",
    "海洋公園": "南區",
    "黃竹坑": "南區",
    "利東": "南區",
    "海怡半島": "南區",
    "尖沙咀": "油尖旺區",
    "佐敦": "油尖旺區",
    "油麻地": "油尖旺區",
    "旺角": "油尖旺區",
    "太子": "油尖旺區",
    "九龍": "油尖旺區",
    "南昌": "深水埗區",
    "深水埗": "深水埗區",
    "長沙灣": "深水埗區",
    "荔枝角": "深水埗區",
    "美孚": "深水埗區",
    "石硤尾": "深水埗區",
    "九龍塘": "九龍城區",
    "樂富": "九龍城區",
    "宋皇臺": "九龍城區",
    "啟德": "九龍城區",
    "何文田": "九龍城區",
    "紅磡": "九龍城區",
    "黃大仙": "黃大仙區",
    "鑽石山": "黃大仙區",
    "彩虹": "黃大仙區",
    "九龍灣": "觀塘區",
    "牛頭角": "觀塘區",
    "觀塘": "觀塘區",
    "藍田": "觀塘區",
    "油塘": "觀塘區",
    "調景嶺": "西貢區",
    "將軍澳": "西貢區",
    "康城": "西貢區",
    "寶琳": "西貢區",
    "坑口": "西貢區",
    "葵芳": "葵青區",
    "葵興": "葵青區",
    "荔景": "葵青區",
    "青衣": "葵青區",
    "荃灣": "荃灣區",
    "大窩口": "荃灣區",
    "屯門": "屯門區",
    "兆康": "屯門區",
    "天水圍": "元朗區",
    "朗屏": "元朗區",
    "元朗": "元朗區",
    "錦上路": "元朗區",
    "羅湖": "北區",
    "上水": "北區",
    "粉嶺": "北區",
    "太和": "大埔區",
    "大埔墟": "大埔區",
    "大學": "沙田區",
    "火炭": "沙田區",
    "沙田": "沙田區",
    "車公廟": "沙田區",
    "大圍": "沙田區",
    "馬場": "沙田區",
    "恆安": "沙田區",
    "馬鞍山": "沙田區",
    "烏溪沙": "沙田區",
    "東涌": "離島區",
    "欣澳": "離島區",
    "迪士尼": "離島區",
}


def normalize_location(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().lower()


def normalize_district(value: str | None) -> str | None:
    text = normalize_location(value)
    if not text:
        return None
    for district, aliases in DISTRICT_ALIASES.items():
        if any(alias.lower() in text for alias in aliases):
            return district
    for station, district in MTR_DISTRICT_MAP.items():
        if station.lower() in text:
            return district
    return None


def district_options() -> list[dict[str, str]]:
    return [{"value": district, "label": district} for district in HONG_KONG_DISTRICTS]
