# Scraper Pthread Exhaustion Fix PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-05-05 — Review pass 1

**Diff scope:** `git diff origin/main...HEAD`
- `src/backend/Dockerfile` (Unit 1)
- `scripts/shared/base_scraper.py` (Unit 2)
- `scripts/tests/unit/test_base_scraper_initialize.py` (Unit 2, new file)
- `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md` (Unit 3, new file)
- `docs/implementations/scraperPthreadExhaustionFix/PLAN.md` (planning artifact)
- `docs/implementations/scraperPthreadExhaustionFix/REVIEW_AUDIT.md` (this file)

**Verifier dispatch:**
- railway-prod-verifier: dispatched (Dockerfile + scraper changes affect Railway deploy)
- vercel-prod-verifier: not dispatched (no matching diff signal)
- postgres-prod-verifier: not dispatched (no matching diff signal)

### Code-review findings

**Critical:**
- `scripts/shared/base_scraper.py:171-178` — `await playwright.stop()` and `await browser.close()` inside `except BaseException` blocks can themselves raise; that secondary exception overwrites the original `chromium.launch` failure, AND the `self.X = None` line never runs (so `close_browser` could double-stop). (silent-failure-hunter)
- `scripts/shared/base_scraper.py:175-178` — `playwright.stop()` can hang under PID exhaustion (no timeout). Loud failure becomes silent stall. (silent-failure-hunter)
- `scripts/tests/unit/test_base_scraper_initialize.py` — No `asyncio.CancelledError` coverage despite `BaseException` being load-bearing per the docstring. A future "tighten to `except Exception`" refactor would silently re-introduce the leak under cancellation. (pr-test-analyzer)
- `scripts/tests/unit/test_base_scraper_initialize.py` — No tests for "cleanup handler itself raises" — pinning that contract will likely surface the `= None` ordering bug above. (pr-test-analyzer)

**Important:**
- `scripts/shared/base_scraper.py:171-178` — Cancellation race: an inner await inside `except BaseException` can itself be cancelled, skipping `self.X = None`. Move attribute-nulling into `finally`. (silent-failure-hunter)
- `scripts/tests/unit/test_base_scraper_initialize.py` — No test asserting `__aexit__` is NOT called when `__aenter__` raises (the language guarantee the whole architecture depends on). (pr-test-analyzer)
- `src/backend/Dockerfile` — Unit 1 has no automated regression guard. Future Dockerfile edit could remove tini or override ENTRYPOINT silently. Add a CI Docker build + `tini --version` step OR a static text assertion in pytest. (pr-test-analyzer)

**Suggestion / Nit:**
- `scripts/shared/base_scraper.py:182-190` (`close_browser`) — Same partial-cleanup bug shape this PR fixed for `initialize_browser`, in the *normal* shutdown path. (silent-failure-hunter S1)
- Comment style: em-dash and other minor wording polish. (comment-analyzer S1, S2, N4)

### Production-environment findings

**Critical:**
- **Live outage was already resolved by an unrelated redeploy.** Railway deployment `9c9251cd` went live at 2026-05-05T14:36:53Z, triggered by PR #95 (`docs(claude): weekly CLAUDE.md audit`) editing `src/backend/CLAUDE.md` — which matches the watch pattern `/src/backend/**`. The PR #95 redeploy restarted the container, draining the leaked PIDs from the b0b36aa1 deployment. The acute outage is no longer active. **This PR's value is now strictly preventive (no recurrence after the next ~13 days of uptime), not curative.** Incident doc and PLAN narrative must be updated. (railway-prod-verifier)

**Important:**
- **Live container does not yet have tini as PID 1.** The 9c9251cd deployment was built from commit `42b081b2` (before Unit 1's Dockerfile change). Logs at 14:39:50Z confirm `Started server process [1]` for uvicorn directly. Merging this PR will trigger a Railway redeploy (watch patterns `/src/backend/**` and `/scripts/**` both match this PR's diff), which will then deploy the tini'd image. (railway-prod-verifier)
- Cannot verify the original `pthread_create` log evidence; deployment b0b36aa1 is in `REMOVED` state. PLAN's prior captures are the canonical record. (railway-prod-verifier)

