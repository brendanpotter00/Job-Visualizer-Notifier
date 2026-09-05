# Postgres Anti-Patterns — reviewer checklist for JVN tables

Design instincts that are **wrong for Postgres** (often carried from MySQL/MariaDB/Mongo),
distilled generically and mapped onto this repo. Companion to
[`POSTGRES-PRINCIPLES.md`](./POSTGRES-PRINCIPLES.md) (the "what to do" side). Each entry:
the tempting instinct → why it's wrong in Postgres → the corrected rule → a **JVN** note.

Ordered roughly by how much a violation hurts a "snappy app" audit.

---

## 1. Reading into a wide/TOASTed JSONB on a hot list path

- **Instinct:** JSONB is free to read; `details->'field'` is just a field access.
- **Why wrong:** a large JSONB value (~KBs) is stored out-of-line in TOAST. Touching any
  sub-field detoasts the **entire** value per row. On a batched list query over thousands of
  rows that is hundreds of MB of extra I/O → past the statement timeout.
- **Rule:** denormalize the few sub-fields the list path filters/shows into real columns; read
  the full JSONB only on the single-row detail path.
- **JVN:** the 2026-07-13 `/api/jobs` outage. `details` (~10 KB) read across ~12k rows blew the
  30s timeout; fixed by `job_listings.experience_level` / `is_remote_eligible` columns. **Audit
  bar: no hot list query touches `details` or any wide JSONB.**

## 2. Indexed, high-churn column on a wide table

- **Instinct:** put `last_seen_at` (updated constantly) on the main table and index it for the
  `ORDER BY ... DESC` — it's just one column.
- **Why wrong:** updating an **indexed** column can't be a Heap-Only-Tuple update, so every
  re-stamp rewrites the heap tuple and every index entry. On a wide/TOAST-heavy table with
  millions of updates/cycle, heap + index bloat outruns autovacuum and the ordered read times
  out.
- **Rule:** move churny columns to a narrow sidecar keyed by the parent PK (composite FK +
  CASCADE + an insert trigger to stay lossless); index the sidecar, not the wide parent.
- **JVN:** `job_freshness` exists for exactly this (`last_seen_at` index hit 100 MB on the
  600 MB `job_listings` and timed out). Any new "written every cycle" column → sidecar, never
  a new index on `job_listings`.

## 3. `OFFSET`/`LIMIT` pagination on a growing or churning list

- **Instinct:** page N = `LIMIT k OFFSET k*N`.
- **Why wrong:** OFFSET still scans and discards every skipped row (linearly slower as you
  page), and when the sort key changes between pages or inserts shift the window, rows slide
  across the boundary — silently dropped or duplicated, a plausible 200 either way.
- **Rule:** keyset pagination on an immutable + unique sort key; reject a bad cursor loudly.
- **JVN:** already done right (`api/pagination.py`). **Watch for:** any *new* endpoint or admin
  query that reintroduces OFFSET on a large table, or accepts a page number and translates it
  to OFFSET server-side (same cost, one layer removed). `offset` is even a 422 in keyset mode.

## 4. Storing timestamps (or numbers) as TEXT

- **Instinct:** ISO-8601 strings are human-readable and "just work."
- **Why wrong:** a `TEXT` timestamp can't be range-scanned by a time index efficiently, can't be
  compared with `now()` without a cast, silently accepts malformed/naive values, and mixes
  representations. `$lte` against a string never matches a date; a bad value disables a sweep
  with no self-heal.
- **Rule:** `TIMESTAMPTZ` for instants; `int`/`smallint` for bounded numbers. Parse and validate
  at the write boundary, quarantine unparseable values — never default to `now()` (fabricates
  history).
- **JVN:** `users.created_at`/`updated_at` and `scrape_runs.started_at`/`completed_at` are
  **TEXT-typed legacy columns** — the models explicitly warn "do NOT mimic," and newer columns
  (`last_visit_at`, `company_enroll_watermark`, `next_run_at`) correctly use `TIMESTAMPTZ`.
  Range queries/sorts over the text columns can't use a time index; treat as tech debt.

## 5. Soft delete "to avoid fragmentation"

- **Instinct (from MySQL/InnoDB):** a `DELETE` fragments the table until `OPTIMIZE TABLE`, so
  prefer `UPDATE ... SET deleted_at = now()`.
- **Why wrong:** Postgres MVCC leaves a dead tuple on **both** UPDATE and DELETE, and autovacuum
  reclaims either automatically in the background — there is no `OPTIMIZE TABLE` step. (They're
  not storage-identical — an UPDATE may qualify for a HOT update that avoids new index entries,
  a DELETE never does — but neither is bloat-free, and this is not a reason to prefer soft
  delete.) If autovacuum falls behind, that's per-table tuning, not evidence soft delete helps.
- **Rule:** hard delete by default; add `deleted_at` only for a real delete/restore/audit caller.
- **JVN:** JVN correctly has **no `deleted_at`**; `status='CLOSED'` is a domain lifecycle, not a
  soft delete. Don't let a future "just in case" `deleted_at` in for the fragmentation reason.

