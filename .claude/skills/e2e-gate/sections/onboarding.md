# First-sign-in onboarding — e2e gate runbook

Full design/reasoning: `e2e/onboarding/PLAN.md`. Live case status: `e2e/onboarding/CASES.md`.
Feature plan: `docs/implementations/onboardingFlow/plan.html`. This file is the "sub-skill": what
each case proves, how to run just it, and what to look at first when it goes red.

## Run it

```bash
e2e/run.sh onboarding              # full gate (API OB-01..OB-09 + UI OB-U1..OB-U17)
e2e/run.sh onboarding --fast       # API tier only — run on every commit
e2e/run.sh onboarding --case OB-U1 # one case (OB-U1 and OB-U2 run together: U2 builds on U1)
e2e/run.sh onboarding --keep-up    # leave the stack on :8205/:3205 (and the identities) for a fix loop
e2e/run.sh onboarding --refresh-db # re-provision jobscraper_e2e_onboarding from scratch
```

**Cost: $0, unconditionally.** No LLM call, no Browserbase session, no Stripe, no PostHog: the
env file blanks `POSTHOG_PROJECT_TOKEN`/`VITE_POSTHOG_KEY` (every case signs up a brand-new
identity, so a token would put fake sign-ups into the North Star funnel), `stack_app.py` refuses
to boot with a token, and the UI tier aborts every browser request that is not to `127.0.0.1`.

