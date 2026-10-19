# agentl examples

Small, real projects built with [agentl](https://agentl.com.br), the YAML ETL library for Python.
Each one runs on a schedule in GitHub Actions and publishes a static site, so you can see the
pipeline, its checks and its output side by side: useful public data that anyone can use, and a
working showcase of what agentl does. Each site shows the pipeline file that built it.

| Project | Live | What it does | agentl features |
| --- | --- | --- | --- |
| [`fx/`](fx/) | [fx.agentl.com.br](https://fx.agentl.com.br) | Euro foreign-exchange reference rates from the European Central Bank, with a 90-day chart and a pipeline status panel | `http.get` with `if_changed`, `fn:` steps, `concat`, `dedupe`, `compute`, `check` (rows, not_null, unique, accepted, fresh), `sqlite.write` with `mode: changeset`, `sqlite.read`, `json.write`, the Python `agentl.run` API with event listeners |

## Run locally

Python 3.10 or newer.

```bash
python -m venv .venv && . .venv/bin/activate
pip install agentl-etl
cd fx
agentl lint pipeline.yaml
python run.py                     # runs the pipeline and writes site/data/status.json
python -m http.server -d site 8000
```

Then open http://localhost:8000. See each project's README for details.

## License

MIT, see [LICENSE](LICENSE).
