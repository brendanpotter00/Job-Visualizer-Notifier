# Endpoint Baseline — prod (onesecondswe.dev)

Measured 2026-09-03 against live prod (Vercel proxy → Railway FastAPI → Postgres).
Latency = end-to-end `curl` from a US dev machine, 6 samples each, median + worst.
Query plans = `EXPLAIN (ANALYZE, BUFFERS)` run directly on prod Postgres via the
`postgres-prod` MCP.

**Prod scale:** `job_listings` 88,809 rows / **38,597 OPEN** · `job_tags` 147,650 ·
`job_locations` 95,007 · `locations` 1,186 · `companies` 159 (2 disabled, 0 private).
Sizes: `job_listings` 105 MB heap + **718 MB TOAST** (`details` JSONB) + 36 MB indexes =
859 MB total. `job_freshness` 8 MB heap but **62 MB on `idx_job_freshness_last_seen`
alone** (≈30× bloat).

Timezone note: all recency predicates use bare `now() - interval '…'` (renders
correctly); no `AT TIME ZONE 'UTC'` / timestamptz→timestamp casts were used, per the
known MCP mis-render.

---

## 1. Endpoint latency + payload

| Endpoint (representative params) | median | worst | payload | DB work | bound by |
|---|---|---|---|---|---|
| `GET /api/health` | 0.25s | 0.29s | 79 B | ~0 | network floor |
| `GET /api/locations/search?q=new` | 0.59s | 0.69s | 2.5 KB | trivial | **fixed overhead** |
| `GET /api/features` (anon) | 0.67s | 0.75s | 1.2 KB | trivial | **fixed overhead** |
| `GET /api/companies` | 0.73s | 0.77s | 60 KB | trivial (159 rows) | overhead + payload |
| `GET /api/jobs/facets` | 0.74s | 0.84s | 1.1 KB | 2 tiny selects | **fixed overhead** |
| `GET /api/jobs?company=stripe&status=OPEN` | 0.80s | 0.90s | 520 KB | ~40 ms | payload |
| `GET /api/jobs/search` bare, limit 100 | 1.01s | 1.04s | 114 KB | **~70 ms** | overhead + payload |
| `GET /api/jobs/search` category=swe, limit 100 | 0.86s | 1.04s | 107 KB | ~50 ms | overhead |
| `GET /api/jobs/search` bare, limit 500 | 1.05s | 1.25s | 571 KB | ~70 ms | payload |
| `GET /api/jobs?companies=stripe,openai&limit=5000` | 1.13s | 1.24s | **2.46 MB** | 107 ms | **payload/serialize** |
| `GET /api/jobs/search` include=go (2-char) | 1.19s | 1.24s | 103 KB | ~500 ms | keyword scan |
| `GET /api/jobs/search` include=ai (short) | 1.11s | 1.14s | 121 KB | ~450 ms | keyword scan |
| `GET /api/jobs/search` **SWE 6-term**, limit 100 (page 1) | **1.45s** | 1.52s | 103 KB | ~600 ms ×2 | keyword scan (×2) |
| `GET /api/jobs/search` SWE 6-term, limit 500 | 1.51s | 1.60s | 513 KB | ~600 ms ×2 | keyword + payload |
| `GET /api/jobs/search` **location=United States** | **2.08s** | 2.19s | 124 KB | **710 ms ×2** | location scan (×2) |

Auth-gated (not force-measured): `GET /api/users`, `/users/enabled-companies`,
`/users/saved-filters*`, all of `/api/admin/*`, `POST /api/feedback`,
`POST /api/companies/resolve`. `resolve` is the one with a genuinely slow ceiling by
design — up to a **25 s** outbound budget (third-party ATS probing), but it is
user-triggered and rate-limited, not a hot read.

### The dominant cost is fixed per-request overhead, not the DB

