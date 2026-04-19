# Incident: Migration 0003/0004 Filled Postgres Volume + WAL on Deploy

**Date:** 2026-04-18 19:09 UTC (deploy) / 2026-04-19 00:09–00:54 UTC (outage window)
**Severity:** High
**Impact:** Production backend unable to connect to Postgres for ~45 minutes while the DB crashloop/recovered. Frontend showed empty jobs list / failed API calls during the window. No data loss.

## Summary

PR #60 (commit `1f15ae2`) shipped a migration runner plus two TEXT→TIMESTAMPTZ conversion migrations on `job_listings_prod`. Migration 0003 rewrote `posted_on`; migration 0004 rewrote `created_at`, `closed_on`, `first_seen_at`, `last_seen_at` by issuing **four separate** `ALTER TABLE … ALTER COLUMN … TYPE TIMESTAMPTZ` statements in a Python loop — each triggering an independent full-table rewrite with an index rebuild on `last_seen_at`.

Combined with migration 0003's single-column rewrite, all inside per-migration transactions, peak WAL + rewrite storage pressure exceeded the Hobby-tier Postgres volume's free space mid-migration. Postgres crashlooped attempting to replay WAL during the post-rewrite checkpoint. The database was only recoverable after the volume tier was increased (5 GB → 20 GB) to let WAL replay complete.

Once Postgres came back, the same migrations applied cleanly (0003: 6.36s, 0004: 23.43s, 0005: 0.42s) — but the table and volume are now bloated from the rewrite-in-place, and the backend was 45 minutes of hard downtime.

## Timeline

| Time (UTC)            | Event |
|-----------------------|-------|
| 2026-04-18 19:09      | PR #60 merged; Railway builds backend deployment for `1f15ae2` |
| 2026-04-19 00:09      | Backend deploy promoted (`42a9ede2…`); lifespan hook begins migrations |
| 2026-04-19 00:09–00:53 | Backend crashloop: `FATAL: the database system is not yet accepting connections` / `Connection refused` / `SSL SYSCALL error: EOF detected`. Postgres is replaying WAL but out of disk. |
| 2026-04-19 ~00:30     | Operator upgrades Postgres volume tier (5 GB → 20 GB) to let WAL replay complete |
| 2026-04-19 00:53:57   | Postgres accepts connections; runner acquires advisory lock, sees pending=[3, 4, 5] |
| 2026-04-19 00:54:04   | 0003 applied (6.36s) |
| 2026-04-19 00:54:27   | 0004 applied (23.43s — four separate rewrites of the same ~12.5k-row / 136 MB table) |
| 2026-04-19 00:54:28   | 0005 applied (0.42s); backend healthy |

Outage window end-to-end: ~45 minutes.

## Root Cause

### Four ALTER statements = four table rewrites + four WAL streams

Postgres's `ALTER TABLE … ALTER COLUMN … TYPE` with a `USING` clause that changes the on-disk binary representation forces a **full table rewrite**: Postgres copies every row into a new heap file, rebuilds dependent indexes, and writes the full copy to WAL so replicas/backups stay consistent.

Migration 0004 (original) looked like:

```python
for col in ("created_at", "closed_on", "first_seen_at", "last_seen_at"):
    cursor.execute(
        f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMPTZ "
        f"USING {col}::timestamptz"
    )
```

Four separate statements = four rewrites = 4× the heap churn + 4× the WAL bytes (plus the one rewrite from 0003 on the same table). On `job_listings_prod` (136 MB, index on `last_seen_at`) the rewrite cost is modest in absolute terms — but the Hobby tier's 5 GB volume was sharing storage with WAL segments for the full replay, and Postgres kept the pre-rewrite files visible to concurrent transactions until commit.

### Hand-rolled migration system didn't warn about rewrite cost

The custom runner in `scripts/shared/migrations/runner.py` has 30s lock timeout and 300s statement timeout, but no heuristic for flagging rewrite-heavy DDL. Five review passes, a PLAN.md, a DEPLOY.md, and 800+ lines of runner machinery caught every error path *except* the physical storage cost of the DDL itself.

