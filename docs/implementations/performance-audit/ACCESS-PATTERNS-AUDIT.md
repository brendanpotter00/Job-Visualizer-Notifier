# Access-Patterns Audit — query/access patterns behind the hot endpoints

Scope: `routers/jobs_search.py` + `services/job_search.py` + `services/database.py`,
the SQL they emit, and `EXPLAIN (ANALYZE, BUFFERS)` re-run on **live prod** (2026-09-03)
via the `postgres-prod` MCP. Companion to `ENDPOINT-BASELINE.md` — this pass digs into
*why* each hot query costs what it does and what the app-level fix is.

Prod scale confirmed live: `job_listings` 88,810 rows / **38,592 OPEN**, `job_tags`
147,650, `job_locations` 95,007, `locations` 1,186, `companies` 159 (2 disabled, **0
private**). Timezone gotcha respected — every recency predicate is bare `now() - interval`.

## The one framing that reorders everything: page vs. count

Every filtered search on **page 1** runs TWO statements on one pooled connection — the
**page query** (`search_jobs`) and the **counts query** (`get_search_counts`, which holds
`filtered_total`). Re-measuring both separately on prod overturns the baseline's "page 1
pays the predicate twice, ~600 ms each" for keywords:

| filter (page 1) | PAGE query | COUNT (`filtered_total`) | who's the villain |
|---|---|---|---|
| bare | 7 ms (keyset early-stop) | **63 ms** (parallel seq scan, exact count of 38 k) | count |
| category=swe | **5 ms** (keyset early-stop) | ~60 ms | count |
| keyword, 3-term | **24 ms** (keyset early-stop) | ~250–450 ms (un-indexed ILIKEs, full corpus) | **count** |
| keyword, 6-term (SWE) | ~40 ms (keyset early-stop) | **~600 ms** | **count** |
| location=United States | **631 ms** (materialize 25 k + sort) | **444 ms** (same bad plan) | both |

The keyword **page** query early-stops on the keyset index and is *cheap* (24 ms measured,
3-term). The expensive half is almost always `filtered_total`, the **exact** count — it
cannot early-stop, so it pays the full predicate over the whole OPEN corpus. This is the
single most important access-pattern fact in the app, and it is what makes Finding 1 the
top lever.

---

## Finding 1 — `filtered_total` is a full exact COUNT on every page-1 search, and it is the expensive half

**Path:** `services/job_search.py:get_search_counts` → `_SEARCH_COUNTS_SQL`
(`SELECT (SELECT count(*) FROM job_listings <filtered_where>) AS filtered_total, …`).

**Plan evidence (live):**
- Bare: `Finalize Aggregate … Parallel Seq Scan on job_listings (Filter status='OPEN',
  removed 16,739) → Hash Anti Join ×2` = **62.9 ms**, `shared hit=7366 read=6165` (reads
  6 k buffers from disk every time).
- Keyword 3-term: the count re-applies 3× (title/location/company ILIKE + hashed tag
  SubPlan) over all ~38 k OPEN rows — LIMIT-independent, so it costs the full scan while
  the page next to it stops at 100.
- Location: `filtered_total` = **444 ms**, identical materialize-25 k plan as the page
  (see Finding 2), so page 1 runs that 25 k scan **twice**.

**Why it's inherent:** `count(*)` over a filtered set has no early-stop. A `LIMIT 100` page
touches ~100–260 rows; the exact count touches every matching row. So the count is 10–100×
the page's row-work on the *same* predicate.

**Fix (app-level, highest leverage):** stop paying an exact count on the hot path. Options,
cheapest blast radius first:
1. **Defer it to a second request.** Return page 1 immediately with `meta=null` for
   `filteredTotal`, fetch the total async (or lazily when the user scrolls). The page is
   already fast; only the tile waits. — removes ~250–600 ms from keyword page 1 and ~444 ms
   from location page 1.
2. **Approximate / cap it.** Show "500+" once the count exceeds the first N pages, or use a
   cheaper estimate. The exact number has little product value on a feed.
3. If it must stay exact and synchronous, at least **skip it when a `cursor` is present** —
   which the code already does (meta is page-1 only). Good; the issue is page 1 itself.

**Expected speedup:** keyword page 1 **1.45 s → ~0.9 s**; location page 1 **2.08 s → ~1.6 s**
(and combined with Finding 2, location → ~0.9 s). Every filtered first-paint drops by the
count's share.

**Blast radius:** MEDIUM. Touches the `meta`/`filteredTotal` envelope contract
(`JobSearchMeta`, `useRecentJobsSearch.ts`, the "N results" UI). Deferring is backward-shaped
(meta can already be null); approximating is a product decision. Recency tiles
(`count_last_24h/3h`) are cheap (windowed over the 24 h slice of the keyset index) — leave
them.

---

## Finding 2 — Location filter drops the keyset index (139× row under-estimate) → materialize 25 k + top-N sort

**Path:** `services/job_search.py:_location_condition` / `_tier_condition`, composed into
`build_search_where`. Emits, per selection, an
`EXISTS (SELECT 1 FROM job_locations jl JOIN locations l ON l.id = jl.normalized_location_id
WHERE jl.job_listing_id = job_listings.id AND (l.canonical_name = %s OR <tier>))`.