**Ports `8205`/`3205`, database `jobscraper_e2e_onboarding`, its own lock** — runs alongside every
other section, refuses a second copy of itself (it would purge this run's identities mid-test).

**Schema source.** The clone is schema-only, read (never written) from `E2E_SOURCE_DB` —
`jobscraper_pr243` when it exists, else the local `jobscraper`. If the source's
`alembic_version` row claims a revision its schema is not at (a backend pytest fixture
`alembic stamp head`-ed it), `seed.py` fails naming the fix:
`E2E_SOURCE_DB_REVISION=<revision the schema is really at> e2e/run.sh onboarding --refresh-db`.

## When to run this gate

Before claiming "ready to test" on anything touching:

- `src/frontend/src/components/onboarding/` — `OnboardingGate`, `OnboardingFlow`, the three
  questions, `ChoiceChip`, `OnboardingSavedToast`, `onboardingModel.ts`
- `src/frontend/src/components/layout/RootLayout.tsx` (where the gate is mounted)
- `src/frontend/src/features/defaultSearch/` and `components/recent-jobs-page/DefaultSearchButtons.tsx`
  (Save / Update / Reset to default search: OB-U14..OB-U17; its signed-out path stamps new accounts and keeps the
  questions closed for that load). `RecentJobsFilters.tsx` itself is gated by `subcategories`
- `features/auth/authService.ts` (`parseUserResponse`, `onboardingCompletedAt`),
  `features/savedFilters/savedFiltersApi.ts` (`completeOnboarding`),
  `features/savedFilters/propagateSavedFilters.ts`
- `src/backend/api/routers/users.py` — `GET /api/users`, `POST /api/users/onboarding`, `/visit`
- `src/backend/api/services/user_service.py` — `complete_onboarding`, `get_or_create_user`
- `src/backend/api/models.py` — `UserResponse.onboarding_completed_at`, `OnboardingRequest/Response`
- `src/backend/api/db_models.py` `User`, and any migration touching `users` or
  `user_saved_filters` (the stamp column has NO server default — on purpose)
- `api/users.ts` (the Vercel proxy's `onboarding` allow-list entry — see non-coverage below)
- `services/job_search.py`'s specialty scope — also gated by `subcategories` SC-03

## Files this suite does NOT own — report bugs there, don't fix them here

All of the above. If a case fails because of a bug in one of them, the case is doing its job —
**report the bug, don't bend the test to it.** The decided behaviours (Skip keeps answers; an
empty Skip stays on the page; a failed Skip closes for this visit only; a specialty narrows only
SWE jobs; never on `/` or `/pricing`) are product decisions in the plan, not test choices.

## Per-case reference

| ID | Proves | First thing to check on red |
|---|---|---|
| **OB-01** | A brand-new account is created with `onboardingCompletedAt` PRESENT and `null` | A server default / INSERT stamping new rows (`db_models.User`, the migration), or a serializer dropping `None` keys |
| **OB-02** | A second GET and a visit do not stamp it | `get_or_create_user` or `record_visit` touching `onboarding_completed_at` |
| **OB-03** | Finish stamps once and saves the four answers; a NEW saved-filters row gets `'all'`/`'90d'` | `complete_onboarding`'s INSERT. `'3h'`/`'7d'` = the column defaults leaked (the INSERT stopped setting the windows) |
| **OB-04** | A second call changes nothing; two concurrent first calls stamp once with ONE request's answers | The `IS NULL` guard on the UPDATE. **Proven to bite**: removing it turned OB-04 (both) and OB-09 red |
| **OB-05** | Skip keeps the answers given; an empty Skip still stamps | `skipped` must not clear the lists — decision `keep` |
| **OB-06** | A specialty is saved only with Software Engineering (mirror: kept with SWE + PM) | `complete_onboarding`'s `SUBCATEGORY_PARENT not in category` rule |
| **OB-07** | An existing row keeps both windows and both keyword-list pointers | The `ON CONFLICT … DO UPDATE SET` list must name only the four answer columns. **Proven to bite** |
| **OB-08** | No bearer, an email-less token, a token from another key: all 401, no row | `get_current_user` / the router's `email` check |
| **OB-09** | The seeded pre-stamped account reads its stamp and a POST leaves it (and creates no saved-filters row) | Same guard as OB-04 |
| **OB-U1** | **HEADLINE** — first sign-in: questions → SWE/Backend, Entry, San Francisco → lands on `/jobs` with the three fields showing the answers, the `/api/jobs/search` request carrying all four, exactly the one matching row (four one-answer decoys absent), the top-right toast linking to `/saved-filters`, DB stamped | Screenshots in `artifacts/<run>/screenshots/OB-U1/`. A missing search request = propagation (`savedFiltersPropagationActions`); two rows = an answer not applied. **Proven to bite** (specialty dropped from the request) |
| **OB-U2** | **HEADLINE** — a NEW context as the same identity (desktop, then phone): no questions on `/jobs` or `/companies`, saved answers hydrated | The server stamp is the only thing a new context has. **Proven to bite** (`GET /api/users` reporting `null`) |
| **OB-U3** | Left half-way → asked again at Q1 with nothing kept, DB NULL; Skip → never again | Nothing may save on close-without-Skip |
| **OB-U4** | Empty Skip on `/companies` stays there, no toast, DB stamped | `savedFiltersHaveAnswers` gating the navigate/toast. **Proven to bite** (always navigating) |
| **OB-U5** | Skip on Q2 after picking Product Manager → `/jobs` with it applied (only the PM row), toast, DB `category=[product_manager]` | Decision `keep`, end to end |
| **OB-U6** | Escape counts as Skip (stamped; a new context is not asked) | `Dialog onClose` → `submit(true)` |
| **OB-U7** | Back disabled on Q1; Back/Continue keep every answer; `1/3`→`2/3`→`3/3` with the bar at ⅓/⅔/1; focus on each h1; moving saves nothing | `OnboardingFlow`'s single draft, `QuestionHeading` focus |
| **OB-U8** | `/pricing` never shows them (evidence: the signed-in plan read + h1); one click on to `/jobs` does | Gate mounted outside `RootLayout`, or `isOnboardingExcludedPath` |
| **OB-U9** | The pre-existing account is never asked | Backfill semantics |
| **OB-U10** | Phone 390x844: full-screen dialog; Back/Continue on screen with 17 specialties open; chips keep their width when tapped; toast under the app bar. Then the 375px filter row: picked levels wrap as chips inside the field, no sideways scroll, a tap on a chip's x removes just that level | `ChoiceChip` padding math, `RESPONSIVE.onboarding`; for the filter-row step, `FacetValueChips.tsx` |
| **OB-U11** | A 500 on save: Skip still closes, the tab title is the page's own again (oracle: the pre-existing account's `/jobs` title), DB NULL; reload asks again; server back → Skip stamps | **Proven to bite** twice: removing `onDismiss()` on a failed Skip, and keying the title restore on mount instead of `open` |
| **OB-U12** | `GET /api/users` without the field (older backend) never opens them; mirror: the field restored does | `OnboardingGate`'s `=== null`. **Proven to bite** (`!onboardingCompletedAt`) |
| **OB-U13** | With prod-like latency on `/api/users*`, a brand-new account's page h1 is never painted before the questions, and a load sends ONE `GET /api/users`; mirror: a stamped account on a new device waits for that one answer, and on its next load is not held | `RootLayout`'s `useOnboardingHold` + the shared `CurrentUserProvider`. **Proven to bite** (pre-fix frontend: page h1 at 818 ms, questions at 2094 ms — the 2026-11-23 prod report) |
| **OB-U14** | Signed in: a solid green, not clickable "Default search saved" on the saved default; a change offers Update and Reset to default search; Update saves the whole Recent search (keywords in a "Default search" list, both pointers on it, trend window untouched); Reset goes back to the saved default and saves nothing; a new context hydrates to it | `DefaultSearchButtons`, `useSaveDefaultSearch` / `defaultSearch.ts` (`planKeywordList`, `toSavedFiltersPayload`, `toRecentFiltersPatch`). Never "saved" = the default (`defaultSearchFromSaved`) disagrees with the slice; Reset to the wrong place = `resetRecentJobsFilters(patch)` |
| **OB-U15** | Signed out → brand-new account: the search survives sign-in in sessionStorage, no questions open, the account is stamped and the search saved | `useApplyPendingDefaultSearch` (restore before `useHydrateSavedFilters`, its `AppContent` order) and `OnboardingGate`'s `hadPendingDefaultSearchAtLoad` |
| **OB-U16** | Signed out → existing account: its old default is replaced, the trend window and the stamp are not touched | Same hook; a Senior/7-day page = the saved row hydrated before the restore |
| **OB-U17** | Decoy: an abandoned sign-in shows the search once, sends nothing, drops the pending search, never shows "Default search saved"; Reset to default search and a new bare `/jobs` visit are the site defaults | The discard effect in `useApplyPendingDefaultSearch` (signed-out load) |

