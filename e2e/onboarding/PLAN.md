# e2e section: onboarding — plan

The first-sign-in questions (role, level, location) are shown **once per account, ever**.
This section proves that end to end, against a real backend, a real Postgres and a real
browser, by **simulating real sign-ins**: a brand-new identity signing in for the first
time, the same identity signing in again later (a new browser context = a new device or a
fresh session), a session abandoned half-way, and an account that existed before the
feature shipped.

Feature plan: `docs/implementations/onboardingFlow/plan.html`. Case table: `CASES.md`.
Gate runbook: `.claude/skills/e2e-gate/sections/onboarding.md`.

## 1. What this section owns, and what it does not

| Owns | Does not own (where it lives instead) |
|---|---|
| The one-time gate: `users.onboarding_completed_at` NULL → ask, stamped → never again, across sign-ins, contexts and devices | The migration's backfill SQL in isolation — `src/backend/api/tests/test_migration_onboarding_completed_at.py` (unit) |
| `POST /api/users/onboarding` against a real DB: stamp once, idempotent, Skip keeps answers, time windows, SWE-only specialties | Per-component rendering details — the Vitest files under `src/frontend/src/__tests__/components/onboarding/` |
| The UI flow in a real browser at phone and desktop sizes: questions → answers → landing on `/jobs` with the answers in the filters → "Saved filters" toast | The specialty-scope SQL rule itself — the `subcategories` section (SC-03 owns it; see §7) |
| Failure paths a unit test cannot see: a failed save, an older backend without the field, a page that must never show the questions (`/`, `/pricing`) | |

## 2. The three rules (same convention as every section — see `add-companies/PLAN.md` §1)

1. **One directory, its own `PLAN.md`, `CASES.md`, `api/`, `ui/`, `run.sh`.** One row in
   `e2e/README.md`, one runbook in `.claude/skills/e2e-gate/sections/onboarding.md`, and the
   section added to `e2e/run.sh`'s usage/cost list.
2. **Generalise `e2e/shared/`, never fork it.** Use the knobs `subcategories` and `billing`
   already added (ports, env file, pidfile dir, target DB). A new knob needs a default equal to
   today's behaviour so every other section is byte-for-byte unaffected.
3. **Every case has an independent oracle and a decoy/mirror.** A case that would also pass
   on a broken build is worse than no case. Each case in `CASES.md` names the wrong behaviour
   it rejects.

## 3. Stack

