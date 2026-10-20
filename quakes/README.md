# quakes: live earthquake map

Live: https://quakes.agentl.com.br

A useful public dataset and a showcase for [agentl](https://agentl.com.br): the page shows a live
map of earthquakes worldwide, the exact `pipeline.yaml` that produced it (with notes on the agentl
features it uses) and the status of the last run.

The U.S. Geological Survey publishes every earthquake it locates as GeoJSON feeds that refresh
every minute. This project fetches them every 15 minutes with agentl, checks them, keeps 30 days
of history in SQLite and publishes a static page: a Leaflet map with circles sized and coloured by
magnitude, 24-hour and 7-day filters with a minimum magnitude, the latest and largest quakes linked
to their USGS event pages, counts by magnitude band, and a pipeline status panel that shows how
many events USGS revised.

No API key: the sources are the public-domain USGS summary feeds
[`all_hour.geojson`](https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson)
and, for backfill and revisions,
[`all_week.geojson`](https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson).

## Files

| File | What it is |
| --- | --- |
| `pipeline.yaml` | The agentl pipeline |
| `steps.py` | `fn:` steps: flatten GeoJSON features, keep the newest version of each event, prune history past 30 days, shape the page JSON and its stats |
| `run.py` | Runs the pipeline with `agentl.run` and writes `site/data/status.json` from the run result, including revisions in the last run and the last 24 hours |
| `site/index.html` | The page: static, no build step, vanilla JS, Leaflet 1.9.4 from cdnjs (pinned, with SRI), OpenStreetMap tiles, Inter and JetBrains Mono from Google Fonts |
| `site/assets/` | agentl logo, wordmarks, favicon, animated logo loop and the Open Graph image `og.png` |
| `og/` | `og.html`, the template for `og.png`, and `render.py`, which renders it with Playwright |
| `site/data/` | `quakes.json` and `status.json`. A seed is committed so the site works before the first run |

## The pipeline

1. `latest` and `backfill`: `http.get` with `if_changed` and `items: features`. When the hourly
   feed has not changed since the last successful run, the run ends with outcome `no_change` and
   nothing is rewritten. The 7-day feed fills a fresh history and carries USGS revisions.
2. `parse` and `events` (`fn:`): one row per event with `id`, `time` and `updated` in UTC, `mag`,
   `mag_type`, `place`, `lon`, `lat`, `depth_km`, `status` (automatic or reviewed), `tsunami` and
   `url`; the newest `updated` wins when both feeds carry an event.
3. `verify`: a `check` step. At least one row, no nulls in the key fields, one row per `id`,
   latitude, longitude and magnitude (-2 to 10) in range, a known status and data less than 6 hours
   old. `severity` per rule: an out-of-range row is rejected alone (`reject`), an unknown status
   and a stale feed only warn. Row `rules` flag events with no magnitude or an odd depth, and with
   `identity: [id]` each run emits a `check.digest` (new, ongoing and resolved findings for the day).
4. `history`: `sqlite.write` with `mode: changeset` on key `id`. USGS revises events for days, so
   `updated` rows are revisions; the page shows them as "Revised by USGS".
5. `retention` (`fn:`, `after: history`): deletes events older than 30 days.
6. `recent` -> `site` -> `export`: the last 7 days of earthquakes plus stats (counts by magnitude
   band, the largest in 24 hours, reviewed share) to `site/data/quakes.json`.

`run.py` then writes `status.json`: outcome, rows read, new and revised, revisions in the last 24
hours, each check rule, the daily digest summary and duration. It also copies `pipeline.yaml` to
`site/pipeline.yaml` (ignored by git), so the page shows the real file.

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

`.github/workflows/quakes.yml` runs every 15 minutes and on demand. It restores `.agentl/`, `data/`
and `site/data/` from the Actions cache, runs `python run.py` with `agentl-etl==0.12.0`, copies
`pipeline.yaml` into `site/` and deploys `quakes/site` to the Cloudflare Pages project
`agentl-quakes` with `cloudflare/wrangler-action`, creating the project on the first deploy. It
uses the same repository secrets as fx: `CLOUDFLARE_API_TOKEN` (Pages: Edit) and
`CLOUDFLARE_ACCOUNT_ID`. The custom domain `quakes.agentl.com.br` is added to the Pages project
once, by hand, after the first deploy.

## Data

Earthquake data: U.S. Geological Survey, public domain. Automatic solutions are preliminary and
are revised by seismologists. This page is not an alert service; for official information see the
[USGS Latest Earthquakes map](https://earthquake.usgs.gov/earthquakes/map/).
Map tiles: © OpenStreetMap contributors.
