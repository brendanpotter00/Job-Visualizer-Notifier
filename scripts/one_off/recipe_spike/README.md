# Recipe spike harness (throwaway)

Spike for ClickUp E7 / 7.2: **can a one-time agent pass produce a deterministic
scrape recipe that replays forever with no AI in the loop?**

Nothing here is production code. It lives under `scripts/one_off/` deliberately
and imports nothing from `src/backend/`. The findings and the frozen schema are
the deliverable; this code is the evidence that produced them.

## The one rule

**Discovery and replay are two code paths that never meet.**

```
capture.py  ──(evidence)──▶  [ agent authors recipe ]  ──▶  recipes/*.json
                                                                  │
                                                                  ▼
                                                            replay.py
                                          imports: stdlib, httpx, bs4, playwright
                                          imports NOT: any agent or LLM client
```

`replay.py` calls `assert_no_agent_imports()` before every run and fails loudly
if `anthropic`, `openai`, `stagehand`, `browserbase`, or `langchain` is in
`sys.modules`. If replay could reach an agent, the whole measurement would be
worthless — the point is proving the recipe stands on its own.

`capture_browserbase.py` (optional cloud arm) is discovery-side only.

## Setup

```bash
# isolated venv — the repo's main .venv is deliberately left untouched
/Users/bpotter/developer/personal/Job-Visualizer-Notifier/.venv/bin/python -m venv .venv
.venv/bin/pip install httpx beautifulsoup4 playwright==1.61.0
```

Chromium comes from the already-populated `~/Library/Caches/ms-playwright`, so
no browser download is needed. Total spend: $0.

## Discovery (agent-driven, once per company)

```bash
.venv/bin/python capture.py --target acme --url "https://acme.com/careers" \
    --wait networkidle --scroll 2
```

Writes `captures/acme/`:
- `report.json` — compact evidence summary. **Read this first.** Ranks every
  JSON response by how job-like its arrays look, lists all XHR, sketches
  embedded JSON islands and repeated DOM classes.
- `raw/NNN.json` — full bodies of the JSON responses worth opening
- `page.html` — final rendered HTML

Then the agent reads that evidence and writes `recipes/acme.json`.
`inspect_embedded.py` helps when the data is a JSON island in the markup.

## Replay (deterministic, forever, no agent)

```bash
.venv/bin/python replay.py --recipe recipes/acme.json
.venv/bin/python replay.py --all --label replay-2      # every recipe
```

Results land in `results/<label>-<utc>.json`.

## Recipe kinds, ranked

| kind | runtime cost | when |
|---|---|---|
| `http_json` | cents/month — plain HTTP | the page calls a JSON endpoint |
| `http_html` | cents/month — plain HTTP | server-rendered; prefer `embedded_json` (a JSON island) over CSS selectors, which rot fastest |
| `browser_dom` | a real browser every run | **last resort** — only when HTTP demonstrably cannot get the data |

`browser_dom` is a *browser*, not an AI: deterministic Playwright, the same
thing `scripts/{google,apple,microsoft}_jobs_scraper/` already run hourly.

## The invariant that matters most

`run_recipe()` **raises** on non-2xx, unparseable payloads, a `records_path`
that doesn't resolve, zero records, or a count below `expected_min_jobs`.
It never returns `[]`.

An empty list is indistinguishable from "this company stopped hiring", which
feeds the miss counter and closes every job. That is not hypothetical here:
see `docs/incidents/2026-03-29-mass-job-closure.md` — 3,582 Apple jobs closed in
two runs. Any recipe runtime that reaches production inherits this contract.
