# Postgres Principles — reviewer checklist for JVN tables

Reusable Postgres design principles distilled from a principal-engineer team's schema
standards, restated generically and mapped onto this repo (`src/backend/api/db_models.py`).
Use it to review any JVN table or migration. Each item has a one-line **JVN** note.

These are the "snappy app" foundations: the schema and index shape decide whether a hot
query is an index seek or a table scan long before any caching helps. Companion:
[`POSTGRES-ANTI-PATTERNS.md`](./POSTGRES-ANTI-PATTERNS.md).

> **How to read the JVN notes.** JVN predates these conventions and deliberately deviates
> on primary keys (it uses natural/ATS-assigned text keys, not BIGINT-identity + UUIDv7).
> A deviation is only a finding if it costs correctness or speed — most of JVN's do not,
> and the notes say so. The value here is the *checklist*, not a demand to rewrite keys.

---

## 1. Identity: separate the internal join key from the public/API id

- [ ] **Internal PK is a compact, DB-owned key** (`BIGINT GENERATED ALWAYS AS IDENTITY`),
  used by FKs and joins. Atomic `nextval()`, gaps allowed, safe under concurrent writers.
- [ ] **API-addressable rows also carry a stable public id** (`uuid UNIQUE`, generated
  UUIDv7 in app code before INSERT) — safe to expose, doesn't leak a row count, orderable
  by time. `UNIQUE` already supplies the index; don't add a second.
- [ ] **Don't invent a second `sequence` column** when the identity PK already gives you
  allocation order. Don't make a random-ordered id the physical PK (see anti-patterns).

**JVN:** JVN does NOT follow this — it uses natural text PKs: `job_listings (source_id, id)`
composite (id = ATS-assigned string), `users.id` = app-generated uuid4 hex used directly as
the PK. Only append-only logs use the standard (`user_visits`, `company_harvests`,
`company_add_attempts` = `BIGINT` identity). This is a defensible deviation — the ATS id is
the real natural key — but it has a real downstream cost: the composite PK blocks
single-column FKs (see §4) and there is no separate opaque API id.

## 2. `created_at` everywhere; `updated_at` + a shared trigger on mutable tables

- [ ] **Every table has `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`** — set by Postgres
  on insert, never by app code.
- [ ] **Every mutable table (rows updated in place) has `updated_at TIMESTAMPTZ NOT NULL
  DEFAULT now()` PLUS a shared `set_updated_at()` BEFORE UPDATE trigger.** The trigger is
  the point — a `DEFAULT now()` alone only stamps insert time; without the trigger a raw
  UPDATE, bulk script, or forgetful new code path leaves `updated_at` stale. Define the
  function once per database, attach per table.
- [ ] **Append-only tables skip `updated_at`/trigger** — no in-place update means nothing to
  record; the column would be dead weight.
- [ ] Timestamps are `TIMESTAMPTZ`, **never TEXT** (see anti-patterns for why text dates rot).

**JVN:** Timestamp columns are mostly `TIMESTAMPTZ DEFAULT now()` (good), but there is **no
shared `set_updated_at()` trigger anywhere** — `users`, `user_saved_filters`,
`user_keyword_lists`, `company_scripts` all have an `updated_at` that only the app touches,
so any write path that forgets leaves it stale. And `users.created_at`/`updated_at` and
`scrape_runs.started_at`/`completed_at` are **TEXT-typed** (legacy) — flagged in the models
themselves as "do NOT mimic." Append-only logs (`user_visits`, `company_add_attempts`,
`enrichment_ticks`) correctly omit `updated_at`.

## 3. Hard delete by default; soft delete only with a real caller

- [ ] **Default to hard delete.** Postgres does NOT reward soft delete the way MySQL does
  (MVCC + autovacuum reclaim dead tuples from both UPDATE and DELETE automatically — no
  `OPTIMIZE TABLE` step). "Soft delete avoids fragmentation" is a false instinct here.
- [ ] **Add `deleted_at` only when a real caller needs it** — a user-facing delete/restore,
  an audit rule, or rows that must still reference the "deleted" parent. Not speculatively.
- [ ] **When present, filter `WHERE deleted_at IS NULL` in the repository layer**, not only
  via a view/partial index — the code shapes behavior; the index just makes it cheap.

**JVN:** JVN has **no `deleted_at` soft-delete anywhere** — correct. `job_listings.status`
(`OPEN`/`CLOSED`) is a domain lifecycle state (a job really closed), not a soft-delete flag,
and it's used as a load-bearing index predicate — a legitimate, different thing.

## 4. Real foreign keys with the right `ON DELETE`

- [ ] **Every relationship has a real FK constraint** — no "logical" FKs enforced only in
  app code, unless something structural blocks it (then say so explicitly).
