# Incident: All Scrapers Returning 0 Jobs in Production

**Date:** 2026-03-30
**Severity:** High
**Impact:** Apple scraper returns 0 jobs every run. Google scraper returns 0 jobs (safety guard from PR #25 prevents data loss for 843 active jobs). Microsoft TBD.

## Summary

After deploying PR #26 (hydration data extraction for Apple) and enabling stderr logging, Railway deploy logs revealed the actual failure modes for each scraper. The original hypothesis — that Apple's bot detection was blocking datacenter IPs — was partially wrong. The primary failure is Chromium page crashes in Docker due to shared memory limits.

## Root Causes

### Apple: Chromium Page Crash (`Page.goto: Page crashed`)

The Chromium renderer process crashes when navigating to Apple's job site. The scraper never reaches the extraction phase — all three page navigation attempts crash, triggering "Too many consecutive navigation errors, stopping pagination. Collected 0 jobs before failure."

**Why it crashes:** Docker containers default `/dev/shm` (shared memory) to 64MB. Chromium uses `/dev/shm` for its renderer processes. Apple's React Router v7 SSR page is heavy enough to exceed this limit, causing renderer OOM → page crash.

**Evidence:**
- Scraper completes in 10-11 seconds every run (never reaches extraction)
- Stderr shows `Page.goto: Page crashed` on pages 1, 2, and 3
- Both `networkidle` and `domcontentloaded` wait strategies crash
- Same code works locally (residential machine with normal `/dev/shm`)
- Google scraper uses the same Chromium but loads a lighter page — it doesn't crash

**Why previous analysis was wrong:** The original plan (PR #26) assumed Apple was serving empty DOM to datacenter IPs as bot detection. The hydration data extraction was built to bypass this. In reality, the page never loaded at all — Chromium crashed before any content was rendered.

### Google: DOM Selector Mismatch

Google's careers page loads successfully ("Found 27 h3 elements on page") but the parser extracts 0 job listings from them ("Successfully extracted 0 job listings"). The h3 elements exist but the subsequent CSS selectors (`a[href*="jobs/results/"]`) no longer match — Google likely updated their careers page markup.

**Evidence:**
- Page loads without crash
- 27 h3 elements found (confirming page rendered)
- 0 jobs extracted (selectors no longer match the new DOM structure)
- Safety guard correctly triggers: "EMPTY SCRAPE DETECTED for google: scraper returned 0 jobs but 843 active jobs exist in database"
- Exit code 3 (safety guard)

## Fixes Applied

### 1. `--disable-dev-shm-usage` Chromium flag (commit `7b57423`)

Added `--disable-dev-shm-usage` to Chromium launch args in `scripts/shared/base_scraper.py`. This makes Chromium use `/tmp` instead of `/dev/shm` for shared memory, avoiding the 64MB default limit in Docker containers. This is the standard fix for Playwright/Puppeteer in Docker.

### 2. Stderr logging on success (commit `d4a1e18`)

`auto_scraper.py` previously only logged subprocess stderr on non-zero exit codes. Diagnostic output (like "EMPTY PAGE 1" errors) was silently dropped when the scraper exited 0. Now stderr is logged at INFO level on success too.

## Files Changed

- `scripts/shared/base_scraper.py` — Added `--disable-dev-shm-usage` to Chromium launch args
- `src/backend/api/services/auto_scraper.py` — Log stderr on success (last 30 lines)
- `src/backend/api/tests/test_auto_scraper.py` — Test for stderr logging on success

## Outstanding Issues

1. **Google DOM selectors need updating** — `google_jobs_scraper/parser.py` CSS selectors no longer match Google's careers page. The h3 elements are found but job links within them aren't extracted. Requires investigating the new DOM structure and updating selectors.

2. **Apple data recovery** — All Apple jobs are CLOSED in the database from the original mass closure incident. Even after the Chromium crash fix, the first successful scrape will only populate new jobs. A full non-incremental scrape or SQL recovery is needed:
   ```sql
   UPDATE job_listings_prod
   SET status = 'OPEN', consecutive_misses = 0
   WHERE company = 'apple' AND status = 'CLOSED';
   ```

3. **Microsoft status unknown** — Microsoft scrape was still running at time of investigation. Needs verification in next deploy cycle.

## Lessons Learned

1. **Always add `--disable-dev-shm-usage` for Chromium in Docker.** This is documented in Playwright's own Docker guide but easy to miss. The symptom ("Page crashed") gives no hint about the shared memory cause.

2. **Log subprocess stderr even on success.** Scrapers that exit 0 can still have critical diagnostic output in stderr. The 10-second Apple runs looked "successful" for days because stderr was dropped.

3. **Don't trust hypotheses without production evidence.** The bot-detection hypothesis was plausible but wrong. The real root cause was only visible once we logged stderr from the production environment. Always instrument first, then fix.

4. **Multiple scrapers can fail for different reasons simultaneously.** Apple crashed (Chromium OOM), Google failed (DOM changes), possibly Microsoft too — each requiring a different fix. Don't assume a single root cause across all failures.
