# Performance Audit — Consolidated Findings & Plan

**App:** JVN / onesecondswe.dev · **Audited:** 2026-09-03 against live prod (Vercel proxy → Railway FastAPI → Postgres).
**Synthesizes:** [`ENDPOINT-BASELINE.md`](./ENDPOINT-BASELINE.md) · [`SCHEMA-AUDIT.md`](./SCHEMA-AUDIT.md) · [`ACCESS-PATTERNS-AUDIT.md`](./ACCESS-PATTERNS-AUDIT.md) · [`CACHING-AUDIT.md`](./CACHING-AUDIT.md) · principles in [`POSTGRES-PRINCIPLES.md`](./POSTGRES-PRINCIPLES.md) / [`POSTGRES-ANTI-PATTERNS.md`](./POSTGRES-ANTI-PATTERNS.md).

> **The one sentence that governs everything:** ~**0.6–0.7 s of every real backend request is fixed
> Vercel→Railway→FastAPI overhead**, independent of the query. The DB is *not* the app's bottleneck —
> the schema is genuinely well built. So the two biggest levers are **(a) caching, which skips the 0.7 s
> hop entirely**, and **(b) not doing avoidable DB work on the hot path** (the exact result-count). Schema
> migrations matter for exactly two slow queries, and are the highest-effort / narrowest-blast items here.

---

## 1. Baseline at a glance — slowest endpoints

Latency = end-to-end curl from a US dev machine (median). DB numbers = `EXPLAIN (ANALYZE, BUFFERS)` on prod.

| Rank | Endpoint (hot shape) | median | payload | DB work | Real bottleneck |
|---|---|---|---|---|---|
| 1 | `GET /api/jobs/search?location=United States` | **2.08 s** | 124 KB | **710 ms ×2** | Planner mis-estimates location 139× → drops keyset index, materializes 25 k rows + top-N sort. Count re-runs it → **page 1 pays it twice**. |
| 2 | `GET /api/jobs/search` keyword, 6-term (SWE), page 1 | **1.45 s** | 103 KB | ~600 ms (count) | Exact `filtered_total` runs 3 un-indexed ILIKEs/term over the whole 38 k OPEN set. Page query itself is only ~40 ms. |
| 3 | `GET /api/jobs/search` include=`go`/`ai`/`ml` (<3 char) | ~1.1–1.2 s | ~110 KB | ~450 ms | Sub-3-char terms yield no trigram key → tag scan falls back to seq. |
| 4 | `GET /api/jobs?companies=…&limit=5000` (trend page) | **1.13 s** | **2.46 MB** | 107 ms | **Payload** — thousands of full rows + per-row tag/location subqueries. DB is fine. |
| 5 | Every "cheap" static endpoint — `facets`, `companies`, `features`, `locations/search` | **0.6–0.75 s** | tiny | ~0 | **Pure fixed overhead.** `facets` returns 1.1 KB of near-immutable taxonomy yet costs a full 0.74 s round-trip on every page load. |
| — | Bare/category search (the healthy baseline) | ~0.9 s | 114 KB | **5–7 ms** | Keyset index early-stops perfectly. This is what the slow shapes *should* look like. |

**The framing that reorders everything (access-patterns doc):** every filtered search on **page 1** runs
two statements — a cheap **page** query (keyset early-stops, 5–40 ms) and an expensive **count**
(`filtered_total`, an *exact* `COUNT(*)` that cannot early-stop). **The count is almost always the villain**,
not the page. Kill/defer the count and most of the search-latency problem disappears with zero schema change.

---

## 2. BIG items — owner's attention, grouped by layer

Ranked within each layer by impact. Full impact-vs-effort ranking in §6.

### Layer A — Caching (highest impact-per-effort in the whole audit; no schema, no query)

**A1 · Edge-cache the 3 static read-only endpoints — `facets`, `companies`, `locations/search`.**
Today nothing is cached above RTK Query's in-memory store: every prod endpoint answers
`x-vercel-cache: MISS, age: 0` because **no proxy sets `s-maxage`** and `forwardResponse` strips backend
headers. These three are unauthenticated and effectively static, yet each eats the full ~0.7 s round-trip on
every visitor's first paint. Setting `Vercel-CDN-Cache-Control: s-maxage=… , stale-while-revalidate=…` on the
proxy serves them from the edge → **removes ~0.7 s from several first-paint requests, app-wide, at near-zero
staleness cost.** This is the single biggest, lowest-risk latency win available anywhere.