- [ ] **`ON DELETE CASCADE`** when the child is meaningless without its parent and has no
  independent retention — kills a class of "forgot to clean the join table" bugs.
- [ ] **`ON DELETE SET NULL`** when the child must survive the parent (audit/snapshot rows).
- [ ] **FK columns are always indexed** (Postgres does NOT auto-index them, unlike the PK).

**JVN:** Mixed, and mostly for a real reason. Strong FK+CASCADE where possible:
`user_visits`, `admins`, `user_enabled_companies`, `feature_upvotes`, `user_keyword_lists`,
`alias_locations`, and notably `job_freshness` (a real **composite** FK to
`job_listings(source_id, id)` with CASCADE — no orphaned freshness rows). But the composite
text PK on `job_listings` **structurally blocks single-column FKs**, so `job_locations`,
`job_tags`, `job_enrichment` key on `job_listing_id` alone with **app-level integrity only**
— documented in each model. `feedback.user_id` uses SET NULL to keep the snapshot after a
user is deleted (correct). Every FK/semijoin column is indexed (see §5).

## 5. Index what real queries run — no seq-scans on hot paths

- [ ] **If a frontend action or API call runs a query, that query has an index** serving it.
- [ ] **FK / join / semijoin columns are indexed.**
- [ ] **Compound-index column order = selectivity:** equality-filtered / most-selective
  column first, the sort/range column last, so the query is an ordered index seek with **no
  Sort node**. A keyset seek is only an index seek when the index key *is* the sort tuple.
- [ ] **Partial indexes** for a hot predicate (`... WHERE status='OPEN'`) keep the index
  small — but the query predicate must **imply** the index predicate exactly (including
  identical function expressions) or the planner won't use it.
- [ ] **`created_at` indexed only when a real query needs it** (recency, TTL sweep) — not
  reflexively; an unused index is write overhead for no read benefit.
