# Scraper PID/Thread Exhaustion Fix Plan

## Context

The Railway-hosted FastAPI backend at `src/backend/api/main.py` runs three scrapers (apple, google, microsoft) hourly via `auto_scraper_loop` (`src/backend/api/services/auto_scraper.py`). Since 2026-05-02 ~05:49 UTC every scrape cycle has been failing at `BrowserType.launch` with `Connection closed while reading from the driver`. Underlying chromium stderr shows `pthread_create: Resource temporarily unavailable (11)` — the kernel/cgroup is refusing to spawn threads. Even the Playwright Node driver process logs the same error.

Last container start was 2026-04-22 03:30 UTC (deploy `b0b36aa1`, commit `ca69f55`). The container has been running ~13 days. No deploy in between (the 2026-04-29 frontend-only commit was SKIPPED by Railway because watch patterns are `/src/backend/**` and `/scripts/**`). Upstream sites (Google Careers, Apple Jobs, Microsoft Careers) all load normally via Playwright MCP — the failure is on our side, before any URL is requested. Upstream-change hypothesis ruled out.

**Root cause:** process/thread accumulation in the container hitting cgroup `pids.max` (or equivalent thread limit). Two compounding factors:

1. **No init system in the container.** `src/backend/Dockerfile` runs `CMD ["uvicorn", ...]` directly, making uvicorn PID 1. Uvicorn does not reap orphan child processes. When scraper subprocesses exit, any leaked playwright/chromium grandchildren get reparented to uvicorn → become zombies (`<defunct>`) → consume PID slots in the cgroup forever.
2. **Partial-init cleanup gap in `BaseScraper.initialize_browser()`** (`scripts/shared/base_scraper.py:143-163`). Python's `async with` calls `__aenter__`; if `__aenter__` raises, `__aexit__` is **never** called. `initialize_browser` does `self.playwright = await async_playwright().start()` first, then `self.browser = await self.playwright.chromium.launch(...)`. If `chromium.launch()` raises, `self.playwright.stop()` is never called → playwright Node driver process is leaked.

After ~10 days × hourly cycles, accumulated zombies push the container to its PID limit, after which every chromium launch fails because chromium needs to spawn many helper threads.

**Goal:** Three small, sequential, independently committable units that (1) add `tini` as PID 1 so zombies are reaped, (2) make `initialize_browser()` self-cleaning on partial failure so orphans are never created, and (3) document the incident. PR merge triggers a Railway redeploy — the container restart drains the leaked PIDs and clears the live outage immediately. The defensive fixes prevent recurrence.

**Deployment:** Backend runs on **Railway** (auto-deploys from GitHub `main`). Railway watch patterns include `/src/backend/**` and `/scripts/**`, both of which match this PR. Frontend is unchanged. No DB schema change. No HTTP/Redux contract change.

**Execution model:** Sequential, one commit per unit. Backend container first (load-bearing fix), then data-collection layer (defensive fix), then docs.

---

## Shared Contracts (frozen — all units must preserve these)

These are the runtime invariants the three units share. They are not changing in this PR; each unit must verify it does not break them.

### Scraper subprocess invocation

`src/backend/api/services/scraper_runner.py` invokes scrapers as:

```
${SCRAPER_PYTHON_PATH:-python3} ${SCRAPER_SCRIPTS_PATH:-/app/scripts}/run_scraper.py \
    --company <apple|google|microsoft> --env <local|qa|prod> \
    --db-url $DATABASE_URL --incremental [--detail-scrape]
```

- The subprocess MUST exit cleanly on success (rc=0) and on internal failure (rc=non-zero) without leaking child processes back to PID 1.
- `scripts/run_scraper.py:208` enters `async with scraper:` which triggers `BaseScraper.__aenter__` → `initialize_browser`. If `__aenter__` raises, `__aexit__` is NOT called by the language — the unit-2 fix lives inside `initialize_browser` itself, not at the `async with` site.
- The runner reads stderr with the streaming ring buffer added in PR #45 (10KB tail). Do not regress this.

### `auto_scraper` hourly loop semantics

`src/backend/api/services/auto_scraper.py` runs `auto_scraper_loop` as a background asyncio task launched in the FastAPI lifespan (`src/backend/api/main.py:75-86`):