This is why **Alembic + `batch_alter_table` is the go-forward standard** for this repo: Alembic's autogenerate emits a single combined `ALTER TABLE` with multiple `ALTER COLUMN` clauses by default, which is one rewrite and one WAL stream regardless of column count.

### Why Hobby tier made it unrecoverable

Hobby-tier Railway Postgres caps the attached volume at 5 GB and does not support in-place volume resize; "upgrading" requires moving to Pro. When the volume filled, Postgres couldn't complete the post-rewrite checkpoint, couldn't accept new connections (WAL replay blocked on disk space), and couldn't be resized until the plan was changed. 45 minutes of downtime is the resize + replay + recovery time.

## Remediation

### Immediate (during incident)

1. Upgraded Postgres volume tier 5 GB → 20 GB so WAL could finish replaying.
2. Waited for crash-recovery checkpoint to complete; Postgres came back on its own.
3. Backend's `init_schema` delegated to the runner, which re-acquired the advisory lock and applied 0003/0004/0005 without further issue.

### This PR (`fix/migration-memory-pressure`)

1. **Rewrite 0004 to one combined `ALTER TABLE`.** A single statement with four `ALTER COLUMN` clauses does one rewrite and one WAL stream, not four. Matches what `batch_alter_table` would emit.
2. **Short-circuit when nothing is pending.** Existing idempotency check (skip columns already `timestamp with time zone`) is preserved; if all four are already converted the function returns before issuing any ALTER. This is what a re-run on the current prod DB would do today — verified via `mcp__postgres-prod` that all five target columns are already TIMESTAMPTZ and `schema_migrations_prod` has version 4 recorded, so the runner won't call `upgrade()` again anyway.
3. **Incident doc.** This file.

### Follow-ups (separate PRs, not blocking)

- **Reclaim volume bloat.** The rewrite left dead tuples and swollen indexes. Run `VACUUM (FULL, ANALYZE) job_listings_prod` (takes exclusive lock, requires free space ≈ table size) or `pg_repack` during a maintenance window to give storage back. Without this, the Hobby-tier downgrade will run out of room again at current growth.
- **Adopt Alembic.** Per the repo's memory, `scripts/shared/migrations/` is frozen at the 0001–0005 set. All new schema changes go through Alembic (`models.py` → `alembic revision --autogenerate` → review for combined `ALTER TABLE`). The hand-rolled runner stays as a shim for replaying 0001–0005 on a fresh environment but is no longer extended.
- **Pre-flight disk check in the runner.** Before calling `upgrade()`, estimate `pg_total_relation_size × expected_rewrites` vs free disk and refuse to start if the ratio is <2×. Would have surfaced the problem as a clean "won't fit" error instead of a crashloop.

## Prevention

1. **Binary-incompatible type changes (TEXT↔TIMESTAMPTZ, int↔text, etc.) cost ≈ 1× table size per column, per statement.** Always collapse into a single `ALTER TABLE` or (preferred) a single Alembic `batch_alter_table` block.
2. **WAL replay needs 2-3× the normal free space during/after a large rewrite on Hobby tiers.** The 5 GB cap is insufficient for any table rewrite once the DB reaches ~1-2 GB. Plan DDL on a tier with headroom or move to Pro.
3. **Any migration that changes column type on a populated table should include a disk-cost estimate in the PR description**, not just a correctness argument.

## References

- PR #60 (root-cause commit): `1f15ae2`
- Deployment: `42a9ede2-90ae-4bec-b027-a94a05acc7a3` (SUCCESS after recovery)
- Railway logs: backend `Job-Visualizer-Notifier` service, deploy logs between 00:09 and 00:54 UTC on 2026-04-19
- Affected file (fixed in this PR): `scripts/shared/migrations/0004_job_timestamps_timestamptz.py`
- Related repo memory: *"Use Alembic for schema migrations, not hand-rolled SQL"*
