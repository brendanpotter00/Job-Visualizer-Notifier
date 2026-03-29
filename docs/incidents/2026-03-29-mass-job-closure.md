# Incident: Mass Job Closure for Google and Apple

**Date:** 2026-03-29
**Severity:** High
**Impact:** All Google and Apple jobs showed as zero on both the Recent Job Postings page and Companies page

## Summary

The FastAPI backend migration (PR #21, commit `167da23`) introduced an auto-scraper background task that runs hourly incremental scrapes. When these scrapes failed (returned 0 jobs), the incremental algorithm had no safety guard and marked ALL existing jobs as CLOSED after 2 consecutive failures (2 hours). The frontend filters by `status=OPEN`, so it displayed zero jobs.

## Root Cause

The incremental scraping algorithm in `scripts/shared/incremental.py` had no protection against empty scrape results. The failure chain:

1. **Auto-scraper runs every hour** (`src/backend/api/services/auto_scraper.py`) — introduced in the FastAPI migration
2. **Always uses `--incremental` mode** (`src/backend/api/services/scraper_runner.py`, line 35)
3. **Scraper subprocess fails** — returns 0 jobs (due to anti-bot blocking, Playwright issues in Docker, network problems, etc.)
4. **Incremental algorithm treats 0 jobs as "all jobs missing"** — `calculate_job_diff(current_ids={}, active_known_ids)` puts every active job into the `missing_jobs` set
5. **`update_existing_jobs()` increments `consecutive_misses`** for ALL jobs
6. **After 2 failed scrapes (2 hours):** `consecutive_misses >= MISSED_RUN_THRESHOLD (2)` triggers mass closure
7. **Frontend requests `status=OPEN`** via `backendScraperClient.ts` and gets 0 results

The scraper code itself was verified to be correct — both Apple's `ul[aria-label="Job Opportunities"]` selector and Google's `h3` + `a[href*="jobs/results/"]` selectors work on the live sites (verified via Playwright). The failures were operational (scraper subprocess failing in Docker/production, not a code bug in the parsers).

## What Went Wrong

The C#-to-FastAPI migration faithfully replicated the auto-scraper behavior from the old backend, but the incremental algorithm was written without considering the scenario where the scraper itself fails completely. The algorithm assumed that if 0 jobs are returned, it means all jobs have been genuinely removed — not that the scraper crashed or was blocked.

## Fix

Added a safety guard to `scripts/shared/incremental.py` in `run_incremental_scrape()`:

```python
if result.jobs_seen == 0 and active_known_ids:
    logger.warning(
        "EMPTY SCRAPE DETECTED for %s: scraper returned 0 jobs but %d active "
        "jobs exist in database. Skipping update/close phases.",
        company, len(active_known_ids),
    )
    result.skipped_update = True
```

When a scrape returns 0 jobs but the database has active jobs, phases 3-5 (insert new, update existing, mark closed) are skipped entirely. A warning is logged for investigation.

## Files Changed

- `scripts/shared/incremental.py` — Safety guard + `skipped_update` field on `ScrapeResult`
- `scripts/run_scraper.py` — CLI warning when safety guard triggers
- `scripts/tests/integration/test_incremental.py` — Tests for safety guard behavior

## Data Recovery

After deploying the fix, run a full (non-incremental) scrape for affected companies to re-populate OPEN jobs:

```bash
python scripts/run_scraper.py --company apple --env prod --db-url $DATABASE_URL --detail-scrape
python scripts/run_scraper.py --company google --env prod --db-url $DATABASE_URL --detail-scrape
```

Or for immediate recovery, update the database directly:

```sql
UPDATE job_listings_prod
SET status = 'OPEN', consecutive_misses = 0
WHERE company IN ('apple', 'google') AND status = 'CLOSED';
```

## Lessons Learned

1. **Incremental algorithms need failure guards.** Any algorithm that can close/delete data based on the absence of data must distinguish between "genuinely absent" and "failed to fetch." A scraper returning 0 results is almost certainly a failure, not a real state.

2. **Auto-scrapers amplify bugs.** The incremental algorithm existed before the FastAPI migration, but it was only triggered manually or on a schedule controlled separately. Embedding it as a background task that runs automatically every hour means any latent bug gets triggered much faster and more reliably.

3. **Verify scraper health in production environments.** Scrapers that work locally may fail in Docker/production due to missing browser binaries, anti-bot blocking of datacenter IPs, or network restrictions. The auto-scraper should log and monitor scrape results to catch 0-result runs early.
