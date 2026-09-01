# Custom companies in the main views — plan

**Branch:** `feat/custom-companies-in-main-views` (worktree, off `origin/main`).
**Written:** 2026-08-31. Every claim below was checked against the code on this branch, plus
production Postgres (read-only) and the Vercel production env/deploy list. Anything I could
not determine is in §10.

**The ask, in the owner's words:** *"The whole point is to integrate it into our existing
system. A user shouldn't have to go to their custom jobs to see them only."* Two concrete
requirements:

1. A user's custom jobs appear in their **Recent Job Postings** feed (`/`).
2. A user's custom companies appear in the **company dropdown** on `/companies` (Company
   Hiring Trends), so their trend page is reachable the way every published company's is.

Only for the owner of those companies. Nobody else, ever.

---

## 0. Read this first — requirement 1 is already built and already live

**Do not re-plan or re-implement the Recent Jobs half.** It shipped in `#248` (E7 Phase 3),
it is on `main`, and it is switched ON in production. Verified:

| Piece | Where | Status |
|---|---|---|
| Owner-scoped aggregate SQL reader | `src/backend/api/services/database.py:466` `get_owned_custom_jobs` | built |
| `GET /api/users/companies/jobs` (authed, keyset, `X-Next-Cursor`) | `src/backend/api/routers/user_companies.py:1116-1197` | built |
| Frontend private-half fetch | `src/frontend/src/features/userCompanies/customJobsClient.ts:26,119-182` | built |
| Merge into the same keyset walk | `src/frontend/src/features/jobs/jobsApi.ts:93-148, 493-516`, reserved chunk key `keysetWalk.ts:105` | built |
| Custom boards survive the enabled-companies prefilter | `src/frontend/src/features/filters/selectors/recentJobsSelectors.ts:23-42` | built |
| `u-<id>` → real name on job cards | `src/frontend/src/components/shared/JobCard/CompanyJobHeader.tsx:41-85` | built |
| `u-<id>` → real name in the Recent company filter | `src/frontend/src/components/recent-jobs-page/RecentJobsFilters.tsx:53-75` | built |
| Never-leak regression tests (incl. "after the feed endpoint exists") | `src/backend/api/tests/test_visibility_leaks.py:85,99,118,210,238,260` | built |
| Signed-out / flag-off / failure contracts, identity assertions | `src/frontend/src/__tests__/features/jobs/jobsApi.customJobs.test.ts` (17 cases) | built |

Production state, checked today:

- `companies` has exactly **2** `visibility='user'` rows (`u-jw8iz8sqvy` "cisco", 1,250 jobs;
  `u-5s080zd2ct` "Raindrop YC", 9 jobs), **1** user, 2 `user_companies` links.
- Vercel production has `VITE_CUSTOM_COMPANIES_ENABLED` set (9h ago) and the newest
  production deploy is 8h old — i.e. **the flag is baked into the live bundle**. The backend
  flag is on too (adds succeeded).

**So the first action in this plan is verification, not code.** See §5 Phase 0. If the owner
is not seeing custom jobs on `/`, the cause is one of the four named there — not a missing
feature.

**What is genuinely missing is requirement 2.** `CompanySelector.tsx:33` maps the
compile-time `COMPANIES` array and nothing else; `jobsApi.getJobsForCompany` (`jobsApi.ts:271-275`)
returns a 404 for any id `getCompanyById` does not know; `lib/url.ts:26` validates
`?company=` against the same list, so `/companies?company=u-…` silently falls back to
`spacex`. Everything in §5 Phases 1-5 is about that.

**Also worth knowing:** the merge-seam selectors the earlier plan named
(`selectEffectiveCompanies`, `selectUserCompanyIdSet`, `selectEffectiveCompanyById`) **do not
exist anywhere** — grep over `src/frontend/src` including tests returns zero hits, and there
is no strict-equality regression test for them. What exists instead are three ad-hoc,
independently-derived seams (`RecentJobsFilters.tsx:58-75` useMemo, `CompanyJobHeader.tsx:41-48`
component branch, `recentJobsSelectors.ts:36` id-shape check). This plan builds the seam
properly and leaves the three in place (§8 R6).

---

## 1. The hard constraint

`src/backend/api/services/database.py:135-155` defines `_USER_COMPANY_PREDICATE` and applies
it **unconditionally** to both public read paths — the list (`get_jobs`, via
`_build_where(exclude_user_companies=True)` at `database.py:246-248` and `:370`) and the
single-job detail (`get_job_by_id`, `database.py:424`). Its comment is a decision, not an
oversight:

