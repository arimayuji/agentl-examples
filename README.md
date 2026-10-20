# agentl examples

Small, real projects built with [agentl](https://agentl.com.br), the YAML ETL library for Python.
Each one runs on a schedule in GitHub Actions and publishes a static site, so you can see the
pipeline, its checks and its output side by side: useful public data that anyone can use, and a
working showcase of what agentl does. Each site shows the pipeline file that built it.

Browse them all, with live run status, at **[examples.agentl.com.br](https://examples.agentl.com.br)**
(source in [`index/`](index/)).

| Project | Live | What it does | agentl features |
| --- | --- | --- | --- |
| [`fx/`](fx/) | [fx.agentl.com.br](https://fx.agentl.com.br) | Euro foreign-exchange reference rates from the European Central Bank, with a 90-day chart and a pipeline status panel | `http.get` with `if_changed`, `fn:` steps, `concat`, `dedupe`, `compute`, `check` (rows, not_null, unique, accepted, fresh), `sqlite.write` with `mode: changeset`, `sqlite.read`, `json.write`, the Python `agentl.run` API with event listeners |
| [`quakes/`](quakes/) | [quakes.agentl.com.br](https://quakes.agentl.com.br) | A live map of earthquakes worldwide from the USGS, refreshed every 15 minutes, with magnitude and period filters, the latest and largest quakes and a count of USGS revisions | `http.get` with `if_changed` and `items`, `fn:` steps, `concat`, `check` (rows, not_null, unique, range, accepted, fresh, per-rule `severity`, row `rules` with a `check.digest`), `select`, `sqlite.write` with `mode: changeset`, `after:`, `sqlite.read`, `json.write`, the Python `agentl.run` API |
| [`spending/`](spending/) | [spending.agentl.com.br](https://spending.agentl.com.br) | New US federal contracts above $1M from USAspending.gov, each explained in one plain-English line by a small LLM, with totals by category and agency, a search box and the model's accuracy and cost on a hand-labelled golden set | `http.get` with `if_changed`, `http.post` per record, `fn:` steps, `check` with `severity`, an `agent` step on `provider: openrouter` with `rules:`, the per-record cache, `budget` (`max_usd`, `max_calls`), `rate_limit`, `review` (`hold: false`), `pii: mask`, `golden:` and `agentl eval`, `sqlite.write` with `mode: changeset`, `json.write`, the Python `agentl.run` API |

## Index site

[`index/site/`](index/site/) is a static page that lists the examples and reads each site's
`data/status.json` in the browser (Cloudflare Pages serves it with `Access-Control-Allow-Origin: *`).
`.github/workflows/index.yml` deploys it to the Pages project `agentl-examples-index` on pushes to
`main` that touch `index/`. Thumbnails in `index/site/assets/` are screenshots of the live sites;
`index/og/render.py` renders the OG image.

## Run locally

Python 3.10 or newer.

```bash
python -m venv .venv && . .venv/bin/activate
pip install agentl-etl
cd fx                             # or: cd quakes, cd spending
agentl lint pipeline.yaml
python run.py                     # runs the pipeline and writes site/data/status.json
python -m http.server -d site 8000
```

Then open http://localhost:8000. See each project's README for details. `spending/` needs agentl from a pinned
commit of main and, for the summaries, an `OPENROUTER_API_KEY`; see [its README](spending/README.md).

## License

MIT, see [LICENSE](LICENSE).