**Plan evidence (live, location=United States, page query = 631 ms):**
```
Limit (rows=100)  Buffers: shared hit=362853
 -> Sort (top-N heapsort)  actual rows=100  (sorts 25,033 rows to take 100)
   -> Nested Loop  est rows=180 / ACTUAL rows=25,033        <-- 139× under-estimate
      -> Seq Scan on locations (Filter canonical_name OR upper(country)='US')  rows=583
      -> Bitmap Heap/Index Scan job_locations (per loc)  -> 69,398 rows
      -> HashAggregate -> 60,062 distinct job_listing_id
      -> Index Scan idx_job_listings_open_id  loops=60,062  buffers=205,319   <-- dominant
      -> anti-join companies (enabled/visibility) per row
   -> Index Only Scan job_freshness_pkey  loops=25,033  Heap Fetches 8,285
Execution 631 ms
```

**Root cause — the estimate, proven by contrast.** The planner estimates the location
`EXISTS` at 180 rows (real: 25,033 — location matches are 65% of the OPEN corpus). Believing
only 180 match, it picks "materialize them all and top-N sort" and **abandons the
`first_seen_at` keyset index**. The keyword page query — same envelope, same `LIMIT 100`,
same freshness join — keeps the keyset index and early-stops in **24 ms** *precisely because*
its ILIKE selectivity is estimated high (35 k). Same machine, same table: the only
difference is the row estimate. Location is slow because the planner is wrong about it, not
because 25 k rows must be read.

**Secondary structural costs** baked into the current predicate:
- Per-candidate **`locations` join + `upper(country/region/city)` functions** — no functional
  index exists on `upper(...)`; `locations.canonical_name` has **no index at all** (only
  `locations_pkey` and the composite `uq_locations_canonical`). Small at 1,186 rows but it's
  on the hot per-row path inside the EXISTS.
- The bad plan probes `idx_job_listings_open_id` **60,062 times** (205 k buffers) to check
  status/columns for every distinct job-location id, ~35 k of which aren't even OPEN.

**Fix — three levers, do 1+3 now, 2 in the schema pass:**
1. **(app) Pre-resolve selections to a concrete `normalized_location_id` set.** The endpoint
   already runs `resolve_location_selections`; extend it to resolve each selection to the
   *set of matching `locations.id`* (one extra query against the 1,186-row table), then emit
   `EXISTS (SELECT 1 FROM job_locations jl WHERE jl.job_listing_id = job_listings.id AND
   jl.normalized_location_id = ANY(%s::int[]))`. Drops the per-row `locations` join and every
   `upper()` call; simpler subplan, better estimate.
2. **(schema pass) Denormalize location onto `job_listings`** (e.g. a `location_country`/
   `location_region` or an indexed `location_ids int[]` with GIN) so the predicate has *real
   selectivity stats and an index* → the planner keeps the keyset early-stop plan (→ ~25 ms
   like keyword). This is the real fix; flag it to the schema owner.
3. **(app) Kill/approximate `filtered_total` for location** (Finding 1) — removes the 444 ms
   twin immediately with no schema change.

**Expected speedup:** with 1+3, location page 1 **2.08 s → ~1.4 s** now; with 2 added,
**→ ~0.9 s** (page query itself 631 ms → ~25 ms). Scales with matches-per-location, not page
size, so it also fixes pages 2, 3… which currently re-scan the whole 25 k each.

**Blast radius:** Lever 1 MEDIUM — `job_search.py` location predicate must preserve the
hierarchical semantics (country matches its regions/cities; remote opt-in on both sides;
`IS NOT DISTINCT FROM` null-equality) and the `canonical_name` exact-match fallback; the
parity oracle test (`test_server_results_match_client_filter_oracle`) guards it. Lever 2 is a
migration + backfill + write-path change (HIGH, schema pass). Lever 3 as in Finding 1.

---

## Finding 3 — Keyword `filtered_total` residual = 4 un-indexed ILIKEs/term on `job_listings`

**Path:** `_KEYWORD_PREDICATE`. Per term: `title ILIKE` + `COALESCE(location,'') ILIKE` +
`company ILIKE` + `EXISTS(job_tags … tag ILIKE)`.

**Plan evidence (live):** the tag half is **healthy** — each `tag ILIKE '%term%'` is a
`Bitmap Index Scan on idx_job_tags_tag_trgm` (~2–8 ms/term, e.g. 6.5 ms/2,494 rows for
"software"). The trigram index (migration `536c1cddcd28`) is doing its job. What no index
touches is the **3 ILIKEs per term on `job_listings` (title / location / company)**; in the
COUNT these are evaluated over the full ~38 k OPEN set (the page query early-stops so it
barely feels them). That's the ~600 ms residual for the 6-term SWE list, and it is entirely
inside `filtered_total`.

**Fixes:**
- Primary: **Finding 1** (defer/approximate the count) removes this from the hot path
  wholesale — cheaper than indexing three columns.
