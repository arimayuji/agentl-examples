"""Python steps for the spending pipeline."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# The categories the agent may answer. Anything else is shown as "other" by the page.
CATEGORIES = ["defense", "health", "IT", "construction", "research", "energy", "transport", "education", "other"]


def window(records: list[dict[str, Any]], days: int = 7, pages: int = 3, **_: Any) -> list[dict[str, Any]]:
    """One record per page to request, with the date window.

    The window ends on the day USAspending last loaded data (`last_updated`, MM/DD/YYYY) and
    covers `days` days. USAspending takes the page number in the JSON body, so each page is a
    record and `http.post` fills `{page}`, `{start}` and `{end}` from it.
    """
    stamp = (records[0].get("last_updated") if records else None) or ""
    try:
        end = datetime.strptime(stamp, "%m/%d/%Y").date()
    except ValueError:
        end = date.today()
    start = end - timedelta(days=int(days) - 1)
    return [
        {"page": p, "start": start.isoformat(), "end": end.isoformat(), "data_as_of": end.isoformat()}
        for p in range(1, int(pages) + 1)
    ]


def _code(v: Any) -> tuple[str | None, str | None]:
    if isinstance(v, dict):
        return v.get("code"), v.get("description")
    return (str(v) if v else None), None


def _clean(s: Any) -> str:
    return " ".join(str(s or "").split())


def flatten(records: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
    """USAspending `spending_by_award` results -> one flat row per award."""
    rows: list[dict[str, Any]] = []
    for r in records:
        naics, naics_desc = _code(r.get("NAICS"))
        psc, psc_desc = _code(r.get("PSC"))
        gid = r.get("generated_internal_id")
        rows.append(
            {
                "award_id": gid,  # USAspending's unique award id; the PIID alone can repeat
                "piid": r.get("Award ID"),
                "recipient": _clean(r.get("Recipient Name")),
                "amount": r.get("Award Amount"),
                "description": _clean(r.get("Description")),
                "agency": r.get("Awarding Agency"),
                "sub_agency": r.get("Awarding Sub Agency"),
                "start_date": r.get("Start Date"),
                "naics": naics,
                "naics_desc": naics_desc,
                "psc": psc,
                "psc_desc": psc_desc,
                "url": f"https://www.usaspending.gov/award/{gid}" if gid else None,
            }
        )
    return rows


def for_agent(records: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
    """Only what the classifier needs. Amount and dates stay out, so a revised amount on the same
    award gives the same cache key and is never paid for twice."""
    keep = ("award_id", "description", "agency", "sub_agency", "recipient", "psc_desc", "naics_desc")
    return [{k: r.get(k) for k in keep} for r in records]


def _golden() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    path = HERE / "golden" / "awards.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                g = json.loads(line)
                out[g["award_id"]] = g
    return out


def no_llm(record: dict[str, Any]) -> dict[str, Any]:
    """Hybrid rule of the classify step. It answers only when classification is off:

    - SPENDING_CLASSIFY=off (no OPENROUTER_API_KEY, or the monthly cap is spent): every award is
      left unclassified, with no model call.
    - SPENDING_CLASSIFY=sample: the hand labels of the golden set, for the committed sample data.

    Otherwise it raises, and the record goes to the llm.
    """
    mode = os.environ.get("SPENDING_CLASSIFY", "on")
    if mode == "sample":
        g = _golden().get(record.get("award_id") or "")
        if g:
            notes = json.loads((HERE / "golden" / "sample_summaries.json").read_text())
            return {
                "category": g["category"],
                "plain_summary": notes.get(g["award_id"]) or record.get("description") or "",
                "clarity": g["clarity"],
                "confidence": 1.0,
            }
        mode = "off"
    if mode == "off":
        return {"category": "unclassified", "plain_summary": "Not classified: no LLM ran on this award.", "clarity": "unknown", "confidence": 0.0}
    raise LookupError("classification is on: ask the llm")


def merge(inputs: Any, **_: Any) -> list[dict[str, Any]]:
    """Award rows plus the classifier's answer, by award id. A row the classifier rejected keeps
    its data and is shown unclassified."""
    rows, answers = inputs["verify"], inputs["labels"]
    by_id = {a["award_id"]: a for a in answers}
    sample = os.environ.get("SPENDING_CLASSIFY") == "sample"
    out = []
    for r in rows:
        a = by_id.get(r["award_id"]) or {}
        path = a.get("_path")
        out.append(
            {
                **r,
                "category": a.get("category") or "unclassified",
                "plain_summary": a.get("plain_summary") or "",
                "clarity": a.get("clarity") or "unknown",
                "confidence": a.get("confidence"),
                "needs_review": a.get("_review") == "pending",
                "classified_by": "llm" if path == "agent" else ("sample" if sample and a.get("category") not in (None, "unclassified") else "none"),
            }
        )
    return out


def to_site(records: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
    """The page JSON: every award of the window, largest first, plus totals."""
    rows = sorted(records, key=lambda r: -(r.get("amount") or 0))
    by_cat: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    by_agency: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for r in rows:
        cat = r.get("category") or "unclassified"
        if cat not in CATEGORIES and cat != "unclassified":
            cat = "other"
        r["category"] = cat
        by_cat[cat][0] += r.get("amount") or 0
        by_cat[cat][1] += 1
        by_agency[r.get("agency") or "Unknown"][0] += r.get("amount") or 0
        by_agency[r.get("agency") or "Unknown"][1] += 1
    fields = [
        "award_id", "piid", "recipient", "amount", "description", "agency", "sub_agency", "start_date",
        "naics", "psc", "psc_desc", "url", "category", "plain_summary", "clarity", "confidence",
        "needs_review", "classified_by",
    ]
    return [
        {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(rows),
            "total": round(sum(r.get("amount") or 0 for r in rows), 2),
            "by_category": sorted(
                ({"name": k, "amount": round(v[0], 2), "count": int(v[1])} for k, v in by_cat.items()),
                key=lambda x: -x["amount"],
            ),
            "by_agency": sorted(
                ({"name": k, "amount": round(v[0], 2), "count": int(v[1])} for k, v in by_agency.items()),
                key=lambda x: -x["amount"],
            ),
            "fields": fields,
            "awards": [[r.get(f) for f in fields] for r in rows],
        }
    ]
