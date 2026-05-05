# Incident: Scraper Outage from PID/Thread Exhaustion

**Date:** 2026-05-02 05:49 UTC (first hard failure), 2026-05-05 (root cause identified and fix deployed)
**Severity:** High
**Impact:** All hourly scrape cycles for apple, google, and microsoft failed for ~3 days. Every `BrowserType.launch` aborted before any URL was requested, so no new jobs were ingested and no jobs were updated. Existing data in `job_listings_prod` was unaffected (the incremental safety guard from the 2026-03-29 incident prevented mass closure on 0-job runs). Outage cleared on the next Railway redeploy because the container restart drained the leaked PIDs.

## Summary

The Railway-hosted backend container ran continuously for ~13 days from deploy `b0b36aa1` (2026-04-22 03:30 UTC) without an intervening redeploy. Two compounding leaks accumulated over that window: (1) uvicorn ran as PID 1 with no init system, so any playwright/chromium grandchild reparented to it after a scraper subprocess exited became a zombie that consumed a slot in the cgroup `pids.max` budget forever; and (2) `BaseScraper.initialize_browser` started the playwright driver before launching chromium, so any failure inside `chromium.launch()` or `browser.new_context()` left the playwright Node driver process orphaned because Python does not call `__aexit__` when `__aenter__` raises. After ~216 hourly cycles the container hit its thread/PID ceiling, after which every chromium launch aborted with `pthread_create: Resource temporarily unavailable (11)` and surfaced to Playwright as `BrowserType.launch: Connection closed while reading from the driver`.

## Timeline

