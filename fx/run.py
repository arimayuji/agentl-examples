"""Run the fx pipeline and write site/data/status.json from the run result.

    cd fx && python run.py

Also copies pipeline.yaml into site/, where the page shows it.
Exits 1 when the run fails, after writing status.json, so the dashboard can show the failure.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import agentl

HERE = Path(__file__).resolve().parent
STATUS = HERE / "site" / "data" / "status.json"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    # The page shows the pipeline it was built with, so it ships a copy next to index.html.
    shutil.copyfile(HERE / "pipeline.yaml", HERE / "site" / "pipeline.yaml")
    events: list[dict[str, Any]] = []

    def listen(event: dict[str, Any]) -> None:
        events.append(event)
        step = f" [{event['step']}]" if event.get("step") else ""
        print(f"{event['type']}{step}", flush=True)

    started = time.time()
    result = agentl.run(HERE / "pipeline.yaml", listeners=[listen])
    finished = time.time()

    sources = {"daily", "backfill"}
    rows_read = sum(
        int(e["data"].get("records") or 0)
        for e in events
        if e["type"] == "step.succeeded" and e["step"] == "parse"
    )
    fetched = [
        e["step"] for e in events if e["type"] == "step.succeeded" and e["step"] in sources
    ]
    checks: dict[str, Any] = {}
    for e in events:
        if e["type"] in ("check.passed", "check.failed", "check.warned"):
            checks = {
                "status": e["type"].split(".", 1)[1],
                "rules": e["data"].get("rules", {}),
                "findings": [f.get("detail") for f in e["data"].get("findings", [])],
            }
    written = result.writes.get("history", {})

    previous: dict[str, Any] = {}
    if STATUS.exists():
        try:
            previous = json.loads(STATUS.read_text())
        except ValueError:
            previous = {}
    outcome = result.outcome or result.status
    status = {
        "pipeline": "fx",
        "run_id": result.run_id,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "duration_s": round(finished - started, 2),
        "outcome": outcome,
        "error": result.error,
        "sources_downloaded": fetched,
        "rows_read": rows_read,
        "rows_changed": int(written.get("inserted", 0)) + int(written.get("updated", 0)),
        "writes": {k: int(written.get(k, 0)) for k in ("inserted", "updated", "unchanged", "deleted")},
        "checks": checks or previous.get("checks", {}),
        "checks_from_run": result.run_id if checks else previous.get("checks_from_run"),
        "last_success_at": _iso(finished) if outcome == "success" else previous.get("last_success_at"),
        "agentl_version": agentl.__version__,
    }
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps({k: status[k] for k in ("outcome", "rows_read", "rows_changed", "duration_s")}))
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
