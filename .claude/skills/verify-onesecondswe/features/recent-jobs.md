# Recent Job Postings — `/` (`ROUTES.RECENT_JOBS`)

The app's home page: recent openings across every tracked company, with filters and an
infinite-scrolling list of job cards. This is the feature the bundled proof drive
(`helpers/drive.spec.ts`) exercises end-to-end.

Page: `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx`.
List: `components/recent-jobs-page/RecentJobsList/RecentJobsList.tsx`.
Card: `components/shared/JobCard/JobListingCard.tsx`.

## Sub-features

- **Server fetch + client-side filter** — the feed reads open jobs and filters them by
  keyword include/exclude, company, location, employment type, software-only, category,
  level, and time window.
- **Filter controls** — the on-page `RecentJobsFilters` dispatch the `recentJobsFilters`
  slice; WebMCP's `apply_feed_filters` / `reset_feed_filters` drive the exact same slice.
- **NO metric row.** The page renders its title, the filters and the list — no numbers of
  its own. The header row was dismantled on 2026-09-05: "Displayed Jobs" first (the server
  defers the filtered total per Wave-1 B1, so it could only ever show a lower bound over
  the rows walked — "50+" — which restates the list under it), then "Past 3 Hours" (a
  redundant second window), then the row itself. **Do not assert any header count.**
  `counts.total` / `last24h` / `last3h` are all still on the wire and still returned by
  `search_jobs` — they are simply not rendered anywhere.
- **Infinite list** — virtualized when signed in; hard-capped at ~12 with a `SignInOverlay`
  when signed out; keyset-paged as the user scrolls.
- **Open a posting** — each card's "Apply" opens the ATS URL in a new tab.
- **Filter catalog + location autocomplete** — the category/level dropdowns come from
  `list_filter_options`; the location filter from `search_locations`; company resolution
  from `list_companies`.

## How to get to it (user POV)

The default landing route (`/`), and the sidebar's first entry, "Recent Job Postings".
Reachable signed-out; signing in lifts the ~12-row cap and enables infinite scroll.

## Driving it with WebMCP

All calls go through `window.__webmcp__.call(name, args)` via `page.evaluate` (see
`helpers/drive.spec.ts` for the `call()` wrapper). WebMCP arranges/acts; read the proof
in the DOM.

- **Read (Tier-1), the quantitative anchor:**
  ```ts
  const res = await call(page, 'search_jobs', { company: ['apple'], timeWindow: 'all', limit: 200 });
  // res.jobs.length > 0; res.meta.serverReturned > 0 (rows on THIS page, ≤ limit);
  // res.meta.filteredTotal is number|null — DEFERRED (null) on the server-side path,
  //   so assert it is positive ONLY when non-null; every res.jobs[i].company === 'apple'
  ```
- **Arrange the live page (Tier-2):**
  ```ts
  await call(page, 'reset_feed_filters');                 // clean slate + navigate('/')
  await call(page, 'apply_feed_filters', { company: ['apple'] });   // dispatch setters + navigate('/')
  ```
- **DOM assert (the real handles):** job title = `getByRole('heading', { level: 3 })`;
  company name renders as text (`getByText('Apple', { exact: true })`); the page title is
  `getByRole('heading', { level: 1, name: 'Recent Job Postings' })` — use it to prove the
  chrome rendered, since there is no metric label left to key on; each card has an `Apply`
  link. Assert the **per-card invariant** — after a company filter every visible card is
  Apple, and a company that was visible unfiltered (e.g. `SpaceX`) is gone.
- **Discovery tools** feed the filters: `list_filter_options` → `{ categories, levels }`;
  `search_locations` → `{ locations: [{ canonicalName, … }] }`; `list_companies` (optional
  `query`) → the curated directory for name→id resolution.
- **Open a posting (Tier-2, intent only):**
  ```ts
  const j = res.jobs[0];
  page.on('popup', p => { /* record intent */ });
  await call(page, 'open_job', { url: j.url });           // returns { opened: true, url }
  ```

## Gotchas

- **DOM count ≠ `meta.filteredTotal`. Never assert row-count equality.** The signed-in list
  is **virtualized** (only a screenful is mounted) and the signed-out list is **hard-capped
  at ~12** behind a `SignInOverlay`. Assert the per-card invariant instead; there is no
  header count to compare against.
- **`search_jobs.meta.filteredTotal` is `number | null` — DEFERRED (null) on the real
  server-side search path** (Wave-1 B1), a number only in demo mode. `serverReturned` equals
  `res.jobs.length` — the rows on THIS server page (≤ `limit`), NOT a pre-filter count. So the
  non-empty check rides `res.jobs.length` / `serverReturned`, and `filteredTotal` is compared
  only when non-null (then it bounds `serverReturned` from ABOVE). Never assert
  `serverReturned >= filteredTotal`. The page no longer renders any total, so there is
  nothing on screen to compare the tool's `meta` against.
- **`category` / `level` filters return ~0 in `jobscraper_e2e`** (enrichment is ~100% NULL).
  This is the clone, not a broken tool — prove those by `meta` shape; use company/keyword/
  timeWindow for a non-empty narrowing.
- **`apply_feed_filters` is additive** — it only touches the fields you pass; omitted fields
  are left untouched (mirrors the per-control UI). Call `reset_feed_filters` first for a
  deterministic slate.
- **Cursors are filter-bound.** A `search_jobs` `nextCursor` replayed after any filter change
  restarts the walk from page 1 (no 409) — treat a filter change as a fresh walk.
- **`open_job` is popup-blocked headlessly.** Assert the *intent* (`page.on('popup')` or a
  `window.open` stub), never a live navigation.
- **Filtering to a company not yet in the loaded window** makes the list auto-deepen the
  keyset walk (bounded — `RecentJobsList`'s empty-fetch budget), so assert visibility with a
  timeout rather than immediately.
