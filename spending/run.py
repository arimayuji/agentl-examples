"""Run the spending pipeline and write site/data/status.json from the run result.

    cd spending && python run.py

- With OPENROUTER_API_KEY set, the classify step asks SPENDING_MODEL (default in pipeline.yaml).
  Without it, or once the month's cap is spent, classification is off: every award is published
  unclassified and no model is called.
- SPENDING_BUDGET_USD (default 5) is the monthly cap. Each run may spend the cap over 31 days,
  and never more than what is left of it this month. The month's spend is kept in status.json.
- eval.json, when present (written by `agentl eval pipeline.yaml --json` in the workflow), is
  added to the status: golden-set accuracy and cost per right answer. Its cost counts this month.
- `--echo` runs with the offline echo provider (no key, no cost) to test the wiring.
- `--sample` publishes the hand labels of the golden set (sample data, no model call).

Also copies pipeline.yaml into site/, where the page shows it.
Exits 1 when the run fails, after writing status.json, so the page can show the failure.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import agentl
from agentl.spec import load

HERE = Path(__file__).resolve().parent
STATUS = HERE / "site" / "data" / "status.json"
EVAL = HERE / "eval.json"
RUNS_PER_MONTH = 31  # daily cron


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _eval_report() -> dict[str, Any] | None:
    data = _read(EVAL)
    if isinstance(data, dict):
        data = data.get("reports") or [data]
    for rep in data or []:
        if isinstance(rep, dict) and rep.get("step") == "classify":
            return rep
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--echo", action="store_true", help="offline echo provider: tests the wiring")
    ap.add_argument("--sample", action="store_true", help="publish the golden-set hand labels as sample data")
    args = ap.parse_args()

    shutil.copyfile(HERE / "pipeline.yaml", HERE / "site" / "pipeline.yaml")
    previous = _read(STATUS) or {}
    now = time.time()
    month_id = datetime.now(timezone.utc).strftime("%Y-%m")
    month = previous.get("month") or {}
    if month.get("id") != month_id:
        month = {"id": month_id, "spent_usd": 0.0, "runs": 0, "eval_usd": 0.0}

    cap = float(os.environ.get("SPENDING_BUDGET_USD") or 5)
    model = os.environ.get("SPENDING_MODEL") or None
    rep = _eval_report()
    eval_cost = float(rep.get("cost_usd") or 0) if rep else 0.0
    month["spent_usd"] = round(month["spent_usd"] + eval_cost, 6)
    month["eval_usd"] = round(month.get("eval_usd", 0.0) + eval_cost, 6)
    left = max(0.0, cap - month["spent_usd"])
    per_run = round(min(cap / RUNS_PER_MONTH, left), 4)

    if args.sample:
        mode, why = "sample", "sample data: hand labels from the golden set, no model call"
    elif args.echo:
        mode, why = "on", "echo provider (offline test)"
    elif not os.environ.get("OPENROUTER_API_KEY"):
        mode, why = "off", "OPENROUTER_API_KEY is not set"
    elif per_run < 0.001:
        mode, why = "off", f"the monthly cap of ${cap:g} is spent"
    else:
        mode, why = "on", None
    os.environ["SPENDING_CLASSIFY"] = mode

    spec = load(HERE / "pipeline.yaml")
    llm = spec.llm["default"]
    update: dict[str, Any] = {}
    if model:
        update["model"] = model
    if args.echo:
        update["provider"] = "echo"
    if update:
        spec = spec.model_copy(update={"llm": {**spec.llm, "default": llm.model_copy(update=update)}})
    if spec.budget is not None:
        spec = spec.model_copy(update={"budget": spec.budget.model_copy(update={"max_usd": max(per_run, 0.0001)})})
    model_id = spec.llm["default"].model if not args.echo else "echo"

    events: list[dict[str, Any]] = []

    def listen(event: dict[str, Any]) -> None:
        events.append(event)
        step = f" [{event['step']}]" if event.get("step") else ""
        print(f"{event['type']}{step}", flush=True)

    started = time.time()
    result = agentl.run(spec, listeners=[listen])
    finished = time.time()

    checks: dict[str, Any] = {}
    for e in events:
        if e["type"] in ("check.passed", "check.failed", "check.warned") and e.get("step") == "verify":
            checks = {
                "status": e["type"].split(".", 1)[1],
                "rules": e["data"].get("rules", {}),
                "findings": [f.get("detail") for f in e["data"].get("findings", [])],
            }
    fetched = sum(
        int(e["data"].get("records") or 0)
        for e in events
        if e["type"] == "step.succeeded" and e.get("step") == "awards"
    )
    spend = result.spend.get("classify") or {}
    paths = spend.get("paths") or {}
    asked = int(paths.get("agent", 0))
    hits = int(spend.get("cache_hits", 0))
    review = spend.get("review") or {}
    rows = result.outputs.get("classified") or []
    flagged = sum(1 for r in rows if r.get("needs_review"))
    by_llm = sum(1 for r in rows if r.get("classified_by") == "llm")
    window = (result.outputs.get("window") or [{}])[0]
    written = result.writes.get("history", {})
    outcome = result.outcome or result.status
    run_cost = float(result.cost_usd or 0)
    month["spent_usd"] = round(month["spent_usd"] + run_cost, 6)
    month["runs"] = int(month.get("runs", 0)) + 1
    calls = int(spend.get("llm_calls", 0))

    evaluation = previous.get("eval") or None
    if rep:
        evaluation = {
            "accuracy": rep.get("accuracy"),
            "fields": rep.get("fields"),
            "records": rep.get("records"),
            "right": rep.get("right"),
            "cost_usd": rep.get("cost_usd"),
            "cost_per_right": rep.get("cost_per_right"),
            "cost_per_record": round(float(rep.get("cost_usd") or 0) / rep["records"], 8) if rep.get("records") else None,
            "model": model_id,
            "at": _iso(now),
        }

    llm_status = {
        "classify": mode,
        "skipped_reason": why,
        "model": model_id,
        "provider": "echo" if args.echo else spec.llm["default"].provider,
        "calls": calls,
        "cost_usd": round(run_cost, 6),
        "cost_per_record": round(run_cost / calls, 8) if calls else None,
        "asked": asked,
        "cache_hits": hits,
        "cache_hit_rate": round(hits / asked, 4) if asked else None,
        "classified_by_llm": by_llm,
        "needs_review": flagged,
        "review": review,
        "max_usd_this_run": per_run,
    }
    if outcome == "no_change" and previous.get("llm"):
        # Nothing new from USAspending: the page still shows the last run that classified.
        llm_status = {**previous["llm"], "calls": 0, "cost_usd": 0.0, "from_run": previous.get("run_id")}

    status = {
        "pipeline": "spending",
        "sample": bool(args.sample or args.echo or previous.get("sample") and outcome == "no_change"),
        "run_id": result.run_id,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "duration_s": round(finished - started, 2),
        "outcome": outcome,
        "error": result.error,
        "window": {"from": window.get("start"), "to": window.get("end")} if window else previous.get("window"),
        "rows_read": fetched,
        "data_as_of": window.get("data_as_of") if window else previous.get("data_as_of"),
        "writes": {k: int(written.get(k, 0)) for k in ("inserted", "updated", "unchanged", "deleted")},
        "checks": checks or previous.get("checks", {}),
        "llm": llm_status,
        "month": {**month, "cap_usd": cap},
        "eval": evaluation,
        "last_success_at": _iso(finished) if outcome == "success" else previous.get("last_success_at"),
        "agentl_version": agentl.__version__,
    }
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps({"outcome": outcome, "rows_read": fetched, "llm": status["llm"], "month": status["month"]}))
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
