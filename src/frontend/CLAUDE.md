# Frontend CLAUDE.md

React SPA for job posting analytics. Visualizes job posting activity over time for multiple companies, all served via the backend `/api/jobs` endpoint (Greenhouse, Ashby, Lever, Gem, Eightfold/Netflix, and Workday boards, plus Google, Apple, Microsoft, Amazon, TikTok). Built with Redux Toolkit, Recharts, and Material-UI.

**Note:** Commands should be run from project root (not this directory). See root CLAUDE.md for full project context.

## Commands (from project root)

```bash
# Development
npm run dev:vercel -w src/frontend  # Start with Vercel Dev (REQUIRED - includes API proxies)
npm run dev              # Vite only (no API proxies, limited functionality)
npm run build            # Production build (runs tsc + vite build)
npm run type-check       # TypeScript validation only

# Testing
npm test                 # Run all tests (Vitest - 1300+ tests)
npm run test:coverage -w src/frontend  # Generate coverage report

# Code Quality
npm run lint             # ESLint
npm run format           # Prettier formatting
```

## Architecture Quick Reference

All paths below are relative to `src/frontend/src/`.

**State Management:**
- Redux Toolkit Query (RTK Query) for jobs data fetching with caching
- Traditional Redux slices for filters, app, and ui state
- Factory patterns: `createAPIClient` (api/clients/baseClient.ts) and `createFilterSlice` (features/filters/slices/createFilterSlice.ts)
- The company hiring-trend page has a single filter source (`graphFilters`) that drives both the graph and the job list — the list reflects the graph
- The timeline chart in `GraphSection.tsx` is collapsible (local `useState`, default expanded, not persisted); collapsing hides only the chart — the filters stay visible because they also drive the list
- Jobs normalized by company ID in `byCompanyId` map for O(1) lookup

**Data Flow:**
User selects company → `getJobsForCompany` RTK Query endpoint (features/jobs/jobsApi.ts) → Factory selects API client → Transform to normalized Job model → RTK Query cache update → Memoized selectors filter data → Components render

**API Clients:**
Backend-Scraper (api/clients/backendScraperClient.ts) is the only production client — every company flows through the backend `/api/jobs` endpoint. Greenhouse, Ashby, Lever, Gem, Eightfold/Netflix, and Workday boards are fetched by the backend Procrastinate worker (SSRF allowlist for Eightfold lives in Python `src/backend/api/services/eightfold_client.py`); Google, Apple, Microsoft, Amazon, and TikTok are scraped via Python scripts. The `createAPIClient` factory (api/clients/baseClient.ts) is retained as scaffolding for future ATS integrations; no production client currently consumes it.

**Key Selectors:**
- `selectCurrentCompanyJobsRtk` (features/jobs/jobsSelectors.ts) - Jobs for selected company
- `selectGraphFilteredJobs` (features/filters/selectors/graphFiltersSelectors.ts) - Apply graph filters
- `selectGraphFilteredJobsSorted` (features/filters/selectors/graphFiltersSelectors.ts) - Graph-filtered jobs sorted most-recent-first; feeds the job list view
- `selectGraphBucketData` (features/filters/selectors/graphFiltersSelectors.ts) - Filtered jobs + time bucketing
- `selectRecentFilteredJobs` (features/filters/selectors/recentJobsSelectors.ts) - Apply recent jobs filters

