# Wave-1 Performance Plan — file-level

Grounded in [`PERF-AUDIT-FINDINGS.md`](./PERF-AUDIT-FINDINGS.md),
[`ACCESS-PATTERNS-AUDIT.md`](./ACCESS-PATTERNS-AUDIT.md),
[`SCHEMA-AUDIT.md`](./SCHEMA-AUDIT.md),
[`CACHING-AUDIT.md`](./CACHING-AUDIT.md); owner calls in
[`DECISIONS.md`](./DECISIONS.md). All paths absolute-from-repo-root, in the
`end-to-end-tests` worktree.

**Wave-1 items only:** A1, RTK TTLs, C1, B1, B2, B3.
**OUT OF SCOPE (Wave 2):** C2 (`primary_country`), C3 (`search_text` + GIN). No new
denormalized columns, no scraper write-path changes.

Principle for every item: **additive / surgical, preserve behavior.**

---

## Three things that are load-bearing and easy to get wrong

1. **`forwardResponse` ends the response.** Every A1 cache header must be set on
   `res` **before** the `forwardResponse(...)` / `res.status().json()` call in that
   proxy. (`api/utils/forwardResponse.ts` copies status + body only — same reason
   `X-Next-Cursor` is re-emitted by hand.)
2. **B3 may NOT drop `locations`.** The trend page's shared `JobListingCard` renders
   `job.locations` chips *and* the client-side location filter matches on them. Only
   the **tags** subquery (→ `enrichmentTags`, which nothing reads) is safe to thin.
   See B3.
3. **C1: a third consumer exists** beyond the audit's "two cold paths" — the admin
   `list_problem_jobs` paged query orders by `f.last_seen_at DESC`
   (`services/location_admin.py:518`, documented at `db_models.py:160`). Still
   admin/cold, so the drop is fine, but the verify step must account for it. See C1.

---

## A1 — Edge-cache the 3 static read-only proxies

TTLs are from `CACHING-AUDIT.md` §6. Pattern from §2: set the split headers **before**
`forwardResponse`. Use `Vercel-CDN-Cache-Control` (edge only) so browser behaviour is
unchanged (browsers keep `max-age=0, must-revalidate` → a purge is instantly visible).

| Endpoint | Proxy file | Guard (only cache these) | Header value |
|---|---|---|---|
| facets | `api/jobs.ts` | `sub === 'facets'` | `s-maxage=86400, stale-while-revalidate=604800` |
| companies | `api/companies.ts` | `GET` + bare directory (`targetPath === ''`) + **no** `Authorization` | `s-maxage=3600, stale-while-revalidate=86400` |
| locations | `api/locations.ts` | `resolveProxyPath(...)==='search'` (the only path) | `s-maxage=600, stale-while-revalidate=3600` |

For each, set both headers before forwarding:
```ts
res.setHeader('Cache-Control', 'public, max-age=0, must-revalidate');
res.setHeader('Vercel-CDN-Cache-Control',
  'public, s-maxage=<N>, stale-while-revalidate=<M>');
```

