# jobListingsCompositePk PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-05-17 — Review pass 3

Dispatched 5 code-review agents + 2 production verifiers in parallel.

- **vercel-prod-verifier:** not dispatched (no matching diff signal — still backend-only).
- All 7 dispatched agents completed successfully.

### Code-review findings

**Critical:**

- `scripts/shared/database.py:329-375` (`upsert_jobs_batch`) — **the pass-2 divergence WARN is built on inverted psycopg2 semantics and will spam Railway logs on every prod Greenhouse fetch >100 jobs.** Confirmed independently by silent-failure-hunter and code-reviewer. `psycopg2.extras.execute_values` docstring explicitly says: *"After the execution of the function the `cursor.rowcount` property will not contain a total result."* It runs one `cur.execute()` per page (default `page_size=100`) and `rowcount` reflects only the LAST page. The pass-2 comment ("from 2.9 onward it sums across pages; the pre-2.9 bug only returned the last-page count") is the reverse of reality. Empirical test: 250 rows in 3 pages → `cursor.rowcount == 50`, not 250. Greenhouse boards routinely have >100 open jobs (Stripe, Airbnb, Coinbase); `src/backend/api/tasks/fetch_greenhouse_company.py:163` calls `db.upsert_jobs_batch(conn, jobs)` with the full per-board list. Once prod Greenhouse traffic ramps, every fetch for a 100+ board WILL log `upsert_jobs_batch affected 50/250 rows — 200 jobs did not produce an insert-or-update`, masking the very silent-failure surface the WARN was meant to detect. **Fix paths:** (a) iterate `jobs` in chunks and sum `cursor.rowcount` per `execute_values` call yourself, (b) use `RETURNING 1` + `cursor.fetchall()` count, or (c) drop the WARN entirely and revert to the original `logger.info(f"Batch upserted {len(jobs)} jobs")`. **Recommend (c) — minimal blast radius, no false promise.** Also strike the misleading "from 2.9 onward sums across pages" / "pre-2.9 page-only rowcount bug" comment + message text. (silent-failure-hunter Critical, code-reviewer Critical, comment-analyzer Important #1)

**Important:**

- `src/backend/api/tests/test_jobs_qa_router.py:134,150,151` — same `apple`-rows-seeded-with-`google_scraper`-source_id problem that pass 2 fixed in `test_jobs_router.py::seed_jobs`. `_make_job({"id": "a1", "company": "apple", ...})` inherits the `google_scraper` default. Stats endpoint groups by `company` so today's tests pass, but the fixture is now lying about data shape — same justification as pass-2 Important #1. One-line fix per row: add `"source_id": "apple_scraper"`. Pin before merge for convergence on the apple fixture problem. (pr-test-analyzer Important #1)
- `scripts/shared/database.py:161-164,194-197,253-256,425-428,468-471,514-517,562-565,608-611` + `scripts/shared/incremental.py:169-172` + `src/backend/api/services/database.py:124-125` — **the 10 new pass-2 `if not source_id: raise ValueError(...)` guards have zero positive test coverage.** Pass-2 "Do not revert" list pins these as load-bearing ("Removing them in the name of 'simplification' would re-open the silent `WHERE source_id = ''` no-op surface"). An untested load-bearing guard can be silently broken by a future refactor (catching ValueError upstream, changing `if not source_id` to `is None`, etc.). Three or four `pytest.raises(ValueError, match="source_id")` tests covering one helper per shape (`get_active_job_ids`, `update_last_seen`, `get_job_by_id`, `update_existing_jobs`) would lock the contract without duplicating across all 10 sites. (pr-test-analyzer Important #2)
- `scripts/shared/database.py:360` — `_build_job_values(job.source_id)` is a wrong function-signature claim in the comment block. `_build_job_values` is `def _build_job_values(job: JobListing)` — takes a `JobListing`, not a `source_id`. Rephrase to `_build_job_values(job)` reads `source_id` from `job.source_id` per row. Fold into the Critical fix above. (comment-analyzer Important #2)

**Suggestion:**

- `src/backend/api/tests/test_enqueue_greenhouse_fan_out.py:51` — `_greenhouse_jobs` helper SELECT is unqualified (`FROM procrastinate_jobs`) while the new cleanup DELETE is qualified (`FROM public.procrastinate_jobs`). Inconsistent; harmless today. (silent-failure-hunter Suggestion, code-reviewer Suggestion)
- `scripts/shared/database.py:405` (`insert_jobs_batch`) — pre-existing same rowcount-after-`execute_values` issue in its INFO log. Pre-PR, out of scope, flag for follow-up. (silent-failure-hunter Critical-context)
- ValueError guards uniformly handle `None` and `""` but not whitespace-only strings (`"  "`). Defensive `if not source_id or not source_id.strip()`. Optional. (silent-failure-hunter Suggestion)
- `reactivate_job` docstring "Today's tests are the only callers" will rot. Drop the historical aside; keep the contract. (type-design-analyzer Nit, comment-analyzer Suggestion, code-reviewer Nit)
- `src/backend/api/routers/jobs.py:28` — `Path(max_length=100)` doesn't enforce `min_length=1`; the empty-source_id guard at the service-layer catches it, but pushing the invariant to the URL boundary (`Path(min_length=1, max_length=100)`) would close the loop. (type-design-analyzer Suggestion S2)
- Procrastinate cleanup IN-clause could broaden to `bootstrap_noop` for future test safety. (pr-test-analyzer Suggestion)
- Migration NULL-source_id pre-flight guard has no test (`_create_pre_migration_job_listings` declares column as NOT NULL so can't seed NULL). (pr-test-analyzer Suggestion)
- Test `test_upgrade_aborts_on_collision_preflight` only checks `id` values — could mirror `test_downgrade_aborts_on_collision_preflight`'s fuller row-equality assertion. (pr-test-analyzer Nit, silent-failure-hunter Suggestion)

### Production-environment findings

**Critical:**

- None.

**Important:**

- None new. Pass-1 and pass-2 carry-forwards stand unchanged (pool exhaustion, Postgres 17.9 vs 15.15 drift, Railway-UI-rollback warning, zero `greenhouse_api` rows in prod). All non-blocking.

**Suggestion:**

- None new this pass.

**Could not verify:**

- Same as pass 1 + 2: Railway container memory/CPU metrics; live ALTER TABLE lock duration on Railway IO.

### Deferred (not fixing this pass)

- `insert_jobs_batch` rowcount-after-`execute_values` fix (pre-PR; out of scope).
- Whitespace-only `source_id` defensive `.strip()` check (defensive; optional).
- `reactivate_job` docstring historical aside removal (polish).
- Router `Path(min_length=1)` (folds with deferred `Literal[…]` source-id registry).
- `bootstrap_noop` cleanup broadening (defense-in-depth; not load-bearing today).
- Migration NULL-source_id pre-flight test (deferred since pass 1).
- Fuller row-equality assertion on upgrade collision test (mirror of pass-2 Suggestion).
- All other polish items from passes 1+2 still deferred.

### Implementation applied

- **`a648192` Review pass 3: drop spurious `upsert_jobs_batch` rowcount divergence WARN** — Removed the `cursor.rowcount`-based divergence WARN that pass 2 added to `upsert_jobs_batch` in `scripts/shared/database.py`. `psycopg2.extras.execute_values` overwrites `rowcount` per page (default `page_size=100`) — its docstring explicitly says: *"After the execution of the function the `cursor.rowcount` property will not contain a total result."* Pass 2's comment claiming "from 2.9 onward sums across pages" was the reverse of reality, so for any batch >100 rows (i.e. every prod Greenhouse board of meaningful size: Stripe, Airbnb, Coinbase) the WARN would have fired spuriously on every fetch once Greenhouse traffic ramps. Replaced with a single `logger.info` line that includes the sorted set of source_ids in the batch (genuinely useful operator data). Struck the misleading "from 2.9 onward sums across pages" / "pre-2.9 page-only rowcount bug" comment block and the wrong `_build_job_values(job.source_id)` signature claim. Resolves audit pass-3 Critical (silent-failure-hunter Critical, code-reviewer Critical, comment-analyzer Important #1, #2). The original silent-failure rationale ("future scraper builds a JobListing with the wrong source_id") cannot be detected by a rowcount-divergence check anyway — `ON CONFLICT (source_id, id) DO UPDATE` will count a mis-routed insert OR mis-routed update normally; the right defense is the per-row `_build_job_values(job)` construction itself.

- **`aa229d8` Review pass 3: apple-fixture source_id symmetry + positive ValueError guard tests** — In `src/backend/api/tests/test_jobs_qa_router.py::test_stats_returns_counts_for_all_companies` and `test_stats_filters_by_company`, overrode `source_id="apple_scraper"` on apple rows and `source_id="google_scraper"` on google rows so the (source_id, id) composite-PK rows are filed in their real namespaces instead of inheriting `_make_job`'s `google_scraper` default. Stats endpoint groups by `company` so today's tests pass either way, but the fixture is no longer lying about data shape — same justification as pass-2 Important #1 in `test_jobs_router.py::seed_jobs`. Added 3 positive `pytest.raises(ValueError, match="source_id")` tests covering the three guard shapes — `get_active_job_ids` (SELECT), `update_last_seen` (bulk UPDATE), `get_job_by_id` (single-row) — as a new `TestSourceScopedHelpersRejectEmptySource` class in `scripts/tests/integration/test_database.py`. Added a 4th test for the highest-level guard `update_existing_jobs` in `scripts/tests/integration/test_incremental.py::TestUpdateExistingJobs::test_update_existing_jobs_rejects_empty_source_id`. The 10 new ValueError guards added in pass 2 are pinned as "Do not revert" but had zero positive coverage — these tests lock the contract without duplicating across all 10 sites. Resolves audit pass-3 Important #1 and #2.

**Do not revert (new in this pass):**

- The simplified `upsert_jobs_batch` log (no `cursor.rowcount` divergence WARN). Re-adding a rowcount check on `execute_values` output cannot reliably detect "wrong source_id" misfiling — `ON CONFLICT (source_id, id) DO UPDATE` counts mis-routed writes normally — and will fire spuriously on any batch >100 rows due to per-page rowcount semantics. The current `logger.info` line includes the sorted set of source_ids in the batch, which IS useful operator data for spotting cross-namespace mixing in logs.
- The `TestSourceScopedHelpersRejectEmptySource` class in `test_database.py` and the `test_update_existing_jobs_rejects_empty_source_id` test in `test_incremental.py` are load-bearing for the pass-2 "Do not revert" ValueError guards. Removing these tests would let a future refactor silently weaken the guards (`if not source_id` → `is None`, upstream `except ValueError`, etc.) and re-open the silent `WHERE source_id = ''` no-op surface.

**Manual action required before merge:**

- None.

**Conflicts with prior audit (not fixed):**

- This commit REPLACES pass-2's `upsert_jobs_batch` divergence WARN with a simple info log. Pass-2's "Do not revert" list pinned the WARN — that pin is OVERRIDDEN by this pass because the WARN was factually broken (built on inverted psycopg2 semantics; cannot detect the bug class it claimed to detect; would spam Railway logs on every prod Greenhouse fetch >100 jobs). The override is justified and documented in the pass-3 Critical write-up above. Future reviewers: do NOT re-add the WARN without first fixing the underlying `execute_values` rowcount-per-page issue (option (a) chunk-and-sum yourself or option (b) RETURNING-based count from the pass-3 audit fix paths) AND a positive test proving the WARN fires only on genuine divergence and not on every multi-page batch.

---

## 2026-05-17 — Review pass 2

---

## 2026-05-17 — Review pass 2

Dispatched 5 code-review agents + 2 production verifiers in parallel.

- **vercel-prod-verifier:** not dispatched (no matching diff signal — still backend-only).
- All 7 dispatched agents completed successfully.

### Code-review findings

**Critical:**

- None. All Critical items from pass 1 are confirmed resolved by the pass-1 fix commits. (code-reviewer, pr-test-analyzer, silent-failure-hunter, comment-analyzer all confirmed "ready to land" / "no Critical").

**Important:**

- `src/backend/api/tests/test_jobs_router.py:10-28` — autouse `seed_jobs` fixture uses `_make_job` which defaults `source_id="google_scraper"`, so the apple rows (`apple-789`, `apple-101`) are silently seeded with `source_id="google_scraper"`. The new disambiguation tests work because they use different ids, but the fixture itself is now lying about data shape — the next person writing an apple-route test will hit this. Cleanup: override `source_id="apple_scraper"` on the apple rows for symmetry. (silent-failure-hunter Important #1)
- `scripts/shared/database.py:311-340` (`upsert_jobs_batch`) — pass-1 added `cursor.rowcount` divergence warnings to four bulk helpers but skipped `upsert_jobs_batch`. The justification (source_id comes from per-row `_build_job_values`, not a uniform arg) is real, but the silent-failure surface still exists: if a future scraper constructs a `JobListing` with the wrong `source_id`, the upsert lands in the wrong namespace with no warning. At minimum log `cursor.rowcount` against `len(jobs)` so divergence shows in Railway logs. (silent-failure-hunter Important #2)
- `scripts/shared/incremental.py:146-189` (`update_existing_jobs`) and `scripts/shared/database.py` helpers — accept `source_id: str` but don't validate it (empty string / None / wrong type). Pass-1 validation lives in `run_incremental_scrape` only. Add `if not source_id: raise ValueError(...)` at the boundary of `update_existing_jobs` and each `db.*` helper so they fail fast instead of silently building `WHERE source_id = ''` and no-opping (the WARN log is a backstop, not a fix). (silent-failure-hunter Important #3)
- `src/backend/api/tests/test_fetch_greenhouse_company.py:138-156` — procrastinate cleanup uses unqualified `DELETE FROM procrastinate_jobs ...`. Silently relies on `search_path` resolving to `public`. Qualify as `DELETE FROM public.procrastinate_jobs ...` to make it robust against future schema-management changes. Same latent bug exists in the sibling at `test_enqueue_greenhouse_fan_out.py:78-81`; fix both together. (silent-failure-hunter Important #5)
- `scripts/shared/database.py:524-555` (`reactivate_job`) — `affected==0` warning fires for legitimate "row doesn't exist" calls. Ambiguous contract: is "row MUST exist" the rule (warning correct) or is the miss recoverable (message text "no row matched the composite key" is misleading because that's exactly what was asked for)? Pin down in the docstring. (silent-failure-hunter Important #4)

**Suggestion:**

- Divergence warning messages are wordy and inconsistent across the 4 bulk helpers — consider a single `_warn_rowcount_divergence(...)` formatter so all four emit identical greppable shapes. (silent-failure-hunter Suggestion)
- Upgrade collision pre-flight RAISE message could include first 5 colliding ids via `string_agg` for faster operator MTTR. (silent-failure-hunter Suggestion)
- Decide whether divergence is ERROR or WARNING — current WARNING undersells if "ids must belong to source" is a hard contract (matches `fetch_greenhouse_company.py:106-110` pattern of using ERROR for surprising prod behavior). (silent-failure-hunter Suggestion)
- `test_upgrade_aborts_on_collision_preflight` asserts state preservation but only checks `id` values — a partial-UPDATE-on-other-columns regression would not be caught. Add a fuller row-content assertion. (silent-failure-hunter Suggestion)
- `test_insert_jobs_batch_does_not_touch_other_source` docstring oversells what it pins (regression of `ON CONFLICT (source_id, id)` → `ON CONFLICT (id)` would error at PG parse time, not via the assertion). Minor docstring fix. (pr-test-analyzer Important — but marked here as Suggestion-tier)
- Test fixture cleanup `DELETE FROM procrastinate_jobs WHERE task_name = 'fetch_greenhouse_company'` is narrow against future task additions. `test_jobs_qa_router.py:31-34` uses safer `task_name IN ('fetch_greenhouse_company', 'enqueue_greenhouse_fan_out')`. Mirror it or use unqualified `DELETE FROM` since per-test schema isolation owns the queue. (pr-test-analyzer Important — Suggestion-tier here)
- `incremental.py:213-219` ValueError guard has zero test coverage — instantiate a MagicMock without SOURCE_ID and assert raises. (pr-test-analyzer Suggestion)
- Divergence-warning paths have zero test coverage. (pr-test-analyzer Suggestion)
- Migration docstring two-guard precision: "RAISE EXCEPTION guards in both directions abort the migration before any destructive write if a collision is detected" — upgrade has TWO guards (NULL-source_id + collision), only one is "collision". Rephrase. (comment-analyzer Suggestion)
- Comment at `test_fetch_greenhouse_company.py:150` says "Wipe greenhouse_fetch task rows" but the SQL filters by `task_name = 'fetch_greenhouse_company'` (queue vs task name conflation). (comment-analyzer Suggestion)
- `get_active_job_ids`/`count_active_jobs` — `(source_id, company)` positional pair is easy to swap by future caller. Consider keyword-only (`def get_active_job_ids(conn, *, source_id, company)`). (type-design-analyzer Important #1 — deferred to a follow-up; flagged Suggestion-tier here)
- Migration RAISE message says "% collisions" but counts unique colliding (source_id, id) groups, not rows. Rephrase to "% duplicated (source_id, id) keys" or sum `count(*) - 1`. (type-design-analyzer Important #2 — Suggestion-tier here)
- `_seed_pre_migration_row` for downgrade test seeds `(google_scraper, 'greenhouse_42')` with `company='google'`. Internally consistent but the comment implies real-world-row provenance that doesn't quite match. Minor. (type-design-analyzer Important #3 — Nit-tier here)

### Production-environment findings

**Critical:**

- None.

**Important:**

- None new from pass-2 fix commits. Pass-1 carry-forwards remain valid (pool exhaustion still flooding live deploy, Postgres 17.9 vs 15.15 drift, Railway-UI-rollback-does-not-run-downgrade). All already tracked, not blocking.

**Suggestion:**

- After deploy, eyeball Railway logs for new `update_last_seen affected N/M ...` divergence warnings. Today (prod `greenhouse_api` count = 0) they will never fire from Greenhouse worker but will if a future caller passes a mismatched `source_id`. (railway-prod-verifier)
- CTE pre-flight is correct without `WHERE id LIKE 'greenhouse_%'` filter (no-op regexp_replace semantics make it safe). Two-line code comment explaining why would help future readers who might flag the unguarded regexp_replace. (postgres-prod-verifier)
- New `WHERE company = %s AND source_id = %s` query shape verified against prod via EXPLAIN — uses `idx_job_listings_company` as before, source_id is a Filter on the heap-scan side. No plan regression. (postgres-prod-verifier)

**Could not verify:**

- Same as pass 1: Railway container memory/CPU metrics; live ALTER TABLE lock duration on Railway IO.

### Deferred (not fixing this pass)

- Keyword-only enforcement on `get_active_job_ids`/`count_active_jobs` source_id+company params — follow-up grade.
- Reformatting divergence warnings into a shared `_warn_rowcount_divergence(...)` helper — polish.
- Adding `string_agg` of colliding ids to migration RAISE message — operator-MTTR improvement; out-of-scope.
- Tests for the `incremental.py` SOURCE_ID-missing ValueError path — dead-code-coverage improvement; out-of-scope.
- Tests for divergence-warning paths — observability not correctness.
- Migration docstring two-guard precision — already accurate enough.
- Rename `greenhouse_fetch` → `fetch_greenhouse_company` in comment at test_fetch_greenhouse_company.py:150 — Suggestion-tier polish.
- Decide WARNING vs ERROR for divergence — semantic call; defer to user.
- Larger refactors: `Literal[…]` source_id type, BaseScraper.SOURCE_ID ClassVar, CLAUDE.md API Endpoints update, ARCHITECTURE.md update, Postgres docker image bump.

### Implementation applied

- **`20e935c` Review pass 2: align test fixture source_ids + qualify procrastinate cleanup** — In `src/backend/api/tests/test_jobs_router.py::seed_jobs`, explicitly set `source_id="apple_scraper"` on the two `apple-*` rows and `source_id="google_scraper"` on the two `google-*` rows (the `_make_job` default of `google_scraper` was silently misfiling the apple rows). Added a fixture docstring explaining why. Verified no test in `test_jobs_router.py` or `test_response_shapes.py` hits the apple rows by URL (the apple rows are only exercised by list-endpoint filtering tests). In `src/backend/api/tests/test_fetch_greenhouse_company.py` and `test_enqueue_greenhouse_fan_out.py`, schema-qualified the procrastinate cleanup as `DELETE FROM public.procrastinate_jobs` and broadened the WHERE clause to the IN-pattern from `test_jobs_qa_router.py:31-34` (`task_name IN ('fetch_greenhouse_company', 'enqueue_greenhouse_fan_out')`). Updated comments in both files to call out the schema-qualification + IN-clause mirroring. Resolves audit pass-2 Important #1 and #4.

- **`2eefe21` Review pass 2: fail-fast source_id guards + upsert_jobs_batch divergence log** — Added `if not source_id: raise ValueError(...)` to every `db.*` helper that takes `source_id` as a separate arg (`get_active_job_ids`, `count_active_jobs`, `get_job_by_id`, `update_last_seen`, `increment_consecutive_misses`, `mark_jobs_closed`, `get_jobs_exceeding_miss_threshold`, `reactivate_job`) in `scripts/shared/database.py`, plus `update_existing_jobs` in `scripts/shared/incremental.py` and `get_job_by_id` in `src/backend/api/services/database.py`. Matches the existing `run_incremental_scrape` ValueError style. The single-row insert/upsert helpers (`insert_job`, `upsert_job`, `insert_jobs_batch`, `upsert_jobs_batch`) take `JobListing` (carries source_id per-row) so they're not in scope per the audit. Added `cursor.rowcount` divergence WARN to `upsert_jobs_batch` (psycopg2 >= 2.9.9 is pinned in both `scripts/requirements.txt` and `src/backend/api/requirements.txt`, so rowcount-after-execute_values is reliable across page boundaries). Pinned the `reactivate_job` contract as "row MUST exist" in its docstring (zero production callers in-repo today; all current tests pre-insert), kept the WARNING-on-`affected==0` per pass-1 semantics, and amended the warning message to explicitly call out "contract violation". Resolves audit pass-2 Important #2, #3, #5.

**Do not revert (new in this pass):**

- The empty-string `source_id` ValueError guards in `scripts/shared/database.py`, `scripts/shared/incremental.py::update_existing_jobs`, and `src/backend/api/services/database.py::get_job_by_id`. Removing them in the name of "simplification" would re-open the silent `WHERE source_id = ''` no-op surface that pass-1's WARN log was only a backstop for. A future caller passing `source_id=""` (e.g. via misconfigured env var, dropped class attr) MUST fail fast at the helper boundary.
- The `reactivate_job` contract is now pinned in its docstring as "row MUST exist". The WARNING-on-miss is intentional and reflects that contract; if the contract ever becomes "miss is recoverable", revisit BOTH the docstring AND the log level.

**Manual action required before merge:**

- None.

**Conflicts with prior audit (not fixed):**

- None.

---

## 2026-05-17 — Review pass 1

---

## 2026-05-17 — Review pass 1

Dispatched 5 code-review agents + 2 production verifiers in parallel.

- **vercel-prod-verifier:** not dispatched (no matching diff signal — diff is backend-only; `api/*.ts`, `vercel.json`, `vercel.ts`, `next.config.*`, `middleware.ts`, `process.env.*` untouched).
- All 7 dispatched agents completed successfully.

### Code-review findings

**Critical:**

- `src/backend/api/tests/test_migration_job_listings_composite_pk.py:281-326` — `test_upgrade_aborts_on_collision_preflight` accepts BOTH abort surfaces (the `DO $$ RAISE EXCEPTION` block OR a `UniqueViolation` from the UPDATE itself). Because the legacy single-column PK is still in force during the UPDATE, the UPDATE always trips `job_listings_pkey` first — meaning the `DO $$` collision-counting block at migration lines 73-93 is effectively dead code, never reached by this test. (pr-test-analyzer Critical #1, silent-failure-hunter Important #1)
- `src/backend/api/tests/test_migration_job_listings_composite_pk.py` (missing test) — the migration's `downgrade()` body has its own `RAISE EXCEPTION` block (lines 106-127) that aborts if re-prefixing greenhouse rows would collide with a non-greenhouse row whose id already equals `'greenhouse_' || <raw>`. There is NO test exercising this path. (pr-test-analyzer Critical #2)

**Important:**

- `src/backend/api/tests/test_fetch_greenhouse_company.py:129-148` — flake root cause is procrastinate_jobs not cleaned in the `procrastinate_open` fixture. The sibling `test_enqueue_greenhouse_fan_out.py` defers fan-out jobs to procrastinate_jobs that are never drained; when this file runs second alphabetically, `_drain()` picks up leftovers and contends with the composite PK. The diff didn't cause it but changes the failure shape (silent ON CONFLICT clobber on `(source_id, id)`). One-line fixture fix mirrors the cleanup pattern from `test_enqueue_greenhouse_fan_out.py:78-85`. (pr-test-analyzer Important #3)
- `scripts/shared/database.py:138-179` (`get_active_job_ids`, `count_active_jobs`) — these filter only by `company`, not `source_id`. The composite-PK change enables multi-source-per-company; today's call pattern in `src/backend/api/tasks/fetch_greenhouse_company.py:101-121` and `scripts/shared/incremental.py:240` will silently miscount `new_jobs_count` and emit no-op miss-increments when that becomes true. Latent bug — recommend adding `source_id` parameter to these helpers in-scope. (silent-failure-hunter Important #3+#4, type-design-analyzer Important #1)
- `scripts/shared/database.py:360-471` (bulk helpers) — `update_last_seen` etc. log `len(job_ids)` not `cursor.rowcount`, so a source_id/id mismatch silently no-ops with misleading logs. Cheap fix: log `cursor.rowcount` and warn on divergence for non-empty input. (type-design-analyzer Important #2, silent-failure-hunter Suggestion #8)
- `src/backend/api/tests/test_jobs_router.py:72-83` — by-id route tests don't assert composite-key disambiguation. No test proves two jobs with the same `id` but different `source_id` are correctly disambiguated by the route, nor that a mismatched `source_id` for a real `id` returns 404. Without this, a regression that drops `source_id = %s` from the WHERE clause would silently pass. (pr-test-analyzer Important #6)
- `scripts/tests/integration/test_database.py` (missing tests) — `get_jobs_exceeding_miss_threshold`, `mark_jobs_closed`, `update_last_seen`, `increment_consecutive_misses`, `reactivate_job`, `insert_jobs_batch` all gained source_id scoping but no cross-source test asserts "operating on source A doesn't touch source B's rows of the same id". A regression that drops `source_id = %s AND` from any of these would not be caught. (pr-test-analyzer Important #5)
- `src/backend/api/tests/test_migration_job_listings_composite_pk.py:230-274` — `test_composite_pk_enforced_after_upgrade` proves the constraint via raw INSERT + UniqueViolation but does NOT prove that `_UPSERT_ON_CONFLICT` targets the composite constraint. A revert of `ON CONFLICT (source_id, id)` to `ON CONFLICT (id)` would fail Postgres at parse time, but no test in the diff directly catches that scenario. (pr-test-analyzer Important #4)
- `src/backend/alembic/versions/20260517_213835_ebb479b7eed5_*.py:13-19` — module docstring claims "RAISE EXCEPTION guards in both directions abort the migration **before any destructive write**". Inaccurate: upgrade order is NULL-check → destructive UPDATE → post-rewrite collision check → PK swap. The transaction rolls back on abort (which IS the safety property), but the literal claim is wrong. (comment-analyzer Important #1)
- `src/backend/alembic/versions/20260517_213835_ebb479b7eed5_*.py:70-72` — comment "Mirror of the e6cbbb3c2f17 pattern" is misleading. `e6cbbb3c2f17` runs its collision check **before** the destructive UPDATE; this migration runs it **after**. (comment-analyzer Important #2)
- `src/backend/api/models.py:41` + `src/backend/api/routers/jobs.py:28` — `source_id` is stringly-typed everywhere (`str`/`str = Path(max_length=100)`). The closed set is exactly `{"greenhouse_api", "google_scraper", "apple_scraper", "microsoft_scraper"}`; PLAN Decisions Locked treats this as finite. A `Literal[…]` would close the gap, and there's prior art in the same file (`SignupProvider`). The route currently does a real DB query for any garbage source_id. (type-design-analyzer Important #3)

**Suggestion / FYI:**

- `src/backend/CLAUDE.md` API Endpoints section still lists `GET /api/jobs/{id}`; should be `/{source_id}/{id}`. Picked up by `/document-release` post-merge or addressable here. (code-reviewer FYI)
- Migration downgrade pre-flight only checks Greenhouse↔non-Greenhouse `'greenhouse_' || id` collisions, not two distinct non-Greenhouse sources sharing a raw id. Real-world risk is low. (code-reviewer FYI)
- `SOURCE_ID` is duplicated as class attribute in 3 scrapers and a module constant in `greenhouse_client.py` with no shared registry. (type-design-analyzer Suggestion #4+#5, silent-failure-hunter Suggestion #5)
- `BaseScraper` docstring doesn't list `SOURCE_ID` in "subclasses must implement". (comment-analyzer Suggestion)
- `scripts/ARCHITECTURE.md:297,302-305` shows pre-PR function signatures — out-of-sync. (silent-failure-hunter Nit #9)

### Production-environment findings

**Critical:**

- None.

**Important:**

- **Prod has ZERO `greenhouse_api` rows.** Distinct `source_id` values in `job_listings`: `apple_scraper` (7,515), `google_scraper` (4,180), `microsoft_scraper` (2,677), `greenhouse_api` (0). The `companies` table is seeded with 45 Greenhouse boards but `procrastinate_jobs` for queue `greenhouse_fetch` is empty and `procrastinate_periodic_defers` is empty. This migration is safe to deploy (UPDATE is a no-op), but it surfaces an upstream incident: the Greenhouse fan-out cron from PR #110 has either never registered or is silently failing on every tick. **DEPLOY.md §Verification check "WHERE id LIKE 'greenhouse_%' = 0" will look identical whether the cron worked-and-was-rewritten or never-ran.** Recommend (a) investigating the Greenhouse worker post-merge, (b) tightening DEPLOY.md verification to assert `count WHERE source_id='greenhouse_api'` is non-zero within N minutes of worker start. **NOT BLOCKING THIS PR.** (postgres-prod-verifier Important #1)
- Postgres major-version drift: prod runs **17.9**, local/CI runs **15.15** (per `docker-compose.yml`). No 17-only features in this migration, but a systemic issue worth flagging. (postgres-prod-verifier Important #3)
- ALTER TABLE PK rebuild takes ACCESS EXCLUSIVE lock on `job_listings`. Current heap 7.86 MB / 14,372 rows / 888 kB PK index — sub-second on Railway. Lifespan boot adds ~8s today (well under Railway's 300s healthcheck default). No risk at current scale; documented for the day `job_listings` crosses ~1 GB. (postgres-prod-verifier Important #2, railway-prod-verifier Important #2)
- DEPLOY.md §Rollback claims `alembic downgrade -1` is the rollback path, but does NOT make clear that **Railway's deploy-rollback UI does NOT run downgrade automatically** — `apply_alembic_migrations()` in `src/backend/api/migrations.py:78-98` only calls `command.upgrade(cfg, "head")`. The operator MUST run `alembic downgrade -1` manually against prod (via Railway shell or `psql $DATABASE_URL`) BEFORE clicking the UI rollback button. Recommend a clarifying one-liner in `DEPLOY.md:144-151`. (railway-prod-verifier Important #3)
- Pre-existing pool-exhaustion errors are flooding the currently-live Railway deploy (`RuntimeError: Timed out waiting for a database connection`, log stream rate-limited "Messages dropped: 3873"). This PR does NOT introduce new DB-bound request-path code (only adds a parameter to the existing query) and will not make the situation worse, but lands on a degraded backend. Tracked under [Railway backend health](project_railway_backend_health.md). **NOT BLOCKING THIS PR.** (railway-prod-verifier Important #1)

**Suggestion:**

- After Greenhouse load arrives, EXPLAIN `WHERE source_id = ... AND id IN (...)` to confirm the composite PK index is used (it should be — `source_id` is the leading column). (postgres-prod-verifier Suggestion)
- One-line comment in the downgrade body explaining "intra-`greenhouse_api` collisions are impossible because the composite PK guarantees `id` uniqueness within `source_id='greenhouse_api'`" would help future readers. (postgres-prod-verifier Suggestion)

**Could not verify:**

- Railway container memory % / CPU % usage trend (Railway MCP `get-logs`/`list-deployments` surface does not expose container resource metrics; check dashboard Metrics tab manually). (railway-prod-verifier)
- Live ALTER TABLE lock duration on Railway's actual IO (cannot benchmark without running the migration). (postgres-prod-verifier)

### Deferred (not fixing this pass)

- Centralizing `SOURCE_ID` into a shared registry (new `src/backend/api/services/source_ids.py` or similar). Larger refactor than this PR's stated scope; flag for a follow-up.
- Adding `SOURCE_ID: ClassVar[str]` to `BaseScraper`. Out of PR scope.
- Updating `scripts/ARCHITECTURE.md`. Out of PR scope; handled by `/document-release`.
- Updating `src/backend/CLAUDE.md` API Endpoints section. Out of PR scope; handled by `/document-release`.
- Bumping `docker-compose.yml` Postgres image to 17. Out of PR scope; separate concern affecting all migrations.
- Investigating pre-existing pool exhaustion and silently-broken Greenhouse cron. Separate incidents, surface to user in PR body.

### Implementation applied

- **`fefe5f4` Review pass 1: reorder migration collision pre-flight + downgrade test** — Moved upgrade's `DO $$ RAISE EXCEPTION` collision check BEFORE the destructive `UPDATE ... regexp_replace(...)` so the descriptive `'collisions ... aborting'` message is the operator's first signal. The pre-flight now simulates the post-rewrite shape via a CTE (`CASE WHEN source_id = 'greenhouse_api' THEN regexp_replace(id, '^greenhouse_', '') ELSE id END`). Tightened `test_upgrade_aborts_on_collision_preflight` to assert the descriptive message only (no more accepting the legacy single-column-PK UniqueViolation surface). Added `test_downgrade_aborts_on_collision_preflight` exercising the downgrade-side `RAISE EXCEPTION` block with `(google_scraper, greenhouse_42)` + `(greenhouse_api, 42)` seeded at head — asserts the descriptive message fires AND the composite PK + both rows are preserved. Updated migration module docstring + collision-block comment so both accurately describe the new ordering. Resolves audit Critical #1, Critical #2, Important #9.

- **`9c0f2a8` Review pass 1: source-scope active-jobs helpers + cross-source tests + rowcount logs** — Added `source_id: str` parameter to `get_active_job_ids` and `count_active_jobs` in `scripts/shared/database.py` (WHERE adds `source_id = %s AND`). Updated all three callers in `src/backend/api/tasks/fetch_greenhouse_company.py` to pass `SOURCE_ID` and the one in `scripts/shared/incremental.py` to pass the resolved `source_id`. Logged `cursor.rowcount` (with a `logger.warning` on divergence for non-empty inputs) in `update_last_seen`, `increment_consecutive_misses`, `mark_jobs_closed`, `reactivate_job` to surface silent source_id-mismatch no-ops in Railway logs. Added `TestSourceScopedHelpersCrossSource` and `TestActiveJobIdsCrossSource` to `scripts/tests/integration/test_database.py` proving source-A operations on a shared `id` never touch source-B's row (one test per helper). Resolves audit Important #4, #5, #6, #7.

- **`17cee0f` Review pass 1: composite-key router tests + fan-out fixture cleanup** — Added `test_get_job_disambiguates_same_id_across_source_ids` and `test_get_job_returns_404_when_source_id_mismatches_real_id` to `src/backend/api/tests/test_jobs_router.py` proving the composite `(source_id, id)` key is correctly threaded through the by-id route. Fixed cross-file flake in `test_fetch_greenhouse_company.py` by adding `DELETE FROM procrastinate_jobs WHERE task_name = 'fetch_greenhouse_company'` to the `procrastinate_open` fixture (mirrors `test_enqueue_greenhouse_fan_out.py:78-85`). Resolves audit Important #3 and the disambiguation portion of #4.

- **`bb74a6a` Review pass 1: DEPLOY.md rollback warning about UI-only rollback** — Added a leading sentence to the Rollback section warning that Railway's deploy-rollback UI does NOT automatically run `alembic downgrade -1` — the operator MUST run it manually against prod (via Railway shell or `psql $DATABASE_URL`) BEFORE clicking the UI rollback button. Resolves audit production-finding Important (railway-prod-verifier #3).

**Do not revert (new in this pass):**

- The upgrade migration's collision pre-flight is now ORDERED BEFORE the destructive `UPDATE`. The test `test_upgrade_aborts_on_collision_preflight` and the operator-facing language in DEPLOY.md ("Symptoms → causes" table) both DEPEND on this ordering. Reverting to "UPDATE → check" would re-introduce the original problem where the legacy single-column PK trips first and the descriptive `DO $$ RAISE EXCEPTION` block becomes unreachable dead code.
- `get_active_job_ids` and `count_active_jobs` now take `source_id` as a positional argument BEFORE `company`. Any external caller (none exist in-repo) would need updating.

**Manual action required before merge:**

- None.

**Conflicts with prior audit (not fixed):**

- None (this is pass 1).

