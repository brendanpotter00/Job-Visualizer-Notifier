# Schema Audit — JVN Postgres (prod, onesecondswe.dev)

Audited 2026-09-03 against live prod via the `postgres-prod` MCP, cross-read with
`src/backend/api/db_models.py`, the `job_search.py` predicates, and the migrations.
Companions: [`POSTGRES-PRINCIPLES.md`](./POSTGRES-PRINCIPLES.md),
[`POSTGRES-ANTI-PATTERNS.md`](./POSTGRES-ANTI-PATTERNS.md),
[`ENDPOINT-BASELINE.md`](./ENDPOINT-BASELINE.md).

**Timezone note:** every elapsed-time check below used bare `now()` /
`EXTRACT(EPOCH …)`; no `AT TIME ZONE 'UTC'` or timestamptz→timestamp casts (the MCP
mis-renders those).

---

## Headline

**The schema is not the app's bottleneck, and it is genuinely well built.** The
baseline already showed ~0.6–0.7 s of every real request is fixed
Vercel→Railway→FastAPI overhead, and the hot read indexes (keyset, partial-on-OPEN,
tag trigram) are exemplary and EXPLAIN-verified. So the schema wins are **narrow and
specific**, not a redesign:

1. **`job_freshness` sidecar has defeated its own purpose** — one indexed churn column
   turns 69.5 M re-stamps into 0.1 % HOT updates and a **62 MB / ~30× bloated index**
   (write-side; the biggest single schema defect).
2. **The location filter (2.08 s, worst endpoint) is a selectivity-estimation failure**
   the planner cannot fix without a **denormalized country column** on `job_listings`.
3. **The keyword haystack spans 4 columns across 2 tables inside one OR** — *no* index
   can serve that shape; the residual ~600 ms of the SWE search needs a **denormalized
   search-text column**, not another trigram index.
4. Minor hygiene: two duplicate indexes on `users`, `scrape_runs` TEXT timestamps.

Everything else in the checklist (FK indexing, compound order, partial predicates,
`text` types, keyset design) is already correct — see the last section.

---

## Storage evidence (the numbers the findings rest on)

Churn / HOT ratio (why the freshness index bloats), from `pg_stat_user_tables`:

| table | n_live | n_tup_upd | **HOT %** | total size | worst index |
|---|---|---|---|---|---|
| **job_freshness** | 88,810 | **69,463,991** | **0.1 %** | 76 MB | `idx_job_freshness_last_seen` **62 MB** (heap only 8 MB) |
| job_listings | 88,810 | 215,601,458 | 15.4 % | 859 MB | 105 MB heap + **718 MB TOAST** (`details`) + 36 MB idx |
| job_tags | 147,650 | 0 (insert-only) | — | 29 MB | trgm 4.8 MB + btree 1.8 MB |
| job_locations | 95,007 | 422 | — | 15 MB | fine |

`idx_job_freshness_last_seen` has had **4,615 autovacuums** and 62 MB for an 8 MB
table. That is the write amplification the sidecar was *supposed* to remove, relocated
onto the sidecar's own index.

---

## Finding 1 — `idx_job_freshness_last_seen`: 62 MB / ~30× bloat, 0.1 % HOT updates  ★ top win (write-side)

