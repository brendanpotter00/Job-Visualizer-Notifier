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

