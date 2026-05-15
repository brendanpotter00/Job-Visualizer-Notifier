# Fix Apple Scraper 90-Minute Hang on Railway

## Context

Since 2026-05-02, the Apple incremental scraper hangs every cycle on Railway
and is killed at `SCRAPER_TIMEOUT_MINUTES=90`. Last successful Apple
`scrape_runs_prod` row is `2026-05-02 05:48Z`. Google and Microsoft (running
on the same container, same scheduler, same Python image) complete in ~4 min.
PR #96 (`d597412`, deployed 2026-05-05 16:32 UTC) cleared the original
`pthread_create EAGAIN` outage; this is a separate, post-cleanup regression.

## Evidence Gathered

### Live Apple page DOM (Playwright MCP, 2026-05-06)

Navigated `https://jobs.apple.com/en-us/search?location=united-states-USA&page=2`
and probed the page directly:

- `ul[aria-label="Job Opportunities"]` → 20 `<li>`s. **List-extraction selector intact.**
- `[aria-label="Next Page"]` → matches a `<button class="icon icon-chevronend"><span class="visuallyhidden">Next Page</span></button>`. **Pagination selector still works** (Playwright's `:has-text("Next Page")` matches via the `visuallyhidden` span).
- `/api/v1/jobDetails/{job_id}?locale=en-us` → returns `404 application/json` for a stale ID. **API endpoint live**, JSON shape intact.

### Local end-to-end run, 2026-05-05 21:23–21:24 (local dev machine)

Ran `python scripts/run_scraper.py --company apple --max-jobs 10 --detail-scrape --headless -v`
(JSON mode, full pipeline including detail fetch). Result:

| phase | duration |
|---|---|
| browser init | 2 s |
| page 1 navigate + parse | 3 s |
| pagination check + page 2 | 2 s |
| 10× detail fetch | ~55 s (~5–6 s/job, includes 2–5 s rate-limit delay) |
| **total** | **68 s** |

Exit code 0. All 10 detail fetches succeeded. Output JSON written.
**The code path is healthy when run from a non-Railway IP.**

### Railway prod logs

`Starting scrape for apple` → 90 minutes of **complete silence on the Apple
subprocess** → `exit code -2 ... Process timed out`. No traceback, no
Apple-side log line in Railway's captured stderr. Same shape across every
cycle since the redeploy.

### Inference from the evidence

What's **proven**:

1. The Apple scraper code path works end-to-end against Apple's production site (local repro, 68 s for 10 jobs).
2. The DOM selectors and the JSON detail API are still correct as of 2026-05-06.
3. Microsoft, which uses the *same* in-browser `page.evaluate(fetch …)` pattern (`microsoft_jobs_scraper/api_client.py:77`), runs healthy on the same Railway container in ~4 min. So this is **not** a generic "in-browser fetch hangs" problem.
4. The hang is **Apple-specific AND Railway-specific** (Apple-only-from-Railway).
5. Whatever the subprocess writes to stderr during 90 min is **lost**:
   - `setup_logging()` (`scripts/google_jobs_scraper/utils.py:41`) configures `logging.basicConfig` writing to stderr. Logs *are* being produced.
   - But `scraper_runner.py:76` sets `stdout=DEVNULL` and Python defaults to **block-buffered stderr when stderr is a pipe** (no PYTHONUNBUFFERED set in the Dockerfile).
   - On `asyncio.TimeoutError` (`scraper_runner.py:87`), the in-flight `_read_stderr_tail` task is cancelled by `asyncio.wait_for` and its accumulated bytes are **discarded** — the timeout branch returns a hardcoded `"Process timed out after N minutes"` string.

What's **not yet proven**:

We do **not** have direct evidence of *which* code path on Railway hangs.
Plausible candidates, none yet observed:

- (a) `page.goto(..., wait_until="networkidle")` repeatedly hitting its 30 s timeout because Apple's edge holds the connection from Railway's IP.
- (b) `page.evaluate(fetch(...))` for a single detail job hanging because Apple's API silently drops the response from Railway's IP.
- (c) Apple's edge serving a bot-challenge interstitial (Akamai BotManager or similar) that Playwright dutifully waits on.
- (d) Something else.

These all share the same symptom (silent 90-min stall) and we have no signal
in the logs to disambiguate.

## Conclusion

**We cannot identify the specific code-path root cause without first fixing
observability.** The "definitive evidence" we need can only come from
Railway's actual subprocess stderr, which we are currently throwing away.

So the plan is in two PRs:

- **PR 1 (this branch):** Observability fix. Surface the subprocess's actual
  stderr in Railway logs, both during the run and on timeout-kill. After
  this lands, the next Apple cycle gives us the ground truth.
- **PR 2 (later, off a fresh branch):** Targeted fix based on what PR 1's
  logs reveal.

PR 1 also bundles two **defensive, evidence-light** changes that cannot
regress healthy scrapers:

1. Bound `page.evaluate(fetch …)` with `AbortSignal.timeout` and
   `asyncio.wait_for` in **both** Apple and Microsoft API clients.
   Shouldn't change behavior on healthy runs (~5 s per fetch, well under
   any 20 s bound). Worst-case-bounds the candidate-(b) failure mode.
