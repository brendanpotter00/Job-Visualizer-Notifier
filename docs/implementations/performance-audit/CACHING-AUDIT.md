# Client + Edge Caching Audit — JVN (onesecondswe.dev)

Measured 2026-09-03 against live prod. Companion to `ENDPOINT-BASELINE.md` (latency +
query plans) — this doc covers the **caching layer**: HTTP cache headers, Vercel edge
(CDN), and RTK Query. The baseline's headline finding drives this whole audit:

> **~0.6–0.7 s of every real backend hit is fixed Vercel→Railway→FastAPI overhead,
> independent of the query.** DB work on the cheap endpoints is trivial.

Caching is the *only* lever that removes that fixed 0.7 s, because it skips the hop
entirely. The schema/query passes make slow queries faster; caching makes repeat reads
free.

---

## 0. The one fact that governs everything

**Nothing is cached anywhere above RTK Query's in-memory store.** Every prod endpoint —
public and static included — answers with the Vercel serverless default:

```
cache-control: public, max-age=0, must-revalidate
x-vercel-cache: MISS        age: 0
etag: W/"…"                 (auto, body hash)
```

Verified on `/api/companies`, `/api/jobs/facets`, `/api/locations/search`,
`/api/jobs/search`, `/api/jobs`. `x-vercel-cache: MISS` + `age: 0` on every call = the
CDN stores nothing and re-runs the function every time.

**Two independent reasons the edge is empty, both in our code:**

1. **No proxy sets `s-maxage`.** Vercel's CDN caches a function response *only* when the
   function emits `Cache-Control` (or `Vercel-CDN-Cache-Control`) with `s-maxage`. None
   of the eight `api/*.ts` proxies set any cache header, so they inherit
   `max-age=0, must-revalidate` = "never cache".
2. **`forwardResponse` strips the backend's headers anyway** (`api/utils/forwardResponse.ts`).
   It copies **status + body only** — same design note that forced `X-Next-Cursor` to be
   re-emitted by hand in `api/jobs.ts`. So even if FastAPI set `Cache-Control`/`ETag`,
   they die at the proxy. The `etag` you see on the wire is Vercel/Node auto-hashing the
   body, **not** the backend's.

**The auto-ETag is nearly worthless here.** The proxy never reads `If-None-Match` and
always re-fetches Railway, so the ETag can at best save browser↔edge *body bytes* via the
platform — it never skips the backend round-trip. **`s-maxage` is what removes the 0.7 s**,
not the ETag.

---

## 1. Top caching wins (ranked by leverage × safety)

