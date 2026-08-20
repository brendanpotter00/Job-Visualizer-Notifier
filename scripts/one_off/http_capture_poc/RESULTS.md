# Tier-1 validation POC — RESULTS (2026-08-19)

Validates the [`DETERMINISTIC-CAPTURE-DIRECTION`](../../../docs/implementations/custom-company-sources/DETERMINISTIC-CAPTURE-DIRECTION.md)
thesis: use a Browserbase session **once** to discover a job board's underlying network
API, then replay it **cheaply with plain HTTP** (no browser, no LLM). Ran against
`amazon.jobs` on a paid Browserbase plan.

## Verdict: ✅ VALIDATED (on Amazon — the clean-public-API case)

## What ran

1. **`amazon_capture_poc.py`** — created a Browserbase session, drove it with Playwright
   over CDP (`connect_over_cdp(connectUrl)`), listened to every JSON XHR/fetch response,
   navigated to `amazon.jobs/en/search?base_query=software`, and identified the
   job-shaped response.
2. **`amazon_paginate_test.py`** — took the discovered endpoint and paged it with plain
   `httpx` only (no browser).

## Evidence

**Capture** — of 10 JSON XHR/fetch responses, exactly one was job-shaped:
```
GET 200  https://www.amazon.jobs/en/search.json?...&offset=0&result_limit=10&sort=relevant&base_query=software
        browser saw 10 jobs
```
(A separate `POST https://www.amazon.jobs/auth/token` returned 401 but was NOT needed —
the search endpoint is public.)

**Replay (plain httpx, no browser, no LLM, no cookies/tokens — only a User-Agent):**
```
replay status: 200, 117074 bytes -> 10 jobs (browser saw 10)   ✅ match
```

**Scale / pagination (plain httpx):**
```
result_limit=100 offset=0   -> 200, TOTAL hits=10000, 100 jobs; first "Director, Software Dev - Network Software"
result_limit=100 offset=100 -> 200, hits=10000,       100 jobs; first "Software Development Engineer, ... Amazon LEO"
```
100 jobs/page, `offset` advances to a different page, `hits` reports the total → all
reachable by paging. $0 per page, no browser.

## What this proves

- Browserbase + CDP network capture **discovers the underlying jobs API** from live traffic.
- That request **replays deterministically with plain HTTP** and returns the same jobs.
- It **scales** to thousands of jobs via `offset` pagination — cheaply, unlike the current
  bounded ≤3-page Stagehand browser read.

## Honest caveats (do not over-generalize)

- This is **Amazon** — a clean, public, unsigned JSON API. It's the *ideal* Tier-1 case,
  not proof for every board. Token-signed / bot-walled boards (Meta) still need the
  browser fallback; the discovery-time **validation gate** is what decides.
- `hits=10000` is Amazon's result **cap** per query (not the true total). Exceeding it needs
  facet/category splitting — a detail for the full plan (the original plan's `facet_sum`
  oracle already anticipated Amazon's 10k cap).
- POC used a fixed `base_query=software`. A real recipe would drop the query to capture the
  whole board and parameterize `offset`/`result_limit`.

## Next (step 3)

Write the full implementation plan: the CDP-capture discovery module, recipe synthesis +
`recipe_runner` wiring, the validation gate, the requires-browser fallback, and how a
recipe is stored/replayed on the existing daily cadence.