2. Lower `wait_until` on `page.goto` from `"networkidle"` to
   `"domcontentloaded"` for Apple specifically. Apple's careers site is
   heavy on long-poll analytics; `networkidle` rarely fires within 30 s
   anyway, so this is closer to what's actually happening on the wire.

These are listed as "defensive" because we don't have proof either fixes
the bug. They prevent the candidate-(a) and candidate-(b) failure modes
from being silent indefinitely, *without depending on which is the real
cause*.

## Branch

`fix/apple-scraper-detail-fetch-hang` (off `origin/main` at `d597412`).

## PR 1 — Implementation Plan

### Step 1 — Stop discarding subprocess output

**File:** `src/backend/Dockerfile`

Add `ENV PYTHONUNBUFFERED=1` near line 41. Forces line-buffered stderr/stdout
so logs flush per-write, not per-4 KB-block.

```dockerfile
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1     # ← add
ENV SCRAPER_SCRIPTS_PATH=/app/scripts
```

**File:** `src/backend/api/services/scraper_runner.py`

Three changes:

1. **Stop discarding stdout.** Switch `stdout=asyncio.subprocess.DEVNULL`
   (line 76) to `stdout=asyncio.subprocess.STDOUT` so `print()` and any
   unconfigured-handler output merges into stderr.
2. **Stream stderr live to the backend logger.** Replace the single
   `_read_stderr_tail` with a reader that does both: (a) append to the
   bounded tail buffer, (b) emit each non-empty line via
   `logger.info("scraper[%s] %s", company, line)`. So Railway's logs for
   the backend service show Apple's subprocess output **as it happens**,
   not just on completion. This is the load-bearing observability change —
   it makes "what was the scraper doing at minute 47?" answerable from
   Railway logs alone.
3. **Surface the captured tail on timeout.** On `asyncio.TimeoutError`
   (line 87), `process.kill()`, then
   `await asyncio.wait_for(reader_task, timeout=5)` to drain whatever was
   buffered, then include the decoded tail in `ScraperResult.error`
   alongside the existing timeout marker.

The `MAX_STDERR_BYTES = 10 * 1024` constant is reused as-is.

### Step 2 — Defensive bounds on the in-browser fetch (Apple + Microsoft)

**Files:**
- `scripts/apple_jobs_scraper/api_client.py:42`
- `scripts/microsoft_jobs_scraper/api_client.py:77` and `:224`

Wrap the in-page `fetch()` with `AbortSignal.timeout(15000)` and the entire
`page.evaluate(...)` call with `asyncio.wait_for(..., timeout=20)`. On
timeout, raise the existing per-module `*FetchError` so the existing
per-job catch (`apple_jobs_scraper/scraper.py:262`) yields
`{**job_card, "_detail_fetch_failed": True}` and the loop continues.

```python
try:
    response = await asyncio.wait_for(
        page.evaluate(
            """
            async ({url, timeoutMs}) => {
                const ctrl = new AbortController();
                const t = setTimeout(() => ctrl.abort(), timeoutMs);
                try {
                    const r = await fetch(url, { signal: ctrl.signal });
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return await r.json();
                } finally {
                    clearTimeout(t);
                }
            }
            """,
            {"url": api_url, "timeoutMs": 15000},
        ),
        timeout=20.0,
    )
except asyncio.TimeoutError as e:
    raise JobDetailsFetchError(
        f"Detail fetch timed out for job {job_id} after 20s"
    ) from e
```

Why bundle this in PR 1: even if it's not *the* root cause, it changes a
hypothetical 90-min silent hang into a 20-s loud failure with traceback.
It makes PR 2 unnecessary if (b) was the cause.

### Step 3 — Apple-specific page.goto strategy

**File:** `scripts/apple_jobs_scraper/scraper.py` — wrap or override
`navigate_to_page` for Apple only.

Pass `wait_until="domcontentloaded"` instead of `"networkidle"` for Apple's
pagination URLs. Keep the existing 30 s timeout. Apple's careers site has
continuous analytics chatter; `networkidle` reliably hits its timeout.

This stays out of `scripts/shared/base_scraper.py:350` (where
`navigate_to_page` lives) — Google still benefits from `networkidle`.
Implement in `apple_jobs_scraper/scraper.py:148` (the only
`navigate_to_page` call site we need to change for Apple) by calling
`page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)`
directly.

