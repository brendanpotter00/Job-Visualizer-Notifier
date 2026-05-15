# Incident: Apple Scraper 90-Minute Hang on Railway

**Date:** 2026-05-02 05:48 UTC (last successful Apple run), 2026-05-05 (regression fully manifest), 2026-05-06 06:11 UTC (first successful cycle on the fix)
**Severity:** Medium
**Impact:** Hourly Apple scrape cycles ran the full `SCRAPER_TIMEOUT_MINUTES=90` budget and were SIGKILLed by `scraper_runner` for ~4 days. No new Apple jobs were ingested and no Apple jobs were updated during that window. Existing Apple data in `job_listings_prod` was unaffected — the per-company try/except in `auto_scraper` kept Google and Microsoft cycling normally (~4 min each), and the incremental safety guard introduced in the 2026-03-29 incident prevented mass closure on 0-job runs. The acute outage cleared on 2026-05-06T06:11 UTC when PR #98's hotfix deploy restored the scraper subprocess's stdout/stderr capture, after which the first Apple cycle ran end-to-end in ~69 min and successive cycles stabilized at ~89 min.

## Summary

Apple's incremental scraper has always required navigating ~250 search-result pages × ~6 s/page plus ~360 detail fetches, totalling ~80–90 min on a healthy Railway run. The base scraper used `page.goto(..., wait_until="networkidle")`, which on Apple's analytics-chatty careers site never fired before its 30-second timeout. Once Railway's egress IP began experiencing consistent slow-pathing from Apple's edge (around 2026-05-02), every page navigation was burning the full 30 s instead of the typical 1–3 s, pushing the cumulative runtime past the 90-minute kill switch on every cycle. Compounding the observability problem: `scraper_runner` set `stdout=DEVNULL`, `PYTHONUNBUFFERED` was unset, and the captured stderr tail was discarded on `TimeoutError` — so Railway logs showed `Starting scrape for apple` followed by 90 minutes of complete silence, then `exit code -2`. With no signal to debug from, the actual root cause could not be identified by inspection.

## Timeline