- One cycle per `SCRAPER_INTERVAL_HOURS` (default `1`).
- Each cycle iterates `SCRAPER_COMPANIES` (default `apple,google,microsoft`) sequentially.
- A failure for one company MUST NOT stop the cycle for the next company. (Existing try/except around each per-company invocation; do not change this.)
- After each cycle: `gc.collect()` + `malloc_trim(0)` (added in PR #45 for the OOM fix). Preserve.

### Railway watch patterns

`railway.json` (or the Railway UI service config) currently triggers a rebuild when files match `/src/backend/**` or `/scripts/**`. Both Unit 1 (`src/backend/Dockerfile`) and Unit 2 (`scripts/shared/base_scraper.py`) match. Unit 3 (`docs/incidents/...`) does NOT match — that is intentional; it must not trigger a wasteful rebuild.

---

## Work Units

### Unit 1 — Backend container: install tini, set as ENTRYPOINT

**Status:** DONE
**Prerequisites:** none — start immediately. This is the load-bearing fix; merging it alone resolves the live outage on next deploy.

**Owned files (edit):**
- `src/backend/Dockerfile`

**Shared-file edits:** none

**Change summary:**

Install the `tini` package via apt in the existing `python:3.13-slim` layer, then set it as the container's ENTRYPOINT so it runs as PID 1 and the existing `uvicorn` `CMD` runs as its child. tini forwards signals (clean SIGTERM passthrough on Railway redeploys) and reaps orphan zombies (`SIGCHLD` → `wait()`).

Sketch (final form to be authored in implementation):

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*
# ... existing layers unchanged ...
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

The `tini` install layer should sit near the top (alongside or just after the `playwright install --with-deps chromium` line that already does apt work) to maximize Docker layer-cache reuse with the existing system-deps layer.

**Done when:**
- `docker build -f src/backend/Dockerfile -t jvn-tini-test .` succeeds locally.
- `docker run --rm --entrypoint /bin/sh jvn-tini-test -c "/usr/bin/tini --version"` prints a version string.
- `docker run --rm jvn-tini-test ps -o pid,comm` (with a one-shot override) shows `tini` as PID 1 and `uvicorn` as its child.
- Existing backend test suite still green: `cd src/backend && pytest -q`.
- Commit message references the incident: `fix(backend): add tini as PID 1 to reap orphan scraper subprocesses`.

---

### Unit 2 — Scraper base class: defensive cleanup in `initialize_browser`

**Status:** DONE
**Prerequisites:** Unit 1 merged (tini is the load-bearing fix; this hardens against future leaks). Logically independent of Unit 1, but commit Unit 1 first so the live outage is resolved before this lands.

**Owned files (edit):**
- `scripts/shared/base_scraper.py` (lines 143-163, `initialize_browser`)

**Shared-file edits:** none (no callers change; the public coroutine signature is unchanged)

**Change summary:**

`initialize_browser` runs three steps in sequence: `playwright.start()` → `chromium.launch()` → `browser.new_context()`. Today, if step 2 or 3 raises, the partially-allocated state from earlier steps is leaked because `__aexit__` is never called when `__aenter__` raises.

Wrap each subsequent step in a `try` whose `except BaseException:` clause tears down the prior step (close browser if context creation fails; stop playwright if browser launch fails) and re-raises. After cleanup, set the corresponding attribute to `None` so a later `close_browser()` call (if any) is a no-op.

Sketch (final form to be authored in implementation):

```python
async def initialize_browser(self):
    logger.info("Initializing browser...")
    self.playwright = await async_playwright().start()
    try:
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        try:
            self.context = await self.browser.new_context(
                viewport=BROWSER_CONFIG["viewport"],
                user_agent=BROWSER_CONFIG["user_agent"],
                locale=BROWSER_CONFIG["locale"],
            )
        except BaseException:
            await self.browser.close()
            self.browser = None
            raise
    except BaseException:
        await self.playwright.stop()
        self.playwright = None
        raise
    logger.info("Browser initialized successfully")
```

Use `BaseException` (not `Exception`) so `asyncio.CancelledError` and `KeyboardInterrupt` also trigger cleanup — tini will reap anything we miss, but defense-in-depth.

`close_browser` already null-checks (`if self.context: ...`), so leaving these attributes as `None` after a partial-init failure is safe for any code path that subsequently calls `__aexit__` (it won't).

**Done when:**
- `cd scripts && pytest tests/unit -k base_scraper -q` green (existing tests still pass — no public API change).
- New unit test added under `scripts/tests/unit/` (e.g. `test_base_scraper_initialize.py`) that:
  - Mocks `async_playwright().start()` to return an object whose `.chromium.launch()` raises, and asserts that `playwright.stop()` was awaited and `self.playwright` is `None`.
  - Mocks `chromium.launch()` to return a browser whose `.new_context()` raises, and asserts that `browser.close()` was awaited, `self.browser` is `None`, AND `playwright.stop()` was awaited (outer `except`).
  - Happy path: all three steps succeed, no cleanup methods called, attributes populated.
- `cd src/backend && pytest -q` still green (no backend-side caller change, but sanity check).
- Commit message: `fix(scrapers): tear down partial state when initialize_browser raises`.

---

### Unit 3 — Incident documentation

**Status:** DONE
**Prerequisites:** Units 1 and 2 merged (so the doc can reference the actual fix as deployed and link the resolution time).

**Owned files (create):**
- `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md`

**Shared-file edits:** none

**Change summary:**

Add a new incident doc matching the format of `docs/incidents/2026-04-09-oom-memory-fragmentation.md` and `docs/incidents/2026-04-15-preview-deploy-auth-unreachable.md`. Required sections (mirroring the 2026-04-09 doc):

- `# Incident: Scraper Outage from PID/Thread Exhaustion` (H1)
- **Date / Severity / Impact** block at top.
- **Summary** — one paragraph: long-running container hit cgroup `pids.max` after ~13 days because uvicorn (no init) cannot reap zombies and `initialize_browser` leaked playwright drivers on partial-init failures.
- **Timeline** — Markdown table mirroring the 2026-04-09 layout, key rows: 2026-04-22 03:30 deploy `b0b36aa1` starts, 2026-05-01 ~17:14 first transient nav failures, 2026-05-02 ~05:49 first `pthread EAGAIN`, 2026-05-02 → 2026-05-05 every cycle fails identically, 2026-05-05 fix deployed and outage clears on container restart.
- **Root Cause** — two subsections: "No init system in container" and "Partial-init cleanup gap in `BaseScraper.initialize_browser`". Quote the chromium stderr `pthread_create: Resource temporarily unavailable (11)` and the Playwright `BrowserType.launch: Connection closed while reading from the driver`. Explain reparenting → zombie → cgroup `pids.max` chain.
- **Fixes Applied** — three subsections matching the three units of this PR (tini ENTRYPOINT, defensive `initialize_browser`, this doc).
- **Files Changed** — bullet list: `src/backend/Dockerfile`, `scripts/shared/base_scraper.py`, `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md`.
- **Verification** — local `docker run` ps check that tini is PID 1; Railway log filter for `pthread_create` returning zero matches in the new deploy; 24-48 hour soak.
- **Lessons Learned** — at minimum: (1) Always use an init in containers that spawn subprocesses. (2) Async context managers don't run `__aexit__` if `__aenter__` raises — multi-step init must self-clean. (3) Long-running-container failure modes compound silently; add cgroup PID metrics if Railway exposes them.
- **Cross-reference** — explicit link to `docs/incidents/2026-04-09-oom-memory-fragmentation.md`. Both incidents share the long-running-container failure pattern but differ in mechanism (memory fragmentation vs PID/thread exhaustion). Note that the 2026-04-09 fixes (gc.collect + malloc_trim, stderr ring buffer) remain valid and address a different axis.

**Done when:**
- File exists at `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md`.
- Section structure matches the 2026-04-09 incident doc (Date / Severity / Impact / Summary / Timeline / Root Cause / Fixes Applied / Files Changed / Verification / Lessons Learned).
- Cross-link to 2026-04-09 incident is present and correct (relative path: `./2026-04-09-oom-memory-fragmentation.md`).
- `git diff --stat` for this commit shows ONLY the new docs file (no code changes leak in — Railway watch patterns will then correctly skip a redeploy for this commit).
- Commit message: `docs(incidents): document 2026-05-05 scraper pthread exhaustion`.

---

## Critical files

| File | Role |
|---|---|
| `src/backend/Dockerfile` | Container build. Currently runs uvicorn as PID 1 with no init reaper. Unit 1 adds tini. |
| `scripts/shared/base_scraper.py` | Async context manager for the Playwright browser lifecycle (`__aenter__` / `initialize_browser` / `close_browser`). Lines 143-163 are the partial-init leak site Unit 2 fixes. |
| `src/backend/api/services/auto_scraper.py` | Hourly cycle driver; invariant preserved across this PR (no edits). |
| `src/backend/api/services/scraper_runner.py` | Subprocess wrapper around `run_scraper.py`; invariant preserved (no edits). |
| `docs/incidents/2026-04-09-oom-memory-fragmentation.md` | Format exemplar and cross-reference target for the new incident doc Unit 3 creates. |

---

## Non-goals

- **Do not refactor `auto_scraper` retry/backoff.** The current "log and continue to next company" behavior is correct; per-cycle retry of failed companies is out of scope.
- **Do not change the scraper interval** (`SCRAPER_INTERVAL_HOURS`). Hourly cadence is unchanged.
- **Do not re-address the 2026-04-09 OOM root cause.** That incident's fixes (gc.collect + malloc_trim, streaming stderr reader, trimmed JSONB) remain in place. This PR is strictly additive on a different axis (PIDs, not memory).
- **Do not add cgroup PID metrics / monitoring** in this PR. Worth doing in a follow-up; out of scope here so the live outage fix ships fast.
- **Do not change Railway watch patterns.** Existing patterns (`/src/backend/**`, `/scripts/**`) correctly trigger redeploy for Units 1 and 2 and correctly skip for Unit 3.
- **Do not refactor `__aenter__` / `__aexit__` to a custom context manager protocol.** The fix lives entirely inside `initialize_browser`; `__aenter__` stays a one-line delegator.
- **Do not switch base image** away from `python:3.13-slim`. tini is available via apt on slim Debian; no image change needed.