### Step 4 — Tests

- `src/backend/api/tests/test_scraper_runner.py` (extend) — Test that on
  `asyncio.TimeoutError`, the returned `ScraperResult.error` contains
  stderr the subprocess wrote before kill. Use a small subprocess writing
  to stderr then sleeping past `scraper_timeout_minutes=0.05` (3 s).
- `src/backend/api/tests/test_dockerfile_tini_guard.py` (extend) — Add a
  parallel test for `ENV PYTHONUNBUFFERED=1` (mirrors the existing
  tini-install test from PR #96).
- `scripts/tests/unit/test_apple_api_client.py` (extend) — Mock
  `asyncio.wait_for` to raise `TimeoutError`; assert
  `JobDetailsFetchError` is raised with the timeout message. Pin the JS
  payload: assert it contains `AbortController` and `signal: ctrl.signal`
  so a refactor can't silently strip the abort.
- `scripts/tests/unit/test_microsoft_api_client.py` (extend) — Same as
  above, mirrored for Microsoft.

### Step 5 — Verification

Local:
```bash
git checkout -b fix/apple-scraper-detail-fetch-hang
# … apply edits …
source .venv/bin/activate
pytest scripts/tests/unit/test_apple_api_client.py scripts/tests/unit/test_microsoft_api_client.py -v
pytest src/backend/api/tests/test_scraper_runner.py src/backend/api/tests/test_dockerfile_tini_guard.py -v
PYTHONUNBUFFERED=1 .venv/bin/python -u scripts/run_scraper.py --company apple --max-jobs 10 --detail-scrape --headless -v
# Expect: same ~68 s end-to-end as the baseline run captured today.
```

Production verification (post-merge, on Railway):
- Wait for the next auto-scraper Apple cycle (≤ 1 hour).
- Pull logs:
  `mcp__railway-mcp-server__get-logs filter:"scraper[apple]" lines:500`.
  Expect to see real-time progress lines: `Initializing browser…`,
  `Scraping page N`, `Fetching details i/N: <title>`.
- If Apple completes: PR 1 was sufficient (the defensive bounds plus
  better logs likely fixed it, or the prod issue self-healed).
- If Apple still times out at 90 min: read the captured
  `ScraperResult.error` tail in `scrape_runs_prod` for the failing run.
  The stderr now contains the **last log line emitted** before the hang.
  **That** is the definitive evidence, and it goes into PR 2.

## Critical Files

- `src/backend/Dockerfile` — Step 1
- `src/backend/api/services/scraper_runner.py` — Step 1
- `scripts/apple_jobs_scraper/api_client.py` — Step 2
- `scripts/microsoft_jobs_scraper/api_client.py` — Step 2
- `scripts/apple_jobs_scraper/scraper.py` — Step 3
- `scripts/tests/unit/test_apple_api_client.py` — Step 4
- `scripts/tests/unit/test_microsoft_api_client.py` — Step 4
- `src/backend/api/tests/test_scraper_runner.py` — Step 4
- `src/backend/api/tests/test_dockerfile_tini_guard.py` — Step 4

## Reuse Notes

- `setup_logging()` (`scripts/google_jobs_scraper/utils.py:41`) is already
  called from `run_scraper.py:393` before either mode dispatch. Logs go to
  stderr via `logging.basicConfig`. No changes needed there.
- `MAX_STDERR_BYTES = 10 * 1024` already defined in `scraper_runner.py:12`.
  Step 1 reuses it.
- The existing `JobDetailsFetchError` / `JobSearchError` types in the
  api_client modules are already caught by the per-job loops in their
  respective scrapers — Step 2 raises them, doesn't introduce new types.
- The Dockerfile-test pattern from PR #96
  (`test_dockerfile_tini_guard.py`) is the template for Step 4's
  `PYTHONUNBUFFERED` test.

## Out of Scope

- **`SCRAPER_TIMEOUT_MINUTES` change.** User confirmed: keep at 90 min on
  Railway.
- **`button:has-text("Next Page")` selector hardening.** Verified live;
  still matches. Won't touch it without evidence it's broken.
- **`navigate_to_page`'s networkidle strategy for Google or the base
  class.** Google works on Railway with `networkidle`; only Apple gets
  the override (Step 3).
- **A direct-`httpx`-instead-of-in-browser-fetch refactor.** The
  in-browser fetch is intentional (rides the page's session cookies).
  Just bound it.
- **The fix itself.** PR 1 ships observability + defensive bounds;
  PR 2 ships the targeted fix once we see the stderr tail. If Apple
  recovers after PR 1 lands (because the defensive bounds happened to
  address the real issue, or because Apple's edge stops throttling
  Railway), PR 2 may not be needed.