## 6. Speculative columns and indexes

- **Instinct:** add `deleted_at` / an extra index / a normalized child table now, "we'll need it."
- **Why wrong:** an unused index is pure write overhead (every insert/update maintains it) for
  zero read benefit; a speculative `deleted_at` adds partial-index sync + un-delete lifecycle
  rules with no caller; a normalized table you never query into just adds joins.
- **Rule:** add the column/index/table when a real query or caller needs it, and validate an
  index choice with `EXPLAIN (ANALYZE, BUFFERS)` on representative data first.
- **JVN:** JVN is disciplined here — indexes are added against a named query and EXPLAIN-verified,
  JSONB stays JSONB until a field is actually filtered on. Hold new work to the same bar; flag
  any index with no query behind it.

## 7. A partial index whose predicate doesn't match the query

- **Instinct:** a partial index `WHERE status='OPEN'` will serve any query about OPEN rows.
- **Why wrong:** the planner uses a partial index only when the **query predicate implies the
  index predicate** — for a function expression that means a *structurally identical* clause
  (`btrim(location) <> ''` must appear verbatim). Miss it and you silently seq-scan.
- **Rule:** make the index predicate mirror the query's WHERE exactly; if a second query must see
  rows the partial index excludes, give it its own (non-partial) index.
- **JVN:** handled carefully — `idx_job_listings_problem_jobs` reproduces all three WHERE clauses
  including `btrim`. When adding a partial index, copy the query's predicate character-for-character
  and confirm with EXPLAIN that it's an Index Cond, not a Filter.

## 8. Leading-wildcard `ILIKE '%term%'` on a plain btree

- **Instinct:** the column is indexed (btree), so substring search is fast.
- **Why wrong:** a btree can't serve a **leading** wildcard; the planner falls back to a full
  scan, and if it's inside a de-correlated `EXISTS`/`SubPlan` the scan runs once per term
  independent of the page `LIMIT` (and page 1 may pay it twice: page + count).
- **Rule:** `pg_trgm` GIN index (`gin_trgm_ops`) for arbitrary-substring `ILIKE`; know the blind
  spot — a term < 3 chars has no complete trigram and still seq-scans.
- **JVN:** `idx_job_tags_tag_trgm` covers the `/api/jobs/search` keyword path; `go`/`ai`/`ml`
  (< 3 chars) still seq-scan by design. Any new substring-search filter needs a trigram index,
  not the plain `idx_job_tags_tag`.

## 9. "Logical" (app-only) foreign keys where a real FK would work

- **Instinct:** enforce the relationship in application code, skip the DB constraint.
- **Why wrong:** app-only integrity drifts — a missed cleanup path leaves orphans the DB would
  have refused; you also lose `ON DELETE CASCADE`, so join/child tables need manual cleanup.
- **Rule:** a real FK unless something structural blocks it (a composite/partial PK the child
  can't reference by one column, or an audit row that must outlive the parent) — and when you
  skip it, document *why* and enforce the invariant explicitly in the service layer.
- **JVN:** JVN skips FKs in several places, mostly forced by the `job_listings (source_id, id)`
  **composite** PK — a single-column FK to `id` is invalid, so `job_locations`, `job_tags`,
  `job_enrichment` are app-level (documented in each model). Others are deliberate audit-survival
  choices (`company_add_attempts.user_id`, `user_companies.company_id`). Where a real FK *is*
  possible it's used (`job_freshness` composite FK + CASCADE). Note that the composite text PK is
  itself the root cause of most missing FKs (see §10).

## 10. Making a random-ordered id the physical primary key

- **Instinct:** use a UUIDv4 (or a hash) as the PK — one column, globally unique, no sequence.
- **Why wrong:** a random PK scatters inserts across the btree (page splits, poor cache
  locality) and, when it's a wide/composite text key, it becomes the thing that blocks
  single-column FKs from children and forces app-level integrity everywhere.
- **Rule:** compact DB-owned identity PK (`BIGINT` identity, or time-ordered UUIDv7) for the
  internal key; expose a separate public id if needed. Reserve natural keys for cases where the
  natural key genuinely *is* the identity and children can reference it.
- **JVN:** `job_listings` uses composite `(source_id, id)` (id = ATS string) and `users.id` =
  uuid4 hex. This is a defensible modeling choice (the ATS id is the real key) but it's the
  direct cause of the app-level-FK situation in §9 and of every child table having to carry
  `source_id` to key correctly. Not worth rewriting, but understand it's the structural root of
  those deviations when auditing.

---

### Adding an entry

New anti-pattern format: the instinct (and which engine it's carried from) → why it doesn't
transfer to Postgres (with the mechanism / a Postgres-docs pointer) → the corrected rule → the
JVN table it maps onto. Keep entries reusable — the mechanism, not one incident's specifics.