`/api/jobs/facets` returns 1.1 KB from two trivial dimension-table selects yet takes
**0.74 s**. `/api/features` (1.2 KB) 0.67 s. The bare search's DB work is ~70 ms but the
request is **1.0 s**. So **~0.6–0.7 s of every real backend hit is Vercel-function →
Railway → FastAPI round-trip + (de)serialization**, independent of the query. The
network floor (`/api/health`, 79 B) is 0.25 s; the extra ~0.4–0.5 s is the proxy hop +
backend framework + Pydantic serialization.

---

## 2. Captured query plans (prod, EXPLAIN ANALYZE BUFFERS)

### 2a. Search page query — BARE (limit 100) — the ideal path: **7.4 ms**
`Index Scan Backward using idx_job_listings_open_first_seen_keyset`, stops at 100 rows.
2,454 buffer hits. No Sort node. This is the keyset index doing exactly its job — the
baseline every other search shape should be compared against.

### 2b. Search page query — location=United States — **710 ms** (THE worst plan)
```
Limit (actual 706..710 rows=100)  Buffers: shared hit=382231
 -> Sort (top-N heapsort) Sort Key: first_seen_at DESC, source_id DESC, id DESC
      actual 706..706  rows=100   (sorts 25,039 rows to take 100)
   -> Nested Loop  (est rows=180, ACTUAL rows=25,039)      <-- 139× under-estimate
      -> HashAggregate over job_locations  est 422 / actual 60,062 distinct job ids
         -> Seq Scan on locations (583 US rows) ⋈ Bitmap Heap Scan job_locations
      -> Index Scan idx_job_listings_open_id  loops=60,062  buffers=205,325
      -> anti-joins companies (hidden/private) per row  loops≈25k  buffers≈50k
   -> Index Scan job_freshness_pkey  loops=25,039  buffers=100,156
Execution Time: 710.803 ms   (no JIT — cost below threshold)
```
**Root cause:** the location `EXISTS(... job_locations ⋈ locations ...)` predicate is
opaque to the planner's selectivity stats (est 180, real 25,039). It therefore abandons
the `first_seen_at` keyset index (which could walk newest-first and stop at 100) and
instead **materializes all 25 k matching rows, joins freshness for every one, then top-N
sorts**. Every location-filtered page pays this — page 2, 3, … re-scan the whole 25 k.
And `get_search_counts.filtered_total` runs the **same** location scan un-LIMITed, so
**page 1 pays it twice** → the 2.08 s end-to-end.

### 2c. Search **counts** query — SWE 6-term `filtered_total` — node ~1.4 s, but **JIT compile = 1030 ms**
```
Aggregate (actual 1425 ms)  Buffers: shared hit=51455
 -> Nested Loop Anti Join  actual 906..1422  rows=20,653
   -> Index Scan idx_job_listings_status (status='OPEN')  rows=20,717, removed 17,880
        Filter: 24 ILIKEs (6 terms × title/location/company) + 6 hashed SubPlans
   -> per-row anti-join companies_pkey  loops=20,717  buffers=41,434
 SubPlan 2..12: Bitmap Index Scan idx_job_tags_tag_trgm  (each ~1–2 ms index, ~30 ms heap)
JIT: Functions 101, Total 1030 ms (Inlining 160 + Optimization 520 + Emission 345)
Execution Time: 1453 ms
```
The endpoint runs `SET LOCAL jit=off`, so **the 1030 ms JIT compile is NOT paid in
prod** — this EXPLAIN confirms the mitigation is load-bearing (JIT would nearly double
the request). Faithful jit-off work ≈ 600 ms. What's left:
- **The trigram tag index works** — each `t.tag ILIKE '%term%'` is a Bitmap Index Scan
  (~10 ms total across 6 terms), not a seq scan.
- The real residual is the **4 un-indexed ILIKEs per term on `job_listings`
  (title/location/company)** evaluated over the whole ~38 k OPEN set via
  `idx_job_listings_status`. No index touches these.
- `filtered_total` is LIMIT-independent (de-correlated hashed SubPlans), so it costs the
  same as a full count, and **page 1 runs this predicate twice** (page query + count).