| Time (UTC)            | Event |
|-----------------------|-------|
| 2026-05-02 05:48      | Last successful Apple `scrape_runs_prod` row before the outage. After this point Apple cycles silently exceed the 90-min budget. |
| 2026-05-02 — 2026-05-05 | Five Apple cycles per ~92-minute interval all SIGKILLed at `Process timed out after 90 minutes`. Google + Microsoft on the same container continue to complete in ~4 min — the hang is Apple-only. Railway logs show *zero* stderr output from the Apple subprocess in this window. |
| 2026-05-05 16:32      | PR #96 (commit `d597412`, pthread-exhaustion fix from a separate incident) deploys. Browser launches succeed reliably again, ruling out the prior pthread/PID failure mode. Apple still hangs at 90 min. |
| 2026-05-06 02:30      | Investigation begins. Live Playwright probe of `https://jobs.apple.com/en-us/search?...` confirms list/pagination/detail-API selectors are all correct (no DOM regression). Local end-to-end run from a non-Railway IP completes 10 jobs in 68 s — the code path is healthy. Conclusion: hang is environment-specific (Apple's edge → Railway egress) and the actual stall point cannot be identified without observability. |
| 2026-05-06 03:08:30   | **PR #97 deploys** (commit `193b042`). Adds live per-line stderr streaming to backend logger, `PYTHONUNBUFFERED=1`, `AbortSignal.timeout(15s)` on in-browser `fetch()` for Apple + Microsoft, and Apple-specific `wait_until="domcontentloaded"` (skipping `networkidle`). |
| 2026-05-06 03:16:56   | First Apple cycle on PR #97. **Fails instantly** with `exit_code=-1` and stderr `STDOUT can only be used for stderr`. PR #97 had set `stdout=asyncio.subprocess.STDOUT` to merge stdout into stderr, but `asyncio.subprocess.STDOUT` is only valid as the `stderr=` argument — the asymmetric API contract was not caught by the kwargs-only mock test. Apple is now failing in 1 ms instead of hanging 90 min, but the observability never gets to run. |
| 2026-05-06 04:16:56   | Second Apple cycle on PR #97 fails identically. |
| 2026-05-06 04:55      | PR #98 opened: hotfix swaps redirection to `stdout=PIPE, stderr=STDOUT` and reads from `process.stdout`. Adds `test_real_subprocess_captures_stdout_and_stderr` — a real Python subprocess test that exercises asyncio's actual API constraint instead of relying on a mock. |
| 2026-05-06 05:01:56   | **PR #98 deploys** (commit `4d5c2eb`). |
| 2026-05-06 05:02:06   | Apple cycle starts on the corrected build. Live `scraper[apple] …` lines begin streaming to Railway in real time — first time we have visibility since 2026-05-02. |
| 2026-05-06 05:30      | Pagination phase completes (~250 pages in 28 min, vs >125 min on the prior `networkidle` strategy). Detail-scrape phase starts on 362 new jobs. |
| 2026-05-06 05:32:50   | Defensive `AbortSignal` fires on detail fetch for job `200626226-3401`: `Page.evaluate: AbortError: signal is aborted without reason`. The per-job catch yields `_detail_fetch_failed=True` and the loop continues — exactly the designed behavior. Without the abort bound, this single fetch would have hung the entire subprocess. |
| 2026-05-06 06:11:47   | **First successful Apple cycle on the fix.** Runtime ~69 min for full 362-job detail backfill. |
| 2026-05-06 07:41 — 13:41 | Five additional consecutive Apple cycles complete successfully, runtime 89 ± 1 min, 3,820–3,821 jobs (typical churn). Outage closed. |

## Root Cause

The acute symptom was a single dominant cause; the inability to diagnose it was a separate compounded cause.

### Why Apple cycles took >90 minutes

`scripts/shared/base_scraper.py` previously navigated to each search-results page with `page.goto(url, wait_until="networkidle", timeout=30000)` and an exception fallback to `wait_until="domcontentloaded"`. `networkidle` resolves only after the network has been idle for 500 ms; Apple's careers site polls analytics endpoints continuously, so on a healthy connection the page reaches `networkidle` only because the 500 ms gap eventually appears between polls. Once Railway's egress IP began experiencing consistent ~30 s response delays from Apple's edge in early May 2026, the analytics polls and the main HTML response interleaved with enough latency that `networkidle` never fired before the 30 s timeout. Every page navigation now burned the full 30 s, then the fallback `domcontentloaded` retry burned more time getting the same page to "doc parsed" state.

For a full Apple incremental cycle this meant ~250 pagination pages × ~30 s/page = **~125 minutes for list-scrape alone**, before any detail-fetch began. The 90-minute `SCRAPER_TIMEOUT_MINUTES` ceiling was hit deep inside list-scrape every cycle.

This was not a code regression — the code had been running for months. The trigger was external (slower edge response from Apple to Railway, likely intermittent throttling of datacenter IP space). What turned a slow-but-finishing run into a hard outage was that the existing strategy had no margin against a 10×–30× per-page latency increase.

### Why nobody could see what was happening

Three independent observability defects in `src/backend/api/services/scraper_runner.py` and the container configuration combined to throw away 100% of the scraper subprocess's diagnostic output:

1. **`stdout=asyncio.subprocess.DEVNULL`** discarded any `print()` output and any logger record routed through stdout.
2. **No `PYTHONUNBUFFERED=1` in the Dockerfile.** Python defaults to block-buffered (~4 KB) stderr when stderr is connected to a pipe rather than a TTY. The subprocess was producing log lines, but they sat in the buffer and were never flushed before SIGKILL closed the pipe.
3. **The captured stderr tail was discarded on `TimeoutError`.** The original `_read_stderr_tail` coroutine was wrapped in `asyncio.wait_for(timeout=timeout_seconds)`. On timeout, `wait_for` cancels the inner coroutine and raises `TimeoutError`. The cancelled coroutine's accumulated `tail` bytes are lost — the timeout branch returned a hardcoded `"Process timed out after N minutes"` string with no captured stderr at all.

Together these meant a 90-minute Apple cycle produced exactly *one* log line in Railway: `Scrape finished with exit code -2 for apple: Process timed out after 90 minutes`. There was no signal to point at the `networkidle` timeouts as the dominant cost, or at any specific page or detail fetch. The investigation could not converge by log inspection alone.

## Fixes Applied

Two PRs landed: **PR #97** (observability + defensive bounds) and **PR #98** (hotfix for an asyncio-API regression introduced by PR #97).

### PR #97 — Observability + defensive bounds (commit `193b042`)

Files: `src/backend/Dockerfile`, `src/backend/api/services/scraper_runner.py`, `scripts/apple_jobs_scraper/{api_client,scraper}.py`, `scripts/microsoft_jobs_scraper/api_client.py`, plus tests.

**Observability changes**

- Added `ENV PYTHONUNBUFFERED=1` to the backend Dockerfile so stderr/stdout flush per write instead of in 4 KB blocks.
- Rewrote `scraper_runner._read_stderr_tail` into a `_stream_and_tail_stderr` reader_task that streams stderr line-by-line, emits each non-empty line through `logger.info("scraper[%s] %s", company, line)` for live Railway visibility, *and* accumulates into a caller-owned `bytearray` (`tail_buffer`). The caller-owned buffer is the load-bearing trick: `asyncio.wait_for` cancellation of the reader task does not destroy the bytearray, so the timeout branch can drain whatever was captured before the kill and surface it in `ScraperResult.error`.
- Switched the subprocess from `stdout=DEVNULL, stderr=PIPE` so stdout was no longer discarded. *(See PR #98 below for the asyncio-API correction.)*
- Added a loud annotation on `ScraperResult.error` if `process.wait()` does not return within `KILL_WAIT_SECONDS=30` of SIGKILL — surfaces zombie risk to operators reading `scrape_runs_prod` rows.

**Defensive bounds**

- Wrapped the in-browser `page.evaluate(fetch …)` call in `scripts/apple_jobs_scraper/api_client.py` and both call sites in `scripts/microsoft_jobs_scraper/api_client.py` with an `AbortController` + `setTimeout(15000)` in the JS payload, plus an outer Python-side `asyncio.wait_for(timeout=20.0)` as belt-and-suspenders. Outer timeout raises the existing per-module `*FetchError`, which the per-job catch already handles by yielding `{**job_card, "_detail_fetch_failed": True}` and continuing. A single hung detail fetch can no longer hang the whole subprocess.
- Added an Apple-specific `navigate_to_page` override in `scripts/apple_jobs_scraper/scraper.py` that uses `wait_until="domcontentloaded"` directly instead of inheriting the base class's `networkidle` strategy. The override preserves the base class's single-retry resilience. **This is the change that ultimately closed the incident** — switching the goto strategy reduced list-scrape time from >125 min to ~28 min, putting the full cycle back inside the 90-min budget.

**Tests**

- `test_subprocess_merges_*`, `test_stderr_lines_emitted_to_live_logger`, `test_stderr_lines_emitted_during_read_loop` (timing-based proof that line N reaches the logger before line N+1 is read), `test_timeout_includes_stderr_tail`, `test_kill_wait_expiry_annotates_zombie_warning`.
- `test_dockerfile_sets_pythonunbuffered` — Dockerfile guard.
- `test_apple_api_client.test_fetch_job_details_outer_timeout_raises_fetch_error` and `test_fetch_js_payload_uses_abort_controller`. Mirrored for Microsoft.
- `test_apple_scraper_methods.py` (new file) — `test_navigate_to_page_uses_domcontentloaded`, retry pin, exception propagation pin.

### PR #98 — Hotfix for asyncio API misuse (commit `4d5c2eb`)

PR #97 set `stdout=asyncio.subprocess.STDOUT` to merge stdout into stderr. `asyncio.subprocess.STDOUT` is only valid as the `stderr=` argument; passing it as `stdout=` raises `ValueError: STDOUT can only be used for stderr` at `create_subprocess_exec` time, before the subprocess starts. Both Apple cycles after PR #97's deploy failed in 1 ms with that ValueError as the only log line.

Fix: swap to `stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT` (merge stderr → stdout, the supported direction) and read from `process.stdout`. Same observability goal.

The kwargs-only mock-based test in PR #97 had asserted `kwargs["stdout"] == STDOUT` — *exactly* the buggy direction — so the test passed while the production call raised. PR #98 added `test_real_subprocess_captures_stdout_and_stderr`, which spawns a real Python child writing to both pipes via `sys.executable` and asserts both lines reach `ScraperResult.error`. This test exercises asyncio's actual API contract (it fails with `ValueError` before reaching any assertion if the kwargs are reversed) and prevents the same regression from recurring.

## Lessons

- **`networkidle` has no margin against external slowdown.** It works on healthy connections but degrades non-linearly when a single external dependency starts responding slowly. Sites with continuous analytics polling (Apple, large enterprise careers pages) are particularly fragile under this strategy. Default to `domcontentloaded` or `load` for list-scrape paths and only opt into `networkidle` when there is a specific need to wait for AJAX-loaded content.
- **Mock-based tests that assert kwargs do not catch API constraint violations.** The PR #97 → PR #98 regression was a pure mock-vs-reality gap: the mock had no concept of `asyncio.subprocess.STDOUT`'s asymmetric validity. The fix was to add a complementary test that exercises the real asyncio call with a tiny real subprocess. For any code that uses an external API contract — asyncio, Playwright, requests — at least one test in the suite should exercise the contract for real, even if all the unit tests are mocked.
- **The capture path matters as much as the emit path.** PR #97 fixed three separate observability defects (`stdout=DEVNULL`, no `PYTHONUNBUFFERED`, tail discarded on timeout). Any one of them alone would have left the same 90-min silence — the emit and capture paths are a chain, and a break anywhere makes the whole thing useless. When wiring observability, design the *capture-on-failure* path before the emit path; that's the path that actually matters for diagnosing incidents.
- **Two-PR shape was correct.** Shipping PR #97 as observability-first plus defensive bounds — without claiming to fix the root cause — meant the next Apple cycle produced enough signal for the actual cause (`networkidle` timeouts) to be visible immediately. PR #98 then closed the regression PR #97 introduced. A single "fix everything" PR would have made the 90-min silence feedback loop one cycle longer at minimum.

## Related

- `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md` — separate incident (Apple, Google, Microsoft all failing on `pthread_create EAGAIN`) resolved by PR #96. That PR cleared the original 2026-05-02 outage symptom; this incident is the post-cleanup Apple-only follow-up.
- `docs/implementations/appleScraperHangFix/PLAN.md` — pre-implementation plan and evidence-gathering trail for PR #97.
- `docs/incidents/2026-04-09-oom-memory-fragmentation.md` — earlier scraper observability gap with similar "no signal in Railway" character.
