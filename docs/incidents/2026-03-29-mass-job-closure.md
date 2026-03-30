# Incident: Mass Job Closure for Apple

**Date:** 2026-03-28 (failure began), 2026-03-30 (root cause identified)
**Severity:** High
**Impact:** Apple scraper returns 0 jobs every run since PR #21 deployed. All 5,504 Apple jobs mass-closed in database after 2 consecutive failures.

## Summary

PR #21 (Refactor .NET to FastAPI) changed the Dockerfile base image from `mcr.microsoft.com/dotnet/aspnet:8.0` (full Debian Bookworm) to `python:3.13-slim` (minimal Debian). The slim image is missing system libraries that Chromium's renderer needs for heavy pages. Apple's React Router v7 SSR page triggers the missing libraries, causing `Page.goto: Page crashed` on every navigation.

The incremental scraping algorithm had no safety guard against 0-job results. After 2 consecutive failures (2 hours), all Apple jobs were marked CLOSED. The frontend filters by `status=OPEN`, displaying zero jobs.

## Timeline (from `scrape_runs_prod`)

| Time (UTC)            | Jobs Seen | Closed | Event |
|-----------------------|-----------|--------|-------|
| 2026-03-28 21:48      | 3,582     | 0      | **Last successful scrape** (~24 min, old .NET Docker image) |
| 2026-03-28 22:39-22:46| —         | —      | **PR #21 deployed** (new python:3.13-slim Docker image) |
| 2026-03-28 22:48      | **0**     | 0      | **First failure** (8 seconds — page crashed immediately) |
| 2026-03-28 22:54      | 0         | **3,582** | **Mass closure** — 2nd consecutive 0-job run hit `MISSED_RUN_THRESHOLD=2` |
| 2026-03-29 onward     | 0         | 0      | All jobs already CLOSED; safety guard (PR #25) has nothing to protect |

## Root Causes

### 1. Missing System Libraries in Slim Docker Image

**Old Dockerfile (working):**
```dockerfile
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base  # Full Debian Bookworm
```

**New Dockerfile (broken):**
```dockerfile
FROM python:3.13-slim  # Minimal Debian Bookworm
```

The Dockerfile manually installs 13 browser libraries (`libnss3`, `libgbm1`, etc.) and runs `playwright install chromium` — but this only downloads the browser binary, NOT system dependencies. Playwright's Chromium needs ~50+ system packages. The old .NET base image (full Debian) shipped most of them pre-installed. The slim Python image doesn't.

Google's lighter careers page works fine because it doesn't exercise the Chromium codepaths that require the missing libraries. Apple's heavier React Router v7 SSR page does.

### 2. No Safety Guard Against Empty Scrapes

The incremental algorithm in `scripts/shared/incremental.py` treated 0 jobs as "all jobs genuinely removed" rather than "scraper failed." After 2 consecutive 0-job runs, `consecutive_misses >= MISSED_RUN_THRESHOLD (2)` triggered mass closure of all 3,582 Apple jobs.

### 3. Crashed Page Reuse

The Apple scraper reused the same Playwright page object after a crash. A crashed page can't be navigated — all subsequent `page.goto()` calls also crash. This meant even if only the first page crashed, pages 2 and 3 would also fail, guaranteeing 0 jobs collected.

## Wrong Hypotheses

1. **Bot detection blocking datacenter IPs** (PR #26) — Built hydration data extraction to bypass empty DOM. Reality: the page never loaded at all.
2. **`/dev/shm` shared memory limit** (commit `7b57423`) — Added `--disable-dev-shm-usage` flag. Reality: the crash is from missing system libraries, not shared memory. Same `Page crashed` symptom, different cause. Deployed and confirmed ineffective.

## Fixes Applied

### 1. `playwright install --with-deps chromium` (Dockerfile)

Replaced manual browser dep apt-get + bare `playwright install chromium` with `playwright install --with-deps chromium`. The `--with-deps` flag installs ALL required system dependencies — Playwright's official recommended approach for Docker.

### 2. Safety guard for empty scrapes (PR #25, commit `4f68822`)

Added guard to `scripts/shared/incremental.py`: when scrape returns 0 jobs but DB has active jobs, skip update/close phases.

### 3. Page crash recovery (Apple scraper)

Create a fresh page after each navigation crash instead of reusing the dead page object.

### 4. Stderr logging on success (commit `d4a1e18`)

`auto_scraper.py` now logs subprocess stderr even on exit code 0.

## Files Changed

- `src/backend/Dockerfile` — `playwright install --with-deps chromium`, removed manual browser dep apt-get
- `scripts/shared/incremental.py` — Safety guard + `skipped_update` field
- `scripts/apple_jobs_scraper/scraper.py` — Fresh page after navigation crash
- `scripts/shared/base_scraper.py` — `--disable-dev-shm-usage` Chromium flag (belt-and-suspenders)
- `src/backend/api/services/auto_scraper.py` — Log stderr on success
- `scripts/run_scraper.py` — CLI warning when safety guard triggers

## Outstanding Issues

1. **Apple data recovery** — All Apple jobs are CLOSED. After confirming the Docker fix works:
   ```sql
   UPDATE job_listings_prod
   SET status = 'OPEN', consecutive_misses = 0
   WHERE company = 'apple' AND status = 'CLOSED';
   ```
   Then the next incremental scrape will properly reconcile.

## Lessons Learned

1. **Use `playwright install --with-deps` in Docker.** Never manually list browser dependencies — the list is incomplete and varies by Chromium version.

2. **Base image changes can break browser automation.** Switching from full Debian to slim removes libraries that Chromium silently depends on. The `Page crashed` error gives no hint about which library is missing.

3. **Incremental algorithms need failure guards.** Any algorithm that can close/delete data based on absence must distinguish "genuinely absent" from "failed to fetch."

4. **Correlate failures with deployments, not hypotheses.** The `scrape_runs` table showed the exact failure moment (22:48) correlating with the deployment (22:39-22:46), pointing directly to the Dockerfile change.

5. **A crashed Playwright page can't be reused.** After `Page crashed`, create a new page to recover.

6. **Log subprocess stderr even on success.** The 10-second Apple runs looked "successful" because stderr was silently dropped on exit code 0.