- [ ] **All-DESC `ORDER BY` is served by a BACKWARD scan of an all-ASC index** — no explicit
  DESC ops needed (and they'd break autogenerate round-trip).
- [ ] **Leading-wildcard `ILIKE '%term%'` needs a `pg_trgm` GIN index** — a plain btree
  can't serve it (terms < 3 chars have no trigram and still seq-scan).
- [ ] **Use `text`, not `varchar(n)`** for non-numeric data (no perf penalty, no guessed
  cap). Reserve `smallint`/`int` for genuinely bounded numeric domains.

**JVN:** This is JVN's **strongest** area — the index design is exemplary and heavily
EXPLAIN-verified. Examples: `idx_job_listings_open_first_seen_keyset` and
`idx_job_listings_open_category_keyset` put the equality/category column first and the
`(first_seen_at, source_id, id)` sort tuple last, partial on `status='OPEN'`, plain-ASC
backward-scanned; `idx_job_listings_problem_jobs` mirrors a query's `btrim(location)<>''`
predicate exactly so the partial index applies; `idx_job_tags_tag_trgm` is a GIN trigram for
the keyword `ILIKE` path; FK/semijoin columns (`idx_job_locations_norm_loc`,
`idx_job_listings_open_id`) are all indexed. Types are `text` throughout. **When auditing a
new query, the bar is this high** — confirm the plan with `EXPLAIN (ANALYZE, BUFFERS)`.

## 6. Keyset (cursor) pagination, never OFFSET

- [ ] **List endpoints that can grow past a page use keyset, not `LIMIT/OFFSET`** — OFFSET
  gets linearly slower (it scans and discards skipped rows) and silently loses/dupes rows
  when the sort key churns or inserts shift the window.
- [ ] **Cursor = the last row's sort key(s)**, on the same columns the index is built on.
- [ ] **Sort key is IMMUTABLE + UNIQUE.** An immutable leading column keeps the cursor stable
  across concurrent writes; a unique tiebreak (append the PK) stops rows that share the
  leading value from paging non-deterministically.
- [ ] **Reject a bad cursor loudly (422), never silently restart at page 1** — a silently
  discarded cursor is an infinite or truncated walk the client can't detect.

**JVN:** Fully implemented and the reasoning is textbook — see `api/pagination.py`. Sort tuple
`(first_seen_at DESC, source_id DESC, id DESC)`: `first_seen_at` is immutable (unlike the
churny `last_seen_at`), `(source_id, id)` is the PK so the tuple is unique. Malformed cursor →
422; a search cursor also carries a filter fingerprint → 409 on a filter-set mismatch. No
OFFSET on growth paths. This is a model for any new list endpoint.

## 7. Retention / TTL is an explicit scheduled hard delete

- [ ] **Postgres has no native TTL index** (no Mongo `expireAfterSeconds`). A retention rule
  is a scheduled job (pg_cron / a cron task) doing a real **hard delete** on the aggregate
  root, `ON DELETE CASCADE` cleaning up children in one statement.
- [ ] **Delete in bounded batches** (`... LIMIT 1000`, commit per batch), not one unbounded
  statement — bounds WAL growth, lock hold time, replication lag.
- [ ] **Index the sweep's discovery predicate** (`WHERE created_at < cutoff`) so finding rows
  to delete is cheap; the `LIMIT` bounds the delete+cascade cost.
- [ ] Retention (a hard delete) and soft delete solve different problems — don't conflate.

**JVN:** JVN's retention is lighter-weight and mostly fine: `worker_heartbeats` is pruned by
a periodic cleanup task (rows > 24h), and `job_listings` closes via `status` rather than
deleting. No unbounded-delete risk seen. If a future large-table TTL sweep is added, use the
bounded-batch pattern and index the discovery column.

---

## 8. Wide rows, TOAST, and JSONB (JVN-critical — the actual outage lessons)

These aren't in the generic standards but are the highest-leverage perf principles for JVN,
learned from real incidents in this repo.

- [ ] **Don't read into a wide/TOASTed JSONB column on a hot list path.** A large JSONB
  (~KBs) lives in TOAST; touching `details->'field'` forces a detoast of the *whole* value
  per row. On a batched list query that is hundreds of MB of TOAST reads → statement-timeout.
- [ ] **Denormalize the 1-2 JSONB sub-fields the list path filters/shows into real columns**
  so the hot query never touches TOAST; keep the full JSONB for the single-row detail path.
- [ ] **Promote a JSONB field to a typed column only when code reads it back / filters on it**
  (it needs to be indexable); leave write-only / read-whole payloads in JSONB. Normalizing a
  never-queried field is speculative.
- [ ] **Keep the hot tuple narrow.** Push heavy audit/description payloads to a 1:1 side table
  so the frequently-scanned row stays small.

**JVN:** Directly lived here. `job_listings.details` (~10 KB JSONB) caused the 2026-07-13
outage when the list query read `details->…` across ~12k rows; the fix denormalized
`experience_level` + `is_remote_eligible` into columns (list query never detoasts; single-row
path still returns full `details`). `job_enrichment` is a 1:1 side table holding the heavy
clean-description/audit payload so `job_listings` stays narrow. When reviewing a new list
query, check it reads no wide JSONB.

## 9. High-churn columns off the wide, indexed hot table (write amplification / HOT)

- [ ] **A frequently re-stamped, indexed column does NOT belong on a wide TOAST-heavy table.**
  Updating an indexed column can't be a Heap-Only-Tuple (HOT) update, so every write rewrites
  the heap tuple AND every index entry → heap + index bloat autovacuum struggles to keep up
  with on a big table.
- [ ] **Move churny columns to a narrow sidecar** keyed by the parent PK (real composite FK +
  CASCADE, and a trigger to create the sidecar row) so the wide table stops being rewritten
  each cycle and the sidecar's own small index stays tight under aggressive autovacuum.

**JVN:** This is exactly why `job_freshness` exists — `last_seen_at`/`consecutive_misses` are
re-stamped on every OPEN job every hourly scrape; on the ~600 MB `job_listings` those were
non-HOT updates bloating the heap and a 100 MB index past the 30s timeout. The sidecar (narrow,
composite-FK, AFTER-INSERT trigger to stay lossless) fixed it. Any new "updated every cycle"
column should follow this.

## 10. Migrations must not rewrite a large table

- [ ] **`ADD COLUMN` stays catalog-only** (metadata-only, instant) when the column is
  **nullable with no default and no backfill**. A `DEFAULT` (on old PG) or an inline
  `UPDATE ... SET` backfill rewrites every row — on a big table that can fill the disk.
- [ ] **Add the column nullable now, backfill later in bounded batches** if you need values.
- [ ] **Combine multiple `ALTER TABLE`s on one table into a single statement** where the
  repo's deploy rules require it (one table rewrite, not N).

**JVN:** A hard-won rule from the 2026-04-18 "migration filled the Postgres volume" incident —
`scrape_runs` (~455k rows) and `companies`/`job_listings` columns (`skipped_update`,
`guard_reason`, `visibility`, the enrichment facets) are all deliberately nullable /
server-default-only so the ALTER stays catalog-only and never rewrites the table. Review every
new migration against this before it ships.

---

### Applying this checklist

When adding or reviewing a JVN table/query/migration, walk every section explicitly — don't
assume a rule was "obviously" followed. If a table intentionally deviates (JVN's text PKs,
app-level FKs behind the composite PK), state that and why in the PR, so a silent deviation
doesn't read as an oversight. For any hot query, the standard of proof is an
`EXPLAIN (ANALYZE, BUFFERS)` at prod scale showing an index seek with no Sort node and no
TOAST detoast — the same bar the existing keyset/partial indexes were held to.
