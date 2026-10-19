# fx: euro reference rates

Live: https://fx.agentl.com.br

A useful public dataset and a showcase for [agentl](https://agentl.com.br): the page shows the
rates, the exact `pipeline.yaml` that produced them (with notes on the agentl features it uses) and
the status of the last run.

Every working day the European Central Bank publishes euro foreign-exchange reference rates for
about 30 currencies. This project fetches them with [agentl](https://agentl.com.br), checks them,
keeps a history in SQLite and publishes a static dashboard: a currency picker (USD by default), a
90-day chart, the latest rates with the day-over-day change, and a pipeline status panel.

No API key: the source is the ECB's public XML,
[`eurofxref-daily.xml`](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml) and, for
backfill, [`eurofxref-hist-90d.xml`](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml).

## Files

| File | What it is |
| --- | --- |
| `pipeline.yaml` | The agentl pipeline |
| `steps.py` | Two `fn:` steps: parse the ECB XML, shape the dashboard JSON |
| `run.py` | Runs the pipeline with `agentl.run` and writes `site/data/status.json` from the run result |
| `site/index.html` | The page: static, no build step, vanilla JS, Chart.js 4.4.1 from jsDelivr (pinned, with SRI), Inter and JetBrains Mono from Google Fonts. Shows the rates, the pipeline (fetched from `site/pipeline.yaml`, highlighted in place) and the run status |
| `site/assets/` | agentl logo, wordmarks, favicon, animated logo loop and the Open Graph image `og.png` |
| `og/` | `og.html`, the template for `og.png`, and `render.py`, which renders it with Playwright |
| `site/data/` | `rates.json` and `status.json`. A seed is committed so the site works before the first run |

## The pipeline

1. `daily` and `backfill`: `http.get` with `if_changed: { by: [etag, last_modified] }`. When the
   daily file has not changed since the last successful run, the run ends with outcome
   `no_change` and nothing is rewritten. The 90-day file fills a fresh history or a missed day.
2. `parse` (`fn: steps:parse_ecb`): the nested `<Cube time>` / `<Cube currency rate>` XML becomes
   rows of `(date, currency, rate)`.
3. `rates`: `dedupe` on `(date, currency)`, since the daily file repeats the newest day.
4. `verify`: a `check` step. At least 20 rows, no nulls, one row per `(date, currency)`, the
   currency is a 3-letter code (`regex`), the rate is above 0, and the newest date is less than 7
   days old. A failure stops the run before anything is written.
5. `history`: `sqlite.write` with `mode: changeset` on key `[date, currency]` into
   `data/fx.sqlite`, which reports inserted, updated and unchanged rows.
6. `recent` -> `site` -> `export`: the last 90 days per currency to `site/data/rates.json`.

`run.py` then writes `status.json`: last run time, outcome, rows read and changed, the result of
each check rule, and duration. It also copies `pipeline.yaml` to `site/pipeline.yaml` (ignored by
git), so the page shows the real file.

## Run locally

```bash
pip install agentl-etl
agentl lint pipeline.yaml
python run.py
python -m http.server -d site 8000
```

The run store lives in `.agentl/` and the history in `data/`; both are ignored by git. Delete them
to start over (or `agentl state reset` to forget only the `if_changed` validators).

## Deploy

`.github/workflows/fx.yml` runs on weekdays at 15:30 UTC, after the ECB publishes (about 16:00
CET), and on demand. It restores `.agentl/`, `data/` and `site/data/` from the Actions cache, runs
`python run.py`, copies `pipeline.yaml` into `site/` and deploys `fx/site` to the Cloudflare Pages project `agentl-fx` with
`cloudflare/wrangler-action`. It needs the repository secrets `CLOUDFLARE_API_TOKEN` (Pages: Edit)
and `CLOUDFLARE_ACCOUNT_ID`.

## Data

Rates are the ECB euro foreign exchange reference rates. The ECB publishes them for information
purposes only; they are not transaction rates.
