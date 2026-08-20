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

## Multi-board spectrum (2026-08-19 follow-up — `board_capture_poc.py`)

Generalized the POC (any URL, POST support, two-tier replay: minimal-headers vs.
full-headers-no-cookie) to classify boards. Ran three:

| Board | Discovered API | Replay (plain httpx) | Verdict |
|---|---|---|---|
| **Amazon** | `GET .../search.json` | 200, same jobs | ✅ **DETERMINISTIC** (public) |
| **Spotify** | `GET api.lifeatspotify.com/wp-json/animal/v1/job/search` (90 jobs) | 200, all 90 | ✅ **DETERMINISTIC** (public WP API) |
| **TikTok** | `POST api.lifeattiktok.com/api/v1/public/supplier/search/job/posts` (12 jobs) | **400** (minimal AND full-no-cookie) | 🔴 **REQUIRES-BROWSER** (ByteDance signs its "public" endpoints) |

**Takeaways:** Tier-1 generalizes (Amazon + Spotify both clean public GETs → free daily
replay). The classifier **correctly detects the fallback case** (TikTok's signed POST 400s
outside the browser) instead of storing a broken recipe — the validation gate works.

## Browserbase recording / live-view (owner asked)

- `GET /v1/sessions/{id}/debug` → **200**, returns **`debuggerFullscreenUrl`** — a hosted,
  **iframe-embeddable live view** of the session (real-time "watch it happen"). This is the
  right primitive for the "embed the browser so the user watches discovery" idea.
- `GET /v1/sessions/{id}/recording` → **404**: *"The rrweb-based Session Replay API is being
  deprecated."* The old after-the-fact recording API is going away; use the live view.

## "Requires-browser" ≠ dead end — the in-browser-fetch tier (TikTok, proven)

TikTok's `search/job/posts` is a signed/origin-checked POST → plain `httpx` 400s. But JVN's
`main` already ships a working `scripts/tiktok_jobs_scraper` that runs the **same deterministic
POST inside the browser** (`page.evaluate(fetch(...))`) on the `lifeattiktok.com` origin, with a
required `website-path: tiktok` header (the endpoint sends no CORS header, so it must be
same-origin). Re-proved it live via Browserbase (`tiktok_inbrowser_poc.py`):
```
in-browser fetch status: 200, payload code=0, jobs found=10   ✅
```

So the real tiering is finer than "http vs fallback":

- **Tier 1a — pure HTTP** (Amazon, Spotify): plain `httpx`, **$0**.
- **Tier 1b — in-browser fetch** (TikTok): the *same deterministic API call* run inside a
  headless browser on the site's origin. Browser-hours, **no LLM, no DOM parsing** — still a
  deterministic recipe. This is how JVN's Apple / Microsoft / Amazon / TikTok scrapers already work.
- **Tier 2/3 — DOM read / agent**: only when there is no clean API at all.

A "requires-browser recipe" stores `{origin_url, method, endpoint, headers (e.g. website-path),
body template, pagination}` with `transport='browser_fetch'`. Discovery validates by replaying
the captured call *inside a browser*; if that returns jobs → store `browser_fetch`; only if even
that fails is the board truly Tier 2/3. **This means TikTok is recipe-able and cheap — not an
agent board.**

## Next (step 3)

Write the full implementation plan: the CDP-capture discovery module, recipe synthesis +
`recipe_runner` wiring, the validation gate, the requires-browser fallback, and how a
recipe is stored/replayed on the existing daily cadence.
