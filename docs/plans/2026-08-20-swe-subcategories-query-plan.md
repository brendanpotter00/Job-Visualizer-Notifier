# SWE subcategories — prod query-plan measurement (RA-8)

**Status: NOT RUN.** This is a runbook, not a record. It becomes a record when
someone pastes real `EXPLAIN (ANALYZE, BUFFERS)` output into §Results below.

`SCHEMA-12` (the backfill/coverage partial index) is CONDITIONAL on this
measurement and ships only if the numbers say so. Until then the epic's alembic
chain ends at `SCHEMA-8` (`c48b0f2e7d19`).

## Why this cannot be decided from a desk

Two plans compete for the subcategory-filtered page query and **which one wins is
unknowable until the data exists**:

* an ordered seek on `idx_job_listings_open_category_keyset`
  (`enrichment_category, first_seen_at, source_id, id` partial on `status='OPEN'`)
  with the `&&` as a heap filter, or
* a bitmap scan on `idx_job_listings_open_subcategories_gin` plus a Sort.

The second only becomes attractive once the array column is selective, and it is
100% NULL today.

**RUN IT AFTER `BF-9`'s backfill canary has produced a realistic distribution.**
An all-NULL column makes every plan look free: the GIN index has no entries, the
`&&` filter discards nothing, and the numbers you record would describe a
database that no longer exists a week later.

**HARD RULE, whatever the numbers say:** a subcategory must NEVER be wedged in as
a fifth equality column on the keyset index. That would order entries by
subcategory within a category and destroy the ordering for the common
category-only query — the same argument that kept `enrichment_level` out of it.

## How to run

Read-only, against production, via `mcp__postgres-prod__query` or a Railway
`psql`. **No writes.** Record the Railway deployment id that is READY at the time,
so the evidence is tied to a container rather than to a date.

Six EXPLAINs: three bucket sizes × two page positions.

| bucket | why |
|---|---|
| `backend` | a COMMON bucket — the ordinary case |
| `infrastructure_platform` | the LARGEST — worst case for a heap filter |
| `quantitative` | the RAREST — worst case for an ordered seek that has to scan far |

| position | why |
|---|---|
| page 1 (no cursor) | what most readers ever see |
| a deep cursor (~page 20) | where an ordered seek's advantage decays |

Take the deep cursor by walking `/api/jobs/search?category=software_engineering&subcategory=<bucket>&limit=100`
twenty times and keeping the twentieth `nextCursor`, then decode it — the walk is
what mints a cursor whose fingerprint matches the filter set.

The query to explain is the real page query, i.e. what
`services/job_search.py::search_jobs` composes. The shape is:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT <_LIST_COLUMNS>
  FROM job_listings
  <_FRESHNESS_JOIN>
 WHERE job_listings.status = 'OPEN'
   AND job_listings.enrichment_category = 'software_engineering'
   AND job_listings.enrichment_subcategories && ARRAY['<bucket>']::text[]
   AND <_HIDDEN_COMPANY_PREDICATE>
   -- deep-cursor runs only:
   AND (job_listings.first_seen_at, job_listings.source_id, job_listings.id)
       < (%s, %s, %s)
 ORDER BY job_listings.first_seen_at DESC, job_listings.source_id DESC,
          job_listings.id DESC
 LIMIT 100;
```

Note the expansion: a `backend` selection is sent to SQL as
`ARRAY['backend','full_stack']` (`expand_subcategories`), so explain THAT, not the
single-element array — the two have different selectivity.

## The pre-committed threshold

**Decided in advance so the measurement cannot be argued with after the fact:**

> **> 250 ms OR > 20,000 buffers on either query ships `SCHEMA-12`.
> Below both, do NOT ship it, and record the numbers.**

Acceptance for the step overall is stricter than the threshold: all six EXPLAINs
under **150 ms**, pasted into the PR with a one-line statement of which index the
planner chose for each.

If `SCHEMA-12` does ship, its `down_revision` is `SCHEMA-8`'s (`c48b0f2e7d19`)
and its test asserts the exact three-clause partial predicate appears in
`pg_indexes.indexdef` — a near-miss silently stops Postgres using the index, and
nothing else would notice.

## Results

_Not run. Paste the six EXPLAIN outputs here, each with the chosen index named,
plus the READY Railway deployment id and the date._

| bucket | position | time (ms) | buffers | index chosen |
|---|---|---|---|---|
| `backend` | page 1 | — | — | — |
| `backend` | deep cursor | — | — | — |
| `infrastructure_platform` | page 1 | — | — | — |
| `infrastructure_platform` | deep cursor | — | — | — |
| `quantitative` | page 1 | — | — | — |
| `quantitative` | deep cursor | — | — | — |

**Verdict:** _ship `SCHEMA-12` / do not ship, measured._