| Time (UTC)            | Event |
|-----------------------|-------|
| 2026-04-22 03:30      | Deploy `b0b36aa1` (commit `ca69f55`) starts. Container runs uvicorn as PID 1, no init reaper. |
| 2026-04-22 — 2026-05-01 | ~216 hourly scrape cycles complete successfully (apple, google, microsoft). |
| 2026-04-29            | Frontend-only commit `9d2ef7f` lands on `main`. Railway watch patterns (`/src/backend/**`, `/scripts/**`) do NOT match — Railway logs `No changes to watched files`, deploy SKIPPED. Container keeps running. |
| 2026-05-01 ~17:14     | First transient failures appear — chromium still launches, but `page.goto()` starts intermittently failing on heavier pages. Cycles still partially succeed. |
| 2026-05-02 ~05:49     | First hard `BrowserType.launch` failure. Chromium stderr shows `pthread_create: Resource temporarily unavailable (11)`. Playwright reports `Connection closed while reading from the driver`. |
| 2026-05-02 — 2026-05-05 | Every hourly cycle fails identically across all three companies. Per-company try/except keeps the loop alive; incremental safety guard (PR #25) prevents mass closure of existing jobs. |
| 2026-05-05            | Unit 1 (tini ENTRYPOINT) committed (`6ca8e31`). |
| 2026-05-05            | Unit 2 (defensive `initialize_browser`) committed (`079df2c`). |
| 2026-05-05            | PR merged to `main`. Railway redeploys. Container restart drains all leaked PIDs; first post-deploy cycle succeeds. Outage cleared. |

## Root Cause

Two independent defects, each individually survivable, compounded over ~13 days of uninterrupted container uptime to exhaust the cgroup process/thread budget.

### No init system in container

`src/backend/Dockerfile` previously ended with:

```dockerfile
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Uvicorn ran as PID 1. The Linux kernel gives PID 1 two responsibilities the rest of the process tree relies on: forwarding signals to children, and reaping orphans (calling `wait()` on any process whose parent has died, after the kernel reparents it to PID 1). Uvicorn does neither — it is an HTTP server, not an init.

The hourly auto-scraper spawns scraper subprocesses via `scripts/run_scraper.py`, which in turn launch the Playwright Node driver and a chromium process tree. When a scraper subprocess exits — cleanly or otherwise — any helper process whose parent was the scraper subprocess gets reparented to PID 1 (uvicorn). Uvicorn never calls `wait()` on them, so they sit in the process table as zombies (`<defunct>`) consuming PID slots. Zombies hold no memory of consequence, but each one occupies one entry against the cgroup `pids.max` budget.

After ~13 days × hourly cycles × per-cycle leak, accumulated zombies pushed the container near its PID ceiling. Chromium needs to spawn many helper threads on launch (renderer, GPU, network, audio, utility); once the budget is exhausted, the kernel refuses new threads. The chromium stderr shows it directly:

```
pthread_create: Resource temporarily unavailable (11)
```

`EAGAIN (11)` from `pthread_create` is the kernel saying "you are out of thread/process slots, try again later." The Playwright driver loses its connection to the dying chromium process and surfaces it to the application as:

```
BrowserType.launch: Connection closed while reading from the driver
```

### Partial-init cleanup gap in `BaseScraper.initialize_browser`

`scripts/shared/base_scraper.py` exposes the browser as an async context manager. The previous `initialize_browser` ran three steps in sequence:

```python
async def initialize_browser(self):
    self.playwright = await async_playwright().start()
    self.browser = await self.playwright.chromium.launch(...)
    self.context = await self.browser.new_context(...)
```

`scripts/run_scraper.py:208` enters this with `async with scraper:`. The Python language guarantees that `__aexit__` is **not** called if `__aenter__` raises — that is the language contract, not a Playwright quirk. So if `chromium.launch()` raised (which is exactly what was happening once the container started failing on PID exhaustion), the line `await self.playwright.stop()` never ran, and the playwright Node driver process was leaked.

Each hourly cycle that hit a `chromium.launch` failure leaked one playwright driver. Combined with the zombies from defect 1, this accelerated the climb toward `pids.max` once symptoms began.

This defect was latent for the entire ~13-day window — it only mattered once the container started failing, but then it made every subsequent cycle worse instead of merely failing in place.

## Fixes Applied

Three units, one commit each, sequenced so the load-bearing fix lands first.

### Unit 1 — `tini` as PID 1 in the backend container (commit `6ca8e31`)

**File:** `src/backend/Dockerfile`

Installed `tini` via apt and set it as the container's `ENTRYPOINT`, with the existing `uvicorn` `CMD` running as its child. tini is a minimal init that forwards signals (clean SIGTERM passthrough on Railway redeploys) and reaps orphan zombies (`SIGCHLD` → `wait()`). Diff applied:

```diff
+# Install tini as PID 1 init/reaper. Without this, uvicorn runs as PID 1 and
+# cannot reap orphan playwright/chromium grandchildren from scraper subprocesses;
+# zombies accumulate against cgroup pids.max and eventually break thread spawn.
+# See docs/incidents/2026-05-05-scraper-pthread-exhaustion.md.
+RUN apt-get update \
+    && apt-get install -y --no-install-recommends tini \
+    && rm -rf /var/lib/apt/lists/*
@@
+ENTRYPOINT ["/usr/bin/tini", "--"]
 CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

This is the load-bearing fix. Merging it triggered the Railway redeploy whose container restart drained the leaked PIDs and cleared the live outage immediately.

### Unit 2 — Defensive cleanup in `initialize_browser` (commit `079df2c`)

**File:** `scripts/shared/base_scraper.py`

Wrapped each step after `playwright.start()` in a `try` whose `except BaseException:` clause tears down the previously-allocated state and re-raises. After cleanup, the corresponding attribute is set to `None` so any subsequent `close_browser()` call (which already null-checks) is a safe no-op. `BaseException` is used (not `Exception`) so `asyncio.CancelledError` and `KeyboardInterrupt` also trigger cleanup — tini will reap anything we miss, but defense-in-depth.

Added `scripts/tests/unit/test_base_scraper_initialize.py` covering three cases: `chromium.launch()` failure (playwright torn down, attribute is `None`), `browser.new_context()` failure (browser closed AND playwright torn down, both attributes are `None`), and the happy path (no cleanup invoked, all three attributes populated).

This is the defense-in-depth fix. With tini in place, leaked driver processes would now be reaped on subprocess exit anyway, but self-cleaning init is the right contract regardless of what runs as PID 1.

### Unit 3 — This incident document

**File:** `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md`

Documents the failure mode, root cause, and the two fixes above. No code change. Railway watch patterns (`/src/backend/**`, `/scripts/**`) do not match `docs/`, so this commit correctly does NOT trigger a wasteful redeploy.

## Files Changed

- `src/backend/Dockerfile` — install `tini` and set as `ENTRYPOINT` (Unit 1)
- `scripts/shared/base_scraper.py` — defensive cleanup in `initialize_browser` (Unit 2)
- `scripts/tests/unit/test_base_scraper_initialize.py` — new unit tests for the three init paths (Unit 2)
- `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md` — this document (Unit 3)

## Verification

- **Local build** — `docker build -f src/backend/Dockerfile -t jvn-tini-test .` succeeds.
- **tini is PID 1** — `docker run --rm jvn-tini-test ps -o pid,comm` shows `1 tini` and `uvicorn` as its child.
- **tini binary present** — `docker run --rm --entrypoint /bin/sh jvn-tini-test -c "/usr/bin/tini --version"` prints a version string.
- **Backend tests** — `cd src/backend && pytest -q` green.
- **Scraper tests** — `cd scripts && pytest tests/unit -k base_scraper -q` green; the three new init tests pass.
- **Railway log filter** — after the redeploy, search Railway logs for `pthread_create` returns zero matches across the next several hourly cycles.
- **24–48 hour soak** — monitor Railway logs for one to two days; every hourly cycle should report success for all three companies. (At hourly cadence, that is 24–48 successful cycles.)

## Lessons Learned

1. **Always use an init in containers that spawn subprocesses.** Application servers are not init systems. Any container whose application fork/execs anything (scrapers, ffmpeg, image processors, headless browsers, language workers) will leak zombies against the cgroup PID budget unless something reaps them. `tini` is one apt install and one `ENTRYPOINT` line — there is no excuse to skip it.
2. **Async context managers do not run `__aexit__` if `__aenter__` raises.** This is the Python language contract, not a library quirk. Any multi-step `__aenter__` (or `initialize_*` it delegates to) must self-clean partial state. Using `BaseException` rather than `Exception` keeps cancellation paths covered too.
3. **Long-running-container failure modes compound silently.** ~13 days of "successful" cycles hid two cooperating leaks. The 2026-04-09 incident exposed the same shape (49 hours of fragmenting memory). Steady-state success metrics are not enough — drift metrics matter. As a follow-up: surface cgroup PID usage if Railway exposes it, the same way memory RSS is already trended.
4. **Skipped deploys extend container uptime.** The 2026-04-29 frontend-only commit did not match `/src/backend/**` or `/scripts/**` watch patterns, so Railway correctly skipped the rebuild — but that meant the container kept accumulating leaks for an extra week. This is the right behavior (no wasted rebuilds), but it is worth knowing that long stretches without backend deploys are exactly when latent leaks surface.

## Related

See [`./2026-04-09-oom-memory-fragmentation.md`](./2026-04-09-oom-memory-fragmentation.md). Both incidents are instances of the same higher-order failure pattern — long-running container, slow accumulation, eventual hard ceiling — but the mechanisms are independent: that one was CPython arena fragmentation ratcheting RSS toward the 4GB memory limit; this one is unreaped zombies and leaked playwright drivers ratcheting against the cgroup `pids.max` thread/PID limit. The fixes from PR #45 (`gc.collect()` + `malloc_trim()` after each cycle, streaming stderr ring buffer, trimmed JSONB in the list endpoint) remain valid and address the memory axis; nothing in this PR replaces or reverts them. Together the two PRs defend the two distinct ratcheting axes a long-lived Python container has.