### 2d. Search counts — BARE — **62 ms**
`filtered_total` = Parallel Seq Scan of `job_listings` (Hash Anti Join vs the 2 disabled
+ 0 private companies) counting all ~38 k OPEN = 48 ms; the 24 h / 3 h window FILTER via
`idx_job_listings_open_first_seen_keyset` = 13 ms. Fine on its own; it is the keyword /
location variants of this same statement that hurt.

### 2e. Legacy `/api/jobs?companies=stripe,openai` (company trend page) — **107 ms**
```
Sort (f.last_seen_at DESC)  rows=2,833
 -> Hash Join  job_listings(company=ANY, Bitmap idx_job_listings_company)
             ⋈ Seq Scan job_freshness (all 88,810 rows)     <-- full sidecar scan
 SubPlan tags/locations per row (2,833 loops)
Execution 107 ms
```
Note: this path **seq-scans all of `job_freshness`** to get `last_seen_at`, and does NOT
use the bloated 62 MB `idx_job_freshness_last_seen` — that index is pure write-side dead
weight here. DB is 107 ms; the endpoint's 1.13 s is the **2.46 MB payload**
(2,833 full rows incl. tags/locations subqueries) serialize + transfer.

---

## 3. Ranked — slowest endpoints/queries

1. **`GET /api/jobs/search?location=…`  — 2.08 s.** Planner under-estimates location
   selectivity 139× → drops the keyset index, materializes 25 k rows + top-N sort
   (382 k buffers), and `filtered_total` re-runs the same scan un-LIMITed (2×). Worst
   plan in the app; scales with how many jobs match the location, not with page size.

2. **`GET /api/jobs/search` keyword (SWE 6-term) page 1 — 1.45 s.** Page + count each run
   24 un-indexed ILIKEs on `job_listings` over the full 38 k OPEN set (~600 ms), and
   page 1 pays it twice. `jit=off` correctly avoids a further +1030 ms compile. Tag
   trigram index is healthy and cheap.

3. **`GET /api/jobs/search` include=`go`/`ai`/`ml` (<3-char) — ~1.1–1.2 s.** Sub-3-char
   terms yield no trigram key → `job_tags` falls back to seq scan per term, on top of the
   `job_listings` ILIKEs.

4. **`GET /api/jobs?companies=…&limit=5000` — 1.13 s.** DB only 107 ms; **2.46 MB payload**
   is the cost (full column list × thousands of rows, plus a full `job_freshness` seq
   scan). The company-trend read path.

5. **Every cheap endpoint — 0.6–0.75 s regardless of payload** (`facets`, `features`,
   `companies`, `locations/search`). DB is trivial; latency is the **fixed
   Vercel→Railway→FastAPI overhead**. `facets` is seeded taxonomy that changes ~never yet
   costs a full round trip on every load.

### Highest-leverage directions (for the schema/query/cache passes to detail)
- **Cache the static endpoints at the edge** (`facets`, `companies`, `features`): biggest
  universal win — removes ~0.7 s from several first-paint requests. `facets` is
  effectively immutable between migrations.
- **Fix the location filter plan** (#1): give the planner real selectivity (e.g. a
  denormalized country/region column or tag-count stats on `job_listings`) so the keyset
  index survives and pages early-stop; and drop/approximate `location` in the un-LIMITed
  `filtered_total`.
- **Keyword `filtered_total`** (#2): page 1 pays the predicate twice; consider skipping /
  approximating the exact total, or a trigram index on `job_listings.title`.
- **Trim the big payloads** (#4): the trend page ships 2.46 MB; paginate or thin the
  per-row columns (tags/locations subqueries) it doesn't need up front.
- **Storage hygiene (write-side, not latency):** `REINDEX idx_job_freshness_last_seen`
  (62 MB ≈30× bloat from `last_seen_at` re-stamping); `details` TOAST is 718 MB but read
  paths already avoid detoast — keep it that way.
