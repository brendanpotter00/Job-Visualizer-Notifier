# onboarding — cases

Design: `PLAN.md`. Runbook: `.claude/skills/e2e-gate/sections/onboarding.md`.
Status legend: ⚪ planned · 🟢 green · 🔴 red (with reason).
Every case mints its OWN fresh identity (`PLAN.md` §4). "Sign in again" = a new browser
context as the same identity.

**Last real runs: 2026-11-22, `E2E_SOURCE_DB=jobscraper e2e/run.sh onboarding` @
`claude/onboarding-flow-prototype-248f2c`, twice back to back with no manual reset. Each: 13 API
+ 12 UI = 25 collected, 25 PASS, 0 FAIL, 0 BLOCKED, exit 0 — summary verdict GREEN.** Measured
**54 s** and **56 s** for the full gate; `--fast` (API tier only) **9 s**. The API
tier itself runs in ~1.3 s; the browser tier is ~47 s. First provision of the database adds
~10 s, once. Cost **$0** (no LLM, no Browserbase, no PostHog, browser fenced to `127.0.0.1`).

**2026-11-23 (OB-U13 added, `fix/onboarding-opens-before-page`):** full gate 13 API + 13 UI = 26 collected, 26 PASS, exit 0; the `subcategories` gate 55/55 alongside it. OB-U13 alone ~13 s.

**2026-11-27 (OB-U14..OB-U17 added, `feat/save-default-search`):** full gate 13 API + 17 UI = 30 collected, 30 PASS, exit 0, 98 s. Three mutations each turned their case red and were reverted: `OnboardingGate` ignoring the pending search (OB-U15; only once the case held the stamping POST 1.5 s and recorded any dialog in the page — a settle-window check alone missed a dialog that opens and closes within one local round trip), no restore of the pending search (OB-U16), no discard on a signed-out load (OB-U17). The `subcategories` gate was NOT run: port 3203 was held by a stale vite from another worktree.
**2026-11-27 (question 4, company types, `feat/company-categories`):** OB-10 and OB-U14 added (renumbered OB-U18 when merged after `feat/save-default-search`, which took OB-U14..OB-U17); every
drive-through answers four questions ("1/4"). The corpus gained `OB-DECOY-NOT-BIG` (fails only the
company type); the other five rows moved to Google, a real Big Tech member (`seed.py` checks the
backend agrees). Full gate 18 API + 14 UI = 32 collected, 32 PASS, exit 0.

**No case was dropped.** Every case keeps its oracle and decoy; where implementation added a
mirror or changed the evidence, the row says so ("Refined").

**Proven to bite.** A gate that has only been green has not been tested, so eight deliberate
mutation runs were made against the feature (one mutation per run; the seventh row pairs two
edits), the relevant cases run, and each mutation reverted (`git status` clean on `src/` after every one):

| Mutation (feature code) | Went RED |
|---|---|
| `OnboardingGate`: `!onboardingCompletedAt` instead of `=== null` (missing field = ask) | OB-U12 (OB-U9 stayed green, correctly) |
| `OnboardingFlow`: a failed Skip no longer calls `onDismiss()` | OB-U11 ("a failed Skip must still let the reader out") |
| `OnboardingFlow`: tab-title restore keyed on mount, not on `open` | OB-U11 ("the tab title is back to the page's own") |
| `OnboardingFlow`: always navigate to `/jobs` after a save | OB-U4 |
| `onboardingModel.toRequestAnswers`: specialty dropped from the request | OB-U1 |
| `routers/users.py`: `GET /api/users` always reports `onboardingCompletedAt: null` | OB-U2, OB-09, OB-03 |
| `user_service.complete_onboarding`: `IS NULL` guard removed + existing row's windows reset | OB-04 (both), OB-07, OB-09 |
| `user_service.complete_onboarding`: a NEW row gets `'3h'`/`'7d'` | OB-03 |

## API tier (`api/`, pytest — `--fast` runs only these)