### Layer B — Access patterns / query (app-only, no migration)

**B1 · Defer or approximate `filtered_total` on filtered page-1 searches.** *The top query lever.*
The exact count is the expensive half of every filtered search (keyword: ~600 ms; location: ~444 ms). It has
no product-critical value on a feed. Return page 1 immediately with the total deferred to a second async
request, or show "500+". **Removes the expensive half of every filtered page-1 search** with an app-only
change. Keyword 1.45 s → ~0.9 s; location loses its 444 ms twin immediately.

**B2 · Pre-resolve location selections to a `normalized_location_id` set (app half of the location fix).**
The endpoint already runs `resolve_location_selections`; extend it to resolve each selection to the concrete
set of `locations.id`, then emit `jl.normalized_location_id = ANY(%s::int[])` instead of the cross-table
`EXISTS`. Drops the per-row `locations` join + every `upper()` call and gives the planner a simpler subplan.
Pairs with B1 to take location page 1 from 2.08 s → ~1.4 s **without any migration**.

**B3 · Thin the trend-page projection (`/api/jobs?companies=…`).** The 2.46 MB payload is the cost, not the
DB (107 ms). The graph only needs timestamps + a few fields per job to bucket; it does *not* need the per-row
`tags`/`locations` JSON subqueries. A lighter column list for this read path cuts serialize+transfer → ~0.7–0.8 s.
(Cannot paginate — the graph buckets the whole set client-side — so column-thinning is the safe lever.)

### Layer C — Schema (highest effort, narrowest scope; only two slow queries need it)

**C1 · Drop `idx_job_freshness_last_seen` (write-side; the single highest-leverage schema change, and it is a *deletion*).**
`last_seen_at` is re-stamped on every OPEN job every scrape → **69.5 M updates, only 0.1 % HOT**, because an
indexed column can never do a HOT update. Result: an 8 MB table carrying a **62 MB / ~30× bloated index** and
4,615 autovacuums. Dropping it makes every re-stamp HOT again — the freshness sidecar finally delivers its
whole purpose — and stops 62 MB of write amplification + cache eviction. **No hot read path uses this index**
(the search paths probe `job_freshness_pkey`; the trend query seq-scans the 8 MB heap and sorts its result).