> A viewer-scoped predicate ("hide private companies unless YOU own them") would turn an
> unconditional leak into a conditional one — the kind that passes review and ships.

`/api/jobs` is unauthenticated and forwarded verbatim by `api/jobs.ts`. **Nothing in this plan
touches that predicate.** Any implementation that adds a viewer argument to `get_jobs`,
`get_job_by_id`, or `_build_where` is wrong and must be rejected in review.

---

## 2. The four designs, and which one is in force

### (A) Client-side merge against the *per-company* owner endpoint — rejected

Fetch `/api/jobs` for the public feed, then `GET /api/users/companies/{id}/jobs` once per
owned company and merge client-side.

Rejected for four independent reasons:

- **N+1.** One request per owned board on every Recent page load. The add quota is 20/user/month
  with no lifetime cap, so N is unbounded over time.
- **No keyset contract.** `GET /api/users/companies/{id}/jobs` (`user_companies.py:1312-1332`)
  takes no `since`, no `cursor`, emits no `X-Next-Cursor`, and hard-caps at `limit=5000`
  silently. Merging N unpaginated full-board dumps into a cursor walk that is explicitly
  bounded by a completeness horizon (`keysetWalk.ts:135-191`) means either fetching every board
  in full on first paint, or inventing a second, bespoke paging protocol per board.
- **Sort-order correctness.** The horizon is `max over ACTIVE chunks of (oldest first_seen_at
  fetched)`. N unpaginated sources have no cursor, so they can never be "active", so they never
  bound the horizon — their rows would appear as an unbounded tail below the public horizon,
  which is exactly the biased-set failure the horizon exists to prevent.
- **Cache split.** N per-company cache entries in `userCompaniesApi` holding rows that
  `getAllJobs` has already copied into `byCompanyId` — two owners for one dataset.

### (B) One authed aggregate endpoint, merged as one more keyset chunk — **CHOSEN, and shipped**

`GET /api/users/companies/jobs` returns only the caller's own custom jobs, across all their
boards, in the same row shape, the same `(first_seen_at DESC, source_id DESC, id DESC)`
ordering, and the same `since`/`cursor`/`X-Next-Cursor` contract as `/api/jobs`. The frontend
runs it as one extra chunk beside the public company-chunks, booking its cursor and floor in the
same `cursors` / `chunkFloors` maps under the reserved key `CUSTOM_JOBS_CHUNK_KEY = 'custom:jobs'`
(`keysetWalk.ts:105`). `computeCompleteHorizon` and `selectHasMoreJobs` therefore account for
the private half **with no special casing**.

Why it beats (A) and (C):

- Authorization is **by construction**, not by a check. `source_ids` is never read from the
  request — the router derives it from the caller's `user_companies` rows
  (`user_companies.py:1181` `svc.list_owned_source_ids`). There is no company-id parameter to
  tamper with and no ownership `if` a future edit can delete. An anonymous caller 401s at
  `get_current_user` before reaching any query. A user with no boards passes `[]` and gets `[]`.
- `/api/jobs` keeps its unconditional predicate. The guarantee is not weakened anywhere.
- One request for all boards, one cursor, one page size, one horizon.

### (C) An authed variant of the jobs read on a different route — rejected