| ID | Behaviour | Oracle / decoy (the wrong behaviour it rejects) | Status |
|---|---|---|---|
| **OB-01** | **First sign-in creates the account unstamped.** A fresh identity: no `users` row before; `GET /api/users` → 200 with `onboardingCompletedAt: null`; the DB row has `onboarding_completed_at IS NULL` | Rejects a server default that stamps new accounts (questions would never show). Asserts the key is PRESENT and null, not absent | 🟢 1/1 |
| **OB-02** | **Signing in again before answering still asks.** A second `GET /api/users` for the same identity → still `null`; no second row | Rejects stamping on read / on visit (`POST /api/users/visit` must not stamp either — call it between the two GETs). Mirror: `visit_count ≥ 1`, so the visit really reached the row | 🟢 1/1 |
| **OB-03** | **Finish stamps once and saves the answers.** `POST /api/users/onboarding` {SWE, backend, entry, San Francisco, skipped:false} → 200 with a timestamp + savedFilters; DB: stamped, `user_saved_filters` holds exactly those four lists with `recent_time_window='all'`, `trend_time_window='90d'`; `GET /api/users` and `GET /api/users/saved-filters` agree | Rejects the column defaults (`'3h'`/`'7d'`) leaking into a new row; rejects a stamp without the answers or vice versa (one transaction). The stamp must fall between two DB `now()` reads around the call. **Proven to bite** | 🟢 1/1 |
| **OB-04** | **It is idempotent; the first answers win.** A second POST with different answers → same `onboardingCompletedAt`, answers unchanged. Two concurrent POSTs for a fresh identity → exactly one stamp, one set of answers | Rejects re-stamping, and a later call clobbering the first answers. Refined: the second call must not even touch `user_saved_filters.updated_at`; the concurrent pair fires on a barrier with NO prior GET (so it also races the users-row INSERT), three rounds, and the stored answers must be ONE request's, never a mix. **Proven to bite** | 🟢 2/2 |
| **OB-05** | **Skip keeps the answers given; Skip with none still stamps.** `skipped:true` with only a level → stamped, level saved, other lists `[]`. A separate identity skipping with nothing → stamped, all lists `[]` | Rejects Skip discarding answers (decision `keep`), and Skip not ending the flow | 🟢 2/2 |
| **OB-06** | **A specialty is saved only with Software Engineering.** {product_manager, backend} → saved `subcategory: []`, `category: [product_manager]` | Rejects saving an orphan specialty that the search would then mis-scope. Refined: mirror identity {SWE, PM, backend} keeps `[backend]`, so the drop is the missing parent, not the pair | 🟢 1/1 |
| **OB-07** | **An existing saved-filters row keeps what onboarding does not set.** Pre-create filters (`PUT /api/users/saved-filters`: recent `'7d'`, an active keyword list) → onboarding replaces only category/subcategory/level/locations; time windows and keyword-list pointers survive | Rejects the upsert overwriting the whole row. Uses a real created keyword list (recent) and `builtin-swe` (trend). **Proven to bite** | 🟢 1/1 |
| **OB-08** | **Auth is required.** No bearer → 401; a token with no `email` claim → 401; neither creates or stamps a row | Rejects an anonymous write path. Refined: a third token signed by a different RSA key → 401 (signature is really checked), and a mirror — the email-less identity WITH an email is accepted, so the 401 is the missing claim. `shared/auth/mint.py` gained `email: None` → no claim (existing tokens unchanged) | 🟢 3/3 |
| **OB-10** | **Question 4 saves company types.** Finish with `companyCategory: [big_tech]`, `step: 4` → saved and read back; `step: 5` → 422, nothing stamped; Skip on question 4 keeps the types; a body WITHOUT the key saves `[]` on a new row and KEEPS a stored value on an existing one | Rejects an older SPA's body wiping a stored type (the keep rule), and a 5th step | 🟢 5/5 |
| **OB-09** | **A pre-existing account is never asked.** The seeded already-stamped account: `GET /api/users` → a timestamp, and a POST leaves the stamp unchanged | Rejects the backfill being undone by a later call. Refined: the stamp is a fixed past time compared exactly, and the POST must not create a `user_saved_filters` row. **Proven to bite** | 🟢 1/1 |

## UI tier (`ui/`, Playwright)