**C2 · Denormalize `primary_country` onto `job_listings` (real fix for the #1 slow endpoint).**
The location EXISTS is un-estimable by the planner (est 180 vs real 25,039). No index on the join tables fixes
that — only giving the planner a column it has stats for. Add `primary_country text` + a partial compound
keyset index `(primary_country, first_seen_at, source_id, id) WHERE status='OPEN'`, populated on the write
path. The country tier's filter becomes a seek that keeps the LIMIT-friendly keyset walk → location page query
631 ms → ~25 ms. (Region/city tiers still use EXISTS but match far fewer rows, so the planner behaves.)

**C3 · Denormalize `search_text` onto `job_listings` + one GIN trigram (real fix for keyword search).**
The keyword predicate is a 4-way OR across `title`/`location`/`company` + an `EXISTS` on `job_tags`. Because
one branch is a subquery on another table, **the whole OR collapses to a per-row filter no trigram index on
the three columns can serve.** Collapsing the haystack into one `search_text` column with a single
`gin_trgm_ops` index makes each term one bitmap scan. **Only worth it if keyword-search latency is a product
priority** — `search_text` includes tags, which change on enrichment, so the write path must recompute it and
a GIN trigram is expensive to maintain on writes. If keyword isn't a priority, **B1 (defer the count) already
removes this from the hot path for free.**

---

## 3. Quick wins (low effort, low risk — batch them)

| Win | Layer | Effect | Risk |
|---|---|---|---|
| `REINDEX INDEX CONCURRENTLY idx_job_freshness_last_seen` | schema | Reclaims ~55 MB now (hygiene; re-bloats over weeks — do C1 for the cure) | None — online |
| Edge-cache `facets` / `companies` / `locations` (A1) | caching | −~0.7 s on first paint, app-wide | ≈none → low |
| Defer/approximate `filtered_total` (B1) | access | −250–600 ms on filtered page-1 | Medium (meta contract) |
| Bump RTK `keepUnusedDataFor`: `companiesApi` 60→3600, `locationsApi` 60→900 | caching | Kills needless in-session refetch on nav-back | Per-browser only; trivial |
| `DROP INDEX idx_users_email` + `idx_users_auth0_id` (dup of the UNIQUE constraints) | schema | Removes redundant write overhead | None — UNIQUE index serves the lookup |
| Pre-resolve location IDs (B2) | access | Simpler location subplan, better estimate | Medium (semantics parity test guards it) |

---

## 4. Caching trade-offs — staleness vs. speed, per data type

Caching is the only lever that removes the fixed 0.7 s (it skips the hop). RTK Query (in-memory, per-tab,
dies on reload) is the *only* cache today — the **edge cache is what fills first-paint + cross-user + reload**.

| Data (endpoint) | Change rate | Auth? | Recommendation | Staleness risk |
|---|---|---|---|---|
| **Facets** `/api/jobs/facets` | ~never (taxonomy migration) | no | **Edge-cache hard** — `s-maxage=1 day, SWR=1 wk` | **≈ none** — immutable between migrations; purge on deploy |
| **Companies** `/api/companies` | rare (onboard) | no | **Edge-cache** — `s-maxage=1 h, SWR=1 day` + RTK 3600 | **Low** — a new company invisible ≤1 h; adds are rare, non-urgent |
| **Locations** `/api/locations/search` | slow | no | **Edge-cache per-query** — `s-maxage=10 min, SWR=1 h` + RTK 900 | **Low** — existence is stable; new locations appear slightly late |
| **Company trend** `/api/jobs?company=…` | daily (nightly harvest) | no | **Edge-cache** — `s-maxage=15 min, SWR=1 day` | **Low** — 15-min staleness imperceptible; big payload → pays off on repeat |
| **Recent feed** `/api/jobs/search` | append-heavy | no | Keep RTK per-filter; **optional** 30 s edge on page-1 for bursts | **Moderate** — new jobs delayed ≤30 s. Real fix is the query plan, not caching a slow answer |
| **Features / saved-filters / my-companies / users / admin** | live / per-user / writes | **yes** | **Never shared-cache** — stay `private` | Would leak one user's data to another. Current behavior is correct |

**Rule:** never edge-cache anything carrying `Authorization` (no `Vary` → cross-user leakage). Don't rely on
the auto-ETag — the proxy never honors `If-None-Match`, so only `s-maxage` skips the backend hop.

---

## 5. Blast radius — for each big change

| Change | Migration? | Backfill? | Online-safe? | Blast radius |
|---|---|---|---|---|
| **A1 edge-cache statics** | no | no | yes | **Tiny.** Proxy sets a header on `res` before `forwardResponse`; independent of backend. Add a CDN-purge note to the company-add / taxonomy-migration runbook (SWR makes it non-urgent, not load-bearing). |
| **B1 defer/approx count** | no | no | yes | **Medium.** Touches the `meta`/`filteredTotal` envelope (`JobSearchMeta`, `useRecentJobsSearch.ts`, the "N results" UI). Deferring is backward-shaped (meta can already be null). Approximating is a **product decision**. |
| **B2 pre-resolve location IDs** | no | no | yes | **Medium.** Must preserve hierarchical semantics (country⊇region/city, remote opt-in, null-equality) + the `canonical_name` fallback. Guarded by the `test_server_results_match_client_filter_oracle` parity test. |
| **B3 thin trend projection** | no | no | yes | **Medium.** The trend graph's client transformer must not consume the dropped columns — verify `getJobsForCompany` consumers before thinning. |
| **C1 drop freshness index** | yes (1-line) | no | **yes** — `DROP INDEX CONCURRENTLY` | **Low, but verify first.** No *hot* path uses it; the no-company legacy `/api/jobs` order-by would sort ~38 k rows on `last_seen_at` (bounded, tens of ms, no real UI caller) and `scraper_health` (daily cron) seq-scans 8 MB. **Confirm via Railway logs nothing hot orders by `last_seen_at`**; if something does, keep the index and REINDEX on a schedule instead. |
| **C2 `primary_country` column** | yes | **yes** (bounded batches) | **yes if done right** | **Medium-large.** ALTER must be **catalog-only** (nullable, no default — per the 2026-04-18 volume incident); backfill separately in batches; index built `CONCURRENTLY` (~3 MB, 4 narrow columns like its category sibling); **write-path change in every `fetch_*_company` upsert** to set `primary_country`. Covers the **country tier only**. Coordinate schema + query owners. |
| **C3 `search_text` column + GIN trigram** | yes | **yes** | yes if done right | **Medium-large, the widest.** `search_text` includes **tags, which change** → write path must recompute on any title/location/company/tag change; GIN trigram is **expensive to maintain on writes**; slightly changes exact match semantics (per-field → one joined string). Only take this on if keyword latency is a committed product priority — otherwise B1 obviates it. |

---

## 6. Everything ranked by impact vs. effort

| # | Change | Impact | Effort | Layer | Verdict |
|---|---|---|---|---|---|
| 1 | **Edge-cache `facets`/`companies`/`locations`** (A1) | ★★★★ app-wide −0.7 s | ★ tiny | cache | **Do first.** Biggest win, lowest risk, no schema/query. |
| 2 | **Defer/approximate `filtered_total`** (B1) | ★★★★ −250–600 ms on every filtered search | ★★ app | access | **Do first.** Top query lever; gated on one product decision (§7). |
| 3 | **Drop `idx_job_freshness_last_seen`** (C1) | ★★★ kills 62 MB write-amp + autovacuum churn | ★ 1-line, online | schema | High-leverage *deletion*; verify no hot `last_seen_at` order-by first. |
| 4 | **RTK TTL bumps + REINDEX + drop dup user indexes** | ★★ hygiene | ★ trivial | cache/schema | Batch quick wins. |
| 5 | **Pre-resolve location IDs + kill location count** (B2+B1) | ★★★ location 2.08 s → ~1.4 s | ★★ app | access | No migration; big share of the #1 endpoint. |
| 6 | **Thin trend-page projection** (B3) | ★★ 1.13 s → ~0.8 s | ★★ app | access | 2.46 MB payload is the cost, not the DB. |
| 7 | **Denormalize `primary_country`** (C2) | ★★★ location page 631 ms → ~25 ms | ★★★★ migration+backfill+write-path | schema | The real location fix; do after B1+B2 prove insufficient. |
| 8 | **Denormalize `search_text` + GIN** (C3) | ★★★ keyword count → bitmap | ★★★★★ widest write-path cost | schema | **Only if keyword is a product priority** — else B1 covers it free. |

---

## 7. The decisions the owner must make

1. **(Top, gates the biggest query wins) Exact counts vs. fast searches.** Are exact "N results" totals on
   filtered searches worth 250–600 ms on every page-1? If we can **defer or approximate** them, B1 unlocks
   most of the search-latency win with no migration — and makes C3 unnecessary. *This is the single cheapest
   high-leverage decision in the audit.*
2. Is **keyword-search latency** a committed product priority worth C3's ongoing write-path + GIN cost? (If #1
   is "approximate is fine," the answer is almost certainly no.)
3. Is the **location filter** important enough to justify the C2 migration+backfill+write-path, or do B1+B2
   (no migration, ~1.4 s) suffice for now?

---

## Do NOT do (from the audits)
- **Don't persist the jobs corpus** in localStorage/IndexedDB — re-introduces the 50 GB memory failure mode
  (CLAUDE.md Gotcha #7/#10).
- **Don't add a GIN trigram on `job_listings.title` alone expecting it to fix keyword search** — the OR shape
  forecloses it; only the collapsed `search_text` column (C3) is index-usable.
- **Don't edge-cache authed endpoints** (features/users/admin/saved-filters) — cross-user leakage.
- **Don't cache `/api/jobs/search` long** — it's append-heavy *and* the slow query; caching a stale slow answer
  is worse than fixing the plan. Short SWR only, if at all.
