# SWE subcategories — Phase 1 deployment verification (SCHEMA-6)

**Status: NOT RUN.** This is a runbook, not a record. It becomes a record when
someone pastes real output into §Results below.

## Why this exists at all

**"The PR merged" is not evidence the schema moved.** Two facts make that a real
hazard rather than a pedantic one:

1. Migrations run **IN-PROCESS**, in the FastAPI lifespan (`api/migrations.py`
   runs `command.upgrade(cfg, "head")`). The schema moves when a container that
   contains the new code actually BOOTS — not when the merge button is pressed.
2. Railway's **merge-train deploy-skip trap** is documented at
   `src/backend/CLAUDE.md` and it has bitten this repo before, on 2026-08-05:
   #232 was stacked under #235/#238, queued deployments were deduped to the
   newest commit, that commit matched no watch path, the whole queue skipped, and
   `alembic_version` stayed at the previous head while everything looked green.

Everything downstream of phase 1 — the enricher's write-back, the backfill drain,
the coverage counters the reveal is read off — assumes these columns exist. Run
the seven queries before any of it writes.

## How to run

Read-only, against production, via `mcp__postgres-prod__query` or a Railway
`psql`. **No writes.** Also record the Railway deployment id whose status is
READY, so the evidence is tied to a specific container, not to a date.

## The seven queries

```sql
-- 1. The chain actually advanced. Expect SCHEMA-11's revision ('2e6f81ad4b57'),
--    NOT '1d2d6c17acfc' (main's pre-#252 head) and NOT '536c1cddcd28' (#252's
--    head — that would mean this epic's three revisions never ran).
SELECT version_num FROM alembic_version;

-- 2. The dimension shipped EMPTY. A non-zero count means someone hand-seeded it
--    and the public dropdown is about to appear with nothing behind it.
SELECT count(*) FROM job_subcategories;

-- 3. Nothing has been labelled yet. Non-zero before the backfill runs means a
--    writer is live earlier than intended.
SELECT count(*) FROM job_listings WHERE enrichment_subcategories IS NOT NULL;

-- 4. ⚠ THE COVERAGE DENOMINATOR. RECORD THIS NUMBER — it is
--    PARAM_BACKFILL_DENOMINATOR, it replaces the ~8,126 placeholder in every
--    downstream estimate, and ADM-6's `swe_open_total` must use this exact
--    definition or the admin tile and the backfill disagree about what 90%
--    means.
SELECT count(*) FROM job_listings
WHERE status = 'OPEN' AND enrichment_category = 'software_engineering';

-- 5. The partial GIN exists with the right predicate, and is near-empty
--    (the column is 100% NULL at this point).
SELECT indexdef, pg_size_pretty(pg_relation_size('idx_job_listings_open_subcategories_gin'))
FROM pg_indexes WHERE indexname = 'idx_job_listings_open_subcategories_gin';

-- 6. Expect 0. `app_settings` ships UNSEEDED — absent means the code default —
--    so a row here means somebody hand-seeded one, and the "a fresh DB, a
--    deleted flag and a rolled-back migration all behave identically" property
--    is no longer true.
SELECT count(*) FROM app_settings;

-- 7. `project_manager` is retired: SIX categories, and zero listings still
--    pinned to it.
SELECT count(*) FROM job_categories;
SELECT count(*) FROM job_listings WHERE enrichment_category = 'project_manager';
```

## Expected values

| # | Query | Expected |
|---|---|---|
| 1 | `alembic_version` | `2e6f81ad4b57` |
| 2 | `job_subcategories` rows | **0** |
| 3 | labelled `job_listings` | **0** |
| 4 | OPEN SWE rows | *record it* — this is the denominator |
| 5 | GIN indexdef | contains `USING gin` and `WHERE (status = 'OPEN'::text)`; size near-empty |
| 6 | `app_settings` rows | **0** |
| 7 | `job_categories` rows / orphan listings | **6** / **0** |

## Results

*(not run — paste real output and the READY deployment id here)*

| # | Value | Run at |
|---|---|---|
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |
| 6 | | |
| 7 | | |

Railway deployment id: *(pending)*