| ID | Behaviour | Oracle / decoy | Status |
|---|---|---|---|
| **OB-U1** | **HEADLINE — first sign-in answers the questions, lands on the filtered list.** Fresh identity, desktop: open `/jobs` → full-screen dialog "What roles are you looking for?" (1/4) → tick Software Engineering, specialty Backend → Continue → Entry → Continue → San Francisco → Continue → Big Tech → Show my jobs. The Company type field shows Big Tech and the search carries `company_category=big_tech`. Lands on `/jobs`; the Job Category / Level / Location fields show the answers; the seeded matching job is listed and every decoy is not; the "Saved filters" toast is visible, top-right, and links to `/saved-filters`; DB stamped | Decoys prove the filters are APPLIED, not just displayed: four decoys, each failing exactly ONE answer, and the list must hold exactly one row (`data-client-window`). Refined: also waits for the `/api/jobs/search` request carrying all four answers. Screenshot each step (`artifacts/<run>/screenshots/OB-U1/`). **Proven to bite** | 🟢 1/1 |
| **OB-U2** | **HEADLINE — signing in again never shows the questions.** After OB-U1, a NEW context as the same identity opens `/jobs` (and then `/companies`): no dialog (§5's wait), filters still show the saved answers. Repeat once more on the phone viewport | The whole point of the feature. Rejects a client-side-only flag (new context = empty storage). Also: the list still holds only the match, no toast, the stamp does not move. **Proven to bite** | 🟢 1/1 |
| **OB-U3** | **Left half-way, asked again; finished, never again.** Fresh identity sees Q1, ticks something, closes the context. Sign in again → the dialog is back at Q1 (nothing was saved, DB still NULL). Skip → sign in again → no dialog | Pins the plan's `asking -leave-> fresh` edge and that only a save ends it. The tick (Product Manager) must NOT come back, and no saved-filters row may exist | 🟢 1/1 |
| **OB-U4** | **Skip with no answers stays where you are.** Fresh identity opens `/companies`, Skip on Q1 → still on `/companies`, no toast; DB stamped with empty lists; sign in again → no dialog | Rejects the old redirect-to-/jobs on an empty Skip (URL and toast held for a 1.5 s settle window). **Proven to bite** | 🟢 1/1 |
| **OB-U5** | **Skip after answering keeps the answers.** Answer Q1 (Product Manager), Continue, Skip on Q2 → lands on `/jobs` with Job Category = Product Manager, toast shown; DB has `category=[product_manager]` | Decision `keep` end to end. Refined: starts on `/companies` so the landing is a real navigation, and the list must hold exactly the one PM row (the SWE rows are decoys) | 🟢 1/1 |
| **OB-U6** | **Escape counts as Skip.** Fresh identity, press Escape on Q1 → dialog closes, DB stamped | Rejects an Escape that only hides the dialog for the session — a new context must not be asked | 🟢 1/1 |
| **OB-U7** | **Back is disabled on Q1 and keeps answers.** Back visible+disabled on Q1; on Q2 Back returns to Q1 with the earlier ticks still checked; "1/3"→"2/3" and the progress bar width grows; focus lands on each question's h1 | Refined: bar measured as fill/track ≈ ⅓, ⅔, 1; the Q2 answer survives Back→Continue too; an untouched role stays unticked; moving through all three saves nothing (DB NULL, no saved-filters row) | 🟢 1/1 |
| **OB-U8** | **Never on `/` or `/pricing`.** Fresh identity opens `/pricing` → no dialog (§5 wait); then navigates to `/jobs` → dialog opens | Rejects a gate mounted outside RootLayout. Refined: `/pricing` never calls `GET /api/users`, so §5's evidence there is its signed-in-only `GET /api/billing/subscription` + the h1; the navigation is the page's own "Browse jobs" link (in-app, same session). `/` itself is not driven: a signed-in reader is redirected from `/` to `/jobs` (where asking is correct), and the signed-out landing page has no reader to ask | 🟢 1/1 |
| **OB-U9** | **A pre-existing account never sees it.** The seeded stamped account signs in → `/jobs`, no dialog | The backfill guarantee, as a user sees it; the stamp is unchanged afterwards | 🟢 1/1 |
| **OB-U10** | **Phone size.** OB-U1's path at 390x844: the dialog fills the screen, Continue/Back are reachable at the bottom, chips do not change width when tapped (measure before/after), the toast does not cover the app bar | Taps (touch context). Footer measured with all 17 specialties open; chips measured on Backend, Entry and San Francisco; ends with the one-row list and the stamp | 🟢 1/1 |
| **OB-U11** | **A failed save does not trap the user.** Route `POST /api/users/onboarding` → 500; Skip → the dialog closes for this visit and `document.title` is back to the page's own title; DB still NULL; reload (same context) → the dialog opens again; remove the route, Skip → stamped | Pins the review fix (failed Skip closes for the visit only) and the tab-title fix. Refined: the "page's own title" oracle is read off the pre-existing account's `/jobs`, never hard-coded. **Proven to bite** (both fixes) | 🟢 1/1 |
| **OB-U12** | **An older backend never opens it.** Route `GET /api/users` to strip `onboardingCompletedAt` from the body (fresh identity) → no dialog; DB still NULL | The staggered-deploy guarantee: `undefined` must never mean "ask". Refined: mirror — un-route and reload, the same account IS asked. **Proven to bite** | 🟢 1/1 |
| **OB-U13** | **A brand-new account goes STRAIGHT to the questions.** Every `GET /api/users*` held back 1.5 s (prod measured 1.5–3.5 s for a new account, 2026-11-23). Fresh identity opens `/jobs` → the questions open, and the page's own "Recent Job Postings" h1 was never painted before them (first-paint times recorded in the page, one clock); the load sent exactly ONE `GET /api/users` | Rejects the page loading first and the questions snapping in over it (the 2026-11-23 report), and one request per caller (Chrome runs identical GETs one after another, so the gate answered after three round trips). Mirror: the pre-existing stamped account on a NEW context is held until its one `GET /api/users` resolves, gets the page and no questions; on reload (same browser, now known) the page is painted while that request is still in flight — a returning reader never pays the hold twice. **Proven to bite** (pre-fix frontend: page h1 at 818 ms, questions at 2094 ms) | 🟢 1/1 |
| **OB-U14** | **Save default search, signed in.** A stamped account (Skip with no answers) on `/jobs`: **Save default search** is grayed out. Add a keyword and pick 24 hours → enabled. Click → "Saved default search", grayed out again. DB: `recent_time_window='24h'`, trend window still `'90d'`, a "Default search" keyword list holding the keyword, and BOTH keyword pointers on it. The next edit drops the confirmation. A new context opens on the saved search, button grayed out | Rejects a button that is never grayed out (or never enabled), a save that drops the keywords or touches the trend window, and a confirmation that outlives the next change | 🟢 1/1 |
| **OB-U15** | **Signed out, then a brand-new account.** Signed out: Software Engineering + Backend, Entry, 24 hours, a keyword; click (the Auth0 navigation is aborted by the fence). Sign in as a fresh identity and `page.goto('/jobs')` in the SAME tab (sessionStorage survives). No questions (§5 wait); "Saved default search" shows; the four fields and the keyword show the search; DB stamped and holding it (both pointers on the "Default search" list); the pending search is cleared. A new context: no questions, same search, stamp unchanged | Rejects the first-sign-in questions opening over the search (and their answers overwriting it), the old saved default hydrating over the pending search, and a stamp-less save. Decoy for the restore: the old row is the server defaults, so every field shown must have come from the pending search | 🟢 1/1. **Proven to bite** (gate ignoring the pending search) |
| **OB-U16** | **Signed out, then an existing account.** An account made through the API (stamped, `level=[senior]`, recent `'7d'`, trend `'30d'`). Signed out: Entry + a keyword; click; sign in; `/jobs`. Level shows Entry (not Senior), Time Window "All time"; DB `level=[entry]`, `recent_time_window='all'`, `trend_time_window='30d'` unchanged, the keyword list as above, the stamp unchanged | Rejects the existing default winning over the click, and the save touching the Companies (trend) window | 🟢 1/1. **Proven to bite** (no restore) |
| **OB-U17** | **Decoy: the sign-in is abandoned.** Signed out: Entry + a keyword; click; back to `/jobs` still signed out. The search shows once (Level Entry, the keyword), then the pending search is dropped from sessionStorage, no "Saved default search", and NO write to `/api/users*`. A new visit to bare `/jobs` shows the site defaults (Level "All", no keyword) | Rejects a pending search that outlives an abandoned sign-in (it would be saved by the next, unrelated sign-in) and any write while signed out. A plain reload is NOT the oracle: the URL sync wrote the filters into the address bar, and a reload re-applies a URL by design | 🟢 1/1. **Proven to bite** (no discard) |
| **OB-U18** | **An older backend that does not know company types.** The saved-filters GET is routed to drop `companyCategory`, and the onboarding POST to 422 a body carrying it or a `step` past 3 (as that backend would). The flow still shows four questions, the headline path saves, the one POST has no `companyCategory` and `step: 3`, and the list holds the three-answer set (the not-Big-Tech decoy is back) | The deploy window: the 4th answer is lost, the save is not | 🟢 1/1 |

## Known non-coverage

- The Vercel proxy (`api/users.ts`'s `onboarding` allow-list entry): plain `vite dev`, the same
  gap as every section — covered by `users.serverless.test.ts`.
- Real Auth0 / Google One Tap sign-in: the minted token rides the Google-credential path, which
  is the path the gate reads, but no OAuth redirect runs.
- PostHog events (`onboarding_viewed`, `onboarding_completed`, `onboarding_skipped`): PostHog is
  deliberately off; the "only the stamping call fires them" rule rests on `newly_completed`,
  which `test_onboarding_router.py` unit-tests.
- Q3's location search box (only the six preset chips are driven).
- Save default search's Location field (OB-U14..OB-U17 drive keywords, time window, category,
  specialty and level; the location row of the field table is covered by `defaultSearch.test.ts`).
- The real Auth0 round trip for a signed-out Save default search: the click's `loginWithRedirect`
  is aborted by the fence and the return is a same-tab `goto('/jobs')` with a minted token.