- If exact synchronous keyword counts are required: add a **GIN trigram index on
  `job_listings.title`** (the field users actually keyword-match; `company` is low-cardinality
  and already effectively covered by the company chip). Turns the title ILIKE into a bitmap
  scan. `location` raw text is largely superseded by the normalized location filter.
- Sub-3-char blind spot (`go`/`ai`/`ml`): a 2-char term yields no complete trigram → the tag
  EXISTS falls back to seq scan (~110 ms/term). A trigram index cannot help; only a different
  matching strategy (exact-token match, or a stop-list) would. Low priority — deferring the
  count masks it too.

**Expected speedup:** folds into Finding 1 (keyword page 1 → ~0.9 s). A title trigram index
alone would cut the *synchronous* count by roughly half.

**Blast radius:** LOW for the index (write-side cost only; `job_tags` already carries a GIN
trigram, so the pattern is proven). MEDIUM if the count is deferred (Finding 1 contract).

---

## Finding 4 — Trend page `/api/jobs?companies=…` seq-scans all of `job_freshness`, ships a 2.46 MB payload

**Path:** `services/database.py:get_jobs` legacy mode (`ORDER BY f.last_seen_at DESC`,
`limit=5000`, no keyset). Frontend `getJobsForCompany` fetches the company's whole job set to
drive the hiring-trend graph.

**Plan evidence (live, companies=stripe,openai):**
```
Sort (f.last_seen_at DESC)  rows=2,833
 -> Hash Join
      -> Seq Scan on job_freshness f  rows=88,810        <-- full sidecar scan for last_seen_at
      -> Bitmap Heap Scan job_listings (idx_job_listings_company)  rows=2,833
Execution 57 ms
```
The DB is fine (~57 ms here; ~107 ms in the baseline with the full column list + per-row
`tags`/`locations` subqueries). The end-to-end 1.13 s is dominated by the **2.46 MB payload**
— thousands of full rows, each running the correlated `_TAGS_SUBQUERY` + `_LOCATIONS_SUBQUERY`.

**Fixes (app-level):**
- **Trim the projection for the trend read.** The graph needs timestamps + a few fields per
  job for bucketing, not `tags`/`locations` JSON per row. A lighter column list for this path
  cuts serialize + transfer sharply. (Cannot simply paginate — the graph bucketizes the whole
  set client-side, so all rows are needed; thinning columns is the safe lever.)
- The `Seq Scan on job_freshness` (88 k rows) to fetch `last_seen_at` for 2,833 matches is
  wasteful vs. a nested-loop index probe on `job_freshness_pkey` (as the search path uses),
  but at 12 ms it's minor next to payload — leave it unless the trend read gets hotter.

**Expected speedup:** payload trim **1.13 s → ~0.7–0.8 s** for a 2-company trend; larger for
readers following many companies.

**Blast radius:** MEDIUM — the trend graph's client transformer must not need the dropped
columns. Verify `getJobsForCompany` consumers before thinning.

---

## Finding 5 — Index hygiene the read paths expose (hand to schema pass)

Live `pg_stat_user_indexes` + sizes:
- **`idx_job_freshness_last_seen` — 62 MB, 153 lifetime scans, on NO hot read path.** The
  trend query sorts the 2,833-row *result* (quicksort), not via this index; the search paths
  probe `job_freshness_pkey`. It's ~30× bloated from `last_seen_at` re-stamping every scrape.
  **Drop it** (or REINDEX if some rare path needs it — 153 scans says drop). Pure write
  amplification otherwise.
- `idx_job_tags_tag` (plain btree, 1.8 MB, 314 scans) — cannot serve the leading-wildcard
  ILIKE (the trigram does); only exact `tag = x`. Verify any remaining exact-match caller;
  likely a drop candidate.
- `idx_job_listings_status` (bare `status`) — probably redundant: `idx_job_listings_status_category`
  and `idx_job_listings_status_level` both lead with `status`. Low value; confirm before drop.
- Note `idx_job_listings_status_level` shows **149,002 scans** — heavily used (enricher/level
  paths), earning its keep; do NOT touch.

**Blast radius:** LOW-MEDIUM, write-side only; no query-latency risk if scan counts are
respected. Schema pass owns the migrations.

---

## Top wins, ranked

1. **Defer or approximate `filtered_total`** (Finding 1) — app-only, removes the expensive
   half of *every* filtered page-1 search. Keyword 1.45 s → ~0.9 s, location −0.44 s.
2. **Fix the location plan** (Finding 2): pre-resolve to `normalized_location_id` set (app) +
   denormalize location for real stats (schema) → 2.08 s → ~0.9 s and pages 2+ stop
   re-scanning 25 k.
3. **Title trigram index** (Finding 3) if exact keyword counts stay synchronous.
4. **Thin the trend-page projection** (Finding 4) — 2.46 MB payload is the cost, not the DB.
5. **Drop `idx_job_freshness_last_seen`** (Finding 5) — 62 MB of write-amplifying dead weight.

Healthy, leave alone: the bare keyset walk (7 ms), the category keyset index (5 ms), the tag
trigram index (~2–8 ms/term), and the recency tiles.