## Reading a red

`e2e/onboarding/artifacts/<run>/summary.md` first, then `cases/<test>/step.txt` (API tier names
the failing step in words), then the UI failure's screenshot + trace under the run's `ui/`, and
the step screenshots under `screenshots/<case>/`. `stack/backend.log` has every request.

| Symptom | Cause | Fix |
|---|---|---|
| `seed.py`: `users.onboarding_completed_at is missing although the clone is stamped …` | The schema source's `alembic_version` is ahead of its schema | `E2E_SOURCE_DB_REVISION=<real revision> … --refresh-db` |
| `seed.py`: `job_subcategories is empty` | The clone predates `ensure_db.sh`'s copy step | `--refresh-db` |
| Every UI case fails on `expectQuestion` (no dialog) | The SPA is signed out: `env.onboarding`'s `VITE_AUTH0_*` pins did not reach vite | Check `stack/frontend.log`; run through `run.sh`, not a bare `vite` |
| A "questions opened" failure in a negative case | Real: the gate opened after every `GET /api/users` came back | Not flake — PLAN.md §5's wait already rules timing out. Read the screenshot |

## Known non-coverage

- The Vercel proxy (`api/users.ts`'s `onboarding` allow-list entry) — plain `vite dev`, same gap as
  every section; covered by `src/frontend/src/__tests__/api/serverless/users.serverless.test.ts`.
- Real Auth0 / Google One Tap sign-in — the minted token rides the Google-credential path, which
  is exactly the path the gate reads (`GET /api/users`), but no OAuth redirect is exercised.
- The PostHog events (`onboarding_viewed`, `onboarding_completed`, …) — deliberately off.
- The location search box on Q3 (only the six preset chips are driven).
- Save default search's Location field, and the real Auth0 round trip of its signed-out click (the
  redirect is fenced; the return is a same-tab `goto('/jobs')` with a minted token).
