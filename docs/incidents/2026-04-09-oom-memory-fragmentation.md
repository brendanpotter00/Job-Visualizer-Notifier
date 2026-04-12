# Incident: OOM Crash from Memory Fragmentation

**Date:** 2026-04-09 06:02 UTC (crash), 2026-04-11 (root cause identified)
**Severity:** Medium
**Impact:** Backend process killed by Linux OOM killer after ~49 hours of uptime. Service automatically restarted by Railway (ON_FAILURE policy). No data loss — scraper resumed from where it left off.

## Summary

The FastAPI backend running on Railway (4GB memory limit) was OOM-killed by the Linux kernel after ~49 hours and ~32 scrape cycles. CPython's pymalloc allocator retained freed memory in fragmented arenas instead of returning it to the OS. Large transient allocations from API responses (5000-row JSONB queries) and subprocess stderr pipes (23-minute Apple/Playwright scrapes) compounded the fragmentation, ratcheting RSS upward ~80MB/hour until hitting the 4GB limit.

The process received SIGKILL — no application-level error logs were produced.

## Timeline

| Time (UTC)            | Event |
|-----------------------|-------|
| 2026-04-07 04:56      | Deployment `9113980a` started (PR #41 pool exhaustion fix) |
| 2026-04-07 05:07      | First scrape cycle begins (apple, google, microsoft) |
| 2026-04-07 — 2026-04-09 | ~32 scrape cycles complete successfully, hourly |
| 2026-04-09 05:49      | Last successful cycle completes: "Scrape cycle complete, waiting 1h" |
| 2026-04-09 06:02      | **Server restarts** — "Started server process [1]" with no preceding error |
| 2026-04-09 06:02      | Auto-scraper resumes, all subsequent cycles succeed |

Gap between 05:49 and 06:02 (13 minutes into 1-hour sleep) with no error/warning logs = SIGKILL from Linux OOM killer.

## Root Cause

### CPython pymalloc Memory Fragmentation

CPython's pymalloc allocator manages memory in 256KB arenas subdivided into fixed-size pools. Once any object in an arena remains alive, the entire arena stays resident — even if 99% of its objects are freed. Over many allocation/deallocation cycles, this fragmentation prevents freed memory from returning to the OS.

**This was a known issue.** PR #35 (2026-04-04) observed "baseline ratcheted up ~20 MB/hour" and reverted `PYTHONMALLOC=malloc` which made it worse. The underlying fragmentation was never addressed.

### Contributing Factors

#### 1. Large API Responses (~150MB peak)

`GET /api/jobs?status=OPEN&company=apple&limit=5000` used `SELECT *`, returning full `details` JSONB (5-20KB per row) and `ai_metadata`. With 5000 rows per company and 3 concurrent requests from the frontend:

- `cursor.fetchall()` loads all rows into Python memory
- psycopg2 `RealDictCursor` auto-parses JSONB into Python dicts
- `_row_to_job_dict()` re-serializes via `json.dumps()` (doubling memory)
- FastAPI constructs 5000 Pydantic models per response

Peak: ~50MB per request, ~150MB for 3 concurrent company requests. All freed after response, but arenas remain fragmented.

#### 2. Unbounded Subprocess stderr Buffering

`scraper_runner.py` used `process.communicate()` which reads ALL stderr into a single bytes object before truncating to 10KB. Apple's 23-minute Playwright scrape produces substantial logging output. The large temporary allocation fragments pymalloc arenas.

#### 3. No Memory Reclamation

No `gc.collect()` or `malloc_trim()` calls between cycles. Freed memory accumulated in pymalloc's internal free lists without ever being returned to the OS.

### Math

~80MB/hour growth x 49 hours = ~3.9GB. Adding ~200MB baseline = ~4.1GB, exceeding the 4GB Railway limit.

## Fixes Applied (PR #45)

### 1. gc.collect() + malloc_trim() After Each Scrape Cycle

**File:** `src/backend/api/services/auto_scraper.py`

After each completed cycle, call `gc.collect()` to break reference cycles, then `ctypes.CDLL("libc.so.6").malloc_trim(0)` to force glibc to return freed heap pages to the OS. Silently no-ops on macOS (dev environment).

### 2. Streaming stderr Reader

**File:** `src/backend/api/services/scraper_runner.py`

Replaced `process.communicate()` with `_read_stderr_tail()` — an incremental reader that keeps only the last 10KB in a ring buffer. Memory is capped at 20KB regardless of how much stderr the scraper produces.

### 3. Trimmed JSONB in List Endpoint

**File:** `src/backend/api/services/database.py`

Replaced `SELECT *` in `get_jobs()` with explicit column selection. For `details`, uses PostgreSQL `jsonb_build_object()` to return only the two fields the frontend transformer actually uses (`experience_level`, `is_remote_eligible`). Returns empty `ai_metadata`.

Reduces per-row size from ~10KB to ~500 bytes. Peak memory for 3 concurrent requests drops from ~150MB to ~7.5MB.

The detail endpoint (`GET /api/jobs/{id}`) still returns full JSONB.

## Files Changed

- `src/backend/api/services/auto_scraper.py` — gc.collect + malloc_trim after each cycle
- `src/backend/api/services/scraper_runner.py` — Streaming stderr tail reader
- `src/backend/api/services/database.py` — Explicit column selection with minimal details
- `src/backend/api/tests/test_scraper_runner.py` — Updated mocks for new stderr reading pattern
- `src/backend/api/tests/test_jobs_router.py` — Tests for trimmed details and full detail endpoint

## Verification

- All 69 backend tests pass
- Monitor Railway memory metrics over 48+ hours post-deploy to confirm RSS stabilizes

## Lessons Learned

1. **CPython doesn't return freed memory to the OS.** pymalloc arena fragmentation is a well-documented behavior. Long-running Python processes that allocate/free large objects will ratchet up RSS. Use `gc.collect()` + `malloc_trim()` periodically, especially after batch workloads.

2. **Don't use `SELECT *` for large result sets with JSONB columns.** A 5-20KB JSONB blob x 5000 rows = 50-100MB per query. If the consumer only needs 2 fields, extract them in SQL.

3. **`communicate()` buffers all pipe output.** For long-running subprocesses, read pipes incrementally to avoid large transient allocations.

4. **SIGKILL from OOM leaves no logs.** When a process dies with zero error output, suspect OOM. Check container memory limits and `dmesg` (if accessible) for OOM killer messages.

5. **Memory issues compound over time.** The 20MB/hour ratcheting from PR #35 was dismissed after reverting `PYTHONMALLOC=malloc`. The symptom slowed but never stopped — it just took 49 hours instead of 12 to hit the limit.