| # | Change | Removes | Staleness risk |
|---|---|---|---|
| **1** | **Edge-cache `/api/jobs/facets`** — `s-maxage=86400, SWR=604800` | ~0.74 s off first-paint for every visitor after the first | **≈ none** — taxonomy is immutable between migrations; purge on deploy |
| **2** | **Edge-cache `/api/companies`** — `s-maxage=3600, SWR=86400` | ~0.73 s + 60 KB per cold load | **Low** — a newly-onboarded company is invisible ≤1 h; adds are rare + non-urgent |
| **3** | **Edge-cache `/api/locations/search`** — `s-maxage=600, SWR=3600`, `Vary` on the query | ~0.59 s per distinct autocomplete term (repeat terms across all users) | **Low** — a location existing/not is stable; new locations appear in autocomplete slightly late (invisible to users) |
| **4** | **Bump RTK `keepUnusedDataFor`** on `companiesApi` (60→3600) and `locationsApi` (60→900) | in-session refetches on nav back to a page | Same as 2/3, but per-browser |
| **5** | **Edge-cache the company-trend read `/api/jobs?company=…`** — `s-maxage=900, SWR=86400` | ~0.8 s (+ up to 2.46 MB on the multi-company variant) for repeat trend-page views | **Low** — data is a nightly harvest; 15-min staleness is imperceptible |
| **6** | *(optional)* **Short edge cache on `/api/jobs/search` page-1** — `s-maxage=30, SWR=120` | absorbs bursts on the busiest read | **Moderate** — new jobs delayed ≤30 s; only worth it if search load bites (it's the slow query, not a cheap one) |

Wins 1–3 are the headline: **three read-only, unauthenticated, effectively-static
endpoints that cost a full 0.7 s round-trip on every single page load today and can be
served from the edge with essentially zero staleness cost.**

---

## 2. How to actually cache at the edge (Vercel)

Two headers, different scopes — prefer the split so the browser and the CDN can disagree:

```ts
// In each read-only proxy, BEFORE forwardResponse (which ends the response):
// Edge/CDN caches for s-maxage and may serve stale while it revalidates in the
// background; browsers always revalidate to the edge (max-age=0), so a purge is
// instantly visible and no user is pinned to a stale copy in their own cache.
res.setHeader('Cache-Control', 'public, max-age=0, must-revalidate');
res.setHeader('Vercel-CDN-Cache-Control', 'public, s-maxage=86400, stale-while-revalidate=604800');
```

- `Vercel-CDN-Cache-Control` steers **only** Vercel's edge; it is not forwarded to the
  browser, so client behaviour is unchanged (still revalidates). Use plain
  `Cache-Control` with `s-maxage` if you want browsers to cache too.
- `stale-while-revalidate` = the edge serves the last good copy *instantly* and refreshes
  in the background — so even the "first viewer after expiry" doesn't eat the 0.7 s.
- **This must be paired with removing the `forwardResponse` header-strip problem?** No —
  the *proxy itself* sets these on `res`, so it's independent of what the backend sends.
  `forwardResponse` still runs; just set the header on `res` before calling it.
- **Purge on deploy:** facets/companies change only via a migration+deploy. A deploy gives
  a new function version, but the CDN key can outlive it — add a manual purge (Vercel
  "Redeploy" or `vercel --prod` invalidates; or bump a cache-busting query the SPA sends)
  to the company-add / taxonomy-migration runbook. With `SWR` the worst case is one stale
  serve, so this is belt-and-suspenders, not load-bearing.

**Do NOT edge-cache anything that carries `Authorization`** (features when authed, users,
admin, saved-filters, feedback, users/companies). A shared cache keyed without
`Vary: Authorization` would serve one user's `hasUpvoted` / private data to another. These
stay `private, no-store` (their effective behaviour today, since nothing sets s-maxage).

---

## 3. Per-data-type staleness verdict

The core question per type: **"is it OK if this is stale, as long as it's fast?"**

| Data (endpoint) | Change rate | Auth? | Stale-OK? | Verdict |
|---|---|---|---|---|
| **Facets** `/api/jobs/facets` | ~never (taxonomy migration) | no | **totally** | **Edge-cache hard** (s-maxage 1 day + SWR 1 wk). Also RTK already 3600 — good. |
| **Companies** `/api/companies` | rare (onboard a company) | no | **yes, hours** | **Edge-cache** (s-maxage 1 h + SWR 1 day) + RTK 3600. New company late by ≤1 h is fine. |
| **Locations** `/api/locations/search` | slow (new locations from scrapes) | no | **yes** | **Edge-cache per-query** (s-maxage 10 min + SWR 1 h) + RTK 900. Existence is stable; `openOnly` drift is harmless. |
| **Recent feed** `/api/jobs/search` | append-heavy (continuous) | no | **short only** | Keep RTK (per-filter 10 min in-session already). Optional 30 s edge cache on page-1 for burst absorption. Real fix is the query plan, not caching. |
| **Company trend** `/api/jobs?company=…` | daily (nightly harvest) | no | **yes, ~15 min** | **Edge-cache** (s-maxage 15 min + SWR 1 day). Big payload → cache pays off on repeat views. RTK 600 already. |
| **Features** `/api/features` | live votes | **yes (authed)** | no (actor) / yes (counts) | **Do not shared-cache** (per-user `hasUpvoted`). Optimistic update + tag-invalidation already make it feel instant. Leave. |
| **Saved filters** `/api/users/saved-filters*` | user edits | **yes** | **no — must be fresh** | Keep private. RTK 300 s + mutation-invalidation is correct as-is. |
| **My companies** `/api/users/companies` | user adds + discovery polling | **yes** | **no — must be fresh** | Keep private, no edge cache. Polled at 4 s/15 s by design. Correct as-is. |
| **Users / admin / feedback** | per-user / writes | **yes** | **no** | Never cache. Correct as-is. |

---

## 4. RTK Query layer — current state + tuning

RTK Query is the **only** cache that exists today, and it's in-memory + per-browser-tab
(lost on reload). It's well-configured for the hot paths but has two under-set TTLs.

| Slice | `keepUnusedDataFor` | Invalidation | Verdict |
|---|---|---|---|
| `jobsApi` (default) | **600** (10 min) | tag `Jobs` per company | Good. `searchJobs` infinite query inherits it — flipping a filter back is instant. |
| `jobsApi.getFacets` | **3600** (override) | none | Good — matches immutability. |
| `savedFiltersApi` gets | **300** (override) | `SavedFilters`/`KeywordLists` on every mutation | Correct — fresh-enough + invalidated. |
| `companiesApi` | **default 60** ← | tag `CuratedCompanies` (never invalidated client-side) | **Bump to 3600.** Directory changes ~never in a session; 60 s forces a needless refetch on nav-back. |
| `locationsApi` | **default 60** ← | none | **Bump to ~900.** Autocomplete terms are stable within a session; per-`{q,limit,openOnly}` cache key already isolates them. |
| `featuresApi` | default 60 | optimistic + refetch | Fine — optimistic patch masks latency; counts want freshness. |
| `userCompaniesApi` | default 60 | tag `MyCompanies` on add/remove/rename | Fine — it's polled and must be fresh. |

**RTK is per-tab and dies on reload** — it does nothing for first paint or a hard refresh.
That's exactly the gap the **edge cache (§2) fills**: shared across all users, survives
reloads. The two layers are complementary — edge for first-paint + cross-user, RTK for
in-session nav.

---

## 5. What NOT to do

- **Don't add `localStorage`/IndexedDB persistence of the jobs corpus.** The whole
  architecture (CLAUDE.md Gotcha #7/#10) exists to *avoid* holding the corpus in memory;
  persisting it re-introduces the 50 GB failure mode.
- **Don't edge-cache authed endpoints** without `Vary: Authorization` — and even then,
  per-user cache fragmentation buys little. Leave features/users/admin/saved-filters
  private.
- **Don't rely on the auto-ETag** to save backend round-trips — the proxy doesn't honor
  `If-None-Match`. Only `s-maxage` skips the hop.
- **Don't cache `/api/jobs/search` long.** It's append-heavy and it's *also* the slow
  query — caching a stale slow answer is worse than fixing the plan. Short SWR only, if at
  all.

---

## 6. Concrete change list (for the implementation pass)

1. **`api/jobs.ts`** — when `sub === 'facets'`: set
   `Vercel-CDN-Cache-Control: public, s-maxage=86400, stale-while-revalidate=604800`.
   When `sub === ''` (legacy company list) and a `company`/`companies` filter is present:
   `s-maxage=900, stale-while-revalidate=86400`. Leave `sub === 'search'` uncached (or
   `s-maxage=30` on page-1 only — no `cursor` param — if burst load warrants).
2. **`api/companies.ts`** — on `GET` of the bare directory (no `resolve`, no
   `Authorization`): `s-maxage=3600, stale-while-revalidate=86400`.
3. **`api/locations.ts`** — `s-maxage=600, stale-while-revalidate=3600`. Query already
   varies the URL, so the CDN keys per term automatically.
4. **`companiesApi.ts`** — add `keepUnusedDataFor: 3600` to `listCuratedCompanies`.
5. **`locationsApi.ts`** — add `keepUnusedDataFor: 900` to `searchLocations`.
6. **Runbook note** — add "purge Vercel CDN for `/api/companies` + `/api/jobs/facets`" to
   the company-add and taxonomy-migration procedures (SWR makes this non-urgent).

Expected effect: the three static endpoints (`facets`, `companies`, `locations`) stop
paying the ~0.7 s fixed overhead on all-but-the-first global load — the single biggest,
lowest-risk latency win available anywhere in the app, and it touches no query and no
schema.