**Routes/Pages:**
- `/` - Recent Job Postings (pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx) - Aggregated recent jobs across all companies
- `/companies` - Company Job Postings (pages/CompaniesPage/CompaniesPage.tsx) - Per-company job visualization with graph
- `/curated-companies` - Curated Companies (pages/CuratedCompaniesPage/CuratedCompaniesPage.tsx) - Searchable directory of all tracked companies with brand info
- `/why` - Why This Was Built (pages/WhyPage/WhyPage.tsx) - About page
- `/qa` - QA (pages/QAPage/QAPage.tsx) - Admin page for triggering scrapers, viewing scrape runs, and debugging
- `/account` - Account (pages/AccountPage/AccountPage.tsx)
- `/saved-filters` - Saved Filters (pages/SavedFiltersPage/SavedFiltersPage.tsx) - Login-gated page to set default time windows (per page), shared locations, the saved-companies picker, and reusable keyword lists that auto-apply (but stay editable) on the Recent and Trend pages
- `/vote-features` - Vote for Features (pages/VoteFeaturesPage/VoteFeaturesPage.tsx) - Feature voting page; shipped features move out of the vote list into a read-only "Shipped — built with the community" section
- `/admin/enrichment` - Admin Enrichment Pipeline (pages/AdminEnrichmentPage/AdminEnrichmentPage.tsx) - Admin-only oversight of the laptop enrichment agent: liveness verdict, backlog funnel, tick EKG/charts (metrics push), eval scorecard, needs-human queue. Each queue row carries a one-click **Confirm** (validate the AI's proposal as-is → `human_decision='confirmed_correct'`), the **Correct** dialog (fix labels → `'corrected'`), and **Re-enrich**. The "confirmed correct" vs "human-corrected" outcome chip is a shared pure helper in `pages/AdminEnrichmentPage/outcomeChip.ts`
- `/admin/users` - Admin Users (pages/AdminUsersPage/AdminUsersPage.tsx) - Admin-only user management (grant/revoke admin); roster also shows per-user engagement (Visits / Last active, sortable columns) backed by `POST /api/users/visit`
- `/admin/location-normalization` - Admin Location Normalization (pages/AdminLocationNormalizationPage/AdminLocationNormalizationPage.tsx) - Admin-only location alias browser, health overview, integrity check, and problem-jobs table
- `/location-pipeline` - Location Pipeline (pages/AdminLocationPipelinePage/AdminLocationPipelinePage.tsx) - Public pipeline visualization; admins get a sidebar link, everyone else reaches it via the Changelog
- `/admin/feedback` - Admin Feedback (pages/AdminFeedbackPage/AdminFeedbackPage.tsx) - Admin-only table of user feedback submissions

**Key Algorithms:**
- Time Bucketing: lib/timeBucketing.ts (dynamic bucket sizing for graph visualization)

## Analytics (PostHog)

Cookieless-by-default product analytics. Entirely gated on `VITE_POSTHOG_KEY` — when it
is unset, `POSTHOG_CONFIG.isEnabled` is `false`, `lib/posthog.ts` never calls
`posthog.init()`, the consent banner never renders, and every hook / event helper
early-returns.

- **Cookieless by default:** `lib/posthog.ts` inits with
  `opt_out_capturing_by_default: false` + `persistence: 'memory'` +
  `person_profiles: 'identified_only'`. PostHog **captures from the first page load** so
  every visitor is counted (the signup-funnel denominator), but the distinct_id lives in
  memory only — **no cookies / localStorage are written until the user clicks Accept**.
  Manual SPA pageviews only (`capture_pageview: false`); session recording stays off until
  consent. `get_explicit_consent_status()` ignores the capture default, so the banner
  still shows until the user makes an explicit choice.
- **Consent state:** `ConsentStatus = 'pending' | 'granted' | 'denied'`, managed in
  `lib/posthogConsent.ts`. `acceptTracking()` upgrades persistence to
  `localStorage+cookie`, opts in, and starts session recording (it does **not** re-fire
  `$pageview` — the landing pageview already fired on load, so re-firing would
  double-count). `declineTracking()` calls `opt_out_capturing()` — the only way a visitor
  leaves analytics entirely. Visitors who never click either button keep being counted
  cookielessly. (Product/legal note: cookieless, in-memory capture with no device storage
  is the intended GDPR posture; revisit if requirements change.)
- **Hooks (`features/analytics/`):** `usePostHogPageview` fires `$pageview` on every
  route change; `usePostHogIdentify` calls `posthog.identify(providerSubject)` when a user
  is authenticated and `posthog.reset()` on sign-out; `useSignupFunnel` owns the top of
  the conversion funnel + the `is_authenticated` super-property.

### Signup-conversion funnel (events)

The metric: **of account-less visitors who reach the app, how many create an account.**
This is measured as an **aggregate count ratio** (number of `signup_funnel_landing` events
vs number of `user_signed_up` events) — it does not depend on stitching each landing to its
own eventual signup. Event taxonomy (custom events live in `features/analytics/events.ts`):

- `signup_funnel_landing` — **denominator.** Fired once per page load by `useSignupFunnel`
  only after auth resolves AND the visitor is unauthenticated, with a short grace delay so
  returning users whose session is silently restored (Auth0 silent-auth / Google One-Tap
  `auto_select`) are excluded. Existing account-holders never fire it. Props:
  `landing_path`, `referrer`.
- `signin_cta_clicked` — mid-funnel. Fired before `login()` from each sign-in CTA, with a
  `location` of `appbar | job_overlay | edit_prefs_link | account_page`. (Google One-Tap is
  intentionally excluded — its success callback can't distinguish a silent re-auth from a
  real tap; One-Tap signups are attributed via the backend signup-provider split.)
- `signin_overlay_viewed` — mid-funnel. Fired when the signed-out job-list overlay becomes
  visible, with `page` of `recent | companies | bucket_modal`.
- `user_signed_up` — **conversion.** Fired **server-side** (`src/backend/api/routers/users.py`)
  with `distinct_id = auth0_id`, only for brand-new accounts. The frontend identifies with
  the same `providerSubject` (= that `auth0_id`). Per-person stitching of a landing to its own
  signup is **best-effort, not guaranteed**: with `persistence: 'memory'` the anonymous
  distinct_id lives in memory and is discarded by the Auth0 full-page redirect
  (`login()` = `loginWithRedirect()`), so a pre-redirect landing is orphaned and does NOT
  merge into the identified person. The stitch holds only when consent was accepted before
  sign-in (id persisted) or sign-in was via in-page Google One-Tap (no reload). The
  aggregate landing-vs-signup count ratio above is unaffected by this and is the primary
  metric.
- `is_authenticated` — super-property registered by `useSignupFunnel` on every event, so the
  funnel can restrict the landing/pageview steps to anonymous traffic.

- **`/ingest` proxy:** PostHog API calls are proxied through `/ingest/*` (rewrites in
  project-root `vercel.json`) to dodge ad-blockers. `VITE_POSTHOG_HOST` defaults to
  `/ingest` — **do not** point it at `us.i.posthog.com` directly; the Vercel rewrite
  handles routing.

**Key files** (relative to `src/frontend/src/`):
- `config/posthog.ts` — PostHog config; `isEnabled` gated on `VITE_POSTHOG_KEY`
- `lib/posthog.ts` — module-scope init (once, StrictMode-safe)
- `lib/posthogConsent.ts` — opt-in/opt-out + consent-status helpers
- `components/shared/CookieConsentBanner.tsx` — consent UI
- `features/analytics/` — `usePostHogPageview`, `usePostHogIdentify`, `useSignupFunnel`,
  `events.ts` (funnel event taxonomy)

**Env vars** (go in `src/frontend/.env.local` — see Gotcha #2):
- `VITE_POSTHOG_KEY` — PostHog project key (optional; analytics off when unset)
- `VITE_POSTHOG_HOST` — ingestion host (optional; defaults to `/ingest`)

## Custom company sources (Add Companies)

Flag-gated. The `/add-companies` page takes a pasted careers URL and tracks the company
behind it — **one press, one outcome**:

**The page was renamed** from "My Companies" / `/my-companies`. The old path is still
registered (behind the same flag) as a splat route that redirects onto `/add-companies`,
sub-path and query preserved, so a bookmarked `/my-companies/u-abc123` still lands on that
company's trend page. `ROUTES.MY_COMPANIES` / `MyCompaniesPage` / `components/my-companies/`
kept their old *internal* names on purpose — renaming files and symbols would have churned
every import for zero user-visible gain.

- **ONE CALL: `POST /api/users/companies`.** Pressing **Add company** adds the company, or
  fails and says why. There is no preview and no confirm. The page used to call
  `POST /api/companies/resolve` first and render a card ("Found 663 open jobs on Workday",
  plus a Job board / How we found it / Final URL grid) behind a second **Track this company**
  button — but the add endpoint re-resolves the raw pasted URL from scratch, probes it,
  applies both limits, runs all three already-published checks and routes a non-ATS URL into
  discovery, so the second press decided nothing. The resolve endpoint still exists, still
  persists nothing, and keeps its own backend tests; **the frontend simply has no caller for
  it**, and re-adding one would re-add the step.
- **Four outcomes, all rendered by `components/my-companies/AddCompanyOutcome.tsx`** (the old
  `AddCompanyCTA`, minus its button): `201`/`200` a tracked `UserCompany` → the success card;
  `202` → the one-time-setup notice; `200 already_public` → the link to the public page; a
  `422`/`4xx`/`5xx` → one alert. `DiscoveryStatus` renders the middle two and nothing else —
  its error branch and its "starting…" placeholder went with the resolve→discovery handoff
  they narrated.
- **The failure alert speaks two vocabularies.** The add endpoint's own six reason codes
  (`unsupported`, `probe_failed`, `empty`, `deadline_exceeded`, `no_ats_detected`,
  `monthly_limit_reached`) get `ADD_REASON_TITLES`; **everything else falls through to
  `describeResolveError`**. That fallback is load-bearing, not tidiness: a URL-shaped refusal
  (`scheme_not_https`, `resolves_to_private_address`, a 429, a 503) used to be answered by the
  resolve call and rendered by `ResolveErrorDisplay`, and without the fallback a mistyped
  scheme would now render "we couldn't add that company (code: scheme_not_https)".
- **A typo costs nothing, and that is enforced on the SERVER now.** The old client-side gate
  ("only POST the add endpoint when the resolver said `no_ats_detected`") was what stopped a
  malformed URL from starting a paid discovery. With one call there is no such gate, so
  `routers/user_companies` refuses any resolver reason other than `no_ats_detected` **before**
  the discovery gate and **without writing a `company_add_attempts` row** — so it starts
  nothing and spends none of the 20 monthly adds. `no_ats_detected` is the opposite: we read
  the page, found no board, and that goes to discovery and charges.
- **There is no spend sentence under the button, and that is deliberate.** One used to
  live in `ResolveUrlForm` directly under **Add company** — *"If this board is new to us,
  Add company starts a one-time setup right away, about a minute"* — itself the
  replacement for an earlier blue consent alert above the whole form. **Both were removed
  at the owner's request (2026-09-02.)** Recorded here because it is the kind of thing a
  later reader re-derives and puts back: the reasoning that produced it ("a line under the
  button is read by someone about to press it") is still sound, it was simply overruled.
  **What the removal costs:** nothing on the page now tells the user that pressing **Add
  company** on a board we do not already read can start paid work — a headless browser
  session and a model call — on their behalf. The spend itself is still bounded
  server-side (20 adds per UTC month off `company_add_attempts`, a 10/60s burst limit, and
  `CUSTOM_COMPANY_DISCOVERY_ENABLED`), so what is missing is the disclosure, not the cap.
  `MyCompaniesPage.test.tsx` asserts the sentence's ABSENCE, so restoring it is a
  deliberate act rather than an accident. If it ever returns it belongs under the button,
  in both the empty and populated states, never behind a click.
- **The field helper is the last statement of the aggregator rule.** *"Paste the link to
  the company's own careers page, not LinkedIn or Indeed."* The clause naming the
  aggregators is there ONLY because the how-to video that was going to say it does not
  exist yet (`HOW_IT_WORKS_VIDEO_SRC` is `null`), and nothing in the product enforces it:
  `_NEVER_MATCH_DOMAINS` is a denylist read on the wrong rung, and it misses `dice.com`,
  `monster.com` and `hiring.cafe`. An aggregator URL therefore resolves, finds no board,
  reaches `no_ats_detected`, and that is precisely the branch that spends a discovery run
  and one of the user's monthly adds. Delete the clause when the video ships; not before.
- **The how-to IS the empty state, and it is now the ONLY place it appears**
  (`AddCompanyHowTo`). A user tracking nothing sees three numbered steps where "No
  companies yet" used to be, and the state is still named for a screen reader by a
  `visuallyHidden` line. One company later the list replaces it and the explanation is
  gone. The **video slot is empty and draws nothing**: set `HOW_IT_WORKS_VIDEO_SRC` and
  the video appears under the same steps, which is the whole change.
- **There is no persistent "How it works" link under the form, and that is deliberate.**
  One used to sit in `MyCompaniesPage` for any user already tracking a company
  (`canReopenHowTo`), re-opening the very same `AddCompanyHowTo` the empty state renders
  — one component, two triggers, so the two could not drift. **Removed at the owner's
  request (2026-09-02):** *"remove the How it works text under the input, it's just
  unnecessary noise. It should only be there when there's an empty state, showing how to
  do it."* Recorded here for the same reason the spend sentence above is: the reasoning
  that produced it is still sound, it was simply overruled, and a later reader will
  otherwise re-derive it and put it back. **What the removal costs:** a user who adds a
  board on day one and comes back on day thirty holding a LinkedIn URL now has **no route
  back to the explanation at all** — the empty state is behind them forever, and nothing
  else on the page says what a careers page is or why an aggregator link will not do. The
  field helper is the last statement of the aggregator rule (above), and it is now the
  only one. If it ever returns it belongs where it was, under the form, as a text link
  rather than an accordion — a shut accordion is a permanent 63px of summary row on every
  visit, the link was 29px only a reader who wanted it ever spent attention on.
- **The card is one click target.** The company name carries a stretched `::after`, so
  pressing anywhere on the card opens that company; the pencil and the X are its SIBLINGS,
  raised to `z-index: 2`, never its children (a `<button>` inside an `<a>` is invalid, and
  the icons would end up navigating). DOM order is name, edit, remove, board link, which is
  also the tab order. The board link, the discovery checklist and the match banner are
  raised too — each is a deliberate hole in the click target. While a rename is open the
  name link is unmounted, so the card is not clickable at all.
- **Discovery has its own server flag.** With `CUSTOM_COMPANY_DISCOVERY_ENABLED` off the add
  endpoint returns `422 no_ats_detected` instead of starting anything, and the failure alert
  renders that verdict plus the boards we read without setup — never an endless spinner.
- **A company we already publish is not added — it is linked.** Before creating anything —
  and before any discovery is enqueued — the add endpoint runs **three** checks against the
  ~135 public companies, in descending order of certainty:
  1. the resolved **`(ats, board_token)`** pair, for the six ATS providers;
  2. the **careers host**, for the five `ats='script'` boards (Amazon, Apple, Google,
     Microsoft, TikTok) that no URL can ever spell as an ATS pair. The host table lives
     in `scripts/shared/constants.py` (`SCRIPT_COMPANY_CAREERS_HOSTS`) and the matcher in
     `api/services/careers_host_match.py`. Match is **exact host** after normalization
     (case, `www.`, port, trailing dot, userinfo), plus a path prefix where the board is a
     path rather than a host (`google.com/about/careers`) — never a registrable-domain
     match, which would claim `learn.microsoft.com`; and
  3. the **company name inside the registrable domain** — `lifeatspotify.com` → Spotify.
     Matcher in `api/services/company_name_match.py` (pure), DB half in
     `custom_companies_service.find_public_company_by_name`. **Not containment**: the
     domain label must BE a published name or be that name wearing one *declared* careers
     affix (`lifeat`, `join`, `weare`, `get`, `careers`, `jobs`, …). Measured against the
     real fleet, plain containment produces 2,294 false hits over an English dictionary
     and answers "General Motors" for `figma.com` (`gm` ⊂ `figma`); the affix rule
     produces 1. Names ≤4 chars match only as the whole label, ATS/aggregator domains
     never match, and the five companies from check 2 are excluded so a guess can never
     overturn an exact refusal.

  Any hit writes **nothing** (no company, no scraper, no jobs, no discovery job) and
  answers `200 {status: 'already_public', companyId, displayName, finalUrl, matchKind}`.
  The user owns nothing afterwards — a public company is already in everyone's list, and
  putting a `user_companies` row on one would point the private jobs feed and the
  purge-on-last-owner delete at a public board. Info severity, terminal, not dismissible.

- **`matchKind` decides whether there is a way past the notice, and certainty decides
  `matchKind`.** This is a rule, not a style choice.

  | `matchKind` | Which check | Headline | Way out |
  |---|---|---|---|
  | `'board'` | 1 or 2 | "We already track Spotify" | **none** |
  | `'name'` | 3 | "This looks like Spotify, which we already track" | `TrackAnywayAction` |

  Checks 1 and 2 are exact identifiers, so there is no plausible reading where the user
  meant a different company — and a private duplicate re-scrapes the same feed for a chart
  whose history starts today while the full one is one click away. Offering that was a trap
  dressed as a choice, so those branches are terminal.

  Check 3 is a guess, and its failure mode is a false positive. With no way out, a wrong
  guess **hard-blocks** somebody from adding a legitimately different company that merely
  shares a string with one of ours, with no way to tell us we are wrong — a worse
  anti-pattern. So that branch keeps `TrackAnywayAction`, worded **"This isn't the same
  company"** (correcting us) rather than "Track it separately anyway" (opting into a
  duplicate). It re-sends the same URL with `trackAnyway: true`.

  **The server still honours `trackAnyway: true` on every check.** Only the UI affordance
  was removed from the certain ones, so a bookmark or a replayed request never 500s.

  **One component renders all three, from either endpoint**: `AddCompanyOutcome` hands the
  add path's `already_public` body to `DiscoveryStatus`, and `MyCompaniesPage` hands the
  search path's `alreadyPublic` block to the same component. It renders `TrackAnywayAction`
  **only** when `matchKind === 'name'` (`isNameGuessMatch`). The `matchKind` on the wire is
  the whole rule — which check answered is no longer visible in the component tree, and must
  not be re-derived from one.

  **The checks themselves are one code path too** (`custom_companies_service.find_published_company_for_urls`), climbed by the add endpoint *and* the
  name-search endpoint. Drift between them is how the search endpoint came to offer a
  careers page for a company the add endpoint already knew we published — see "A THIRD
  STATE" under the name-search section below.

  **What NONE of the three catches**, and the copy must never imply otherwise: a careers
  site whose domain does not name the company at all. Only the job set links those — see
  `published_board_match`, which *suggests* the link after the first harvest.
- **Two independent flags.** `VITE_CUSTOM_COMPANIES_ENABLED` only reveals the page; the
  backend has its own `CUSTOM_COMPANY_SOURCES_ENABLED` setting and answers **503** while it
  is off. Both must be on for the flow to work. With the frontend flag off there is no nav
  entry, no route (`App.tsx` skips registering it), and no network calls.
- **One endpoint: `POST /api/users/companies`** (Bearer auth, 10 requests/60s per user, 20
  adds per user per UTC month — **admins are exempt from the monthly cap only**, and
  the server tells the page so by sending no `quota` block at all, which
  `addsRemaining` already renders as no counter and nothing disabled). It reaches the
  backend through the existing `api/users.ts`
  Vercel proxy — no new proxy, and `api/companies.ts` is no longer used by this page at all.
  The burst limiter on this route is what bounds how fast discoveries can be started; it used
  to be the resolve endpoint's limiter doing that indirectly, which a replayed bearer token
  skipped entirely.
- **A user can RENAME a board they track**, inline on the card (`PATCH
  /api/users/companies/{id}`, its own 30/60s bucket, charging neither add budget). The
  non-obvious half is in the backend and is the reason the feature is not a trap:
  `companies.display_name` is DERIVED from the URL and re-derived by more than one path
  (`_promote_to_tracked` on every discovery accept, `restart_refused_discovery` on the
  retry of a refused board — which is the only retry the UI offers). A rename stored in
  that column would be silently reverted by an ordinary re-add, so it lands in a separate
  `companies.user_display_name` and readers COALESCE the two. Nothing can clobber a column
  it does not write. Full reasoning:
  `docs/implementations/custom-company-sources/RENAME-PLAN.md`.
  - The editor holds a **pending state, never an optimistic patch** — a rename that
    appears to succeed and then reverts is the exact failure this is designed against.
  - Its 422 codes (`name_empty`, `name_too_long`) live in `userCompaniesApi.ts` beside
    `describeRenameError`, keyed by a closed union for the same reason the add codes are.
  - `api/users.ts` needed no change: its allowlist is per PATH, and `companies/:id` was
    already listed for DELETE.
- **Two different 422 bodies.** The endpoint's own failure is *flat*
  (`{reason, detail, finalUrl}`); FastAPI request-validation failure is
  `{detail: [...]}` with no `reason`. `features/userCompanies/resolveErrors.ts` is the single
  place that tells them apart and owns all user-facing copy for the resolver's codes — add new
  `reason` codes there (the `Record<ResolveFailureReason, …>` map makes a missing one a
  compile error). The add endpoint's own six codes live in `AddCompanyOutcome.tsx`, keyed by
  a closed union for the same reason.

### Typing a NAME: two answer states, and they must not look alike

Behind `VITE_COMPANY_NAME_SEARCH_ENABLED` (its own flag; with it off the page does not even
*classify* the input — `MyCompaniesNameSearchFlagOff.test.tsx` pins that). A pasted URL still
takes the URL path and never spends a search. A name goes to `POST
/api/companies/search-by-name`, which returns probed `candidates[]` (each with an
`autoAddable` verdict) plus a `careersUrl`. **`candidates[].autoAddable` picks the layout,
and that one field is the whole rule** — `boardsAreTheQuestion` in `MyCompaniesPage`.

| | State A — something is `autoAddable` | State B — nothing is |
|---|---|---|
| Leads | `CompanyCandidateList` | `CareersPageAnswer` |
| Heading | "Which board is “X”?" | "No board we can confirm belongs to “X”" |
| Primary action | per-row **contained** "Track this one" | **contained** "Use this careers page" |
| The other block | careers page as a footnote below (caption + outlined "Use this") | boards folded below, **outlined** "Track this one anyway" |
| Live region | the list (`aria-live="polite"`) | the careers block; the list keeps `role="region"` but gives up `aria-live` so only one polite region speaks |

**STATE B HAS A SHORT CIRCUIT, AND IT SPENDS MONEY: no board at all + exactly one
trusted careers URL is ADDED WITHOUT A SECOND PRESS.** Owner, 2026-09-03: *"When there
is no [board], it should automatically just use that careers website. The idea is to
have fewer clicks."* The card it replaces — *"No job board found for “X” — their
careers page is the way in"* over a filled **Use this careers page** — asked a question
with one answer, which is the same thing the deleted preview step did.

The branch lives in `handleNameSearch` (`MyCompaniesPage`) beside the existing
single-confident-board auto-add, and **all three conditions are load-bearing**:

| Condition | Why dropping it is wrong |
|---|---|
| `candidates.length === 0` | Any board that came back, even one the name gate rejected, is an alternative a person might recognise — the IBM case, Harvey's live Ashby board beside `ibm.com/careers`. It keeps its click. |
| `careersUrl !== null` | The server picked exactly one and vouched for it (`services/careers_page_pick.py` collapses the trusted results to a single URL). Null means no result's host named the company — nothing to take. |
| no `alreadyPublic` | Enforced by the early return above it. That answer is "we already track this", which is never an add. |

**What it costs, and it is real.** Accepting a careers page is precisely what starts
**paid work** — a headless browser session plus a model call — and spends one of the 20
monthly adds. The disclosure that used to sit under the button was removed on
2026-09-02 (see "There is no spend sentence under the button" above), so a single press
now goes from keystroke to paid discovery with nothing on screen saying so. The owner's
call; the spend is still bounded server-side, so what is missing is the disclosure, not
the cap. The full reasoning is written on the branch itself rather than left to be
re-derived.

**One auto-add per press, guarded by a ref** (`autoAddedRef`), reset only in
`handleSubmit`. Both auto-add paths fire from an async continuation, so `adding` is
stale there and guards nothing; a ref survives re-renders and is per component instance.
A double fire would spend a second monthly add and could start a second discovery, so
`MyCompaniesNameSearch.test.tsx` pins it under `StrictMode` **and** pins that a second
press still re-arms.

**A CONSEQUENCE:** `CareersPageAnswer`'s leading form with a non-null URL and zero
unconfirmed boards is now **unreachable from this page**. The component still renders it
and is deliberately left alone — one server change (a `careersUrl` beside a confirmed
board) away from mattering again. What still reaches it: boards came back but none was
confirmed (with or without a URL), and zero boards with a null `careersUrl`.

**A THIRD STATE SITS ABOVE BOTH, and it is a replacement rather than an addition:
`alreadyPublic`.** Typing `databricks` used to render State B — *"No job board found for
“databricks” — their careers page is the way in"* over a filled **Use this careers page** —
and only the press behind that button answered *"This looks like Databricks, which we
already track."* The owner's verdict: *"There should not be that flow. If we already track
it, just say that."* He was right: `search_company_by_name` had **no database access at
all** (no `conn`, no `Depends(get_db)`), so it was structurally incapable of knowing what we
publish, and the three checks lived only on the add path.

The search endpoint now runs the same three checks — **the same code path**, `find_published_company_for_candidate` / `find_published_company_for_urls` in `custom_companies_service` — against **both** every name-gated candidate board and the careers URL it is about to offer, and returns the add endpoint's own `AlreadyPublicResponse` as `alreadyPublic`.

- **When it is set, it IS the answer**: `MyCompaniesPage` renders `DiscoveryStatus` **in place
  of** `CareersPageAnswer` *and* `CompanyCandidateList`, not above them. Everything those two
  were for was choosing what to add, and there is nothing here to add.
- **Same `matchKind` rule as the add path**, because it is the same component: `'board'`
  terminal, `'name'` keeps `TrackAnywayAction`. The Databricks case is a `name` match (rung 3
  read `databricks` out of `databricks.com`), so it keeps its escape hatch — the page holds
  that notice in its own state, so `handleSearchTrackAnyway` clears it before adding or it
  returns beside the success card.
- **A published match suppresses BOTH auto-adds.** A name whose own board we publish
  resolves exactly one auto-addable candidate — the page's auto-add shape — so without the
  guard in `handleNameSearch` we would spend the add call and a monthly slot to have the
  server hand back the answer we were already holding. The same early return is what keeps
  the careers-page short circuit above from firing on a published company: `databricks`
  returns zero boards and one trusted careers URL, which is the auto-add shape exactly.
- **Only name-gated candidates are asked about**, and that gate is the safety property.
  Browserbase Search is semantic, so "meta" really returns Anthropic's and Cohere's live
  boards; without it, the first published one would answer "we already track Anthropic" —
  confident, wrong and terminal, which is worse than the dead end this removed.
- **It also saves the second paid search**: a candidate match means no careers page will be
  offered, so the `"{name} careers"` escalation never runs.
- **The add endpoint keeps every one of its own checks.** This is an earlier, friendlier
  answer, never a replacement for server-side enforcement — a bookmarked or replayed add
  still hits the same wall.
- `MyCompaniesNameSearchAlreadyPublic.test.tsx` covers all of it, including an older backend
  that omits the field (absent must read as "no match", never a blank notice).

- **State B is the fix for a real failure.** Typing "meta" returned five live boards —
  anthropic (582 jobs), cohere (144), gleanwork (111), headway (83), gc-ai (27) — because
  Browserbase Search is Exa, i.e. *semantic*: the host-shaped query reads as "AI company job
  board". The server did everything right (all five `autoAddable: false`, nothing added, a
  second query found `metacareers.com`); the page rendered the five rejects as large cards
  with black buttons and the right answer as caption-grey text under a small outlined button.
  **The boards we had already rejected outweighed the answer.** Nothing about the search, the
  gate, or the fallback changed — only the presentation.
- **A rejected board must never wear a one-press "Track this one" as a peer of the answer.**
  That is the rule to preserve; the fold and the outlined variant are how it is kept.
- **The rejects are folded, not dropped**, because the gate is occasionally too strict —
  measured, it suppressed exactly one correct answer across the whole evaluation (Poke, whose
  board token is `interaction`). Two presses recover it, and the fold's summary refuses to
  imply an answer: *"Show 5 other boards we found (none confirmed as “meta”)"*. The count is
  what will actually be RENDERED (`MAX_RENDERED` = 5), never what came back.
- **`Collapse` + `unmountOnExit`**, so an unopened fold is zero focusable buttons, with
  `timeout={0}` under `prefers-reduced-motion` — Collapse writes its duration as an inline
  style, which no `@media` rule can outrank.
- **Identity display is unchanged in both states**, and that is deliberate: the board token
  and its live job count at full readable size are the ONLY thing that catches a stranger's
  board ("Guidehouse · 794 jobs" under a search for Databricks). Folding the list is not
  shrinking a row — see the header comment in `CompanyCandidateList` before touching it.
- **A null `careersUrl` still says something.** No result's host named the company, so we
  offer nothing rather than a guess that would cost a paid discovery run and one of their
  monthly adds — the block keeps the honest headline and says to paste the careers URL.
- `MyCompaniesNameSearchAnswerOrder.test.tsx` asserts **document order** (`compareDocumentPosition`)
  and the button variants for both states. Presence assertions cannot catch this bug: every
  element in the broken screenshot was present.

**Key files** (relative to `src/frontend/src/`):
- `config/customCompanies.ts` — the flag (`VITE_CUSTOM_COMPANIES_ENABLED === 'true'`)
- `features/userCompanies/userCompaniesApi.ts` — RTK Query slice; `baseUrl: '/api'` on
  purpose, so endpoints under more than one path prefix can share it
- `features/userCompanies/resolveErrors.ts` — resolver-code → copy mapping
- `components/my-companies/ResolveUrlForm.tsx` — the input, the only button, the helper
  carrying the aggregator rule (the spend sentence that used to sit under the button was removed 2026-09-02)
- `components/my-companies/AddCompanyHowTo.tsx` — the three steps and the video slot;
  `HOW_IT_WORKS_VIDEO_SRC` at the top is the one line to change when a video exists
- `components/my-companies/AddCompanyOutcome.tsx` — every outcome one press can land on
- `components/my-companies/CompanyCandidateList.tsx` — the boards a name search found;
  `demoted` is state B (folded, secondary, no live region)
- `components/my-companies/CareersPageAnswer.tsx` — the careers page, as the answer
  (`lead`) or as the footnote beside a confirmed board. **Its leading form WITH a URL is
  now only reached when boards came back and none was confirmed** — zero boards plus one
  trusted URL is auto-added instead, so that combination never renders. Left intact on
  purpose; see the branch comment in `MyCompaniesPage`
- `components/my-companies/NameSearchProgress.tsx` + `nameSearchNarration.ts` — the search,
  narrated after the fact (never a faked live feed) as **one list that narrows to its
  answer**: the results land as rows, everything that was not a board folds away, then the
  boards whose token does not name the company, and what survives is the answer. One status
  line morphs alongside it. The rows come from `trace.nonBoards` (the real, server-redacted
  result URLs), `candidates` and `careersUrl` — **there is no path that draws a row from a
  count**, so an older backend gets a shorter list, never an invented one. Replaced a stack
  of seven ✓ ticks, rejected as *"all these steps, it's really confusing… it should be this
  morphing list"* (2026-09-02); the seven sentences were merged to at most five, not dropped.
  Same row vocabulary and the same 260ms fade+rise as `DiscoveryNetworkLog`, on purpose —
  one language for "here is what we saw", not two. All `animation-delay`, no timers and no
  state, and `prefers-reduced-motion` gets the **end state** (the answer) rather than every
  row at once.
- `pages/MyCompaniesPage/` — the page (signed-out gate + form + results), and the one place
  that decides which of the two answer layouts is on screen

**Discovery-progress checklist** (`VITE_DISCOVERY_PROGRESS_ENABLED`, its own flag, default
off): a non-ATS URL is handed to a one-time backend capture, and the row it creates
narrates five named steps — *Opening the page → Reading jobs → Building web scraper →
Ready to track → Fetching all current jobs*. The first four are ticked by discovery; the
fifth is opened by discovery and closed by the **first harvest**, which is a different
run. A refusal names the step that stopped, carries the reason on it, and offers the ONE
thing that changes the answer (paste the URL of the actual listings) — never a bare retry,
because discovery is deterministic and re-running the same URL reproduces the same answer.

- **It is an accordion.** OPEN while something is happening (`discovering`, an accepted
  board whose first harvest hasn't landed) or something went wrong (`refused`); CLOSED
  once the row settles, i.e. `lastSuccessAt` is set. `shouldExpandDiscovery` is the whole
  rule, read once on mount so a landing harvest can't snap the panel shut under a reader.
  `Collapse` + `unmountOnExit`, so a closed row is one line and *zero* extra DOM.
- **The evidence is now permanent on every tracked row**, not just partial ones. It used
  to disappear the moment `lastSuccessAt` was set (a permanent setup receipt is clutter —
  true while the panel was always expanded). Folded, it costs one line, and the record of
  *how* we read a board stops looking deleted. Still hidden on `quarantined` (a success
  receipt under a "Tracking paused" badge contradicts the badge) and on any unknown
  `healthState`.
- **A ✓'s `result` is never rendered.** It is engine telemetry ("recorded 14 JSON
  request(s)"), and one under every rung doubled the length of a list whose job is being
  scannable. Exactly three rungs carry a line: a ✕ (the reason), a ○ that already tried
  (`first_scan` failed — see below), and a ◐ (the board's own numbers).

- The step state rides the **existing** `getUserCompanies` payload (`company.discovery`),
  polled by the list that already polls; there is no second channel. The cadence drops to
  4s while a row is `discovering` (four steps of a few seconds each read as a spinner at 15s)
  — but only while `discovery.updatedAt` is recent. A row can be stranded in `discovering`
  forever (flag flipped off mid-flight, undrained queue, the task's SIGKILL "wedged-row"
  caveat), and an unbounded 4s poll would hammer the list endpoint for as long as the tab
  stays open; past the staleness window it falls back to the ordinary 15s cadence.
- A failed poll is **non-destructive**: RTK Query keeps the last good `data` while marking
  the entry rejected, so the list renders on with an inline "couldn't refresh" warning and
  the poller stays mounted. Only a load with nothing cached becomes the full error card.
- **Flag OFF must render byte-for-byte what shipped before** — the gate lives in
  `MyCompaniesList`, and `MyCompaniesList.test.tsx` pins it against an identical payload.
- The live-view iframe is optional and absent by default: only a Browserbase capture has a
  hosted view and the backend runs its own Chromium. When present it opens **expanded**
  (the session lasts ~30s — a run that ends before the user notices a "Watch live" button
  showed them nothing) behind a toggle that can put it away, and `pointer-events: none`
  either way. Never infer browser liveness from step state, which is always at least one
  write behind.
- **The backend's null is structurally too late, and that used to be the bug.** The
  browser dies inside the capture child (`_capture_main.py`'s `await browser.close()` is
  its last act); the parent only writes `live_view_url: null` after that child exits, and
  a poll then has to carry it — by which time Browserbase's frame has already painted
  *"Debugging connection was closed. Reason: WebSocket disconnected"* into our layout. No
  poll can win that race. So `liveViewUrl` is treated as a **claim with an expiry**, and
  `DiscoveryChecklist`'s `LiveView` retires the frame on whichever of four comes first:
  the frame's own `browserbase-disconnected` postMessage (the only one that beats the
  paint — origin-pinned to the frame we mounted, exact-payload matched, and *not*
  authoritative: it is undocumented and sent with `targetOrigin: "*"`); the server's null;
  the **trust lease** (`LIVE_VIEW_TRUST_MS` = **three** poll intervals, renewed by every
  fulfilled payload, which is what closes the *unbounded* cases — a failing poll keeps
  serving the last good payload, banner and all); and the session ceiling
  (`_BROWSERBASE_SESSION_TTL_S`, 300s, for a row a SIGKILLed worker will never retract).
  Retirement is always recorded as *the URL it refers to*, so no verdict outlives its
  session. `receivedAt` (`fulfilledTimeStamp`) is a **required** prop for exactly this
  reason — a caller that forgets it would get a frame that outlives its session.
- **THE LIVE VIEW WAS BROKEN BY A 400-CHARACTER CLIP, AND IT WAS NEVER A FRONTEND BUG.**
  `services/discovery/progress.py`'s `_safe_url` bounded every URL in the discovery blob
  at `_MAX_TEXT_CHARS` (400) — right for the network log, where a URL is a *label*.
  `liveViewUrl` is not a label: it goes in an `<iframe src>`. Browserbase's
  `debuggerFullscreenUrl` measures **479 characters**, essentially all of it one signed
  `?wss=` parameter, so the stored URL lost the tail of that parameter and gained an
  ellipsis. The iframe loaded, connected to a truncated websocket address, and painted
  *"Debugging connection was closed. Reason: WebSocket disconnected"* about **700ms
  later** — on a session that ran for another twenty-five seconds.
  - **Two frontend fixes failed before this was found, because the frontend was right**:
    the frame really was dead and its `browserbase-disconnected` really was telling the
    truth. Evidence: seven probe mounts using the *raw* URL never disconnected; eleven
    product mounts using the *stored* URL all did, ~700ms after each load.
  - Fixed by `_safe_live_view_url` / `_MAX_LIVE_VIEW_URL_CHARS = 2048`. After it, a real
    capture keeps the frame on screen for **95%** of the session (it was 7%), and the
    `frame-shots/` artifact shows it painting the live job list.
  - **The lesson for this panel:** "the frame is mounted" and "the frame is painting a
    browser" are different questions with opposite answers, and only a picture separates
    them. `e2e/live-view --live` takes those pictures.
- **The frame's `browserbase-disconnected` is a HINT, not a verdict.** It used to set the
  same sticky state as the session ceiling, which meant one undocumented string from
  someone else's page could end a session by itself. It is now soft the same way the lease
  is — it records the payload it was decided on, and a newer payload carrying the same URL
  disproves it — bounded by `LIVE_VIEW_DISCONNECT_GRACE = 1`. One disproof, then
  permanent. This is defence in depth rather than the fix for the bug above: without the
  bound a genuinely dead session would flap the frame once per poll for the whole 12s
  lease, and without the softness any future frame-side flakiness silently deletes the
  feature again.
  - **The cost, written down:** after a genuine end the frame may come back once, briefly,
    on the payload the server has not caught up with. It shows a blank reconnecting frame,
    not their error text — the message is emitted *before* Browserbase builds its
    "Debugging connection was closed" dialog, so a frame that never gets past reconnecting
    never paints one. `e2e/live-view`'s LV-05 pins that bound. In practice it is almost
    never seen: the backend writes its null within ~400ms of `browser.close()`, well
    inside one 4s poll.
- **The lease is a SOFT closer too, and both halves of that were bugs.** It was one poll
  interval + 2s (6s), and expiry was permanent. But the gap the lease has to survive is the
  end-to-end one between two *fulfilled* payloads, and through `vercel dev` — which proxies
  the list endpoint — that measured 4.8s / 5.4s / **7.0s** / 5.7s on a real run. So the
  lease expired mid-session, and because expiry was sticky one slow poll ended the frame
  for the remaining ~25s: the live view "popped up and disappeared within a second". Now it
  is three intervals (12s, i.e. three missed polls) **and** soft — a fresh `receivedAt`
  carrying the *same* url restores the frame. The other three closers stay permanent
  because each is a statement about the *session*, which does not un-end; the lease is a
  statement about *us*, which a later payload can disprove. **The cost:** a session that
  genuinely died while polls are failing can linger up to ~12s showing Browserbase's
  "Debugging connection was closed". Accepted — the postMessage fast path and the server's
  own retraction still close the healthy path immediately, so the lease is only the
  failing-poll backstop.
- **This panel is gated by a real browser test, not by unit tests — `e2e/live-view/`.**
  Both live-view bugs were invisible to jsdom: one was about the gap between two fulfilled
  polls, the other about a `postMessage` from a page we do not own. The gate scripts the
  list endpoint and serves its own cross-origin stand-in for the hosted iframe, then
  asserts the frame is **continuously on screen from first paint until the session really
  ends**, naming the closer responsible for any gap. `$0`, ~3.5 min:
  `e2e/run.sh live-view`. `--live` opts into one real Browserbase discovery. The component
  narrates itself through `liveViewDebug.ts`, which is compiled out of production builds
  (`import.meta.env.DEV`) and stays silent in dev until a harness sets
  `window.__JVN_LIVE_VIEW_DEBUG__`. **Change a closer, run that gate.**
- **It says goodbye rather than vanishing.** Mid-run the frame unmounts immediately (DOM
  removal, never `display: none` — while mounted it is Browserbase's page and free to
  paint their error), the toggle is replaced by *"Live view ended — still setting up"*,
  the 16:10 box slides shut under it, and then the line goes too. Same 260ms fade+rise as
  `DiscoveryNetworkLog`'s `ROW_ANIMATION`. On a run that ended there is **no** note — the
  checklist directly above has just said how it turned out.
- **Every tracked row links to the board it was built from**, on the list row and in the
  `MyCompanyTrendPage` header. **The URL is the server's** — `boardUrl` on the
  `UserCompany` payload, computed in `api/services/board_url.py`. The label is the host
  so the row answers the question without a click; the exact URL is on `title`
  (`sourceBoardUrl` / `sourceBoardLabel` in `companyHealth.ts`).
  - **It moved to the server because `provider_config` is there and not here.** Workday's
    real board is `{base_url}/{career_site_slug}` and Eightfold's is
    `https://{tenant_host}/careers?domain={domain}`; both live in that column, which the
    list payload does not carry, and `boardToken` for both is a cosmetic tenant label
    (`blueorigin`, `netflix`) naming no host. So **those two rows used to render no link
    at all** — and that is precisely what a company added by NAME looks like, since
    "Cisco" resolves to Workday. Teaching the browser those shapes would mean putting
    `provider_config` on the wire plus a second copy of every provider's URL grammar.
  - **`null` and absent are different, and the difference is load-bearing.** `null` is the
    server's considered answer (it saw the config and could not build an honest URL) and
    the UI renders nothing. **Absent** is a server that predates the field — Vercel and
    Railway deploy separately, so a frontend build can be live against one — and
    `sourceBoardUrl` falls back to the old local derivation: the pasted URL for a
    discovered board, host + slug for Greenhouse/Ashby/Lever/Gem. That fallback still
    refuses to guess Workday or Eightfold, because the only version of them it could build
    is a guess.
  - Every shape `board_url.py` emits is one the backend already depends on, and each is
    re-validated before it becomes an `href`: the Workday host against
    `WORKDAY_HOST_PATTERN`, the Eightfold host against the same SSRF allowlist the fetch
    uses, and everything against `http(s)` on both sides of the wire.
- **The network log** (`DiscoveryNetworkLog.tsx`) is the evidence under the checklist:
  every JSON request the capture browser recorded, which one we picked, and a sample of
  the JSON it returned. **Open by default, and it NARROWS** (one decision, not two):
  rows landing three and four at a time is the only part of a one-time setup a person can
  watch, and that was happening inside a closed box — but the moment a request is picked
  the list becomes that one row plus its JSON, with the discarded ones one caption-sized
  "Show the other 13 requests" away. Its heading keeps counting them (`11 requests so far`
  → `14 requests · 1 picked`). A refusal has no winner, so nothing narrows and the whole
  list stays — that case is why the panel exists. It renders nothing when nothing was
  recorded. Backed by `discovery.network` on the same
  poll; the backend streams rows as the capture sees them, throttled to at most 12 extra
  writes per run (`capture/discover.py`'s `_MAX_REQUEST_PUBLISHES`).
- **Nothing secret is published.** No request headers, no cookies, no POST bodies, and
  no query *values* — `discovery/progress.py::display_url` strips userinfo and port and
  replaces every query value with `…`, on write AND again on read.
- Copy + state helpers are pure and live in `components/my-companies/companyHealth.ts`
  (`DISCOVERY_STEP_LABELS` is a `Record` over a CLOSED union, so a backend rename is a
  compile error here); the components are `DiscoveryChecklist.tsx` and
  `DiscoveryNetworkLog.tsx`.

**Row chips: alarm colour is only for states the reader can act on.** This is a rule, not
a palette preference — an amber chip promises "this needs you", and spending it on
something with no available action teaches people to ignore amber everywhere else.

| Row state | Chip | Why |
| --- | --- | --- |
| `discovering` | blue `Setting up…` | one-time capture in flight |
| `unverified`, no `lastSuccessAt` | blue `Fetching all current jobs…` | first harvest hasn't landed; applies to **ATS rows too**, which have no checklist at all |
| ...and `first_scan` is `failed` | blue `Couldn't fetch yet — retrying` | the scheduler retries tonight; nothing for the reader to do |
| tracked, whole board | **filled** green `Successfully tracking` | |
| tracked, `outcome: partial` | **outlined** green `Tracking part of this board` | the board's own API refuses to go further (Amazon hard-refuses `offset + limit > 10000`). Same hue, hollow, different words — separable at a glance without claiming anything is broken |
| `quarantined` | amber `Tracking paused` | tracking has genuinely stopped; amber is right here |
| `refused` | red `Not trackable` | |

- A **partial** board is a success — every job it can see is refreshed daily and none is
  ever closed. It used to be amber, sitting directly above five green ticks, and the row
  read as a malfunction. The fix is two-sided: the chip stops shouting, AND the last rung
  stops claiming it fetched everything (`◐` + `describePartialScope`, which lifts the
  board's own count out of `verify_read`'s prose and pairs it with `openJobCount`). The
  chip now corroborates the list instead of contradicting it.
- **A row mid-fetch must never claim partiality.** The verdict is decided at discovery
  time and the harvest runs afterwards, so `outcome: 'partial'` genuinely exists over a
  count that is still climbing — asserting the end of a story mid-sentence, right above
  the number a reader would check it against.
- **The freshness line says "Last fetched", never "Last checked".** It renders
  `lastSuccessAt`, which the backend stamps only on a run that did NOT fail
  (`mark_last_success`), so "checked" claimed nobody had looked at a board we look at
  nightly and fail on nightly — it read as merely quiet instead of broken. "Fetched"
  survives that case (a failed fetch fetched nothing) and reframes the line as a fact
  about the count beside it. Not **"Last full scrape"** either: the same stamp is written
  by a knowingly-partial read, so "full" swaps this lie for a completeness claim we cannot
  back. Relative (`2 hours ago`, `Not fetched yet`), because the fact behind it is a
  nightly harvest and seconds-level precision was noise; the exact instant stays on the
  element's `title`. All of it lives in `describeLastFetched`.
- **Known gap:** an ATS row has no signal on the wire distinguishing "added ten seconds
  ago" from "has failed every night this week" (no created-at, no last-attempt, no
  last-failure). A discovered row does (`first_scan: failed`). This is what stops the
  freshness line from ever reporting an *attempt* — it can only be honest about the last
  success. The backstop is the backend's own — repeated failures quarantine the row.

**Env vars** (go in `src/frontend/.env.local` — see Gotcha #2):
- `VITE_CUSTOM_COMPANIES_ENABLED` — set to exactly `true` to show the Add Companies page
  (optional; **defaults to off**, and any other value keeps it off)
- `VITE_DISCOVERY_PROGRESS_ENABLED` — set to exactly `true` for the discovery checklist,
  job preview and live view (optional; **defaults to off**; nested under the flag above —
  it reveals nothing on its own)

## Frontend Foundations

All paths below are relative to `src/frontend/src/`.

This section documents the shared primitives and cross-cutting rules every page and feature must follow. These are the canonical building blocks — new code consumes them rather than re-inventing loading spinners, error alerts, or fetch lifecycles.

### Shared primitives

- **`LoadingState`** — `components/shared/LoadingIndicator.tsx`. Centered spinner with optional `caption` and `fullPage` props. Exported as `LoadingState` (preferred alias) and `LoadingIndicator` (original name). Use for any loading view: `<LoadingState fullPage />` for page-level initial loads, `<LoadingState size={60} minHeight={400} caption="…" />` for in-layout spinners.
- **`ErrorState`** — `components/shared/ErrorDisplay.tsx`. Error view with optional `inline` (Alert) vs card mode and optional `onRetry`. Exported as `ErrorState` (preferred alias) and `ErrorDisplay` (original name). Use `<ErrorState inline message={msg} onRetry={fn} />` for in-page errors; omit `inline` for the full-card variant.
- **`EmptyState`** — `components/shared/ErrorDisplay.tsx`. Empty-results view. Exported as `EmptyState` (preferred alias) and `EmptyStateDisplay` (original name). The job-specific `EmptyJobListState` wrapper stays — it reads copy from `constants/messages.ts`.
- **`extractErrorMessage(err, fallback?)`** — `lib/errors.ts`. Single source for decoding unknown errors (RTK Query `{ data }` shape, `Error` instances, strings, generic `{ message }` objects). Replaces the `err instanceof Error ? err.message : '…'` boilerplate and the nested RTK-Query ternaries. Always use this instead of hand-rolling the decode at the call site.
- **`useFetchWithStatus<T>`** — `hooks/useFetchWithStatus.ts`. Abortable fetch-lifecycle hook for page-level data loads. Mirrors the `AbortController` + `mountedRef` pattern used in `features/auth/useCurrentUser.ts` and `features/preferences/useEnabledCompanies.ts`. Use when a page or component needs to coordinate `loading` / `error` / `data` around a non-RTK-Query fetch. **Scope note:** RTK Query endpoints and the two auth-aware hooks above are intentionally not migrated — they have specialized behavior worth keeping separate.

### Rules

1. **Typed Redux hooks only.** All Redux consumers import `useAppDispatch` and `useAppSelector` from `app/hooks.ts`. Raw `useDispatch` / `useSelector` from `react-redux` is forbidden in `src/` outside that single file (it is the intended entry point). If a new file imports raw hooks, the review is rejected.
2. **Page-level fetch lifecycles use `useFetchWithStatus` or RTK Query — never both, never neither.** Inline `useState` + `useEffect` + `fetch` blocks for page/component data are prohibited. If a fetch needs caching, invalidation, or cross-page sharing, use RTK Query (`features/jobs/jobsApi.ts` pattern). If a fetch is page-local and read-only with a simple lifecycle, use `useFetchWithStatus`. User-action mutations (e.g. QAPage's trigger-scrape button) stay hand-rolled and do not fall under this rule — `useFetchWithStatus` is read-only by design.
3. **All error decoding goes through `extractErrorMessage`.** Do not introduce new `err instanceof Error ? err.message : '…'` ternaries or new `'data' in err` blocks.
4. **All page loading / error UI uses `LoadingState` / `ErrorState`.** Do not render raw `<CircularProgress />` in a centered `<Box>` or raw `<Alert severity="error">` at the page level. Nested-component spinners (e.g. chart skeletons, job-card skeletons) are fine and live alongside `LoadingState` in `components/shared/LoadingIndicator.tsx`.
5. **Mobile sizing goes through `RESPONSIVE` tokens — no hard-coded px.** Every page/component must look good on an iPhone in portrait (~390px) **without** changing the desktop/tablet (>= 600px) look. Consume the `RESPONSIVE` tokens in `config/responsive.ts` (and the `useIsMobile` hook for raw-number props) instead of inlining mobile pixel sizes/fonts/paddings. Each `{ xs, sm }` token's `sm` slot restates the current desktop value, so applying a token is a no-op >= 600px. Wide tables wrap in `TABLE_SCROLL_SX`. **Before adding any page or restyling one, read `src/frontend/docs/RESPONSIVE.md`** — the agent dock with the token catalog, the three token shapes, the "add a token" recipe, and the mobile checklist. A new magic number that should be a token is rejected in review.

### Remaining `eslint-disable` comments (authoritative list)

The following `eslint-disable` directives are allowed; all others must be justified in review. Each is documented here with the justification pulled from the code.

**`react-hooks/*` family:**

- `hooks/useFetchWithStatus.ts:141` — `react-hooks/exhaustive-deps`. The hook spreads the caller-provided `deps` array into its internal `useEffect` dep list. ESLint's exhaustive-deps rule cannot prove the spread is stable-by-convention across renders. The hook contract requires callers to pass a stable `fetcher` (via `useCallback`) and a deps array, mirroring `useEffect` semantics. The disable is localized to the single `useEffect` line.
- `components/layout/RootLayout.tsx:56` — `react-hooks/set-state-in-effect`. Auto-syncs `drawerOpen` local state with the `isMobile` MUI `useMediaQuery` breakpoint. `isMobile` is an external subscription (MUI wraps `matchMedia`), so mirroring it into local state via an effect is the React-recommended pattern. A `useSyncExternalStore` rewrite against `matchMedia` would be net-neutral for behavior and adds visual-regression risk around drawer-width transitions.
- `components/companies-page/MetricsDashboard/hooks/useTimeBasedJobCounts.ts:25` — `react-hooks/purity`. Samples `Date.now()` inside `useMemo` to compute rolling time-window counts (last 12h / 24h / 3d). Injecting `now` as an argument would relocate the `Date.now()` call into every caller in `MetricsDashboard/*`. Keeping the disable localizes the impurity to one line.

**Other disables:**

- `features/filters/slices/graphFiltersSlice.ts:67` — `@typescript-eslint/no-explicit-any`. `createFilterSlice` generates action creators via computed property names (`[set${CapitalizedName}TimeWindow]`), which TypeScript cannot infer through. The `as any` cast on `slice.actions` is the documented TS limitation (see https://github.com/reduxjs/redux-toolkit/issues/368). Types are still enforced at dispatch sites.
- `features/filters/slices/recentJobsFiltersSlice.ts:71` — `@typescript-eslint/no-explicit-any`. Same rationale as `graphFiltersSlice.ts`.
- `features/auth/GoogleCredentialContext.tsx:10` — `react-refresh/only-export-components`. The file exports both a React component (`GoogleCredentialProvider`) and the context object (`GoogleCredentialContext`) consumers need for `useContext`. Splitting into two files is possible but adds no runtime value; the disable is the established pattern for context modules.

New code must not add disables. If a new disable appears unavoidable, update this list with the file, line, rule, and justification in the same PR.

## Common Tasks

**Adding a Company:**
Use the `add-company` skill (repo-root `.claude/skills/add-company/`, `/add-company`) for the full procedure — `config/companies.ts` entry + `COMPANY_IDS`, the backend `companies` seed migration, the `changelog.ts` entry, and logos. Architecture context that still matters here: every ATS flows through the backend `/api/jobs` endpoint, so each new company is a `createBackendScraperCompany()` entry backed by a row in the backend `companies` table (the true Custom Web Scrapers — Google, Apple, Microsoft, Amazon, TikTok — omit `sourceAts`).

**Adding ATS Provider:**
1. Create transformer in `api/transformers/[provider]Transformer.ts`
2. Create client using `createAPIClient` factory (~15 lines)
3. Add Vercel serverless proxy in project root `api/[provider].ts`
4. Add to company configs and client selection logic

**Adding Filters:**
1. Add field to `GraphFilters` type (types/index.ts)
2. Update `createFilterSlice` factory (features/filters/slices/createFilterSlice.ts)
3. Update filtering logic (features/filters/selectors/graphFiltersSelectors.ts)
4. Add UI control (components/companies-page/GraphFilters.tsx)

**Debugging:**
- Redux DevTools for state inspection
- Selector tests: __tests__/features/filters/
- API transformer tests: __tests__/api/transformers/
- Time bucketing tests: __tests__/lib/timeBucketing.test.ts

## Critical Gotchas

1. **Use Vercel Dev**: Must run `npm run dev:vercel -w src/frontend` (not `npm run dev`) - Vercel serverless functions in `api/` directory proxy ATS API calls to avoid CORS issues
2. **Vite env files must live in `src/frontend/`, NOT the project root**: Two `vite.config.ts` files exist — `src/frontend/vite.config.ts` (used by `npm run dev`; no explicit `root:` key, so Vite defaults to `src/frontend/` as its root) and the project-root `vite.config.ts` (used by `vercel dev`; sets `root: path.resolve(__dirname, 'src/frontend')` explicitly). In both cases Vite resolves `.env` files relative to `src/frontend/`, so it reads `src/frontend/.env.local`, NOT `<project-root>/.env.local`. **DO NOT add `envDir` to either `vite.config.ts` to point at the project root** — this breaks Vercel Dev's API proxy routing, causing all `/api/*` requests to fail. Instead, frontend `VITE_*` env vars go in `src/frontend/.env.local` and backend/Vercel env vars go in `<project-root>/.env.local`.
3. **Vercel Dev cloud env vars override ALL local `.env` files for serverless functions (`api/*.ts`)**: `vercel dev` pulls env vars from the linked Vercel project and they take absolute precedence — `.env.local`, `.env.development.local`, and even shell env vars are all ignored. The `api/utils/backendUrl.ts` helper works around this by detecting `localhost` in the request Host header to use `http://localhost:8000` for local dev. **Do NOT rely on `process.env` in serverless functions for local dev config.**
4. **macOS port 5000 is AirPlay**: Never configure backend services on port 5000 — macOS Monterey+ runs AirPlay Receiver there via ControlCenter. It silently accepts HTTP connections and returns 403, masking "connection refused" errors. The backend runs on port 8000.
5. **Single Filter Source (companies page)**: The graph and the job list share one filter slice (`graphFilters`) — the list reflects the graph. There is no separate list-filter slice and no sync buttons.
6. **Empty Buckets Matter**: Time bucketing creates empty buckets for full range - don't filter them out
7. **Factory Patterns**: When modifying API or filter logic, update the factory functions, not individual implementations
8. **Zero TypeScript Errors Required**: Run `npm run type-check` before committing
9. **Test Coverage**: Maintain >80% coverage (1300+ tests passing)
10. **Memory Management**: Large job datasets require careful handling:
   - **Tables**: Always paginate tables with 100+ rows - unpaginated tables with thousands of rows cause severe browser memory issues (50+ GB)
   - **Selectors**: `selectAllJobsFromQuery` flattens all jobs - use filtered selectors when possible
   - **Pattern**: See QAPage jobs table for pagination pattern (useMemo for slice + TablePagination component)

## Key Files

All paths relative to `src/frontend/src/`:

- Redux Store: `app/store.ts`
- Type Definitions: `types/index.ts`
- Company Config: `config/companies.ts`
- Route Definitions: `config/routes.ts`
- API Client Factory: `api/clients/baseClient.ts`
- Backend Scraper Client: `api/clients/backendScraperClient.ts`
- Filter Slice Factory: `features/filters/slices/createFilterSlice.ts`
- Jobs RTK Query API: `features/jobs/jobsApi.ts`, `jobsSelectors.ts`, `progressHelpers.ts`, `keysetWalk.ts`
- Recent Jobs Filters: `features/filters/slices/recentJobsFiltersSlice.ts`, `features/filters/selectors/recentJobsSelectors.ts`
- Time Bucketing: `lib/timeBucketing.ts`
- Main App: `app/App.tsx`

## Vercel Serverless Functions

Located in project root `api/` directory (proxies to avoid CORS):

- `jobs.ts` - Backend jobs API proxy (every company, including all Greenhouse, Ashby, Lever, Gem, Eightfold/Netflix, and Workday boards)
- `jobs-qa.ts` - Backend QA endpoints proxy (scraper triggers, run history)
- `users.ts` - Backend users API proxy (forwards Authorization header)
- `features.ts` - Feature voting API proxy (forwards Authorization header)
- `admin.ts` - Admin API proxy (forwards Authorization header; admin-only endpoints)
- `companies.ts` - Curated-companies directory proxy (public, unauthenticated)
- `feedback.ts` - User feedback submission proxy (public, optional auth — stores anonymous if token missing/invalid)
- `locations.ts` - Canonical-location search proxy (public, internal-key auth; feeds Location filter dropdowns)

## See Also

- **Root CLAUDE.md** - Full project documentation including backend and scripts
- **docs/architecture.md** - Comprehensive Mermaid diagrams for data flow, state shape, factory patterns (located at `src/frontend/docs/architecture.md`)
- **Greenhouse API**: https://developers.greenhouse.io/job-board.html
- **Lever Postings API** (used by backend client): https://github.com/lever/postings-api
