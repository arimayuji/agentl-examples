"""Python steps for the fx pipeline."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, timedelta
from typing import Any


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_ecb(records: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
    """ECB eurofxref XML bodies -> one row per (date, currency, rate).

    The file nests `<Cube time=...>` days around `<Cube currency=... rate=...>` rates, which is
    why this is a small function instead of `xml.read` (that reads one level of attributes).
    """
    rows: list[dict[str, Any]] = []
    for record in records:
        text = record.get("text") or ""
        if not text:
            continue
        if "<!ENTITY" in text:
            raise ValueError("ECB XML with entity declarations is not read")
        root = ET.fromstring(text.encode())
        for day in root.iter():
            if _local(day.tag) != "Cube" or "time" not in day.attrib:
                continue
            for cube in day:
                if "currency" in cube.attrib:
                    rows.append(
                        {
                            "date": day.attrib["time"],
                            "currency": cube.attrib["currency"],
                            "rate": float(cube.attrib["rate"]),
                        }
                    )
    return rows


def to_site(records: list[dict[str, Any]], days: int = 90, **_: Any) -> list[dict[str, Any]]:
    """History rows -> one document for the dashboard: the last `days` days per currency."""
    if not records:
        return []
    latest = max(r["date"] for r in records)
    since = (date.fromisoformat(latest) - timedelta(days=days)).isoformat()
    series: dict[str, list[list[Any]]] = defaultdict(list)
    for r in sorted(records, key=lambda r: (r["currency"], r["date"])):
        if r["date"] > since:
            series[r["currency"]].append([r["date"], float(r["rate"])])
    return [{"base": "EUR", "latest": latest, "days": days, "series": dict(series)}]
