# Incident: `/api/jobs` Times Out — Homepage Serves No Jobs

**Date:** 2026-07-13 (onset ~11:49 UTC; production restored 15:02 UTC). Postmortem written 2026-08-04, at which point the follow-through work was still unshipped — see "Disposition".
**Severity:** High
**Impact:** `GET /api/jobs` returned HTTP 500 for every caller for roughly 3h15m. The anonymous homepage (`onesecondswe.dev`) fires three concurrent batched requests (`?companies=<~50>&status=OPEN&limit=50000`); all three failed with `psycopg2.errors.QueryCanceled: canceling statement due to statement timeout` after 31–38 s against the 30 s app statement timeout (`api/dependencies.py:28`). The site rendered an empty job list for logged-out and logged-in users alike. Both Railway services stayed healthy throughout — this was a slow query, never a crash — so no alert fired on process health and no restart helped. Non-`/api/jobs` routes (users, features, admin, locations) were unaffected.

## Summary

Two independent performance problems existed in `job_listings` on the morning of 2026-07-13, and the first one found became the assumed cause of the outage. It was not.

**The real cause** was that `_LIST_COLUMNS` — the deliberately "lightweight" column list for the list endpoint — read two sub-fields out of the `details` JSONB with `details->'experience_level'` / `details->'is_remote_eligible'`. Accessing *any* key of a JSONB value forces Postgres to detoast the *entire* value, and `details` is ~10 KB per row because the scrapers duplicate their full raw payload under `details.raw`. For the ~12,262 OPEN rows the homepage's batched query matched, that is ~100 MB of TOAST reads against `shared_buffers = 128 MB`. Warm and alone the query took 769 ms; cold and 3× concurrent — exactly the homepage's access pattern — it thrashed the buffer cache and blew past 30 s.

**The decoy** was index bloat. `idx_job_listings_last_seen` had reached 100 MB for 57,919 rows (~50× bloated; the PK was 5 MB) because the scraper re-stamps `last_seen_at` on every open job on every hourly cycle, and because that column is indexed every one of those ~127.6 M updates was a non-HOT update appending a dead entry to the btree — concentrated at the "most recent" end, precisely where `ORDER BY last_seen_at DESC` starts scanning. This was real, measurable, and getting worse. It was also **not what took the endpoint down**: a `REINDEX INDEX CONCURRENTLY` brought the `ORDER BY last_seen_at DESC LIMIT 5000` query to ~20 ms and `/api/jobs` stayed at 500. The homepage does not use that query shape.