**Suggestion:**
- After merge, verify the new `apt-get install tini` layer succeeds in the Railway build log (Debian trixie ships tini at `/usr/bin/tini`). (railway-prod-verifier)
- Out of scope: add `healthcheckPath: /health` to Railway service config; add post-deploy smoke test asserting tini is PID 1. (railway-prod-verifier)

**Could not verify:**
- railway-prod-verifier: live `pthread_create EAGAIN` errors on b0b36aa1 (deployment REMOVED, logs unavailable).

### Deferred (not fixing this pass)

- silent-failure I2: `logger.info` after init outside try — extremely rare path, not worth complexity.
- silent-failure S1: `close_browser` has same bug — fix in this pass (out of strict PR scope but right next to the code we're touching, and the railway verifier's "preventive value" framing means we should harden the normal shutdown path too while we're here).
- pr-test-analyzer S2 (`playwright.start()` failure test): low value, defer.
- pr-test-analyzer S3 (SIGTERM forwarding test): defer; would require a Docker-in-CI integration test.
- All comment-analyzer suggestions: cosmetic, defer.

### Implementation applied (pass 1)

Four commits on `fix/scraper-pthread-exhaustion`:

- **`e39b58e`** — `Review pass 1: harden initialize_browser/close_browser cleanup`
  - File: `scripts/shared/base_scraper.py`
  - Wrapped each cleanup await (`browser.close`, `playwright.stop`) in `try/except BaseException` with error-level logging so a secondary failure during teardown no longer overwrites the original exception.
  - Bounded each cleanup await with `asyncio.wait_for` timeouts: 5s `context.close`, 10s `browser.close`, 15s `playwright.stop`.
  - Moved attribute nulling (`self.browser = None`, `self.playwright = None`) into `finally` so partial state is dropped even when cleanup raises or hangs.
  - Same hardening applied to `close_browser` so the normal shutdown path tolerates per-step failures and continues teardown (covers silent-failure S1, deferred-but-fixed).
  - Updated `initialize_browser` docstring to document cleanup-failure handling and timeouts.

- **`3a48978`** — `Review pass 1: pin BaseException, cleanup-failure, async-with contracts`
  - File: `scripts/tests/unit/test_base_scraper_initialize.py` (10 tests, was 3)
  - Parametrized launch and new_context failure paths over `RuntimeError` AND `asyncio.CancelledError` (covers C1).
  - Added 3 cleanup-handler-raises tests: launch + stop-also-raises, new_context + close-also-raises, and stop-hangs (bounded by `asyncio.wait_for(_run(), timeout=20.0)` so a regression doesn't hang CI). Each asserts original exception propagates, attribute nulling still ran, and cleanup failure was logged at error level via `caplog` (covers C2, I1).
  - Added async-with propagation test asserting `__aexit__` is NOT called when `__aenter__` raises (covers I2).
  - Added `close_browser` after partial-init safety test (covers S1).

- **`2a0b8b0`** — `Review pass 1: incident doc — outage cleared by unrelated redeploy`
  - File: `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md`
  - Updated Impact line to reflect that outage cleared at 2026-05-05T14:36:53Z via the unrelated PR #95 redeploy (`docs(claude): weekly CLAUDE.md audit`, commit `42b081b2`), not via this PR.
  - Added Timeline row for the 14:36:53Z incidental resolution.
  - Reframed Fixes Applied preamble: both code fixes are now strictly preventive, installing the load-bearing init reaper and defensive cleanup before the next ~13-day buildup can recur.
  - Updated Unit 1 narrative so it no longer claims merging this PR cleared the outage.

---

## 2026-05-05 — Review pass 2

**Diff scope:** `git diff origin/main...HEAD` — same files as pass 1 plus:
- `src/backend/api/tests/test_dockerfile_tini_guard.py` (new file from pass 1 fix)
- pass-1 commits significantly expanded `scripts/shared/base_scraper.py` and `scripts/tests/unit/test_base_scraper_initialize.py`

**Verifier dispatch:**
- railway-prod-verifier: dispatched (Dockerfile + scraper changes still in scope)
- vercel-prod-verifier: not dispatched (no matching diff signal)
- postgres-prod-verifier: not dispatched (no matching diff signal)

**Do-not-revert reminders carried from pass 1:**
- Cleanup awaits MUST be guarded with try/except + log + `asyncio.wait_for` timeout.
- Attribute nulling MUST be in `finally`.
- The same hardening MUST apply to `close_browser`.
- Dockerfile regression guard test (`src/backend/api/tests/test_dockerfile_tini_guard.py`) MUST stay.

### Code-review findings

**Critical:**
- (none — pass 1 closed all C-tier silent-failure and test gaps)

**Important:**
- `scripts/shared/base_scraper.py:217-241` (`close_browser`) — Three independent issues identified by code-reviewer + silent-failure-hunter consensus:
  1. **Does not null `self.context` / `self.browser` / `self.playwright` after cleanup**, so a double-call (e.g. manual + `__aexit__`, or wrapper-driven belt-and-suspenders teardown) re-attempts cleanup on already-closed handles → spurious error logs and up to 15s wasted on stale `playwright.stop()` timeouts. Asymmetric with `initialize_browser`'s pass-1 `finally`-nulling.
  2. **Swallows `asyncio.CancelledError` and `KeyboardInterrupt` at every step** via `except BaseException`. A SIGTERM mid-shutdown is silently downgraded to "cleanup failed, continuing teardown" log lines — task cancellation is lost. Tini reaping protects in production but the cancellation contract is violated.
  3. **`logger.info("Browser closed")` fires unconditionally** — even when 1/3/all steps failed or timed out. Operators reading INFO logs see a clean-shutdown message that lies.
- `scripts/tests/unit/test_base_scraper_initialize.py` — **No tests pin the `close_browser` per-step hardening contract** (do-not-revert list says "Subsequent awaits MUST run even if an earlier one fails" but only the after-partial-init-all-None path is tested). A regression that re-introduces a bare `await self.browser.close()` would silently re-open the leak. Need parametrized tests for each of the three steps raising. (pr-test-analyzer I1, code-reviewer #4, silent-failure-hunter #4)
- `scripts/tests/unit/test_base_scraper_initialize.py:298-337` — **Stop-hangs test does not actually exercise production `asyncio.wait_for`.** Verified empirically by pr-test-analyzer: monkeypatching `wait_for` to a no-timeout passthrough leaves all assertions passing. The test pins the `finally`-nulling contract but not the wait_for-fires contract. Either assert `caplog` records `TimeoutError` or shrink the test's outer timeout below the production timeout. (pr-test-analyzer Q3)

**Suggestion / Nit:**
- `scripts/tests/unit/test_base_scraper_initialize.py:128-201` — CancelledError parametrize branches don't pin exception identity (no `excinfo.value is original` check, only `isinstance`). The `RuntimeError` branches do pin identity. Apply same rigor to CancelledError. (pr-test-analyzer Q1, I4)
- `scripts/shared/base_scraper.py:184-188, 197-201, 220-224, 228-232, 236-240` — Six near-identical `logger.error(... %r ...)` calls don't distinguish `TimeoutError` from runtime failure. Consider isinstance check + include configured timeout in message. (silent-failure-hunter S, code-reviewer #5)
- `src/backend/api/tests/test_dockerfile_tini_guard.py` — Doesn't specifically assert the `apt-get install … tini` line is present. Substring "tini" appears in many places (e.g. ENTRYPOINT). A targeted install-line check closes a gap. (pr-test-analyzer S2)

### Production-environment findings

**Critical:**
- (none — drain-timeout interaction confirmed safe; close_browser runs in scraper subprocess, not uvicorn lifespan)

**Important:**
- **Successful scrape cycle on the post-restart container `9c9251cd` not yet confirmed at 14:57Z.** Apple started at 14:40:03Z, expected completion ~15:03Z. Re-check at ~15:30Z before merge. If by 15:30Z still no completion line and no `"Scraper exited with code"` line, the un-tini'd image is failing for a different reason and the diagnosis embedded in this PR may be incomplete. **Manual action: re-verify before merge.** (railway-prod-verifier)

**Suggestion:**
- (carried from pass 1, still out of scope) — add `healthcheckPath: /health` to Railway service config. (railway-prod-verifier)

**Could not verify:**
- railway-prod-verifier: live `pthread_create EAGAIN` evidence on REMOVED b0b36aa1 (carried from pass 1, no change).

### Deferred (not fixing this pass)

- pr-test-analyzer I3 (`playwright.start()` failure test): low value, defer.
- silent-failure-hunter S1 (six near-identical logger calls refactor into helper): cosmetic, defer.
- All comment-analyzer pass-1 carry-overs: cosmetic, defer.

---

## 2026-05-05 — Review pass 3

**Diff scope:** `git diff origin/main...HEAD` — all pass-1 + pass-2 commits applied.

**Verifier dispatch:**
- railway-prod-verifier: dispatched (Dockerfile + scraper changes still in scope; verify pass-2 hardening hasn't introduced env/config drift)
- vercel-prod-verifier: not dispatched (no matching diff signal)
- postgres-prod-verifier: not dispatched (no matching diff signal)

**Do-not-revert reminders carried from passes 1 & 2:**
- Cleanup awaits MUST be guarded with try/except + log + `asyncio.wait_for` timeout.
- Attribute nulling MUST be in `finally`.
- The same hardening MUST apply to `close_browser`.
- Dockerfile regression guard tests (`src/backend/api/tests/test_dockerfile_tini_guard.py`) MUST stay.
- `close_browser` MUST null `self.X` in `finally` per step.
- `close_browser` MUST re-raise caught `CancelledError` / `KeyboardInterrupt` after running all steps.
- `close_browser` MUST conditionally log success — INFO when no failure, WARNING otherwise.
- Cleanup-await timeouts MUST be module-level constants `CONTEXT_CLOSE_TIMEOUT` / `BROWSER_CLOSE_TIMEOUT` / `PLAYWRIGHT_STOP_TIMEOUT`.

### Code-review findings

**Critical:**
- (none — pass 3 confirmed prior passes closed all C-tier issues; code-reviewer reports "Ready to merge")

**Important:**
- `scripts/shared/base_scraper.py:255, 271, 287, 304-307` — **Stale "Browser closed" INFO on no-op double-close.** A second `close_browser()` call on a fully-nulled scraper short-circuits all three steps, leaves `had_failure = False`, and emits `INFO: Browser closed` again. Operators relying on that line as a one-per-shutdown marker will get false positives. Gate the success log on `attempted_anything = True` (set inside any non-skipped branch). (silent-failure-hunter Q2)
- `scripts/shared/base_scraper.py:33-35` — **Unguarded zero/negative timeout constants.** A future maintainer setting `PLAYWRIGHT_STOP_TIMEOUT=0` (mistaking it for the requests-library "0 means infinite" convention) flips every shutdown to instant `TimeoutError`. Add module-load-time `assert` guards. (silent-failure-hunter Q3)
- `scripts/shared/base_scraper.py:261-268, 277-284, 293-300` — **`logger.error` raising silently bypasses WARNING and `pending_cancellation` re-raise.** If the logging handler itself fails (full disk on FileHandler, socket dropout on RemoteHandler), the function exits via the new logger exception — WARNING never fires AND `pending_cancellation` is silently dropped. Wrap each `logger.error` in a defensive `try/except Exception: pass` so logging failures cannot break the cleanup contract. (silent-failure-hunter Q4)
- `scripts/tests/unit/test_base_scraper_initialize.py:549-569` — **Cancellation propagation only tested at the first step.** `pending_cancellation` overwrites with the most-recent across all three steps but the test exercises only `context.close` raising. Extend to parametrize over `(context.close, browser.close, playwright.stop) × (CancelledError, KeyboardInterrupt)`. (pr-test-analyzer Important #1, #2)

**Suggestion / Nit:**
- silent-failure-hunter Q1: chain `__context__` for multiple cancellations — default Python behavior already chains via implicit `__context__` when raising inside an except, so this is redundant. Defer.
- pr-test-analyzer S1, S2: zero-timeout misuse test, multi-cancellation order test — defer (covered structurally by the assertion-guard fix above).
- pr-test-analyzer N1, N2: trivial polish — defer.

### Production-environment findings

**Critical:**
- (none — Railway verifier reports GO)

**Important (RESOLVED-WITH-EVIDENCE):**
- **Pass-2 carryover RESOLVED:** Container `9c9251cd` (deployed 14:36:53Z, ~35 min uptime at pass-3 verification) has produced **zero** completed scrape rows. `MAX(scrape_runs_prod.started_at) = 2026-05-02T06:49:07Z`. The un-tini'd image is silently hanging scraper subprocesses — exactly the failure mode this PR addresses. This **strengthens** the case for merging: the diagnosis is correct, the live image is exhibiting the silent-hang variant, and merge is now operationally needed. (railway-prod-verifier)

**Suggestion:**
- After merge, watch the new deployment for: (a) `apt-get install ... tini` line in build output, (b) first scrape cycle producing either "Scrape completed for apple" OR a loud `TimeoutError` / "playwright.stop() failed during close_browser" within the 30s budget. If neither appears within 30 minutes, diagnosis incomplete and rollback. (railway-prod-verifier)

**Could not verify:**
- railway-prod-verifier: live `pthread_create EAGAIN` evidence on REMOVED `b0b36aa1` (carried from passes 1 & 2).

### Deferred (not fixing this pass)

- silent-failure-hunter Q1 (multi-cancellation `__context__` chaining): redundant with Python default behavior; defer.
- silent-failure-hunter helper extraction (six near-identical try/except blocks): cosmetic, defer.
- pr-test-analyzer Important #3 (BaseException-tier non-cancellation failures): impractical scenarios, defer.
- pr-test-analyzer S2, S3, N1, N2: cosmetic / structural-only, defer.
- All carry-overs from passes 1 & 2 already deferred remain deferred.

### Implementation applied (pass 3)

Two commits on `fix/scraper-pthread-exhaustion`:

- **`0ddc2da`** — `Review pass 3: harden cleanup-side logging + gate success log`
  - File: `scripts/shared/base_scraper.py`
  - Module-load `assert (CONTEXT_CLOSE_TIMEOUT > 0 and BROWSER_CLOSE_TIMEOUT > 0 and PLAYWRIGHT_STOP_TIMEOUT > 0)` so a future maintainer setting any of them to 0/negative (mistaking the constant for the requests-library "0 means infinite" convention) trips at import time instead of silently flipping every shutdown to instant `TimeoutError` (Fix 1, silent-failure-hunter Q3). Tests can still patch the constants down to small positive values via `monkeypatch` — only literal 0/negative values are blocked.
  - New module-scope `_safe_log_cleanup_failure(message, *args)` helper wrapping `logger.error` in a bare `try/except Exception: pass`. Replaces all six cleanup-side `logger.error(...)` calls (three in `initialize_browser`, three in `close_browser`). Logging-handler failures (full disk on FileHandler, socket dropout on RemoteHandler) can no longer break the cleanup contract: the WARNING fallback log AND the `pending_cancellation` re-raise both still execute even when the logging subsystem itself fails (Fix 2, silent-failure-hunter Q4). Only cleanup-side ERROR calls were swapped — `logger.info` and `logger.warning` calls in success paths remain unchanged.
  - `close_browser` now tracks `attempted_anything` (set inside each `if self.X:` branch). After the three steps: `if not attempted_anything: return` (silent no-op for double-close / post-partial-init paths), else conditionally emit `WARNING` or `INFO` and finally re-raise `pending_cancellation` if set. Operators relying on `INFO: Browser closed` as a one-per-shutdown marker no longer get false positives on no-op double-close (Fix 3, silent-failure-hunter Q2). Docstring updated to match.

- **`d599660`** — `Review pass 3: parametrize cancellation sweep + pin no-op log silence`
  - File: `scripts/tests/unit/test_base_scraper_initialize.py`
  - Replaced `test_cancellation_at_first_step_runs_remaining_then_re_raises` with `test_cancellation_at_step_runs_remaining_then_re_raises`, parametrized over `step_index ∈ {0,1,2} × exc_type ∈ {CancelledError, KeyboardInterrupt}` — 6 parametrize cells covering every (step, cancellation-type) combination. The pre-pass-3 test only exercised step 0 + CancelledError; cancellation propagation at steps 1 and 2 and under KeyboardInterrupt was not pinned. A regression that early-returns on the first per-step cancellation (skipping subsequent close/stop awaits) would now fail in 5 of the 6 parametrize cells (pr-test-analyzer Important #1, #2).
  - Added `test_double_close_browser_emits_no_logs` — strict tightening of the existing `test_double_close_browser_is_no_op`. Pre-pass-3 only asserted no ERROR-level records on the second call; new test asserts NO records at INFO or higher across the second call, pinning the new `attempted_anything` gate from Fix 3.
  - `test_success_logs_info_browser_closed` still passes unchanged (Fix 3's INFO-on-attempted_anything-True path is exactly what that test exercises).

**Verification:**
- `cd scripts && pytest tests/unit -q` — 230 passed (was 224; +6 net from the new parametrize cells minus the one replaced test, plus the new no-logs test).
- `cd src/backend && pytest -q` — 226 passed (unchanged from pass 2 — no backend files touched in pass 3).

#### Do not revert (new in this pass)

- **`close_browser` MUST gate the success/warning log on `attempted_anything = True`** to avoid false-positive shutdown signals on no-op double-close. A second `close_browser` call on a fully-nulled scraper (after the per-step `finally` nulling drained all three handles on the first call) MUST emit no INFO/WARNING/ERROR log at all — operators relying on `INFO: Browser closed` as a one-per-shutdown marker must not see duplicates. Test `test_double_close_browser_emits_no_logs` pins this contract; reverting the gate to unconditional INFO/WARNING would fail it.
- **Cleanup logger calls MUST be wrapped in `_safe_log_cleanup_failure`** (or an equivalent helper that swallows `Exception` from the logger). A logging-handler failure (full disk on FileHandler, socket dropout on RemoteHandler) MUST NOT break the cleanup contract: the WARNING fallback AND the `pending_cancellation` re-raise both still execute. Replacing the helper with a bare `logger.error(...)` would re-introduce the silent-cancellation-drop hole (silent-failure-hunter Q4).
- **Module-level timeout constants MUST be guarded by an `assert`** against zero/negative values. A future maintainer setting `PLAYWRIGHT_STOP_TIMEOUT = 0` (mistaking it for the "0 means infinite" convention from other libraries) would otherwise flip every shutdown to instant `TimeoutError`. The assert catches the misconfiguration at module-load time. Tests can still `monkeypatch.setattr` to small positive values for fast-running tests; only literal 0/negative values trip the assert.

### Implementation applied (pass 2)

Three commits on `fix/scraper-pthread-exhaustion`:

- **`d0aac1e`** — `Review pass 2: harden close_browser + extract timeout constants`
  - File: `scripts/shared/base_scraper.py`
  - Per-step `finally: self.X = None` in `close_browser` for `context`, `browser`, `playwright` so a subsequent call (e.g. wrapper-driven double-teardown) is a safe no-op rather than re-attempting cleanup on stale handles (Fix 1).
  - Track caught `asyncio.CancelledError` / `KeyboardInterrupt` per step in `pending_cancellation`; re-raise the most recent one after running all three steps so SIGTERM mid-shutdown is no longer silently swallowed (Fix 2).
  - Track `had_failure` flag; emit `INFO "Browser closed"` only on clean teardown, `WARNING "Browser teardown finished with errors above"` otherwise — operators no longer see a misleading clean-shutdown signal when a step actually failed (Fix 3).
  - Extracted `CONTEXT_CLOSE_TIMEOUT` (5.0), `BROWSER_CLOSE_TIMEOUT` (10.0), `PLAYWRIGHT_STOP_TIMEOUT` (15.0) as module-level constants and referenced them from BOTH `initialize_browser` and `close_browser` cleanup awaits, so tests can override the timeouts via `monkeypatch` (required to make the stop-hangs test actually exercise production `asyncio.wait_for` on a fast budget). Updated docstrings to reference the constants.

- **`d96abfa`** — `Review pass 2: pin close_browser hardening + tighten cancellation tests`
  - File: `scripts/tests/unit/test_base_scraper_initialize.py`
  - Added `_populate_scraper_with_mocks` helper + `TestCloseBrowserStepHardening` class (7 new tests):
    - `test_step_failure_runs_subsequent_steps[context|browser|playwright]` — parametrized over each step raising `RuntimeError`, asserts subsequent close/stop AsyncMocks still awaited, error logged at error level, `close_browser` does NOT re-raise, all three attributes nulled (Fix 1 + S1 contract).
    - `test_cancellation_at_first_step_runs_remaining_then_re_raises` — `context.close` raises `CancelledError`; all three steps still run; `CancelledError` re-raised by `close_browser` afterward (Fix 2).
    - `test_double_close_browser_is_no_op` — first call tears down cleanly; second call attempts no awaits (proves Fix 1 nulling prevents stale-handle re-attempts); no error logs.
    - `test_success_logs_info_browser_closed` / `test_failure_logs_warning_not_info` — INFO fires only on clean teardown; WARNING replaces it when any step failed (Fix 3).
  - Strengthened `test_playwright_stop_hangs_does_not_block_forever`:
    - `monkeypatch.setattr("shared.base_scraper.PLAYWRIGHT_STOP_TIMEOUT", 0.5)` — production wait_for fires almost immediately instead of after 15s.
    - Outer test bound dropped from 20s to 2s — a regression that removes `asyncio.wait_for` would block past 2s and fail loudly via outer `asyncio.wait_for(_run(), timeout=2.0)`.
    - Added explicit `caplog` assertion that a record contains `"TimeoutError"` substring — pins that production `asyncio.wait_for` actually fired (only path that produces TimeoutError in this scenario).
  - Tightened `test_launch_failure_stops_playwright[CancelledError]` and `test_new_context_failure_closes_browser_and_stops_playwright[CancelledError]` to assert `excinfo.value is exc` (exception identity), matching the rigor of `test_launch_failure_with_playwright_stop_also_raising`'s `excinfo.value is original` check (Fix 6a).

- **`9d49545`** — `Review pass 2: add Dockerfile apt-get install tini guard test`
  - File: `src/backend/api/tests/test_dockerfile_tini_guard.py`
  - Added `test_dockerfile_installs_tini` — whitespace-normalizes each line and asserts at least one line contains both `apt-get install` and `tini`. Closes a gap the existing three tests miss: a refactor that deletes the install layer but leaves the ENTRYPOINT line dangling would still pass the substring/ENTRYPOINT/CMD checks but produce an image that crashes at exec with `no such file or directory` (Fix 6b).

**Verification:**
- `cd scripts && pytest tests/unit -q` — 224 passed (was 217; +7 from new `TestCloseBrowserStepHardening` class).
- `cd src/backend && pytest -q` — 226 passed (was 225; +1 from new `test_dockerfile_installs_tini`).

#### Do not revert (carried from pass 1)

- **Cleanup awaits in `initialize_browser` and `close_browser` MUST be guarded with `try/except BaseException` + error-level logging + `asyncio.wait_for` timeout.** A naked `await self.browser.close()` re-introduces the C1 silent-failure bug (secondary exception masks the primary). A naked await without `wait_for` re-introduces C2 (hung cleanup blocks the subprocess indefinitely under PID exhaustion).
- **Attribute nulling (`self.browser = None`, `self.playwright = None`) MUST live in `finally`, not in the body of the `except`.** Otherwise a cleanup-await failure / cancellation skips the nulling and `close_browser` would attempt to double-stop already-dead handles. Tests `test_launch_failure_with_playwright_stop_also_raising` and `test_new_context_failure_with_browser_close_also_raising` pin this contract.
- **`close_browser` MUST keep the same hardening as `initialize_browser`** — independently guarded `context.close` / `browser.close` / `playwright.stop` awaits with their own `try/except BaseException` + logging + `wait_for`. Subsequent awaits MUST run even if an earlier one fails (S1 contract). Reverting any of the three to a bare `await` would re-introduce a partial-cleanup hole on the normal shutdown path.
- **`src/backend/api/tests/test_dockerfile_tini_guard.py` MUST stay.** It is the only automated guardrail preventing a future Dockerfile refactor from silently removing tini or reverting ENTRYPOINT to shell-form, which would re-introduce the no-PID-1-reaper failure mode at the heart of the 2026-05-05 incident. If the Dockerfile is intentionally restructured (e.g., multi-stage, dumb-init), update this test alongside the change rather than deleting it.

#### Do not revert (new in this pass)

- **`close_browser` MUST null `self.context` / `self.browser` / `self.playwright` in per-step `finally` blocks** — defense against double-close stale-handle re-attempts. A subsequent `close_browser` call (manual + `__aexit__`, or wrapper-driven belt-and-suspenders teardown) MUST be a complete no-op — no awaits attempted on already-closed handles, no spurious error logs, no wasted `PLAYWRIGHT_STOP_TIMEOUT` seconds. Test `test_double_close_browser_is_no_op` pins this contract.
- **`close_browser` MUST re-raise caught `asyncio.CancelledError` / `KeyboardInterrupt`** after running all three steps. Per-step `except BaseException` deliberately catches cancellation in order to keep the "subsequent awaits run" contract, but propagation is required so SIGTERM mid-shutdown is not silently swallowed. Test `test_cancellation_at_first_step_runs_remaining_then_re_raises` pins this contract.
- **`close_browser` MUST conditionally log success** — `INFO "Browser closed"` only when no step failed; `WARNING "Browser teardown finished with errors above"` otherwise. An unconditional INFO message on any teardown lies to operators when steps actually failed/timed out/were cancelled. Tests `test_success_logs_info_browser_closed` and `test_failure_logs_warning_not_info` pin this contract.
- **Cleanup-await timeouts MUST be module-level constants `CONTEXT_CLOSE_TIMEOUT` / `BROWSER_CLOSE_TIMEOUT` / `PLAYWRIGHT_STOP_TIMEOUT`** referenced from both `initialize_browser` and `close_browser` cleanup awaits. Inlining literal floats is forbidden because it removes the only injection seam tests use to exercise production `asyncio.wait_for` on a fast budget — the strengthened `test_playwright_stop_hangs_does_not_block_forever` would silently revert to its pre-pass-2 weakness (passing even if production `wait_for` is removed).

