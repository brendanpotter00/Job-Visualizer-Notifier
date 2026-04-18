# Migration Prod-Ready PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-04-18 — Review pass 1

### Findings

**Critical:**
- `docs/implementations/migrationProdReady/DEPLOY.md:19-31` — Pre-deploy "Applied: 2 / 4" expectation is wrong. This PR introduces the tracking table; first run will show `0/4`. The "less than 2/2, stop" guard will cause an operator to halt the deploy. (agent: comment-analyzer)
- `scripts/shared/migrations/runner.py:66-83` — `_advisory_lock` finally clause: if `pg_advisory_unlock` or `conn.commit()` raises, the "Released" log line never fires and the exception masks any upstream error. Wrap the unlock/commit in its own try/except and log outcome explicitly. (agent: silent-failure-hunter)
- `scripts/shared/database.py:523-530` — `get_all_active_jobs` uses `hasattr(value, 'isoformat')` which silently no-ops on unexpected types (`bytes`, `Decimal`, unexpected `str` values), hiding schema drift. Narrow to `isinstance(datetime)`, raise on non-None unexpected types. This mirrors the "correctness over don't-crash" user feedback memory. (agent: silent-failure-hunter)
- `scripts/shared/migrations/0003_posted_on_timestamptz.py:29-57` and `0004_job_timestamps_timestamptz.py:47-68` — Missing-table/column path produces `UndefinedTable`/`UndefinedColumn` with no migration context. Raise contextual RuntimeError naming table/env/migration when `_column_type` returns None. (agent: silent-failure-hunter)
- `scripts/tests/integration/test_database.py:91-94` — Cleanup comment describes the wrong failure mode (claims 0003 would run against missing table; actually the table isn't recreated because migrations are already tracked as applied). Rewrite. (agent: comment-analyzer)

**Important:**
- `scripts/shared/migrations/runner.py:74, 184` — `SET LOCAL` requires non-autocommit mode to take effect. Add an assertion or explicit `BEGIN` so a caller that enables autocommit gets a clear failure rather than a silently ignored timeout. (agents: code-reviewer, silent-failure-hunter)
- `docs/implementations/migrationProdReady/DEPLOY.md:80` — Says `psycopg2.LockNotAvailable`; operators will grep logs for the actual message "canceling statement due to lock timeout". Document both the class name and the log string. (agent: code-reviewer)
- `scripts/tests/unit/test_migration_runner.py:20` — Imports `from scripts.shared.migrations import runner`; the convention elsewhere in the test tree is `from shared.migrations import runner`. Align. (agent: code-reviewer)
- `scripts/shared/migrations/runner.py:178-196` — Log wall-clock elapsed time per migration. A 250s migration in a 5-migration batch is currently indistinguishable from a fast one without this. (agent: silent-failure-hunter)
- `scripts/migrate.py:36-38` — `_connect` has no error handling. psycopg2 errors at connect time surface as opaque tracebacks at 2am. Wrap with a clear stderr message + `sys.exit(2)`. (agent: silent-failure-hunter)
- `scripts/shared/migrations/0004_job_timestamps_timestamptz.py:47-52` — If `_column_type` returns None (column missing), fall-through to `_scan_malformed` raises opaque UndefinedColumn. Raise named error first. (agent: silent-failure-hunter, merged with Critical #4)
- `scripts/shared/database.py:523-525` — Normalization comment doesn't flag the `Z` → `+00:00` format change. Today's callers don't care but it's a silent wire-format shift. Note it. (agent: comment-analyzer)
- `scripts/shared/migrations/runner.py:71-73` — Comment claims "sharing the pool"; the init_schema caller uses a dedicated temp_conn that's never pooled. Fix to describe the actual failure mode (setting leaks to next tx on same connection). (agent: comment-analyzer)
- `docs/implementations/migrationProdReady/DEPLOY.md:60-65` vs `runner.py:202` vs `migrate.py:114` — `--to` inclusive vs exclusive wording is inconsistent across three sources. Unify. (agent: comment-analyzer)
- `scripts/shared/migrations/0004_job_timestamps_timestamptz.py:12-13` — Docstring says "USING posted_on::timestamptz" but 0004 doesn't touch `posted_on`. Copy-paste leftover from 0003. (agent: comment-analyzer)
- `src/backend/api/tests/test_jobs_router.py:150-175` — ISO 8601 serialization test covers `createdAt`/`firstSeenAt`/`lastSeenAt` but skips `postedOn`/`closedOn` (also converted to timestamptz). Add a seeded job with those fields non-null and extend the regex loop. (agent: pr-test-analyzer)
- `scripts/tests/integration/test_database.py` TestTimestamptzColumns — Add a `test_get_all_active_jobs_returns_iso_string_timestamps` asserting the `datetime.isoformat()` conversion actually produces ISO 8601 strings parseable via `fromisoformat`. Without this, `get_all_active_jobs` could silently regress to returning datetimes (Pydantic `str` coercion might still pass repr-style strings). (agent: pr-test-analyzer)

**Deferred (not fixing this pass):**
- Test #3 — add `SHOW statement_timeout` / `lock_timeout` assertions to verify the timeout values take effect. Valuable but requires introspection plumbing; defer to a follow-up.
- Test #4 — add `statement_timeout` to `migrate_down`. The PLAN treats downgrade as operator-run not lifespan-startup; acceptable asymmetry, document in runner.py docstring only.
- Test #5 — Parameterized malformed-row guard across 0004's four columns. Same code path as 0003; low regression risk.
- Test #6 — Advisory-lock multi-connection concurrency test. PostgreSQL contract; defer.
- Test #7 — "Pending migrations: []" no-op log. Runbook can state "line is absent on healthy no-op deploys"; either direction works.
- Silent-failure I2 — "Migrations MUST NOT call conn.commit()". Add a one-liner to the runner docstring; no runtime assertion.
- Silent-failure I5 — Widen the pre-flight regex to full ISO 8601 timestamp shape. PLAN deliberately calls this a conservative filter; safer to keep as-is and soften the module docstring wording only.
- Suggestion #8 — `TestPostedOnMalformedRowGuard` cleanup block is dead code; harmless.

### Implementation applied

Commit: `fd363b4` — "Review pass 1: fix silent failures, doc inaccuracies, and coverage gaps"

Files changed:
- `docs/implementations/migrationProdReady/DEPLOY.md` — first-run 0/4 expectation, LockNotAvailable class + log string, unified `--to` semantics
- `scripts/migrate.py` — `_connect` error handling with masked DB URL, `--to` help text
- `scripts/shared/database.py` — narrowed `isinstance(datetime)` normalization in `get_all_active_jobs` with `TypeError` on unexpected types, comment note on `Z` → `+00:00` shift
- `scripts/shared/migrations/runner.py` — `_require_transactional`, advisory-lock release try/except with explicit `released=<bool>` log, per-migration elapsed wall time, `migrate_down` docstring expanded
- `scripts/shared/migrations/0003_posted_on_timestamptz.py` — named `RuntimeError` on missing table/column
- `scripts/shared/migrations/0004_job_timestamps_timestamptz.py` — named `RuntimeError` on missing column, docstring `USING <col>::timestamptz` fix
- `scripts/tests/integration/test_database.py` — accurate cleanup comment, new `test_get_all_active_jobs_returns_iso_string_timestamps`
- `scripts/tests/unit/test_migration_runner.py` — import convention aligned with sibling tests
- `src/backend/api/tests/test_jobs_router.py` — ISO regex loop extended to `postedOn`/`closedOn` with a seeded job

**Do not revert (new in this pass):**
- `get_all_active_jobs` MUST keep converting tz-aware `datetime` → ISO string. The shared `JobListing` Pydantic model types these as `str`; returning `datetime` directly breaks `JobListing(**row)` construction.
- `_advisory_lock` release path MUST log `released=True/False` and re-raise on unlock failure, not swallow. Silent release failure will mask stuck locks on subsequent boots.
- DEPLOY.md first-deploy expectation stays at `0/4` — the tracking table is introduced by this PR.
- `--to N` semantics: **N is kept, anything >N is reverted** (inclusive keep). Runner, CLI help, and runbook must stay aligned.

Test gates:
- `pytest scripts/tests` — 391 passed
- `pytest src/backend/api/tests` — 128 passed
- `npm run type-check` — clean

---

## 2026-04-18 — Review pass 2

### Findings

**Critical:**
- `docs/implementations/migrationProdReady/DEPLOY.md:47-51` — Deploy-sequence log example still reads `Pending migrations env=prod: [3, 4]` / `Applied 2 migration(s) ... [3, 4]`. After pass 1's `0/4` fix, first-run pending is actually `[1, 2, 3, 4]`. The same runbook now contradicts itself across the Pre-deploy and Deploy-sequence sections. (agent: comment-analyzer)
- `docs/implementations/migrationProdReady/DEPLOY.md:5-7` — Intro still says migrations 0001/0002 are "already applied in prod" which implies they're skipped; after the pass-1 clarification they're _replayed_ as no-ops (0001 via `IF NOT EXISTS`, 0002 via pg_constraint probe). Align intro with lines 29-34. (agent: comment-analyzer)

**Important:**
- `scripts/shared/migrations/0003_posted_on_timestamptz.py:18-26`, `scripts/shared/migrations/0004_job_timestamps_timestamptz.py:36-44` — `_scan_malformed` f-string-injects the column name. Today's callers pass module-local constants, but the helper should enforce the allow-list with an `assert col in _COLUMNS` so a future migration copy-pasting this helper doesn't inherit an injection primitive. (agent: code-reviewer)
- `scripts/tests/integration/test_migrations.py:215-239` — `TestPostedOnMalformedRowGuard` cleanup lives outside a `try/finally`, so if the error-message regex ever drifts and `pytest.raises` misses, the rollback+delete never runs and downstream tests see a partial schema. (agent: code-reviewer)
- `src/backend/api/main.py:27-43` — Lifespan try/except logs "Failed to connect to database" whether the failure is `get_connection()` or a migration error. A RuntimeError from the pre-flight scanner ends up nested under a message that _lies_ about what failed. Split the try/except into connect vs migrate, or rephrase the log. (agent: silent-failure-hunter)
- `scripts/shared/database.py:538-540` — `get_all_active_jobs` has `elif isinstance(value, str): continue` flagged as "legacy" post-migration. In prod this branch should never fire; silently skipping hides schema drift. Log a warning the first time it hits so it surfaces. (agent: silent-failure-hunter)
- `scripts/shared/migrations/0003_posted_on_timestamptz.py:69-73`, `0004_job_timestamps_timestamptz.py:63-67` — Pre-flight error message says "non-ISO-8601 values" but the regex only catches bad prefixes. An ISO-shaped but invalid value like `2026-13-45T99:99:99` passes pre-flight and the ALTER then raises opaque psycopg2 cast errors. Tighten the message (or strengthen the regex — widening is deferred per pass 1; tighten wording here). (agent: silent-failure-hunter)
- `scripts/shared/migrations/runner.py:249` — `migrate_down` docstring one-liner "(exclusive)" contradicts the body that follows (inclusive-keep). Drop "exclusive". Also the "CLI-only" claim is aspirational — replace with explicit "no per-migration statement_timeout" note so the asymmetry with `migrate_up` is documented rather than implied. (agent: comment-analyzer)
- `scripts/shared/migrations/runner.py:216-218` — Comment "conn.commit() ran at the end of the previous migration" is mis-cause; commit does not flip autocommit. Trim to the accurate "a misbehaving migration could flip the flag" rationale. (agent: comment-analyzer)
- `docs/implementations/migrationProdReady/DEPLOY.md:50` — Expected log line `Released migration advisory lock env=prod` is stale; pass 1 changed the release log to include `key=<int> released=<bool>`. Update the example so operator-grep patterns match actual output. (agent: comment-analyzer)
- `scripts/tests/unit/test_migration_runner.py` — Missing `TestRequireTransactional` coverage; the autocommit guard added in pass 1 would silently regress if removed. (agent: pr-test-analyzer)
- `scripts/tests/integration/test_migrations.py` — Missing assertion that the 0003/0004 missing-table/column RuntimeError paths fire with the contextual message. Without it, pass 1's named-error work can silently regress to opaque psycopg2 errors. (agent: pr-test-analyzer)
- `scripts/tests/unit/test_migrate_cli.py` (new file) — Missing coverage for `_connect` failure path and `_mask_db_url` masking invariant. Pass 1 added these specifically for the 2am runbook; no test pins the behavior. (agent: pr-test-analyzer)
- `scripts/tests/unit/test_migration_runner.py::TestAdvisoryLockLogging` — Missing regex assertion on the `Applied migration X in Y.YYs` log format. DEPLOY.md tells operators to grep it; monitoring can silently break on format drift. (agent: pr-test-analyzer)

**Deferred (not fixing this pass):**
- silent-failure #2 — chained-exception context on unlock-after-failure. Real but low-probability; Python's standard `__context__` chain + pass-1's release-failure `logger.exception` is enough for ops.
- silent-failure #4 — `applied` set staleness in the migrate_up loop. Today's INSERT+commit per-iteration prevents double-apply; no live bug.
- silent-failure #5 — wrap migrate_up/down psycopg2 errors at CLI level. `_connect` already covers the most common 2am path; migration errors produce contextual exceptions. Low ROI.
- silent-failure #7 — document crashloop semantics in DEPLOY.md. Railway runbook territory, not this PR.
- code-reviewer #3 — `init_schema` docstring note about advisory lock. Covered sufficiently by `migrate_up` docstring; grep reaches it.
- code-reviewer #4 — `_row_value` helper for dict-vs-tuple polymorphism. Refactor; no regression risk.
- code-reviewer #5 — inline `datetime`/`re` imports in tests. Style; not worth a commit.
- code-reviewer Nit #6 — DEPLOY.md 300s coordination procedure. Runbook could be longer; current text is adequate.
- pr-test-analyzer #3 — `_advisory_lock` failed-release log-line test. Requires cursor-level mocking for a single-line log invariant; ROI low given `released=<bool>` is already asserted in the happy path.
- pr-test-analyzer #6, #7 — idempotent-skip execute() spy and `_mask_db_url` unparseable-input branch. Nice-to-haves; core paths are covered.

### Implementation applied

Commit: `352f524` — "Review pass 2: runbook accuracy, drift warnings, and test lockdown"

Files changed:
- `docs/implementations/migrationProdReady/DEPLOY.md` — intro rephrased (0001/0002 replayed as no-ops), deploy-sequence log example corrected to `[1,2,3,4]` with per-migration elapsed lines and `released=True` in the release log
- `scripts/shared/migrations/runner.py` — `_advisory_lock` docstring notes 30s timeout + LockNotAvailable; leakage comment softened; `migrate_down` docstring rewritten ("target kept", statement_timeout asymmetry explicit); mis-cause "conn.commit() ran" comment trimmed; `_MIGRATION_STATEMENT_TIMEOUT` comment rephrased from "our scale" to the current-table-size language
- `scripts/shared/migrations/0003_posted_on_timestamptz.py` — `_ALLOWED_COLUMNS` frozenset + assertion in `_scan_malformed`, tightened malformed-row error message, module docstring clarifies prefix-scan conservatism
- `scripts/shared/migrations/0004_job_timestamps_timestamptz.py` — assertion in `_scan_malformed`, tightened malformed-row error message
- `scripts/shared/database.py` — `get_all_active_jobs` logs a warning when the str-branch fires post-migration, wire-format `+00:00` shift documented as one-way
- `src/backend/api/main.py` — lifespan startup split into three labeled try-blocks (connect / migrate / pool-init) so a migration failure no longer logs under a "Failed to connect" header
- `scripts/tests/unit/test_migration_runner.py` — `TestRequireTransactional` (3 tests), elapsed-time log regex assertion, `released=True` assertion
- `scripts/tests/integration/test_migrations.py` — `TestSchemaDriftGuards` (3 tests), `TestPostedOnMalformedRowGuard` cleanup wrapped in `try/finally`, match string updated to "ISO 8601 prefix"
- `scripts/tests/unit/test_migrate_cli.py` — new file; covers `_mask_db_url` masking and `_connect` failure exit(2) + stderr contract

**Do not revert (new in this pass):**
- DEPLOY.md deploy-sequence log example shows `[1,2,3,4]` and `released=True`; operator grep patterns key off this exact shape.
- `_scan_malformed` allow-list assertion in 0003/0004 is defense-in-depth for future copy-paste; removing it reopens the injection surface.
- `get_all_active_jobs` schema-drift warning MUST fire on the str-branch post-migration — silent passthrough was the original bug.
- Backend lifespan MUST keep connect / migrate / pool-init as separate try-blocks; collapsing them restores the misleading "Failed to connect" header on migration errors.
- `TestRequireTransactional`, `TestSchemaDriftGuards`, and the elapsed-time log regex assertion are the executable form of pass-1 "do not revert" items — removing them lets those regress silently.

Test gates:
- `pytest scripts/tests` — 401 passed (10 new)
- `pytest src/backend/api/tests` — 128 passed
- `npm run type-check` — clean

---

## 2026-04-18 — Review pass 3

### Findings

**Critical:**
- `docs/implementations/migrationProdReady/DEPLOY.md:128-131` — Stale error-message example. Pass 2 tightened the malformed-row error in `0003`/`0004` to `Migration {name}: cannot convert {table}.posted_on to TIMESTAMPTZ: N row(s) do not match the ISO 8601 prefix '^YYYY-MM-DDT'. Sample ids: [...]`, but the runbook still shows the pre-pass-2 wording. Operators grepping for "non-ISO-8601" will find nothing. (agents: code-reviewer, comment-analyzer)

**Important:**
- `docs/implementations/migrationProdReady/DEPLOY.md:101-106` — "Hung advisory lock" symptom should anchor on the visible `Waiting for migration advisory lock` line and the absence of a matching `Acquired` line — that's the precise observable, not "no Acquired log within 30s." (agent: code-reviewer)

**Suggestions / Nits (deferred):**
- code-reviewer Suggestion — Add a `_release_advisory_lock` helper to dedupe finally clauses across `_advisory_lock` / explicit unlock paths. Cosmetic; won't block ship.
- pr-test-analyzer — All listed gaps (advisory-lock concurrency multi-conn, statement_timeout introspection, idempotent-skip execute-spy) were already deferred in passes 1/2 with documented rationale. No new gaps surfaced.
- silent-failure-hunter — No remaining silent-failure findings; pass-2 fixes (split lifespan blocks, schema-drift warning, allow-list assertions) close the surface.

**Conflicts with prior audit (not fixed):**
- None. Pass-3 fixes touch documentation only and do not contradict any pass-1 or pass-2 "Do not revert" items.

### Implementation applied

Commit: `b2b142c` — "Review pass 3: align DEPLOY.md with tightened pass-2 error message"

Files changed:
- `docs/implementations/migrationProdReady/DEPLOY.md` — Malformed-row example in "Failure modes" rewritten to match the actual `Migration 0003_posted_on_timestamptz: ...` / `Migration 0004_job_timestamps_timestamptz: ...` text emitted by `_scan_malformed`; added clarifying note that the prefix differs by migration. "Hung advisory lock" symptom now anchors on the `Waiting for migration advisory lock` log line so operators have a concrete grep target.

**Do not revert (new in this pass):**
- DEPLOY.md "Malformed ISO 8601 row" example MUST track the exact error string formatted by `_scan_malformed` in `0003_posted_on_timestamptz.py` and `0004_job_timestamps_timestamptz.py`. Diverging again breaks 2am log greps; keep them in lockstep on any future error-string change.
- DEPLOY.md "Hung advisory lock" symptom MUST reference the `Waiting for migration advisory lock` line — that log was added precisely so operators can diagnose stuck deploys without psql access.

Test gates:
- `pytest scripts/tests` — no source changes; not re-run (doc-only PR delta vs pass 2)
- `pytest src/backend/api/tests` — no source changes; not re-run (doc-only PR delta vs pass 2)
- `npm run type-check` — no source changes; not re-run (doc-only PR delta vs pass 2)
