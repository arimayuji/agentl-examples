# spending: where federal money went this week

Live: https://spending.agentl.com.br

A useful public dataset and a showcase for [agentl](https://agentl.com.br) agent steps: the page
lists the new US federal contracts above $1 million from the last 7 days, each explained in one
plain-English line by a small LLM, with totals by category and by agency, a search box, the exact
`pipeline.yaml` that produced it and the status of the last run. An "AI accuracy" panel shows how
often the model is right on a hand-labelled golden set, what each right answer cost and the
month's LLM spend against its cap.

Source: the [USAspending.gov API](https://api.usaspending.gov/docs/endpoints), public domain, no
key: `GET /api/v2/awards/last_updated/` and `POST /api/v2/search/spending_by_award/` with contract
award types A, B, C and D, `date_type: new_awards_only`, a lower bound of $1M, sorted by amount.

## Files

| File | What it is |
| --- | --- |
| `pipeline.yaml` | The agentl pipeline |
| `steps.py` | `fn:` steps: the date window and pages, flatten the search results, the fields the classifier sees, the rule that answers when classification is off, merge, the page JSON with totals |
| `run.py` | Runs the pipeline with `agentl.run`: sets the per-run budget from the monthly cap, turns classification off without a key, folds in `eval.json` and writes `site/data/status.json` |
| `golden/awards.jsonl` | 30 real awards labelled by hand (category and clarity), for `agentl eval` |
| `golden/sample_summaries.json` | Hand-written summaries of the same 30, used only by `run.py --sample` |
| `site/index.html` | The page: static, no build step, vanilla JS, inline SVG bar charts, Inter and JetBrains Mono from Google Fonts |
| `site/assets/` | agentl logo, wordmarks, favicon, animated logo loop and the Open Graph image `og.png` |
| `og/` | `og.html`, the template for `og.png`, and `render.py`, which renders it with Playwright |
| `site/data/` | `awards.json` and `status.json`. A sample is committed so the site works before the first run (below) |

## The pipeline

1. `stamp`: `http.get` of USAspending's `last_updated` with `if_changed`. That endpoint sends no
   ETag or Last-Modified, so the body hash decides; when the load date has not changed, the run
   ends with outcome `no_change` and nothing is fetched, asked or rewritten.
2. `window` and `awards`: one record per page (the last 7 days up to the load date, at most 3
   pages of 100), then `http.post` once per page. USAspending takes the page number in the JSON
   body, so `{page}`, `{start}` and `{end}` are filled from each record (`paginate` puts the page
   in the query string, and this API reads it from the body).
3. `rows` and `verify`: one flat row per award (`award_id` is USAspending's unique
   `generated_internal_id`; the PIID alone can repeat across agencies). Checks: at least one row
   (warn), no missing id, amount, agency, recipient or URL, one row per `award_id`, amount above
   zero. Failing rows are rejected alone.
4. `brief` and `classify`: the agent step sees only the description, agency, sub agency,
   recipient, PSC and NAICS descriptions. Amounts and dates stay out of the cache key, so an award
   is asked once and never paid for again, even when its amount is revised. Output: `category`
   (defense, health, IT, construction, research, energy, transport, education, other),
   `plain_summary`, `clarity` (clear or opaque) and `confidence`.
   - `review: {below: 0.6, hold: false}`: low-confidence answers are published with a
     "needs review" badge and wait in the review queue (`agentl review list`).
   - `pii: mask`: e-mails, phones and names are replaced by placeholders before the call.
   - `rules: [fn: steps:no_llm]`: answers every award as `unclassified`, with no call, when
     classification is off (no key, or the monthly cap is spent). Otherwise it defers to the llm.
   - `golden: golden/awards.jsonl`: `agentl eval` scores the step on it.
   - `budget` (`max_usd`, `max_calls`) and `llm.rate_limit` (60 requests a minute).
5. `labels`: odd labels are reported (warn), not dropped. The page shows them as "other".
6. `classified`, `history`, `site`, `export`: rows plus answers, a `sqlite.write` changeset keyed
   on `award_id`, and `site/data/awards.json` (largest first, totals by category and agency).

## The model and its budget

The llm is `provider: openrouter`, which reads `OPENROUTER_API_KEY` and uses the cost OpenRouter
reports for each call, so no price is configured. Two optional repository variables:

| Variable | Default | What it does |
| --- | --- | --- |
| `SPENDING_MODEL` | `openai/gpt-4.1-nano` | Any OpenRouter model id that supports structured outputs |
| `SPENDING_BUDGET_USD` | `5` | Monthly cap. Each daily run may spend a 31st of it, and never more than what is left this month |

The default model was picked from OpenRouter's public model list (`/api/v1/models`) on
2026-10-20: a small non-reasoning model with structured outputs at $0.10 per million input tokens
and $0.40 per million output tokens. `agentl plan` on the 72 awards of the week of 13 to 19
October 2026 estimates about 35,000 to 51,000 tokens, $0.006 to $0.009 for a cold run; later
runs only pay for new awards. The daily eval adds 30 calls. The month's spend (runs and evals) is
kept in `status.json` and shown on the page.

Without the key the workflow does not fail: the eval is skipped and the awards are published
unclassified, with the reason in the status panel.

## Run locally

This example uses features of agentl that are newer than the 0.12.0 release (the llm
`rate_limit` and the eval cost per right answer), so it installs agentl from a pinned commit of
main:

```bash
pip install "agentl-etl @ git+https://github.com/arimayuji/agentl@b83f2bbfdd11fa9bb16fa045f0bfd67e93d7a504"
agentl lint pipeline.yaml
export OPENROUTER_API_KEY=...       # optional
agentl eval pipeline.yaml --json > eval.json   # optional, needs the key
python run.py
python -m http.server -d site 8000
```

- `python run.py --echo` uses the offline echo provider: no key, no cost. Echo cannot fill the
  required output fields, so every award is rejected by the classifier and shown unclassified;
  it tests the fetch, checks, cache, rate limit and the rest of the wiring.
- `python run.py --sample` publishes real awards with the hand labels of the golden set and no
  model call. The committed `site/data/` was made this way, and the page says so until the first
  scheduled run replaces it.
- The run store lives in `.agentl/` and the history in `data/`; both are ignored by git.
  `agentl state reset spending` forgets the `if_changed` stamp so the next run fetches again.

## Deploy

`.github/workflows/spending.yml` runs daily at 06:07 UTC and on demand. It restores `.agentl/`
(including the LLM cache), `data/` and `site/data/` from the Actions cache, runs `agentl eval`
and `python run.py`, and deploys `spending/site` to the Cloudflare Pages project
`agentl-spending`, creating it on the first deploy. Secrets: `OPENROUTER_API_KEY` (optional),
and the same `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` as the other examples. The custom
domain `spending.agentl.com.br` is added to the Pages project once, by hand, after the first
deploy.

## Golden set

`golden/awards.jsonl` holds 30 awards from the week of 13 to 19 October 2026, labelled by hand
from their descriptions, PSC and NAICS codes. Ambiguous awards (for example wheelchair van
transport for veterans, which could be health or transport) were left out rather than guessed.
That week had no defense, energy, transport or education awards above $1M among new contracts
(Department of Defense data reach USAspending with a delay), so those categories are not in the
set. Clarity is `opaque` when the filed description alone does not say what is bought (a bare
executive order number, "exercise option period", "PHASE II SBIR").

## Data

Award data: USAspending.gov, public domain. Amounts are obligations at award time, not money
spent, and agencies revise them. Summaries and categories are written by an AI model and can be
wrong; each award links to its official record.
