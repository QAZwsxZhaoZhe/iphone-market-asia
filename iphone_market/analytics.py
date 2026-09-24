from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable, Mapping, Sequence


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def price_metrics(rows: Iterable[Mapping | object]) -> dict[str, float | int | None]:
    prices = [
        float(_row_value(row, "price_cny"))
        for row in rows
        if _row_value(row, "price_cny") is not None
    ]
    if not prices:
        return {
            "count": 0,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "max": None,
        }
    return {
        "count": len(prices),
        "min": round(min(prices), 2),
        "p25": round(percentile(prices, 0.25) or 0, 2),
        "median": round(percentile(prices, 0.5) or 0, 2),
        "p75": round(percentile(prices, 0.75) or 0, 2),
        "max": round(max(prices), 2),
    }


def grouped_metrics(
    rows: Iterable[Mapping | object],
    key_names: tuple[str, ...],
) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[tuple(_row_value(row, key) for key in key_names)].append(row)
    output = []
    for key, group_rows in groups.items():
        item = dict(zip(key_names, key))
        item.update(price_metrics(group_rows))
        output.append(item)
    output.sort(key=lambda item: tuple(str(item.get(name, "")) for name in key_names))
    return output


def median_change(current: Mapping, previous: Mapping | None) -> float | None:
    if previous is None:
        return None
    current_value = current.get("median")
    previous_value = previous.get("median")
    if current_value is None or previous_value in (None, 0):
        return None
    return round(float(current_value) - float(previous_value), 2)


def cny(value: float | Decimal | None) -> str:
    if value is None:
        return "-"
    return f"¥{float(value):,.0f}"


def _row_value(row: Mapping | object, key: str):
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, None)