Both were fixed the same day, in that order, by two different PRs — and only the second one restored production. The bloat fix (#222) shipped as Unit 1 of a 4-unit plan and then **stalled with 3 units unshipped**, which is the reason this postmortem is being written three weeks later rather than on the day.

## Timeline

| Time (UTC) | Event |
|---|---|
| 2026-07-13 ~11:49 | Railway HTTP logs begin showing `GET /api/jobs 500` with 31,000–38,000 ms durations. Deploy logs carry `psycopg2.errors.QueryCanceled: canceling statement due to statement timeout` originating in `get_jobs` (`routers/jobs.py:93`). Both Railway services report healthy; CPU and memory are unremarkable. |
| ~12:10 | Investigation opens on the database. `pg_stat_user_tables` shows `job_listings` at **127.6 M** updates with a **0.1 % HOT** ratio. `pg_total_relation_size('job_listings')` is **604 MB** against a **29 MB** live heap. `idx_job_listings_last_seen` is **100 MB for 57,919 rows**; the composite PK covering the same table is 5 MB. |
| ~12:25 | `EXPLAIN` on the per-company query confirms `Index Scan Backward using idx_job_listings_last_seen` serving `ORDER BY last_seen_at DESC LIMIT 5000` (`services/database.py:148`). Theory A — *the bloated index is the outage* — is adopted. The write-amplification mechanism is understood correctly and written up as plan `wiggly-cuddling-cosmos.md`: a narrow `job_freshness` sidecar so the wide, TOAST-heavy parent stops being rewritten every cycle. |
| ~12:40 | **Mitigation applied to prod:** `REINDEX INDEX CONCURRENTLY idx_job_listings_last_seen`. The index rebuilds; the `LIMIT 5000` query drops to **~20 ms**. |
| ~12:45 | **`/api/jobs` is still returning 500.** The mitigation fixed a query the homepage does not run. |
| 14:08 | Live re-verification with Playwright against the anonymous homepage plus Railway deploy logs: the page fires **three concurrent** `GET /api/jobs?companies=<~50>&status=OPEN&limit=50000` batches and all three 500. This is a different query shape from the one that was reindexed — no `LIMIT 5000`, no per-company filter, ~50 companies at once. |
| 14:10:40 | **PR #222 merges** (`2038b53`) — Unit 1 of the sidecar plan: the `job_freshness` table, its composite FK, the `AFTER INSERT` trigger, and the backfill. Purely additive; **no application code reads or writes it**. Deploys cleanly. `/api/jobs` is still down, as expected — Unit 1 changes no query. |
| ~14:20 | Theory B identified by reading `_LIST_COLUMNS` (`services/database.py:120-129`) rather than the query plan: the `jsonb_build_object('experience_level', details->'experience_level', …)` projection touches `details`, which is TOASTed at ~10 KB/row. |
| ~14:35 | **Measured against prod.** The identical batched query with the two `details->` accesses removed runs in **192 ms** (Seq Scan plus the ~12 k correlated locations subqueries, no detoast). With them, warm and alone: 769 ms. Cold and 3× concurrent: >30 s. ~12,262 matched OPEN rows × ~10 KB ≈ **100 MB of TOAST** against `shared_buffers = 128 MB`. Theory B confirmed; plan `idempotent-scribbling-sketch.md` written. |
| ~14:45 | Frontend contract verified before changing the projection: `experience_level` and `is_remote_eligible` are the **only** two `details` sub-fields the list path's consumers read (`backendScraperTransformer.ts:36,39` → `job.department`, `job.isRemote`). Both must keep arriving; the response shape must stay byte-identical. |
| 15:02:43 | **PR #225 merges** (`09bb01e`) — promotes `experience_level` / `is_remote_eligible` to real top-level columns, populated on upsert, and re-points `_LIST_COLUMNS` at the columns instead of `details->`. Railway auto-deploys, Alembic runs the metadata-only `ADD COLUMN` migration on startup. **`/api/jobs` returns 200. Production restored.** |
| ~15:30 | PR #224 (Units 2–3 of the sidecar: write path + read path, plus the `a3c32c2aa4d3` re-sync migration) is pushed as a **draft**. It is not merged. Unit 4 (the contract migration) is worked on in a separate worktree at `.claude/worktrees/job-freshness-sidecar/` and never committed. |
| 2026-07-13 → 08-04 | The sidecar plan sits at Unit 1 of 4. The expand migration keeps the sidecar structurally correct — the trigger seeds every new listing, the FK prevents orphans — but nothing reads or writes it, so `job_listings` keeps absorbing the full write load and `idx_job_listings_last_seen` re-bloats from the 2026-07-13 REINDEX. |
| 2026-08-04 | Re-verification for this postmortem (read-only against prod). The index has re-bloated **27.8 MB → 46.8 MB** (438 → **737.7 bytes/row**) in the ten days since 2026-07-25, at a 0.1 % HOT rate over ~**182 M** lifetime updates. The sidecar infrastructure is verified sound after 22 days: the `job_listings ⟕ job_freshness` anti-join is **0**, the trigger is seeding every new listing, the backfill is complete. The Unit-4 worktree is found **pruned**, its uncommitted work lost. |
| 2026-08-04 | Disposition decided: **finish the sidecar, full contract, two deploys.** See below. |

## Root Cause

### The outage: JSONB detoast on the list path

`_LIST_COLUMNS` existed specifically to keep the list response small — it projects two `details` sub-fields and an empty `ai_metadata` instead of the whole row, cutting per-row payload from ~10 KB to ~500 bytes. That reasoning is sound at the *network* layer and exactly backwards at the *storage* layer:

```sql
jsonb_build_object(
  'experience_level',   details->'experience_level',
  'is_remote_eligible', details->'is_remote_eligible') AS details
```

Postgres cannot fetch one key of a TOASTed JSONB without materializing the whole value. There is no partial-detoast path. So a projection written to *avoid* sending 10 KB per row still *reads* 10 KB per row off TOAST. The "lightweight" column list was doing the single most expensive thing in the query.

That cost was invisible for as long as the result set was small. The batched call shape that made it fatal — `?companies=<~50>&limit=50000`, three at a time — was itself introduced by the fix for a *previous* incident (see "Upstream" below), and it grew the matched set to ~12,262 rows. At ~10 KB each that is ~100 MB of TOAST reads per request against a 128 MB `shared_buffers`. One such query warm and alone fits, barely, at 769 ms. Three concurrent, cold, evict each other's pages and re-read continuously; the query never converges inside 30 s.

The fix (#225) removes the read entirely: `experience_level` and `is_remote_eligible` become real nullable columns on `job_listings`, written by the upsert path, and `_LIST_COLUMNS` reads the columns. The emitted JSON object is byte-identical, so nothing downstream changed. `get_job_by_id` was deliberately left alone — a single-row detoast is cheap, and the detail view still needs the full `details`.

### The decoy: write amplification on `idx_job_listings_last_seen`

`update_last_seen` (`scripts/shared/database.py:526`) re-stamps `last_seen_at` on every open job on every hourly scrape cycle. Because `last_seen_at` carries an index, none of those updates can be HOT: each one writes a new heap tuple *and* a new index entry, and the dead entries pile up at the high end of the btree — the exact region a `DESC` scan enters first. Over ~127.6 M updates the index reached 100 MB for 57,919 rows while the table's own live heap was 29 MB.

This is a genuine defect with a real cost, and it scales with *number of scrape cycles × number of tracked jobs*, so it worsens as the product grows. It is simply not the thing that returned 500s on 2026-07-13, and the REINDEX proved that within five minutes — the reindexed query got 50× faster and the endpoint did not move.

### Why the wrong theory was adopted first

Nothing about the investigation was careless; the ordering was just unlucky. The database *volunteered* the bloat — a 100 MB index on a 29 MB table is conspicuous in any size query, and `EXPLAIN` on the first query anyone reaches for (`get_jobs`' per-company path) named that exact index. The real cause was in application source, not in any plan or catalog view, and the query that actually failed had to be reconstructed from the frontend's behavior before it could be explained. The diagnostic lesson is in "Lessons": reproduce the failing request before explaining it.

### Verdict table

| | Theory A — index bloat | Theory B — `details->` detoast |
|---|---|---|
| **Claim** | `idx_job_listings_last_seen` bloated ~50× makes the `ORDER BY last_seen_at DESC` scan exceed 30 s | Reading `details->'…'` detoasts ~10 KB/row; ~12,262 rows ≈ 100 MB vs `shared_buffers` 128 MB |
| **Evidence for** | 100 MB index / 57,919 rows; 604 MB total relation vs 29 MB live heap; 127.6 M updates at 0.1 % HOT; `EXPLAIN` shows `Index Scan Backward` on it | Same query without the two `details->` accesses: **192 ms**. With them, warm + alone: 769 ms; cold + 3× concurrent: **>30 s** |
| **Test performed** | `REINDEX INDEX CONCURRENTLY` on prod | Removed the JSONB access from the projection and re-`EXPLAIN`ed on prod |
| **Result of test** | Target query **20 ms**. `/api/jobs` **still 500** | Query **192 ms**. Deployed as #225 → `/api/jobs` **200** |
| **Verdict** | **Real defect. NOT the outage.** Wrong query shape — the homepage never runs `LIMIT 5000` | **The outage.** Confirmed by measurement before the fix and by production recovery after it |
| **Disposition** | Durable fix = the `job_freshness` sidecar (this ticket). Bloat has already returned since the REINDEX | Shipped and closed in #225 |

### The two PRs

| PR | Merged (UTC) | What it did | Effect on the outage |
|---|---|---|---|
| **#222** (`2038b53`) | 2026-07-13 **14:10:40** | Unit 1 of the sidecar plan: `job_freshness` table, composite FK `ON DELETE CASCADE`, `AFTER INSERT` trigger, backfill. Purely additive — no app code reads or writes it | **None, by design.** Addresses Theory A. Changes no query the API runs |
| **#225** (`09bb01e`) | 2026-07-13 **15:02:43** | Promotes `experience_level` / `is_remote_eligible` to real columns; `_LIST_COLUMNS` reads columns, not `details->` | **This is the fix.** `/api/jobs` returned 200 on the deploy |

The 52 minutes between them is the window in which the correct diagnosis was reached. It is worth being explicit that #222 shipped *first* and did *not* help: it is the fix for the problem that was found first, not for the problem that was happening.

### Upstream: the 2026-05-17 incident that shaped the failing query

The batched request shape that made the detoast fatal was introduced by the fix for `docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md`. That incident collapsed a 49-way per-company fanout into a single batched `/api/jobs?companies=<csv>` call — the right architectural call, and it fixed the pool exhaustion. To make the batched response complete, the `limit` cap was raised from `le=10000` to `le=50000` and the frontend's batched default from 5000 to 50000.

That raise had no bounding filter behind it. The result set became "every OPEN job across ~50 companies", which is ~12,262 rows and grows with every company onboarded. Under the old per-company `LIMIT 5000` shape the detoast cost was survivable; under the new shape it was not.

The May postmortem *named this exact risk* in its Lessons:

> "Where a query param's semantics depend on whether another param is present, name the limits accordingly (`limit_per_company`, `total_limit`) **or push the time/recency filter into SQL so the result set bounds itself**."

That recommendation was never implemented. `/api/jobs` still has no server-side recency bound; the frontend fetches everything OPEN and filters by date client-side. Had the recency filter been pushed into SQL in May, the 2026-07-13 result set would have been a fraction of 12,262 rows and the detoast would very likely never have crossed the timeout. This remains open and is tracked as **sibling ticket 1.3**; it is the highest-value item to come out of this incident, because it is the one that would have prevented it.

## Fixes Applied

### Shipped 2026-07-13

- **#225 — the outage fix.** `experience_level` / `is_remote_eligible` promoted to real nullable columns on `job_listings` (metadata-only `ADD COLUMN`, single combined `ALTER TABLE` per the rule in `docs/implementations/alembicMigration/DEPLOY.md`, one-time backfill via `op.execute`); write path persists them on upsert; `_LIST_COLUMNS` reads them instead of `details->`. Response shape unchanged. Revision `5ee285a3c724`.
- **#222 — Unit 1 of the sidecar (expand).** `job_freshness(source_id, id, last_seen_at, consecutive_misses)`, composite FK to `job_listings(source_id, id)` `ON DELETE CASCADE`, `AFTER INSERT` trigger seeding each new listing from `first_seen_at`, and a race-free backfill (table → FK → trigger → `INSERT … SELECT … ON CONFLICT DO NOTHING`). Revision `01fef5c9c582`.
- **Manual `REINDEX INDEX CONCURRENTLY idx_job_listings_last_seen`** against prod. A stopgap by construction — see the 2026-08-04 re-measurement.

### Shipped 2026-08-05

- **PR #224 — Units 2–3 (migrate).** Write path (`scripts/shared/database.py`) repointed so `job_listings` is no longer touched for freshness; read path (`api/services/database.py`, `api/services/location_admin.py`) joins `job_freshness`. Data-only re-sync migration `a3c32c2aa4d3` corrects the drift accrued during the Unit-1-only window, with `lock_timeout = 5s`. Plus the double-head fix and the guard test below. Merged `0380e8a`, live in prod 04:39 UTC.
- **PR-B — Unit 4 (contract), second deploy. SHIPPED 2026-08-05.** `DROP INDEX idx_job_listings_last_seen; ALTER TABLE job_listings DROP COLUMN last_seen_at, DROP COLUMN consecutive_misses;` (metadata-only drop; dropping the index *frees* ~46 MB) and removal of the dead columns from `db_models.py`. Revision `18fe9c20a8fd`. Gated on the post-cutover prod verification: zero pre-cutover freshness re-stamps since 04:39 UTC, HOT rate 0.115 % → ~91 %, both `job_listings ⟕ job_freshness` anti-joins 0, `freshness_behind = 0`. Rides along with `idx_job_listings_problem_jobs`, a partial index whose predicate mirrors the admin problem-jobs filter exactly; it removes the full seq scan (prod cost 14,627) from that endpoint's bounded `count(*)` after Unit 3 moved its `ORDER BY` onto the sidecar (13.6 ms → 206 ms regression). The paged half keeps its nested-loop plan either way — the planner cannot estimate `btrim(location) <> ''`.

### The double-head hazard fixed in passing

PR #224's migration `a3c32c2aa4d3` was authored on 2026-07-13 with `down_revision = '01fef5c9c582'`. So was #225's `5ee285a3c724` — both branched off Unit 1 on the same afternoon. #225 merged, `a7c31d9e0b46` later stacked on top of it, and #224 sat unmerged with a stale parent. Merging it as-is would have produced **two Alembic heads**, and `api/migrations.py:95` runs `command.upgrade(cfg, "head")` — *singular* — inside the FastAPI lifespan and re-raises on failure. That is a crash-on-boot on Railway, not a warning.

Resolved by **re-parenting** `a3c32c2aa4d3` onto `a7c31d9e0b46` during the rebase, not by `alembic merge` — this repo's history is strictly linear and has no merge-revision precedent. Re-parenting is safe here because the revision is data-only: it depends on `job_freshness` (created by an ancestor either way) and on the `job_listings` freshness columns (still present until PR-B drops them).

A DB-free regression guard now runs in the ordinary backend test step: `src/backend/api/tests/test_alembic_single_head.py` asserts `len(ScriptDirectory.get_heads()) == 1` and that every revision is reachable from that head. It needs no Postgres and no `TEST_DATABASE_URL`, so it fires in CI on the branch that would fork the graph — the only cheap moment to catch this.

## Disposition: finish the sidecar

Three options were weighed on 2026-08-04 — **abandon** the sidecar (revert to Unit-1-only and live with periodic REINDEX), **hybrid** (ship Units 2–3, defer Unit 4 indefinitely), or **finish** (Units 2–3 now, Unit 4 as a second deploy). The decision is **finish**.

1. **The urgent hazard is fixed either way.** The double-head crash-on-boot had to be resolved no matter which option won; re-parenting during this rebase is that fix. It is not an argument for any particular option, and it is listed first so it is not mistaken for one.
2. **The infrastructure is proven, not theoretical.** 22 days in prod, verified read-only on 2026-08-04: the `job_listings ⟕ job_freshness` anti-join is 0, the trigger seeds every new listing, the backfill is complete. The risky part of a table split — the two halves drifting — has already been running correctly under production write load for three weeks.
3. **The problem is real and compounding.** `idx_job_listings_last_seen` went 27.8 MB → 46.8 MB (438 → 737.7 bytes/row) in ten days, at 0.1 % HOT over ~182 M lifetime updates. The REINDEX bought weeks, not a fix. Sibling ticket **1.2** adversarially verified the alternatives and refuted every one of them — `fillfactor` tuning, autovacuum tuning, and dropping the index outright are all inadequate; the sidecar is the only durable fix.
4. **~80 % of the work already exists at review quality** in PR #224 — write path, read path, re-sync migration, and tests.
5. **Abandoning throws that away** and buys permanent human REINDEX toil on a schedule nobody owns, against a table that keeps growing.
6. **Hybrid fails the epic's acceptance criterion** that no half-migrated state remains. Deferring Unit 4 leaves `job_listings.last_seen_at` as a live-looking column that nothing maintains — a trap for the next reader — plus the 46.8 MB index still on disk and still being written to.
7. **Risk is bounded and the blast radius is understood.** The re-sync migration is data-only with `lock_timeout = 5s`; PR-B's column drops are metadata-only; every revision has a real `downgrade()`; and prod is verified between the two deploys before the contract lands.

### Deviation from the original plan: no autovacuum reloptions on `job_listings`

`wiggly-cuddling-cosmos.md` (Unit 4) specified setting `autovacuum_vacuum_scale_factor = 0.05` on `job_listings` alongside the column and index drops. **This will not be done.** Ticket 1.2's verification refuted autovacuum tuning as a fix for this table — the problem is the rate of non-HOT updates, not vacuum's aggressiveness, and vacuum cannot outrun index churn it is not the cause of. Ticket 1.2 requires that `job_listings.reloptions` stay `NULL`. PR-B will drop the columns and the index and set no storage parameters. (The aggressive settings on the *sidecar* table itself, applied by the Unit 1 migration, stand — that table is small enough for them to work as intended.)

### Deviation: Unit 4 was lost and is being regenerated

Unit 4 was implemented in a parallel git worktree at `.claude/worktrees/job-freshness-sidecar/` and **never committed**. The worktree was pruned at some point before 2026-08-04 and the work is gone. It is being **regenerated from scratch** in PR-B rather than recovered. This is cheap — the contract migration is autogeneratable from `db_models.py` (remove the two columns, `alembic revision --autogenerate`, review per the combined-ALTER rule) and the index drop is one `op.execute` — so recovery was not worth attempting. Noted here because "Unit 4 exists somewhere" would otherwise be a reasonable and wrong assumption for the next reader.

## Lessons

- **Reproduce the failing request before explaining it.** The investigation `EXPLAIN`ed a query the failing caller never ran. `/api/jobs` has two very different shapes — per-company `LIMIT 5000` and batched `companies=<50> LIMIT 50000` — and only the second was down. Three hours and one production DDL statement went into a query nobody was executing. Start from the actual request (URL, params, concurrency) captured from logs or the browser, and only then look at plans.
- **A fix that doesn't fix it is data.** The REINDEX making the target query 50× faster while the endpoint stayed at 500 falsified Theory A immediately and conclusively. That signal was available at ~12:45 but the theory was not abandoned until ~14:20 — #222 was still merged at 14:10 under the old theory. When a mitigation lands cleanly and the symptom does not move, treat the theory as refuted right then, not as "the fix must be incomplete."
- **Projecting fewer JSONB keys does not read fewer bytes.** There is no partial detoast. `details->'x'` costs the same as `details` — the full TOASTed value, per row. Any per-row JSONB access inside a large result set is a full-value read multiplied by the row count. If only a couple of scalar sub-fields are needed on a hot path, they belong in real columns; that is what #225 did and it should be the default reflex, not an incident response.
- **Raising a `limit` cap without a bounding filter defers the failure, it doesn't remove it.** `le=10000 → le=50000` in May was necessary for correctness of the batched response and quietly made the result set unbounded in practice. The May postmortem said to push the recency filter into SQL; nobody did, and this incident is the bill. **Sibling ticket 1.3.** When a cap is raised because a response was truncated, the follow-up question is always "what bounds this set instead?" — and if the answer is "nothing", that is the actual work item.
- **An unheeded lesson in a postmortem is not a lesson.** The May document identified the mechanism precisely and it still happened. Postmortem recommendations that survive as prose and not as tickets have no effect. Every "we should" in this document has a ticket number next to it or it does not belong here.
- **Migrations authored in parallel fork the graph silently.** Two revisions written the same afternoon both pointed at `01fef5c9c582`. Neither diff looked wrong; the graph only forks at merge time, and the failure mode is a crash-on-boot rather than a test failure. Cheap structural guards beat vigilance — hence `test_alembic_single_head.py`, which is DB-free and runs in the ordinary test step.
- **Uncommitted work in a worktree is not work.** Unit 4 was written, never committed, and pruned. Commit early on a branch even for work-in-progress, especially in a disposable worktree. In this case the loss was cheap because the artifact was autogeneratable — that was luck, not design.
- **A multi-unit plan that stops after Unit 1 leaves the codebase worse than not starting.** For three weeks the schema carried a `job_freshness` table that was structurally perfect and functionally inert, while the problem it exists to solve kept compounding. Additive-first migration strategies are correct, but they create a window where the cost has been paid and the benefit has not — and that window has to be closed on a schedule, not on availability.

## Related

- `docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md` — introduced the batched `companies=` call shape and the `le=10000 → le=50000` cap raise that made this result set large; its unimplemented "push the recency filter into SQL" lesson is the direct upstream cause (sibling ticket 1.3).
- `docs/incidents/2026-04-18-migration-filled-postgres-volume/` — why every schema change here must be an autogenerated Alembic revision using a single combined `ALTER TABLE`, and why both fixes were deliberately shaped to avoid rewriting `job_listings`.
- `docs/implementations/alembicMigration/DEPLOY.md` — the combined-ALTER-TABLE rule both migrations follow.
- PR **#222** (`2038b53`) — Unit 1, expand migration `01fef5c9c582`. Addressed the decoy; did not affect the outage.
- PR **#225** (`09bb01e`) — the fix that restored production; revision `5ee285a3c724`.
- PR **#224** — Units 2–3 (write + read paths) plus re-sync migration `a3c32c2aa4d3`; drafted 2026-07-13, rebased and re-parented in PR-A.
- `src/backend/docs/job-listings-bloat.md` — the write-amplification runbook: the dated measurements, the three refuted fixes, the `REINDEX INDEX CONCURRENTLY` stopgap and why it is moot, and the group-**S** monitor checks that watch the sidecar index and the anti-join invariants.
- `src/backend/api/db_models.py::JobFreshness` — the sidecar's design rationale and drift guarantees.
- `src/backend/api/tests/test_alembic_single_head.py` — the single-head regression guard added by PR-A.
- `scripts/tests/integration/test_job_freshness.py` — the anti-drift invariants (both anti-joins zero across a full scrape cycle; the `AFTER INSERT` trigger fires on a bare SQL insert) that make the read-side INNER JOIN safe.
- Sibling ticket **1.2** — adversarial verification that the sidecar is the only durable fix for the write amplification, and the source of the "`job_listings.reloptions` stays NULL" constraint.
- Sibling ticket **1.3** — push the recency filter into SQL so `/api/jobs` bounds its own result set.
