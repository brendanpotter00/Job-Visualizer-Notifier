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
- **The sentence under the button IS the consent, and it may not promise a confirm.** It
  lives in `ResolveUrlForm`, directly under **Add company**: *"If this board is new to us,
  Add company starts a one-time setup right away, about a minute."* It used to be a blue
  info alert above the whole form saying the same thing at greater length; the alert was
  cut ("the consent alert can be completely removed") and this replaced it, because a line
  under the button is read by someone about to press it and a banner above the field is
  read on the way past. It may never move behind a click, and it may never shrink back to
  promising a read-only check — that is what the deleted "nothing is tracked until you
  press Track this company" did, and the button it named is gone.
- **The field helper is the last statement of the aggregator rule.** *"Paste the link to
  the company's own careers page, not LinkedIn or Indeed."* The clause naming the
  aggregators is there ONLY because the how-to video that was going to say it does not
  exist yet (`HOW_IT_WORKS_VIDEO_SRC` is `null`), and nothing in the product enforces it:
  `_NEVER_MATCH_DOMAINS` is a denylist read on the wrong rung, and it misses `dice.com`,
  `monster.com` and `hiring.cafe`. An aggregator URL therefore resolves, finds no board,
  reaches `no_ats_detected`, and that is precisely the branch that spends a discovery run
  and one of the user's monthly adds. Delete the clause when the video ships; not before.
- **The how-to IS the empty state** (`AddCompanyHowTo`). A user tracking nothing sees three
  numbered steps where "No companies yet" used to be, and the state is still named for a
  screen reader by a `visuallyHidden` line. One company later the list replaces it and a
  persistent **How it works** link under the spend sentence re-opens the same component —
  one component, two triggers, so the two renders cannot drift. The **video slot is empty
  and draws nothing**: set `HOW_IT_WORKS_VIDEO_SRC` and the video appears under the same
  steps, which is the whole change.
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

  **One component renders all three**: `AddCompanyOutcome` hands any `already_public` body
  to `DiscoveryStatus`, which renders `TrackAnywayAction` **only** when
  `matchKind === 'name'` (`isNameGuessMatch`). The `matchKind` on the wire is the whole
  rule — which check answered is no longer visible in the component tree, and must not be
  re-derived from one.

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

**Key files** (relative to `src/frontend/src/`):
- `config/customCompanies.ts` — the flag (`VITE_CUSTOM_COMPANIES_ENABLED === 'true'`)
- `features/userCompanies/userCompaniesApi.ts` — RTK Query slice; `baseUrl: '/api'` on
  purpose, so endpoints under more than one path prefix can share it
- `features/userCompanies/resolveErrors.ts` — resolver-code → copy mapping
- `components/my-companies/ResolveUrlForm.tsx` — the input, the only button, the helper
  carrying the aggregator rule, and the spend sentence under the button
- `components/my-companies/AddCompanyHowTo.tsx` — the three steps and the video slot;
  `HOW_IT_WORKS_VIDEO_SRC` at the top is the one line to change when a video exists
- `components/my-companies/AddCompanyOutcome.tsx` — every outcome one press can land on
- `pages/MyCompaniesPage/` — the page (signed-out gate + form + results)

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
  the **trust lease** (`LIVE_VIEW_TRUST_MS` = one poll interval + a round trip, renewed by
  every fulfilled payload, which is what closes the *unbounded* cases — a failing poll
  keeps serving the last good payload, banner and all); and the session ceiling
  (`_BROWSERBASE_SESSION_TTL_S`, 300s, for a row a SIGKILLed worker will never retract).
  Retirement is always recorded as *the URL it refers to*, so no verdict outlives its
  session. `receivedAt` (`fulfilledTimeStamp`) is a **required** prop for exactly this
  reason — a caller that forgets it would get a frame that outlives its session.
- **It says goodbye rather than vanishing.** Mid-run the frame unmounts immediately (DOM
  removal, never `display: none` — while mounted it is Browserbase's page and free to
  paint their error), the toggle is replaced by *"Live view ended — still setting up"*,
  the 16:10 box slides shut under it, and then the line goes too. Same 260ms fade+rise as
  `DiscoveryNetworkLog`'s `ROW_ANIMATION`. On a run that ended there is **no** note — the
  checklist directly above has just said how it turned out.
- **Every tracked row links to the board it was built from** (`sourceBoardUrl` /
  `sourceBoardLabel` in `companyHealth.ts`), on the list row and in the
  `MyCompanyTrendPage` header. A discovered board's `boardToken` *is* the normalized URL
  the user pasted; Greenhouse/Ashby/Lever/Gem are built from the slug. **Workday and
  Eightfold get no link** — their `boardToken` is a cosmetic tenant label and the real
  host lives in `provider_config`, which the list payload does not carry, so a link would
  be a confident 404. The label is the host so the row answers the question without a
  click; the exact URL is on `title`.
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
- Jobs RTK Query API: `features/jobs/jobsApi.ts`, `jobsSelectors.ts`, `progressHelpers.ts`
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
