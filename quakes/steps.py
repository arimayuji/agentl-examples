"""Python steps for the quakes pipeline."""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Magnitude bands for the map legend and the stats, lower bound inclusive.
BANDS = [("<2", -10.0), ("2-4", 2.0), ("4-5", 4.0), ("5-6", 5.0), ("6+", 6.0)]


def _iso(ms: Any) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_usgs(records: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
    """USGS GeoJSON features -> flat rows: time in UTC, coordinates split, the fields the map uses.

    Both feeds (the last hour and the last week) can carry the same event; the step after this
    one keeps the newest version of each id.
    """
    rows: list[dict[str, Any]] = []
    for f in records:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        lon, lat, depth = (list(coords) + [None, None, None])[:3]
        rows.append(
            {
                "id": f.get("id"),
                "time": _iso(p.get("time")),
                "updated": _iso(p.get("updated")),
                "mag": p.get("mag"),
                "mag_type": p.get("magType"),
                "place": p.get("place") or p.get("title"),
                "lon": lon,
                "lat": lat,
                "depth_km": depth,
                "status": p.get("status"),
                "tsunami": bool(p.get("tsunami")),
                "event_type": p.get("type"),
                "url": p.get("url"),
            }
        )
    return rows


def newest(records: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
    """Keep the most recently updated version of each event id."""
    best: dict[str, dict[str, Any]] = {}
    for r in records:
        cur = best.get(r["id"])
        if cur is None or (r.get("updated") or "") > (cur.get("updated") or ""):
            best[r["id"]] = r
    return list(best.values())


def prune(records: list[dict[str, Any]], db: str, days: int = 30, **_: Any) -> list[dict[str, Any]]:
    """Delete events older than `days` from the history table. Returns one summary row."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = Path(db)
    if not path.exists():
        return [{"pruned": 0, "cutoff": cutoff}]
    with sqlite3.connect(path) as con:
        cur = con.execute("delete from quakes where time < ?", (cutoff,))
        pruned = cur.rowcount
    return [{"pruned": pruned, "cutoff": cutoff}]


def _band(mag: float | None) -> str:
    label = BANDS[0][0]
    for name, low in BANDS:
        if mag is not None and mag >= low:
            label = name
    return label


def to_site(records: list[dict[str, Any]], days: int = 7, **_: Any) -> list[dict[str, Any]]:
    """History rows -> one compact document for the map: the last `days` days plus stats."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_ago = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = sorted((r for r in records if (r["time"] or "") >= since), key=lambda r: r["time"], reverse=True)
    fields = ["id", "time", "updated", "mag", "mag_type", "place", "lon", "lat", "depth_km", "status", "tsunami", "url"]
    quakes = [
        [
            r["id"],
            r["time"],
            r["updated"],
            None if r["mag"] is None else round(float(r["mag"]), 2),
            r["mag_type"],
            r["place"],
            round(float(r["lon"]), 4),
            round(float(r["lat"]), 4),
            None if r["depth_km"] is None else round(float(r["depth_km"]), 1),
            r["status"],
            1 if r["tsunami"] else 0,
            r["url"],
        ]
        for r in rows
    ]
    last24 = [r for r in rows if r["time"] >= day_ago]
    largest = max((r for r in last24 if r["mag"] is not None), key=lambda r: r["mag"], default=None)
    stats = {
        "count_7d": len(rows),
        "count_24h": len(last24),
        "bands_7d": dict(Counter(_band(r["mag"]) for r in rows)),
        "bands_24h": dict(Counter(_band(r["mag"]) for r in last24)),
        "reviewed_7d": sum(1 for r in rows if r["status"] == "reviewed"),
        "tsunami_7d": sum(1 for r in rows if r["tsunami"]),
        "largest_24h": None
        if largest is None
        else {k: largest[k] for k in ("id", "time", "mag", "mag_type", "place", "url")},
    }
    return [
        {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "days": days,
            "bands": [b[0] for b in BANDS],
            "fields": fields,
            "stats": stats,
            "quakes": quakes,
        }
    ]