### `api/jobs.ts`
- Insert the header set inside the existing branch where `sub === 'facets'`.
  Currently facets falls through the generic `else` (single-valued params). Add the
  facets cache header just before the `try { fetch(...) }` (line ~106), gated on
  `sub === 'facets'`. **Leave `sub === 'search'` and the legacy company list
  uncached** — search is append-heavy *and* the slow query; the trend read is B3's
  problem, and its edge-cache (CACHING-AUDIT win #5) is **not** part of Wave-1 A1.

### `api/companies.ts`
- Add the header only when `req.method === 'GET' && targetPath === '' &&
  !req.headers.authorization`. The proxy forwards `Authorization` when present and
  serves `POST resolve`; **neither may be edge-cached** (auth leak / mutation). Set it
  just before `await forwardResponse(response, res)` (line ~72).

### `api/locations.ts`
- Public GET, keyed per URL (`q`/`limit`/`openOnly`) by the CDN automatically. Set the
  header just before `await forwardResponse(response, res)` (line ~43).

### Runbook note (non-blocking; SWR makes it belt-and-suspenders)
- Add "purge Vercel CDN for `/api/companies` and `/api/jobs/facets`" to the
  company-add procedure (`.claude/skills/add-company/`) and any taxonomy-migration
  doc. A stale serve is at worst one SWR window; not load-bearing.

**Verify:** `curl -sI https://onesecondswe.dev/api/jobs/facets` twice → second shows
`x-vercel-cache: HIT`. Confirm `/api/features` (authed) and `/api/jobs/search` still
show `MISS`.

---

## RTK `keepUnusedDataFor` bumps

Kills needless in-session refetch on nav-back. Per-browser only; trivial.

- `src/frontend/src/features/companies/companiesApi.ts` — add
  `keepUnusedDataFor: 3600` to the `listCuratedCompanies` endpoint (line 27-31 block).
- `src/frontend/src/features/locations/locationsApi.ts` — add
  `keepUnusedDataFor: 900` to the `searchLocations` endpoint (line 80-91 block). The
  per-`{q,limit,openOnly}` cache key already isolates terms.

**Verify:** `npm run type-check`; existing slice tests still green.

---

## C1 — Drop `idx_job_freshness_last_seen` + index hygiene

The single highest-leverage schema change, and it is a **deletion**. `last_seen_at` is
re-stamped every scrape (69.5 M updates, 0.1 % HOT because the column is indexed) →
8 MB heap carrying a 62 MB / ~30× bloated index. Dropping it makes every re-stamp HOT
again. Bundle the two duplicate `users` indexes (audit Finding 4a) into the same
migration.

### Files
1. **`src/backend/api/db_models.py`** — remove three `Index(...)` lines so the model
   matches the migration (and `Base.metadata.create_all` in tests + future
   autogenerate stay consistent):
   - line 291 `Index("idx_job_freshness_last_seen", "last_seen_at")` (in `JobFreshness`)
   - line 460 `Index("idx_users_auth0_id", "auth0_id")` (in `User`)
   - line 461 `Index("idx_users_email", "email")` (in `User`)
   - **Keep** the UNIQUE constraints `users_auth0_id_key` / `users_email_key` — they
     already serve the equality lookups. Update the nearby comment at `db_models.py:160`
     that says the problem-jobs paged query is "driven by idx_job_freshness_last_seen"
     (post-drop it sorts — see verify).
2. **New Alembic migration** in `src/backend/alembic/versions/`,
   `down_revision = '776b9dbc68cc'` (current single head — verified via the merge
   `20260903_011500_776b9dbc68cc`). Generate with `alembic revision --autogenerate`
   after step 1 (it will emit `op.drop_index` for all three), then hand-adjust the
   freshness drop to run **CONCURRENTLY** (the table is write-hot; a plain `DROP INDEX`
   takes a brief ACCESS EXCLUSIVE lock that would block scrape writes). CONCURRENTLY
   cannot run inside Alembic's transaction, so wrap it:
   ```python
   def upgrade() -> None:
       # dup-user-index drops: tiny table (345 rows), plain drop is instant + safe
       op.drop_index("idx_users_auth0_id", table_name="users")
       op.drop_index("idx_users_email", table_name="users")
       # freshness index: online, outside the migration txn
       with op.get_context().autocommit_block():
           op.execute(
               "DROP INDEX CONCURRENTLY IF EXISTS idx_job_freshness_last_seen"
           )

   def downgrade() -> None:
       with op.get_context().autocommit_block():
           op.execute(
               "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
               "idx_job_freshness_last_seen ON job_freshness (last_seen_at)"
           )
       op.create_index("idx_users_email", "users", ["email"])
       op.create_index("idx_users_auth0_id", "users", ["auth0_id"])
   ```
   (`if_exists`/`if_not_exists` keep it idempotent — a CONCURRENTLY failure can leave
   an INVALID index; re-run is safe.)

### The "verify no hot `last_seen_at` order-by first" check (mandatory, pre-merge)
Every `ORDER BY … last_seen_at DESC` consumer, enumerated:
- `services/database.py:195` `_LEGACY_ORDER_BY` — the **no-`since`/`cursor`** `/api/jobs`
  path. With a company filter (the trend read) the planner **seq-scans `job_freshness`
  + sorts ~2,833 rows** and does **not** use this index (EXPLAIN in ACCESS-PATTERNS
  Finding 4). Only the **no-company** shape would use it — and no live UI caller hits
  it (Recent moved to `/search`; trend always passes a company).
- `services/location_admin.py:518` `list_problem_jobs` — admin
  `/admin/location-normalization` problem-jobs page, `ORDER BY f.last_seen_at DESC LIMIT`.
  **This is the third consumer** (the audit named only two). Admin, low-traffic;
  post-drop it does a bounded sort (the WHERE limits the set) — acceptable.
- `services/scraper_health.py` — `MAX(f.last_seen_at) … GROUP BY company` (daily cron);
  grouping, needs no ordered index.
- `api/eval/monitor_prod.py:324` — read-only on-demand storage monitor; not hot.

**Action:** confirm via Railway logs that nothing hot hits the no-company legacy
`/api/jobs`. If something does, keep the index and REINDEX on a schedule instead
(`REINDEX INDEX CONCURRENTLY idx_job_freshness_last_seen` reclaims ~55 MB but
re-bloats — hygiene, not cure). **REINDEX is moot once dropped** — it is only the
fallback if the drop is deferred.

**Verify:** backend suite against a throwaway clean DB (known stale-`alembic_version`
gotcha — run pytest against a fresh schema); `list_problem_jobs` still returns rows in
`last_seen_at DESC` order (now via sort). Confirm `alembic_version` advances on deploy.

---

## B1 — Defer / approximate `filtered_total` (owner decision ①)

The exact count is the expensive half of every filtered page-1 search. Stop computing
it on the hot path; return it `null`; the UI approximates from loaded rows. The two
recency tiles (`count_last_24h/3h`) are cheap (windowed over the 24 h slice of the
keyset index) — **keep them.** Backward-compatible with the nullable meta.

### Backend
1. **`src/backend/api/services/job_search.py`**
   - `SearchCounts` TypedDict (line 83): `filtered_total: int | None`.
   - `_SEARCH_COUNTS_SQL` (line 661): **remove** the
     `(SELECT count(*) FROM {jobs}{filtered_where}) AS filtered_total,` subquery. The
     statement becomes just the two windowed `count(*) FILTER (...)` tiles over
     `{header_where}` — no `{filtered_where}` at all.
   - `get_search_counts` (line 674): drop the `build_search_where(**filters)` call for
     the filtered count and its params; return `filtered_total=None`. (Keep
     `_header_counts_where`.) This deletes the second, expensive predicate evaluation
     entirely — page 1 no longer runs the keyword/location predicate twice.
2. **`src/backend/api/models.py`** — `JobSearchMeta.filtered_total` (line 1044):
   `filtered_total: int | None = None`.
3. **`src/backend/api/routers/jobs_search.py:566`** — `JobSearchMeta(filtered_total=
   counts["filtered_total"], ...)` now passes `None`. No other change.

### Frontend (make `total` nullable end-to-end)
4. **`src/frontend/src/features/jobs/searchJobsTypes.ts`** — `SearchJobsCounts.total:
   number | null` (line 24).
5. **`src/frontend/src/features/jobs/validateSearchJobsResponse.ts`** — `validateCounts`
   (line 28) currently **throws** if `filteredTotal` is not a number. Relax: accept
   `filteredTotal` `number | null | undefined`, map to `null`; keep requiring
   `countLast24h` / `countLast3h` as numbers. This is the one place that would reject
   the new envelope.
6. **`src/frontend/src/components/recent-jobs-page/RecentJobsList/RecentJobsList.tsx:107`**
   — `announcedTotal = counts === null ? null : Math.max(counts.total, displayedJobs.length)`
   goes **NaN** when `counts.total` is null. Change to: when `counts.total == null`,
   announce the **approximate** lower bound from loaded rows (`displayedJobs.length`,
   with a "+" affordance when `hasNextPage`) — this is the "approximate" half of the
   decision and costs nothing. This drives `aria-setsize`; keep the ARIA-unknown (`-1`)
   degradation intact for the genuinely-absent case.
7. **`src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx:64`** —
   `totalJobs={counts?.total ?? null}` is already null-safe; confirm the display
   component renders `null` as an em-dash / hidden (no code change expected).
8. Already null-safe, no change: `webmcp/tools/tier1Read.ts:204`
   (`filteredTotal: body.counts?.total ?? null`), `jobsApi.ts:360`,
   `useRecentJobsSearch.ts:371`.

### Optional follow-up (NOT required for Wave 1)
- If an exact total is later wanted, add a dedicated `?countOnly=1` async request /
  endpoint the client fires after page 1. Deferring-to-nothing + client-side
  approximation is the Wave-1 minimum and matches the decision ("fast searches beat
  exact counts").

**Verify:** `test_jobs_search_filters.py` (meta assertions expect `filteredTotal` — update
to accept `null`); recency-tile tests unchanged; frontend
`useRecentJobsSearch.test.tsx` / `jobsApi.search.test.ts` /
`recentJobsSearchHydrationGate.test.tsx` still green with nullable total. Expected:
keyword page-1 1.45 s → ~0.9 s; location loses its 444 ms count twin.

### ✅ IMPLEMENTED (Wave 1 — QUERY/APP)

Approach chosen: **defer-to-null + client approximation** — the least-invasive of the
two options, and it keeps the meta envelope byte-compatible (the `filteredTotal` KEY
still ships, now always `null`; no separate `?countOnly` request added).

- **Backend.** `_SEARCH_COUNTS_SQL` dropped the `(SELECT count(*) … {filtered_where})
  AS filtered_total` subquery entirely — the statement is now ONLY the two windowed
  recency tiles. `get_search_counts` no longer calls `build_search_where` at all (the
  second, expensive predicate evaluation is gone) and returns `filtered_total=None`.
  `SearchCounts.filtered_total` → `int | None`; `JobSearchMeta.filtered_total: int |
  None = None`. So page 1 now runs the filter predicate ONCE, not twice.
- **Frontend.** `SearchJobsCounts.total` → `number | null`. `validateCounts` relaxed to
  accept `filteredTotal` = number | null | undefined (→ `null`) while STILL rejecting a
  wrong type like the string `'137'`; the two recency tiles stay required numbers.
  `RecentJobsList.tsx` `announcedTotal` (drives `aria-setsize`): `counts === null` →
  `null` (ARIA `-1`); an exact total (demo mode) → `Math.max(total, rows)`; a deferred
  (`null`) total → `-1` while `hasNextPage` (the rows are only a lower bound mid-walk),
  and the exact rows-in-hand once the walk is exhausted. `counts?.total ?? null`
  consumers (`RecentJobPostingsPage`, `tier1Read`) were already null-safe.
- **Product note (deliberate, flag for owner):** with `filteredTotal` null, the "Displayed
  Jobs" metric tile renders an **em-dash** (per plan step 7 — no tile code change). The
  rows are still visible and both recency tiles keep real numbers. If a visible
  approximate count ("500+") is later wanted on that tile, it is a small follow-up.

---

## B2 — Pre-resolve location selections to `normalized_location_id` (app half of decision ③)

Replace the per-row cross-table `EXISTS (… JOIN locations l … upper(l.country)=…)` with a
pre-resolved integer-set probe `EXISTS (… WHERE jl.normalized_location_id = ANY(%s::int[]))`.
Drops the per-row `locations` join and every `upper()` call and gives the planner a
simpler subplan. No migration.

### File: `src/backend/api/services/job_search.py`
1. **Extend resolution to ids.** `resolve_location_selections` (line 277) currently
   returns one `LocationDescriptor` per selection (used for the fingerprint). Add a
   companion resolution — same function or a sibling — that, per selection, computes the
   **set of matching `locations.id`** =
   `{ id WHERE canonical_name = <selection> }  ∪  { id WHERE <tier predicate for that
   selection's descriptor> }`. One extra query over the 1,186-row `locations` table
   (batchable across selections). The **canonical-name branch must stay** (audit
   requires the exact-name fallback): a selection with no descriptor still resolves the
   ids whose `canonical_name` equals it.
2. **Preserve hierarchy semantics.** Run the existing `_tier_condition` logic
   (`country ⊇ region/city`, `l.kind <> 'remote'` for geographic tiers, remote opt-in,
   `IS NOT DISTINCT FROM` null-equality on region/country) **at resolve time against the
   `locations` catalog** to gather the id set, instead of at query time per job row.
   "United States" and "<State>, US" (no catalog row for the name) resolve via the tier
   predicate (`country=US` / `region=<ST>,country=US`) exactly as today — the ids come
   from real `locations` rows the tier matches.
3. **Rewrite `_location_condition`** (line 385) for the pre-resolved path: emit
   ```sql
   EXISTS (SELECT 1 FROM job_locations jl
           WHERE jl.job_listing_id = job_listings.id
             AND jl.normalized_location_id = ANY(%s::int[]))
   ```
   with the selection's resolved id array as the single param. A selection resolving to
   an **empty** id set yields `= ANY('{}')` → matches nothing, identical to today's
   name-miss behaviour. A job with no location tags matches no filter (unchanged).
4. **Thread the id sets through `SearchFilters`** so the page query and the count query
   share one resolution (the router already resolves once and unpacks into both). Since
   B1 removes the filtered count, only the page query consumes it now — but keep the
   plumbing symmetric.

### Semantics parity is the guard
- The port must keep `matchesLocation`'s exact behaviour. The oracle test
  **`src/backend/api/tests/test_jobs_search_filters.py::test_server_results_match_client_filter_oracle`**
  (line 622) runs the Python translation of the client matcher against the same corpus
  — **it must stay green**. Add cases if needed for: country⊇region/city containment,
  Remote (US) not matching an unscoped global-remote tag, and the "United States" /
  "<State>, US" synthesized options.

**Verify:** parity oracle green; captured-SQL tests (the generated SQL text changes —
update fixtures); EXPLAIN on prod shows the `locations` join and `upper()` gone from the
subplan. Expected with B1: location page-1 2.08 s → ~1.4 s. (C2 later → ~0.9 s.)

### ✅ IMPLEMENTED (Wave 1 — QUERY/APP)

- New `resolve_location_ids(conn, selections, descriptors)` runs the SAME
  `(canonical_name = %s OR <tier>)` group per selection — reused via
  `_location_match_group`, which factors it out of the old `_location_condition` — but
  as ONE `SELECT id FROM locations l WHERE …` over the 1,186-row catalog, returning the
  sorted union of matching ids. The router resolves descriptors (for the fingerprint,
  unchanged) then ids, and threads `location_ids` through `SearchFilters` in place of
  `location_descriptors`.
- `_location_predicate(location_ids)` replaces the per-row cross-table EXISTS with
  `EXISTS (SELECT 1 FROM job_locations jl WHERE jl.job_listing_id = job_listings.id AND
  jl.normalized_location_id = ANY(%s::int[]))` — no `locations` join, no `upper()` on the
  hot path. **The N-selection OR collapses to one EXISTS legitimately**: the filter is
  `loc(sel₁) OR … OR loc(selₙ)` over the same `job_locations` rows and `∃t (P₁∨…∨Pₙ)` ≡
  `(∃t P₁) ∨ … ∨ (∃t Pₙ)`, so one probe over the union id-set is exactly equivalent.
- **Parity preserved** (hierarchy containment, remote opt-in, null-equality,
  canonical-name fallback, duplicate-canonical resolution, empty-set → matches nothing):
  the tier branch still uses only each selection's single ranked descriptor and the
  exact-name branch still matches every same-named row — verified against every case in
  `test_jobs_search_locations.py`. **`test_server_results_match_client_filter_oracle`
  passes.** The fingerprint still folds the DESCRIPTORS, so the mid-walk resolution-flip
  409 is unchanged.

---

## B3 — Thin the trend-page projection (`/api/jobs?company=…`)

The 2.46 MB payload is the cost, not the DB (~107 ms). **The naive "drop tags +
locations" is UNSAFE and would change behavior** — verified against consumers:

| Column (subquery) | → transformer field | Consumed on trend page? | Verdict |
|---|---|---|---|
| `_LOCATIONS_SUBQUERY` | `raw.locations` → `locations` | **YES** — `JobListingCard.tsx:121-130` renders location chips; `jobFilteringUtils.ts:253` `matchesLocation` filters on it | **KEEP** |
| `_TAGS_SUBQUERY` | `raw.tags` → `enrichmentTags` | **NO reader** — grep for `enrichmentTags` finds only the type def, the transformer write, and landing `mockData`; no component/selector/card reads it | **SAFE to drop** |

So Wave-1 B3 = **drop only the tags subquery, scoped to the legacy trend read path**,
keeping locations. That removes one of the two correlated per-row subqueries and the
per-row tags JSON array — a real, safe payload cut.

### File: `src/backend/api/services/database.py`
- **Do NOT edit the shared `_LIST_COLUMNS`** (line 308) — it is also used by
  `search_jobs` (Recent page), `get_user_company_jobs`, `get_owned_custom_jobs`,
  `get_job_by_id`. Editing it in place widens blast radius.
- Add a **trend-scoped column list** — `_LIST_COLUMNS` minus `_TAGS_SUBQUERY` (i.e. the
  base columns `+ _LOCATIONS_SUBQUERY` only) — and use it **only in `get_jobs`** (line
  329, the `/api/jobs` legacy path that the trend read hits via
  `getJobsForCompany → backendScraperClient → /api/jobs?company=&limit=5000`, no
  `since`/`cursor`). All other callers keep `_LIST_COLUMNS` unchanged.
- The transformer sets `enrichmentTags: raw.tags ?? []` → `[]` when absent; no reader,
  so behavior is preserved.

### Mandatory pre-drop verification (surprise-proofing)
- Re-run `grep -rn "enrichmentTags" src/frontend/src` (excluding tests + `mockData`) to
  confirm zero readers before dropping. If any reader is found (a new job overlay, QA
  page, webmcp surface), **do not drop** — keep tags and reduce B3 to a no-op for Wave 1,
  and flag that the real payload win needs the graph-only fetch decoupled from the
  rich list fetch (a larger change → Wave 2).
- `get_job_by_id` (single-posting detail) still returns tags via its own subqueries —
  unaffected, so any detail view that shows enrichment tags keeps them.

**Note on the audit's larger claim:** ACCESS-PATTERNS Finding 4 ("the graph needs
neither tags nor locations") is true for the **graph** but false for the **trend page
as a whole** — the same payload feeds the job list (location chips) and the client
location filter. Dropping locations too would require splitting the graph's
bucket-only fetch from the list's rich fetch; that is a bigger refactor, **deferred
past this surgical wave.**

**Verify:** `getJobsForCompany` consumers (graph buckets, `JobList`, cards, graph
filters) render identically; measure payload drop on `/api/jobs?company=stripe`.
Expected: trend read 1.13 s → ~0.8–0.9 s (locations retained, tags gone).

### ✅ IMPLEMENTED (Wave 1 — QUERY/APP)

- `database.py`: extracted `_LIST_BASE_COLUMNS` (everything but the two subqueries);
  `_LIST_COLUMNS` = base + tags + locations (UNCHANGED, still used by `search_jobs`,
  `get_user_company_jobs`, `get_owned_custom_jobs`, single-job detail); NEW
  `_TREND_LIST_COLUMNS` = base + locations only, used **only in `get_jobs`** (both
  legacy and keyset modes — no `get_jobs` caller reads tags).
- **Zero-reader re-grep confirmed**: `enrichmentTags` (the transformer field the backend
  `tags` column maps to) has no reader anywhere in `src/frontend/src` — only the type
  def, the transformer write (`raw.tags ?? []`), and landing `mockData`. `get_jobs`
  callers (trend `getJobsForCompany`, admin QA `/api/jobs`) don't read it.
  `_row_to_job_dict` fills a missing `tags` key with `[]`, so a thinned row still
  serializes `tags: []` and `enrichmentTags` stays `[]` — behaviour preserved.
  `test_database_service.py` + `test_jobs_router.py` green.

---

## OUT OF SCOPE — do NOT implement in this workflow

- **C2 — `primary_country` column.** Migration + backfill + write-path change in every
  `fetch_*_company` upsert. Wave 2 (owner decision ③). The real location fix; B1+B2
  cover this wave.
- **C3 — `search_text` column + GIN trigram.** Schema + write-path recompute on every
  title/location/company/tag change. Wave 2 (owner decision ②). B1 removes the keyword
  count from the hot path for free, so no urgency.
- No new denormalized columns; no scraper write-path changes anywhere in Wave 1.

---

## Suggested build order (independent items first)

1. **A1 + RTK TTLs** — zero risk, biggest first-paint win, no schema/query.
2. **C1** — the deletion; needs the `last_seen_at` verify + clean-DB pytest.
3. **B1** — backend nullable meta + the 4 frontend consumers.
4. **B2** — depends on the location predicate; guarded by the parity oracle.
5. **B3** — smallest, gated on the `enrichmentTags` zero-reader re-grep.

`npm run type-check` (Node 22.14.0), `cd src/backend && mypy`, and the relevant test
suites gate each. Never pipe a test/build through `tail` — redirect to a file and read
it. Do NOT `git commit` except in the final stage.
