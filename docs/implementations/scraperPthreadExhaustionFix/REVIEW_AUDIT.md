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
  - Root-cause analysis (`pthread_create EAGAIN`, zombie accumulation, partial-init driver leak) preserved unchanged.

- **`c882abe`** — `Review pass 1: Dockerfile tini regression guard test`
  - File: `src/backend/api/tests/test_dockerfile_tini_guard.py` (new, 3 tests)
  - Resolves `src/backend/Dockerfile` via `Path(__file__).resolve().parents[2] / 'Dockerfile'`.
  - Asserts `tini` substring is present, exec-form `ENTRYPOINT ["/usr/bin/tini", "--"]` line is present (whitespace-normalized), and uvicorn `CMD` is preserved.
  - Tradeoff documented inline: fragile to legitimate restructures, but no-guard alternative would let the incident recur silently (per pr-test-analyzer I3).

**Verification:**
- `cd scripts && pytest tests/unit -q` — 217 passed (was 210; +7 from parametrize + new cleanup-handler-raises + async-with + close-after-partial tests).
- `cd src/backend && pytest -q` — 225 passed (was 222; +3 new Dockerfile guard tests).

#### Do not revert (new in this pass)

- **Cleanup awaits in `initialize_browser` and `close_browser` MUST be guarded with `try/except BaseException` + error-level logging + `asyncio.wait_for` timeout.** A naked `await self.browser.close()` re-introduces the C1 silent-failure bug (secondary exception masks the primary). A naked await without `wait_for` re-introduces C2 (hung cleanup blocks the subprocess indefinitely under PID exhaustion).
- **Attribute nulling (`self.browser = None`, `self.playwright = None`) MUST live in `finally`, not in the body of the `except`.** Otherwise a cleanup-await failure / cancellation skips the nulling and `close_browser` would attempt to double-stop already-dead handles. Tests `test_launch_failure_with_playwright_stop_also_raising` and `test_new_context_failure_with_browser_close_also_raising` pin this contract.
- **`close_browser` MUST keep the same hardening as `initialize_browser`** — independently guarded `context.close` / `browser.close` / `playwright.stop` awaits with their own `try/except BaseException` + logging + `wait_for`. Subsequent awaits MUST run even if an earlier one fails (S1 contract). Reverting any of the three to a bare `await` would re-introduce a partial-cleanup hole on the normal shutdown path.
- **`src/backend/api/tests/test_dockerfile_tini_guard.py` MUST stay.** It is the only automated guardrail preventing a future Dockerfile refactor from silently removing tini or reverting ENTRYPOINT to shell-form, which would re-introduce the no-PID-1-reaper failure mode at the heart of the 2026-05-05 incident. If the Dockerfile is intentionally restructured (e.g., multi-stage, dumb-init), update this test alongside the change rather than deleting it.