- **Ports `8205` (backend) / `3205` (frontend)**, database **`jobscraper_e2e_onboarding`**,
  its own run lock. Never `8000`/`8100`/`3000` (the owner's), and never another section's
  ports, so this gate can run alongside the others.
- Provisioned by `shared/db/ensure_db.sh` (schema clone + `alembic upgrade head`, so the
  `onboarding_completed_at` column exists) — the source DB comes from `E2E_SOURCE_DB`
  (default `jobscraper_pr243`; on this machine `jobscraper` is the local dev DB).
- Cost: **$0, unconditionally.** No LLM, no Browserbase, no Stripe, no host but its own
  stack. Say so in `run.sh`'s banner like every section does.
- **As built**, three things make that claim enforced rather than hoped:
  - `env.onboarding` blanks `POSTHOG_PROJECT_TOKEN` and `VITE_POSTHOG_KEY` — every case signs up a
    brand-new identity, and with the root `.env.local`'s real token each run would mirror a dozen
    fake `user_signed_up` / `onboarding_completed` events into the North Star funnel.
    `stack_app.py` (the section's `E2E_APP_MODULE`, wrapping the shared `e2e_app`) refuses to
    boot if a token is set anyway.
  - The UI tier's contexts abort every request whose host is not `127.0.0.1`/`localhost`
    (`ui/helpers.ts::openSignedIn`) — e.g. the Google sign-in script the providers load.
  - `env.onboarding` PINS the SPA's auth switch (`VITE_AUTH0_DOMAIN=e2e.local.test`,
    `VITE_AUTH0_CLIENT_ID`, empty `VITE_GOOGLE_CLIENT_ID`). `useAuth` reports a signed-in reader
    only when `AUTH_CONFIG.isEnabled`, and the Google-credential provider the minted token rides
    in is not even mounted otherwise; borrowing a developer's `src/frontend/.env.local` would
    make the gate mean different things on different machines (a worktree has none at all).
- Schema source: `E2E_SOURCE_DB`, else `jobscraper_pr243` if it exists, else the local
  `jobscraper` (billing's fallback). Two shared generalisations of `ensure_db.sh` came with this
  section, both no-ops for the sources it was written against: when `job_subcategories` is still
  empty after `upgrade head` (a source already past its seed migration), its rows are copied
  from the source; and the opt-in `E2E_SOURCE_DB_REVISION=<rev>` stamps a FRESH clone at the
  revision the source's schema is really at before `upgrade head`, for a source whose
  `alembic_version` row is ahead of its schema. The local `jobscraper` was exactly that on
  2026-11-22 (stamped `ef0f7d8c8e11`, no `users.onboarding_completed_at`), so this machine
  provisions with `E2E_SOURCE_DB_REVISION=bcbc67dbd87e … --refresh-db` once; `seed.py` fails
  naming that fix if the column is missing.
- Seed (`seed.py`, idempotent, like `subcategories/seed.py`):
  - the reveal flag `app_settings.swe_subcategories_enabled = true` (the SWE accordion only
    exists with it on);
  - a small job corpus so "the list opens with the answers applied" is a visible fact, not
    only filter text: at least one SWE/backend/entry/San Francisco row that must SHOW after the
    headline answers, plus decoys that must NOT show (SWE/frontend, SWE/backend/senior,
    a New-York-only row) and one product_manager row for the scope case;
  - one **pre-existing, already-stamped** account (as the migration's backfill leaves every
    account that existed at deploy time) for OB-U9.

## 4. Identities — how sign-in is simulated

Sign-in is the app's own path: `shared/auth/storage_state.ts::signInContext` writes a minted
RS256 credential into `localStorage['jvn.googleCredential.v1']` via an init script, and the
patched JWKS seam in `shared/stack/e2e_app.py` accepts it. Rules for this section:

- **Every case mints its own fresh identity** (`mintToken({ sub, email })`, i.e. mint.py
  `custom`) with a run-unique suffix, e.g. `e2e|onboarding-OB-U1-<runId>`. "First sign-in"
  must mean **no `users` row exists** — assert that in the DB before the first page load.
  Never reuse `primary`/`other` (other sections own their state).
- **"Sign in again" = a NEW browser context signed in as the SAME identity** (fresh
  localStorage — a new device or a later session). Closing a context without finishing is
  "left half-way".
- Teardown: purge every identity the run created (users row + `user_saved_filters`), through
  a small helper that refuses any sub not prefixed `e2e|onboarding-`.
- **As built** (`identities.py`): identities are `e2e|onboarding-<case>-<runId>-<rand>` /
  `e2e+onboarding-…@jvn.test`; the API tier purges each test's own identities at teardown, and
  `run.sh` purges every prefixed row (sub OR email prefix) at the end of the run and in `seed.py`
  before each tier (the pre-clean an aborted run needs). The pre-existing account is
  `e2e|onboarding-preexisting`, re-seeded stamped at the fixed `2026-01-15T12:00:00Z` with no
  saved-filters row before each tier. The UI tier reads DB state through
  `python -m e2e.onboarding.identities state <sub> <email>`.

## 5. Waiting without flakiness

"The questions do NOT appear" is a negative assertion, the classic flaky one. Never assert
absence after a fixed sleep alone. Wait for the evidence that the gate has decided:
the page's `GET /api/users` response has arrived (`page.waitForResponse`), the user menu
avatar is rendered, and the page `h1` is visible — THEN assert there is no dialog, and keep
asserting for a short settle window (e.g. 1.5s polling) to catch a late open.

As built (`ui/helpers.ts::expectQuestionsNeverOpen`): it counts EVERY `GET /api/users` the page
starts (the user menu, the drawer and the gate each make one) and waits until all have finished,
then the user menu and the h1 (CSS locators — an open dialog makes the rest of the page
aria-hidden, and a role locator would time out naming the wrong thing), then polls for no
dialog every 100 ms for 1.5 s. `/pricing` (OB-U8) makes no `/api/users` call, so its evidence
is its signed-in-only `GET /api/billing/subscription` plus its h1.

## 6. Tiers

- `api/` (pytest, fast, `--fast` runs only this): direct HTTP against `:8205` with minted
  bearer tokens + DB assertions via `shared/db/assertions.py`. Covers OB-01..OB-09.
- `ui/` (Playwright, chromium): OB-U1..OB-U12, at desktop (1280x800) and phone (390x844)
  where the case says so. Screenshots on the headline steps into the run's artifacts dir.

## 7. The `subcategories` gate must change with this PR

This PR deliberately changed the specialty scope: a SWE specialty narrows only
software-engineering rows, and another selected category keeps all its rows. `SC-03` pins the
OLD rule ("a subcategory paired with the WRONG parent category is unsatisfiable"). Update it
to the new rule — do not delete it, and do not weaken it to "returns something":

- `category=product_manager&subcategory=backend` returns **exactly the product_manager rows**
  (mirror: no SWE row at all);
- `category=software_engineering&category=product_manager&subcategory=backend` returns the PM
  rows **plus** exactly the SWE rows matching `backend` (with its `full_stack` widening) and no
  other SWE row;
- `subcategory` with no category, and `software_engineering` alone, are unchanged (that is
  what SC-02/SC-04 already pin — they must stay green untouched).

Update `subcategories/CASES.md`, `subcategories/PLAN.md` where it states the old rule, the
API test, any UI spec that asserted it, and `.claude/skills/e2e-gate/sections/subcategories.md`.

## 8. Done means

**Status 2026-11-22: done.** Both gates green — onboarding twice back to back (54 s, 56 s; 25/25
each), subcategories twice (49 s, 44 s; 55/55 each) — with the measured detail in each `CASES.md`.


- `e2e/run.sh onboarding` (full) and `e2e/run.sh subcategories` (full) are both green twice
  in a row (a second run proves cleanup and idempotent seeding).
- `CASES.md` statuses updated with measured counts and runtime, like the other sections.
- No change to `.venv` committed (it is a tracked symlink to another machine's path; work
  around it locally only).