**Issue.** `job_freshness.last_seen_at` is re-stamped on *every* OPEN job *every* scrape
cycle — **69,463,991 updates** logged. Only **57,694 (0.1 %) were HOT.** The reason is
exactly anti-pattern #2: `last_seen_at` is **indexed**, and updating an indexed column
can never be a Heap-Only-Tuple update, so every one of those ~69 M re-stamps writes a
fresh index entry. Result: an **8 MB heap carrying a 62 MB index** (`pg_stat`:
`idx_scan` = 152 over the index's lifetime), and autovacuum thrashing it 4,615 times.

**Why it's slow / costly.** This is write-side, not a per-request latency spike, but it
is not free for reads either: the constant re-bloat + autovacuum on this table competes
for the same I/O and buffer cache the hot reads use, and a 62 MB index is 62 MB of cache
it evicts. The sidecar was created (2026-07-13 outage) precisely to make these updates
HOT on a narrow table — and the `last_seen_at` index silently reintroduced the problem
it was built to kill. `fillfactor=90` (set in the migration) cannot help: HOT is
impossible while the changed column is indexed, so free-space tuning buys nothing here.

**Who actually reads it** (so the fix's blast radius is known): only two paths, both
cold.
- `GET /api/jobs` **legacy mode with no company filter** — `ORDER BY f.last_seen_at DESC
  LIMIT n`. EXPLAIN confirms a backward index scan, 1.4 ms. But the live UI never calls
  this shape: the Recent page moved to `/api/jobs/search` (orders by `first_seen_at`),
  and the company-trend page always passes a company (baseline 2e: that path
  **seq-scans** `job_freshness` and ignores this index).
- `scraper_health.py` — `MAX(f.last_seen_at) … GROUP BY company` (daily cron, groups →
  doesn't need the ordered index).

**Fix.**

*Immediate, safe, online — do this now:*
```sql
REINDEX INDEX CONCURRENTLY idx_job_freshness_last_seen;  -- reclaims ~55 MB
```
It will re-bloat over weeks; it is hygiene, not a cure.

*The actual cure — evaluate dropping the index:*
```sql
DROP INDEX CONCURRENTLY idx_job_freshness_last_seen;
```
With `last_seen_at` no longer indexed (and `consecutive_misses` never was), every
`_upsert_freshness` re-stamp becomes **HOT again** — the sidecar finally delivers its
whole promise, and the 62 MB of write amplification + 4,615-autovacuum churn simply
stops. **Blast radius:** the no-company legacy `/api/jobs` order-by loses its index and
sorts ~38 k OPEN rows on `last_seen_at` (bounded, tens of ms, and no real UI caller hits
it); `scraper_health` seq-scans the 8 MB heap (a daily cron — irrelevant). Confirm with
Railway logs / access patterns that nothing hot orders by `last_seen_at` before
dropping; if something does, keep the index and just REINDEX on a schedule. This is the
single highest-leverage schema change in the app, and it is a *deletion*.

---

## Finding 2 — Location filter (2.08 s): planner can't estimate the EXISTS, drops the keyset index  ★ top win (read latency)

**Issue.** `GET /api/jobs/search?location=United States` is the slowest endpoint in the
app (baseline 2b). The filter is
`EXISTS (SELECT 1 FROM job_locations jl JOIN locations l … WHERE jl.job_listing_id =
job_listings.id AND l.kind <> 'remote' AND upper(l.country) = 'US')`. The planner
estimates this EXISTS at ~180 rows; the real answer is **25,039**. That 139× miss makes
it **abandon `idx_job_listings_open_first_seen_keyset`** (which could walk newest-first
and stop at the LIMIT) and instead materialize all 25 k matching rows, join freshness for
each, and top-N sort — 382 k buffers. And `get_search_counts.filtered_total` re-runs the
identical un-LIMITed scan, so **page 1 pays it twice**.

**Why it's slow.** A cross-table `EXISTS` semijoin is opaque to Postgres' per-column
statistics — there is no stat that says "how many `job_listings` rows have a US
location". No index on `job_locations`/`locations` fixes this; the indexes are already
right (`idx_job_locations_norm_loc`, `idx_job_locations_job_listing_id`, and `locations`
is 1,042 rows). It is an **estimation** problem, and extended statistics
(`CREATE STATISTICS`) don't cross tables, so they can't help the EXISTS either.

**Fix (schema — denormalize the filtered field onto the hot table).** Give the planner a
real column it *has* stats for, so the keyset index survives and the page early-stops.
Add a denormalized primary-country (and optionally region/city-key) column to
`job_listings`, populated from `job_locations` on the write path:
```sql
-- catalog-only ADD (nullable, no default, no backfill in the ALTER — see the
-- 2026-04-18 volume incident); backfill separately in bounded batches.
ALTER TABLE job_listings ADD COLUMN primary_country text;   -- 'US', 'CA', …
-- then a partial compound index so a country filter is an ordered seek that
-- keeps the LIMIT-friendly first_seen_at walk:
CREATE INDEX CONCURRENTLY idx_job_listings_open_country_keyset
  ON job_listings (primary_country, first_seen_at, source_id, id)
  WHERE status = 'OPEN';
```
The location filter for the country tier becomes `job_listings.primary_country = 'US'`
— a seek with a known selectivity — instead of the un-estimable EXISTS. This mirrors the
exact play that already fixed the 2026-07-13 outage (denormalize the sub-field the hot
list path filters on; principles §8) and the existing category keyset index.

**Blast radius: medium-large, and it needs coordination with the query audit.** It adds
a column + index to the 859 MB table (index build reads the parent once but only 4
narrow columns, ~3 MB like its category sibling), a backfill job, and write-path work in
every `fetch_*_company` upsert to set `primary_country` from the normalized locations —
and it only covers the **country** tier cleanly (region/city selections still need the
EXISTS, though those match far fewer rows so the planner behaves). Scope it with the
query pass, which owns the same query. A cheaper stopgap the query pass can also weigh:
**drop the `location` predicate from the un-LIMITed `filtered_total`** (or approximate
the total) so page 1 stops paying the 25 k-row scan twice.

---

## Finding 3 — Keyword search haystack spans 4 columns across 2 tables in one OR: unindexable as written  ★ (read latency, SWE path 1.45 s)

**Issue.** `_KEYWORD_PREDICATE` (job_search.py:144) is, per term:
```
job_listings.title ILIKE %s
  OR COALESCE(job_listings.location,'') ILIKE %s
  OR job_listings.company ILIKE %s
  OR EXISTS (SELECT 1 FROM job_tags t WHERE … AND t.tag ILIKE %s)
```
The tag branch has a trigram index (`idx_job_tags_tag_trgm`) and is cheap (~10 ms across
6 terms). The residual ~600 ms of the SWE 6-term search (baseline 2c) is the **three
un-indexed `ILIKE '%term%'` on `job_listings` (title / location / company)** evaluated
per-row over the full ~38 k OPEN set — and `filtered_total` runs it again, so page 1
pays it twice.

**Why another trigram index won't fix it.** The natural instinct — add
`gin (title gin_trgm_ops)` on `job_listings` — **will not be used here.** For the planner
to turn this predicate into a BitmapOr of trigram scans, every OR branch would have to be
a bitmap over the *same* table. One branch is an `EXISTS` subquery on `job_tags`, which
can never join a `job_listings` bitmap, so the whole OR collapses to a per-row filter
regardless of what trigram indexes exist on the three `job_listings` columns. (This is
the subtle trap behind anti-pattern #8: the index class is right, but the query *shape*
forecloses it.)

**Fix (schema — collapse the haystack into one indexable column).** Materialize the
whole searchable haystack into a single column and put one trigram index on it, so the
per-term predicate becomes one indexable clause instead of a 4-way OR:
```sql
ALTER TABLE job_listings ADD COLUMN search_text text;  -- title ‖ location ‖ company ‖ tags
CREATE INDEX CONCURRENTLY idx_job_listings_search_text_trgm
  ON job_listings USING gin (search_text gin_trgm_ops);
-- predicate collapses to:  job_listings.search_text ILIKE %s
```
Then a term is one `Bitmap Index Scan`, the count and page share it, and the
sub-3-char blind spot (`go`/`ai`/`ml`) is the only residual.

**Blast radius: medium-large — this is a query+schema change, coordinate with the query
audit.** `search_text` includes `tags`, which **change** (tags are re-derived on
enrichment), so it is not immutable — the write path must recompute it whenever
title/location/company/tags change, and a GIN trigram index is comparatively expensive to
maintain on writes. It also changes the exact match semantics slightly (per-field vs
one joined string — the same divergence the code comment at job_search.py:130 already
notes). Worth it only if keyword search latency is a product priority; if not, the
honest cheaper move (query pass) is to **stop running the keyword predicate twice** by
skipping/approximating `filtered_total` when keywords are active.

---

## Finding 4 — Minor hygiene (low blast radius, do opportunistically)

**4a. Duplicate indexes on `users`.** `email` carries both the `users_email_key` UNIQUE
constraint (0 scans) *and* a plain `idx_users_email` (21,817 scans) — identical btrees;
same story for `auth0_id` (`users_auth0_id_key` UNIQUE + `idx_users_auth0_id`). The plain
copies are redundant write overhead (the UNIQUE index serves equality lookups equally
well). Trivial size (40 kB each on 345 rows), but clean to drop:
```sql
DROP INDEX idx_users_email;      -- users_email_key already covers it
DROP INDEX idx_users_auth0_id;   -- users_auth0_id_key already covers it
```
Blast radius: none — the UNIQUE constraint indexes take over the same lookups.

**4b. `scrape_runs.started_at` / `completed_at` are TEXT (anti-pattern #4).** The
`idx_scrape_runs_company_started_at (company, started_at)` index orders by a **TEXT**
timestamp (273 scans). ISO-8601 UTC text sorts lexically-correct *by luck of zero-padding*,
so the backward scan works today, but it is fragile and can't be range-scanned as a real
instant. `users.created_at/updated_at` are TEXT for the same legacy reason. Not a hot app
path (QA/admin), so **tech debt, not a latency fix** — convert to `TIMESTAMPTZ` when that
table is next touched. Flagged already in the principles doc; noted here for completeness.

**4c. Unused indexes worth *keeping*.** `idx_job_listings_problem_jobs` (0 scans, 16 kB,
partial ~182 rows — admin queue), `idx_worker_heartbeats_lane_at` (0 scans — planner
seq-scans the tiny table), `idx_feature_upvotes_user_id` (0 read scans but it is the FK
index that keeps a user-delete CASCADE off a seq scan). All negligible write cost; leave
them.

---

## What's already right (verified, not just assumed)

- **FK / semijoin columns are indexed** where a real query hits them: `job_freshness`
  composite FK on pkey, `idx_job_locations_norm_loc`, `idx_job_locations_job_listing_id`,
  `idx_job_listings_open_id`, `idx_feedback_user_id`, `idx_user_enabled_companies_user_id`,
  the enrichment-category/level FKs ride the status/keyset indexes. The only unindexed FKs
  (`admins.granted_by`, `alias_locations.normalized_location_id`) are on tiny admin tables
  — negligible.
- **Compound order = selectivity, no Sort node.** `idx_job_listings_open_category_keyset`
  (`enrichment_category, first_seen_at, source_id, id`) and
  `idx_job_listings_open_first_seen_keyset` put equality first, the sort tuple last,
  plain-ASC + backward scan. Verified: the bare search is a 7.4 ms index-only walk that
  stops at the LIMIT (baseline 2a).
- **Partial predicates match the query exactly** — `WHERE status='OPEN'` on the keyset
  indexes, and `idx_job_listings_problem_jobs` reproduces all three `btrim(location)`
  clauses verbatim (anti-pattern #7 handled).
- **Types are `text` throughout** the hot tables (no `varchar(n)`), numeric domains are
  `int`/`smallint`/`bigint` appropriately.
- **Keyset pagination is textbook** (immutable `first_seen_at` + composite-PK tiebreak),
  no OFFSET on growth paths.
- **Wide-JSONB discipline holds** — `details` (718 MB TOAST) and `ai_metadata` are kept
  off the list path via the denormalized `experience_level`/`is_remote_eligible` columns;
  the hot `_LIST_COLUMNS` SELECT never detoasts. Keep any new list column off `details`.
- **`company` is well-indexed** (`idx_job_listings_company`, 2.19 M scans, `n_distinct`
  159) — the company-trend read path is a clean bitmap seek; its 1.13 s is payload
  serialization (2.46 MB), not the DB (107 ms), so that one is a query/payload finding,
  not schema.