E.g. `GET /api/jobs/authed` that unions public + owned-private. It preserves the letter of the
constraint (the unauthenticated route's predicate stays unconditional) but it re-creates the
hazard one level up: a single query whose result set depends on the viewer, sharing its
`_build_where` / column list / index strategy with the public one. The next person who
refactors `_build_where` has to keep two callers with opposite security postures correct. (B)
has no such query — its reader (`get_owned_custom_jobs`, `database.py:466`) can only ever
return `custom:*` source ids, so a bug in it cannot leak a *public* company either.

It is also strictly more work: the union has to interleave two ownership domains under one
cursor, whereas (B) reuses the multi-chunk merge the walk already performs.

### (D) Anything better — considered, nothing better found

Two variants were considered and dropped:
- *Server-side merge at the Vercel proxy* — `api/jobs.ts` would need the bearer token and would
  become a security boundary. Worse than (B) and no upside.
- *Materializing the user's boards into the public roster with a row-level policy* — that is (C)
  with more moving parts and a Postgres RLS dependency the codebase does not otherwise use.

**Conclusion: (B) is right and is already in force. Requirement 2 must be built the same way —
public data from the public path, private data only from an authed owner-derived path, never a
viewer-scoped public query.**

---

## 3. Recommended design for requirement 2 (the `/companies` dropdown)

Three seams. Nothing on the backend is required for the core (Phase 4 is a parity nicety).

### 3.1 An effective-company seam (new file)

`src/frontend/src/features/userCompanies/effectiveCompanies.ts`

```ts
export interface CompanyOption {
  id: string;
  name: string;          // rename wins — see 3.4
  isCustom: boolean;
  jobsUrl?: string;      // static company jobsUrl, or the custom board's source URL
  sourceLabel: string;   // "Greenhouse" | "Custom Web Scraper" | the board host
}

export const PUBLIC_COMPANY_OPTIONS: readonly CompanyOption[];  // module constant, built once from COMPANIES
export const selectUserCompanyIdSet: (s: RootState) => ReadonlySet<string>;
export const selectEffectiveCompanies: (s: RootState) => readonly CompanyOption[];
export const selectEffectiveCompanyById: (s: RootState, id: string) => CompanyOption | undefined;
```

Reads the user's boards straight out of the existing RTK Query cache —
`userCompaniesApi.endpoints.getUserCompanies.select()(state).data?.companies` — so **no new
endpoint and no new request**. `getUserCompanies` already exists at `userCompaniesApi.ts:591-594`.

**The identity guarantee.** `selectEffectiveCompanies` returns `PUBLIC_COMPANY_OPTIONS`
**by reference** whenever the flag is off, the user is signed out, or they own no custom
companies. Same for `selectUserCompanyIdSet` returning a frozen `EMPTY_ID_SET`. This is what
makes the flag-off path provably a no-op for downstream memoization, and it is asserted with
`toBe` (§7 T1).

**Deviation from the earlier sketch, recorded on purpose.** The earlier plan called for
`selectEffectiveCompanies` to return the static `COMPANIES: Company[]` by identity. That would
force custom boards to be minted as fake `Company` objects, and a `Company` carries `ats` +
`config`, which `getClientForATS` (`api/utils.ts:24`) dispatches on — a fake
`ats: 'backend-scraper'` entry reaching that dispatcher would send a `u-<id>` to the **public**
`/api/jobs` client. `CompanyOption` is a deliberately narrower type that cannot be handed to
`getClientForATS` at all. The identity guarantee moves to `PUBLIC_COMPANY_OPTIONS`, which is
just as stable and just as testable.

### 3.2 A fetch branch inside `getJobsForCompany`

The **entire** companies-page chain reads one cache entry:
`selectCurrentCompanyJobsRtk` (`jobsSelectors.ts:10-16`) →
`selectGraphFilteredJobs` / `selectGraphFilteredJobsSorted` / `selectGraphBucketData`
(`graphFiltersSelectors.ts:25,41,48`) → chart, list, metrics, bucket modal. Branching inside
`getJobsForCompany.queryFn` therefore delivers **filters, graph, list, metrics and the bucket
modal for custom boards with no changes to any of them.**

```
getJobsForCompany({ companyId }, { signal, extra })
  ├─ isCustomCompanyId(companyId)?                    // customJobsClient.ts:83
  │    ├─ !CUSTOM_COMPANIES_CONFIG.isEnabled → 404    // byte-identical to today
  │    ├─ token = await tokenFromExtra(extra)         // jobsApi.ts:75-79, already exists
  │    ├─ token === null → { error: 401 }             // page renders a sign-in prompt
  │    └─ GET /api/users/companies/{id}/jobs, Bearer  // authed, owner-scoped, 403s a non-owner
  └─ else → today's path, untouched
```

Rows map through `transformBackendJob(row, companyId)`
(`api/transformers/backendScraperTransformer.ts:23`) — the same transformer the per-company
private trend page already uses (`userCompaniesApi.ts:660-661`). Metadata is built with the
existing `calculateJobDateRange`, so `selectCurrentCompanyMetadataRtk` keeps working.

Put the fetch itself next to its sibling in
`src/frontend/src/features/userCompanies/customJobsClient.ts` (new
`fetchMyCompanyJobs(token, id, { signal })`) so the private URL and the `Authorization` header
live in exactly one file.

**Status parity.** The public path sends `status=OPEN` (`backendScraperClient.ts:41`); the
private per-company endpoint returns every status (`database.py:435-462` docstring). Filter to
`status === 'OPEN'` in the branch for now, and prefer the server-side `status` param once
Phase 4 lands. Harmless today (nothing closes custom jobs yet) but it must not be left implicit.

### 3.3 URL + deep link

`lib/url.ts` gains an optional parameter, defaulting to today's behaviour exactly:

```ts
export function getCompanyFromURL(extraValidIds?: ReadonlySet<string>): string | undefined
export function getInitialCompanyId(extraValidIds?: ReadonlySet<string>): string
```

Callers: `useCompanyLoader.ts:42` and `useBrowserNavigation.ts:34` pass
`useAppSelector(selectUserCompanyIdSet)`.

**The cold-load race is the hard part of this phase.** On a fresh load of
`/companies?company=u-abc123`, `getUserCompanies` has not resolved yet, so the id is not in the
set, so `getInitialCompanyId()` returns `spacex`, and `useURLSync` (`app/hooks.ts:44`) then
rewrites the URL — the deep link is destroyed before it can work. The gate must be:

- If the raw `?company=` value does **not** match `/^u-[0-9a-z]+$/` → dispatch immediately.
  **Every public deep link keeps today's exact timing and behaviour.** This is the important
  half: `/companies` must not get slower for anyone.
- If it does match → hold the initial dispatch until one of: the flag is off, auth has resolved
  to signed-out, or the `getUserCompanies` query has settled (`isSuccess || isError`). Then
  dispatch once, with the resolved id (or the default if the id is not theirs).

`useCompanyLoader` must also subscribe to `useGetUserCompaniesQuery(undefined, { skip:
!isAuthenticated || !CUSTOM_COMPANIES_CONFIG.isEnabled })` so the set is populated on
`/companies` even for a user who never opens `/add-companies`. Both `skip` conditions are
load-bearing for the same reasons documented at `RecentJobsFilters.tsx:63-67`.

### 3.4 Name resolution — every site that needs the effective lookup

`UserCompany.displayName` on the wire is **already** the effective name: the backend selects
`COALESCE(c.user_display_name, c.display_name)`
(`custom_companies_service.py:50` `EFFECTIVE_DISPLAY_NAME_SQL`, used at `:91`), and rename
writes `user_display_name` specifically so re-discovery cannot stomp it
(`user_companies.py:1201-1226`). **A rename therefore wins for free** — there is no second
field to merge on the client.

Sites that resolve a company id to a display name:

| Site | Today | Needs |
|---|---|---|
| `components/companies-page/CompanySelector/CompanySelector.tsx:33` | maps `COMPANIES` | **Phase 1** — `selectEffectiveCompanies`, custom entries under a `ListSubheader` ("Your companies") |
| `pages/CompaniesPage/CompaniesPageHeader.tsx:18-20` | `getCompanyById` → "Job Posting Analytics" + "Unknown Source" for a `u-` id | **Phase 1** — `selectEffectiveCompanyById`; source line shows the board host |
| `components/companies-page/MetricsDashboard/MetricsDashboard.tsx:23,41` | `getCompanyById` → no board link | **Phase 1** — `selectEffectiveCompanyById`; `jobsUrl` = `sourceBoardUrl(row)` (`companyHealth.ts:696`) |
| `components/shared/JobCard/CompanyJobHeader.tsx:41-85` | already resolves `u-` ids | none |
| `components/recent-jobs-page/RecentJobsFilters.tsx:58-75` | already resolves `u-` ids | optional: refactor onto the seam (§8 R6) |
| `features/filters/selectors/recentJobsSelectors.ts:147` | `getCompanyById(id)?.name \|\| id` | none — `RecentJobsFilters` overlays the name downstream |
| `components/companies-page/FetchProgressBar/FetchProgressBar.tsx:57,58,150` | `getCompanyById(...)?.name ?? id` | none — the progress bar is deliberately public-only (`jobsApi.ts:125-132`) |
| `lib/company.ts:22,64` (`getCompanyNameById`, `isValidCompanyId`) | static-only | leave static; do **not** widen — `isValidCompanyId` has non-UI callers |
| `pages/CuratedCompaniesPage/CompanyCard.tsx:27` | static-only, correct | none (a custom board is not curated) |

### 3.5 Signed-out and flag-off

- **Flag off** (`CUSTOM_COMPANIES_CONFIG.isEnabled === false`, `config/customCompanies.ts:33`):
  every new seam early-returns the module constants; `getJobsForCompany` returns the same 404;
  `getCompanyFromURL` receives no extra ids. No new network call exists in the bundle's
  reachable paths. Pinned by T4/T5.
- **Signed out:** `selectUserCompanyIdSet` is empty (the query is skipped), so a `u-` id is never
  valid, the dropdown is exactly `COMPANIES`, and `/companies?company=u-…` falls back to the
  default company having issued **zero** authed requests. Pinned by T3.
- **Sign-out cache purge:** `useAuth.logout` (`useAuth.ts:80`) calls Auth0 `logout({ returnTo:
  window.location.origin })`, a full navigation, which destroys the store — so no private rows
  survive a real sign-out. The QA bypass path (`useAuth.ts:120-123`) is a no-op logout, but it is
  build-time-only and never authenticates against the real backend. Note it; do not add a
  `resetApiState` for it.

### 3.6 How "never leak" is preserved here, and what would fail loudly

The property: **private jobs are served only by authed, owner-derived backend paths, and
`/api/jobs` is never asked for a `u-` id.**

- Backend: unchanged. `_USER_COMPANY_PREDICATE` stays unconditional on both public paths.
- The custom branch calls `GET /api/users/companies/{id}/jobs`, which 403s a non-owner at
  `user_companies.py:1328-1330` (ownership checked before the reader, and the reader takes no
  viewer argument — `database.py:435-462`).
- The dropdown can only ever offer ids from the caller's own `getUserCompanies` response.
- A signed-out or flag-off client cannot construct the private request at all.

Tests that fail loudly if a future refactor breaks it: T2 (selecting a custom company issues
zero `/api/jobs` requests), T3 (signed-out issues zero authed requests), T8 (backend unit-level
predicate guard), plus the existing `test_visibility_leaks.py:99/118/260`.

---

## 4. New / changed API surface

**Backend — no change required for the core.** Optional Phase 4:

```
GET /api/users/companies/{company_id}/jobs
  + status: str|None  (pattern ^(OPEN|CLOSED)$)   # parity with GET /api/users/companies/jobs
  + limit:  int       (default 5000, ge=1, le=50000)
```
`get_user_company_jobs` (`database.py:435`) already takes `limit`; add a `status` condition the
same way `get_owned_custom_jobs` does (`database.py:501-503`).

**Frontend — new exports:**

| Symbol | File | Note |
|---|---|---|
| `CompanyOption`, `PUBLIC_COMPANY_OPTIONS`, `selectEffectiveCompanies`, `selectEffectiveCompanyById`, `selectUserCompanyIdSet` | `features/userCompanies/effectiveCompanies.ts` (new) | §3.1 |
| `fetchMyCompanyJobs(token, id, opts)` | `features/userCompanies/customJobsClient.ts` | sibling of `fetchMyCustomJobsPage` (:119) |
| `getCompanyFromURL(extraValidIds?)`, `getInitialCompanyId(extraValidIds?)` | `lib/url.ts:17,45` | optional param, default = today |

**Frontend — changed behaviour:** `jobsApi.getJobsForCompany` (`jobsApi.ts:268-307`) gains the
custom branch and reads `extra` from its `queryFn` context.

---

## 5. Phased change list

### Phase 0 — verify requirement 1 in production before writing any code

Sign in as the owner on the live site and confirm custom rows appear on `/`. If they do not,
the cause is one of these four, in order of likelihood:

1. **The complete-horizon clamp** (§8 R2). `u-jw8iz8sqvy` has 1,250 rows and
   `RECENT_JOBS_PAGE_SIZE` is 1,000 (`keysetWalk.ts:35`), so the custom chunk keeps a cursor
   after page 1 with a floor around 2026-08-14, while the three public chunks reach ~07-21.
   `computeCompleteHorizon` takes the **max** over active chunks, so the whole feed — public rows
   included — is clamped to ~08-14 until scrolling walks the custom chunk out. Rows below the
   horizon are cached, not lost.
2. **An active category/level filter.** 1,246 of the 1,250 cisco rows have
   `enrichment_status = NULL` and no category/level (verified in prod). `matchesCategory`
   (`jobFilteringUtils.ts:313-323`) and `matchesLevel` (`:327-342`) hide an unenriched job once
   the filter is active. Defaults are empty, but a **saved filter** with a category or level
   would hide the entire board.
3. **A stale bundle** — check that the Vercel production deploy postdates the env var. It does
   as of writing (deploy 8h, var 9h), but a rollback would invert that.
4. **The custom half failing silently.** `fetchCustomJobsPageOrNull` (`jobsApi.ts:93-117`)
   swallows the error by design and logs `[getAllJobs] custom-company jobs page failed`. Check
   the browser console.

Record the finding. If requirement 1 works, this plan is only about requirement 2.

### Phase 1 — the effective-company seam + the dropdown (frontend, no fetch changes)

1. Add `features/userCompanies/effectiveCompanies.ts` (§3.1).
2. `CompanySelector.tsx` — source options from `selectEffectiveCompanies`; group custom entries
   under a `ListSubheader`. Delete the `setSelectedATS` dispatch (`:17`) or leave it as
   `BackendScraper`: `state.app.selectedATS` has **no reader anywhere in the app** (only
   `appSlice.ts:13,21,33`), so it is dead state either way — do not add a fake ATS value for it.
3. `CompaniesPageHeader.tsx:18-20` — `selectEffectiveCompanyById`; for a custom board show the
   name and, as the source line, `sourceBoardLabel(sourceBoardUrl(row))` (`companyHealth.ts:696,719`)
   instead of "Unknown Source".
4. `MetricsDashboard.tsx:23,41` — `selectEffectiveCompanyById`; `jobsUrl` from the board URL,
   `recruiterLinkedInUrl` stays undefined.
5. `useCompanyLoader.ts` — subscribe to `useGetUserCompaniesQuery` with both skips (§3.3).

At the end of Phase 1 the dropdown lists the user's boards; selecting one still 404s. That is
fine and is a good checkpoint.

### Phase 2 — the fetch branch

1. `customJobsClient.ts` — add `fetchMyCompanyJobs(token, id, { signal })`.
2. `jobsApi.ts:268-307` — add the branch per §3.2. Keep the public path byte-identical.
3. `useCompanyLoader.ts:47-50` — while the selected id is custom and auth is still loading, skip
   the query; on a `401` from the branch render the same sign-in panel
   `MyCompanyTrendPage.tsx:124-140` uses.
4. `CompaniesPage.tsx:36-44` — a `403` should read "This isn't one of your tracked companies"
   rather than the generic failure banner (mirror `MyCompanyTrendPage.tsx:61-69,175-179`).

### Phase 3 — URL + deep link

1. `lib/url.ts:17,45` — the optional `extraValidIds` parameter.
2. `useCompanyLoader.ts:42` and `useBrowserNavigation.ts:34` — pass `selectUserCompanyIdSet`.
3. The cold-load gate (§3.3). Keep the public path's timing unchanged.
4. Link `/add-companies` rows to `/companies?company=<id>` **in addition to** the existing
   `buildMyCompanyDetailPath` link (`MyCompaniesList.tsx:340`), or leave both. Do **not** delete
   `MY_COMPANY_DETAIL` in this PR (§8 R5).

### Phase 4 — backend parity params (optional, small)

`status` + a raised `limit` on `GET /api/users/companies/{company_id}/jobs` (§4). Motivation:
the endpoint currently caps at 5,000 rows **silently** — a board bigger than that renders a
partial trend chart with no signal. Same class of defect as the Workday 2,000-job ceiling.

### Phase 5 — cache coherence on add/remove

`addUserCompany` / `removeUserCompany` (`userCompaniesApi.ts:614,648`) invalidate
`['MyCompanies']`, which is a **different API slice** from `jobsApi`. So today:

- adding a board does not make its jobs appear on `/` until a reload;
- **removing a board leaves its rows in the `getAllJobs` cache** for the rest of the session.

Fix: in `userCompaniesApi`, add `onQueryStarted` → on `queryFulfilled`, dispatch
`jobsApi.util.invalidateTags(['Jobs'])`. Blunt (a full Recent refetch) but correct. The removal
half is the one that matters and needs a test (T7).

---

## 6. Filters, sorting and pagination — the specifics

- **Recent feed sorting** is already correct: custom rows land in the same `byCompanyId` map
  (`jobsApi.ts:120-135`), the selector flattens and sorts the whole set by `firstSeenAt`
  (`recentJobsSelectors.ts:98-102`), so a custom row's position is decided by its timestamp
  alone.
- **Recent feed pagination** is already correct: the private half is one more chunk in the same
  walk, replaying `since`/`cursor` on its own endpoint, with its cursor and floor in the shared
  maps (`keysetWalk.ts:89-105`, `jobsApi.ts:136-148, 630-631, 746`). Pinned by
  `jobsApi.customJobs.test.ts:441,477,496,553`.
- **Recent feed filters** already apply to custom rows — the whole filter chain runs downstream
  of `selectAllJobsFromQuery`, which is the merged set.
- **The `/companies` page has no pagination at all** — `getJobsForCompany` fetches the full
  board in one request. That is true today for public companies (`limit=5000`,
  `backendScraperClient.ts:42`) and stays true for custom ones. Nothing to merge, so the hard
  part of this problem does not exist on this route.
- **Graph page default window is 90d** (`graphFiltersSlice`), which comfortably covers both
  existing custom boards.

---

## 7. Test list

**Regression tests that pin the guarantees (write these first):**

- **T1 — flag-off / no-custom identity.** `selectEffectiveCompanies(state)` `toBe`
  `PUBLIC_COMPANY_OPTIONS` and `selectUserCompanyIdSet(state)` `toBe` `EMPTY_ID_SET` for each of:
  flag off, signed out, signed in with zero boards. `toBe`, not `toEqual`.
- **T2 — the never-leak property, client side.** With the flag on and a signed-in owner,
  selecting `u-…` on `/companies` issues **zero** requests whose path is `/api/jobs`, and exactly
  one to `/api/users/companies/<id>/jobs` carrying `Authorization: Bearer`. Model on
  `jobsApi.customJobs.test.ts:173-233`'s `pathsHit` helper.
- **T3 — signed out.** `/companies?company=u-abc` renders the default company, issues no authed
  request, and leaves `state.app.selectedCompanyId` a public id.
- **T4 — flag off, byte-identical.** With `VITE_CUSTOM_COMPANIES_ENABLED` off: the dropdown's
  options `toEqual` today's, `/companies?company=u-abc` falls back to `spacex`, and no request to
  `/api/users/**` is made. Extend `__tests__/app/customCompaniesFlagGate.test.tsx`.
- **T5 — public deep link unchanged.** `/companies?company=figma` selects `figma` on the very
  first dispatch, with no extra tick and no dependence on `getUserCompanies` having resolved.
  This is the guard against Phase 3 slowing the page down for everyone.
- **T8 — backend, unit level.** In `test_visibility_leaks.py` (or `test_database_service.py`),
  seed a `visibility='user'` company with a job and assert `get_jobs(conn)` and
  `get_job_by_id(conn, source_id, job_id)` return `[]` / `None` **at the service layer**, not just
  through the router. The existing `:99`/`:118` cases go through HTTP; a service-level case also
  fails if someone rewires the router.

**Feature tests:**

- T6 — the dropdown lists the user's boards under a "Your companies" group, with the **renamed**
  name (`user_display_name` wins — assert against a row whose `displayName` differs from its
  derived name).
- T7 — after `removeUserCompany` resolves, the removed board's rows are gone from the Recent
  feed's `byCompanyId` (Phase 5).
- T9 — `/companies?company=u-…` on a cold load: the initial dispatch waits for
  `getUserCompanies` to settle, and the URL is **not** rewritten to `spacex` in the meantime.
- T10 — a `403` from the private per-company fetch renders the "not your company" state, not the
  generic error banner.
- T11 — the custom branch filters to `status === 'OPEN'`, matching the public path.
- Backend (Phase 4 only) — `status=OPEN` filters, `status=BOGUS` is a 422, ownership still 403s.

**Existing tests that must keep passing unchanged:** `test_visibility_leaks.py` (all 9),
`jobsApi.customJobs.test.ts` (all 17), `customCompaniesFlagGate.test.tsx` (all 18),
`jobsApi.keyset.test.ts`, `keysetWalk.test.ts`, `useCompanyLoader.test.tsx`,
`CompanySelector.test.tsx`, `CompaniesPageHeader.test.tsx`.

---

## 8. Risks

**R1 — the cold-load selection race is the biggest technical risk.** `/companies` is the app's
second-most-used page and its first dispatch currently happens synchronously on mount
(`useCompanyLoader.ts:40-43`). Any gate that makes *all* users wait for an authed query before
the company is selected is a visible regression for everyone, including signed-out visitors.
The mitigation — gate only when the raw `?company=` value matches `/^u-[0-9a-z]+$/` — must be
implemented exactly, and T5 exists to catch it if it is not.

**R2 — one large custom board throttles the whole Recent feed's horizon.** Measured against prod
today: `u-jw8iz8sqvy` has 1,250 rows against a 1,000-row page size, so its chunk stays active
with a floor near 2026-08-14 while the public chunks reach ~07-21, and `computeCompleteHorizon`
takes the max. The feed shows ~17 days instead of ~40 until the user scrolls. This is the
horizon working as designed (a biased set is worse than a short one), but it is a real,
user-visible effect of the already-shipped integration and the owner should know it is the
mechanism, not a bug. If it becomes a problem the lever is a larger `limit` on the private half
only — it is a separate request with its own `limit` (`customJobsClient.ts:123-128`).

**R3 — enrichment lag makes enrichment-dependent filters silently empty a new board.** 1,246 of
1,250 cisco rows are unenriched. Once a category or level filter is active, every one of them is
hidden (`jobFilteringUtils.ts:313-323, 327-342`) with no explanation. **UI recommendation:** on
the `/companies` page for a custom board, when a category/level filter is active *and* the
board has unenriched rows, show an inline note — "N of M jobs are still being categorized and
are hidden by this filter." Do not auto-disable the filter and do not fabricate a category.
Filters that do not depend on enrichment (time window, location, keyword, title) work today.

**R4 — the `/companies` page loads a whole board in one request.** 5,000-row silent cap
(`database.py:441`), no pagination, and the repo's own gotcha #7 about unbounded lists. A 12k
board would render partial with no signal. Phase 4 raises the cap; the honest fix (paging the
companies page) is out of scope and should stay out.

**R5 — two trend pages for the same company.** After Phase 3, `/add-companies/u-x` and
`/companies?company=u-x` both render a trend for the same board with different affordances: the
private page has the day-0 seed banner (`MyCompanyTrendPage.tsx:150-166`), the board link, and
the 403 state; the companies page has the full filter set, metrics and bucket modal. Deliberate
for this PR — do not delete `MY_COMPANY_DETAIL`, its route, or its flag-gate tests. Converging
them (redirecting `/add-companies/:id` → `/companies?company=:id` and porting the seed banner)
is a good follow-up and should be its own PR.

**R6 — three independent "is this custom?" predicates.** `isCustomCompanyId` (regex,
`customJobsClient.ts:83`), `getCompanyById(id) === undefined` (`CompanyJobHeader.tsx:42`), and
the `RecentJobsFilters` useMemo overlay. They are not equivalent — the second also catches a
public company dropped from `companies.ts` whose jobs remain in the DB (acknowledged at
`CompanyJobHeader.tsx:66-69`). Use `isCustomCompanyId` for every **new** site. Refactoring the
existing three onto the seam is optional and must not change behaviour.

**R7 — `state.app.selectedATS` is dead state.** No reader outside `appSlice.ts`. Do not invent
an ATS value for custom companies to satisfy it.

**R8 — half-off deployments.** The frontend flag and the backend flag are independent
(`src/frontend/CLAUDE.md:279-282`); the backend answers 503 while its flag is off. The custom
branch must render an error state, never a blank chart, on a 503.

---

## 9. What "done" looks like

1. A signed-in user with custom boards sees their jobs interleaved by date on `/` — **verify,
   already built**.
2. That user's boards appear in the `/companies` dropdown under "Your companies", with their
   chosen name.
3. Selecting one renders the normal hiring-trend page — chart, filters, job list, metrics — from
   the authed owner endpoint.
4. `/companies?company=u-<id>` deep-links correctly, including on a cold load and via browser
   back/forward.
5. Signed out, or with `VITE_CUSTOM_COMPANIES_ENABLED` off, the app is indistinguishable from
   today, and no request to `/api/users/**` is issued.
6. `_USER_COMPANY_PREDICATE` is untouched and every test in `test_visibility_leaks.py` still
   passes.

---

## 10. What I could not determine

- **The literal value of `VITE_CUSTOM_COMPANIES_ENABLED` in Vercel production.** The variable
  exists and was set 9h before the newest production deploy, but Vercel returns values encrypted
  and I did not pull them. Everything else (custom companies exist in prod, adds succeeded)
  says both flags are on. Confirm with `vercel env pull` if it matters.
- **Whether the owner has actually observed the Recent feed failing**, or is asking for something
  he has not yet seen working. Phase 0 exists to settle that before any code is written.
- **The intended long-term fate of `/add-companies/:id`** (R5). Left in place; needs an owner
  decision.
- **Whether a custom board should be offered in the `/companies` dropdown while its first
  harvest is still running** (`healthState` on `UserCompany`). Suggest: list it, and let the
  empty-state copy carry the "tracking just started" message the private page already uses.
