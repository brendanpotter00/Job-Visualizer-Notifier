# E2E gate — Add Companies (section 1)

**Status: plan only. Nothing here is built yet.**
Written 2026-08-26 against `feat/e7-phase3-discovery` @ `29714c4` + uncommitted sibling work.

## What this is for

> "I let you work like three hours and I come back and you're just broken and I need to test it myself."

This suite runs **before** any agent says "ready to test". It is a **regression gate**, not a demo.
If it goes green and Add Companies is still broken, the suite failed.

It is also **section 1 of a multi-feature initiative** — the layout below is designed so section 2
drops in beside it without reshaping anything.

---

## 0. TL;DR for the implementing agent

| | |
|---|---|
| **Build order** | §12. Do the stack + auth first. Everything else is blocked on them. |
| **Riskiest part** | **Test-account provisioning** (§4). Read it before writing a line. |
| **Non-negotiable** | `CAPTURE_USE_BROWSERBASE=false`, dedicated DB, never write to `jobscraper_pr243`. |
| **One case starts life RED** | AC-06. It is catching a real defect (§11.2). Do **not** weaken it to green. |
| **AC-01 / AC-02 changed under me** | The host-match wiring landed **while this plan was being written** (§11.1). They should now go green — verify, don't assume. |
| **Ports** | backend `8201`, frontend `3201`. `8000`, `8100`, `3000` are the owner's — leave them alone. |

---

## 1. Directory structure

```
e2e/
├── README.md                     # index: what sections exist, how to run any of them
├── run.sh                        # e2e/run.sh <section> [--fast] [--case AC-06]
├── shared/                       # feature-AGNOSTIC infrastructure. No board names in here.
│   ├── stack/
│   │   ├── e2e_app.py            # uvicorn entrypoint: imports api.main:app, patches the JWKS seam
│   │   ├── stack_up.sh           # postgres check → db ensure → backend :8201 → vite :3201 → wait-for-ready
│   │   ├── stack_down.sh         # kill by pidfile; never kills anything it did not start
│   │   ├── env.e2e               # the ONLY env the e2e backend reads
│   │   ├── vite.e2e.config.ts    # proxies the WHOLE /api prefix at :8201 (see Trap 2)
│   │   └── preflight.py          # board reachability probe + guard rails (§6)
│   ├── auth/
│   │   ├── keypair.py            # generate/cache an RSA keypair under artifacts/
│   │   ├── mint.py               # mint an RS256 access token for a named test user
│   │   └── storage_state.ts      # Playwright helper: inject the token the app's own way
│   ├── db/
│   │   ├── ensure_db.sh          # create jobscraper_e2e from a dump of the dev DB if absent
│   │   ├── reset_user.py         # purge one test user and everything they own
│   │   └── assertions.py         # shared DB predicates (row counts, purge-complete, ownerless delta)
│   └── playwright/
│       ├── playwright.config.ts  # base config: reporters, trace/video/screenshot policy
│       └── fixtures.ts           # signed-in page fixture, per-test artifact dir
└── add-companies/                # ← SECTION 1
    ├── PLAN.md                   # this file
    ├── CASES.md                  # the case table the skill reads
    ├── boards.py                 # the six board URLs + expected classification — ONE source of truth
    ├── api/                      # pytest — API + DB level cases
    │   ├── conftest.py
    │   ├── test_already_public.py
    │   ├── test_ats_path.py
    │   ├── test_discovery.py
    │   ├── test_public_match.py
    │   └── test_lifecycle.py     # delete/purge, idempotency, isolation, flags
    ├── ui/                       # Playwright — UI-truth cases only
    │   ├── add-delete.spec.ts
    │   ├── already-public.spec.ts
    │   └── checklist.spec.ts
    └── artifacts/                # gitignored. Every run writes here. (§10)
```

### The convention for adding section 2

Three rules, and they are the whole convention:

1. **A section is a directory under `e2e/` named after the skill section, not the code area.**
   `e2e/<section>/`. It owns `PLAN.md`, `CASES.md`, its own `api/` and `ui/`, and nothing else.
2. **Anything a second section could reuse belongs in `e2e/shared/` and must not name a board,
   a company, or a page.** The stack, the auth mint, the DB reset, the Playwright base config are
   already section-agnostic. If section 2 needs to *edit* a file in `shared/`, that is the signal it
   was written too specifically — generalise it, do not fork it.
3. **The skill gains a section file, not a new skill.** `.claude/skills/e2e-gate/sections/<section>.md`.
   `SKILL.md` lists sections and dispatches; it never grows per-feature detail.

`e2e/README.md` carries a one-row-per-section table (section · what it gates · runtime · cost).
Adding a section = one directory, one section file, one row.

---

## 2. The stack the suite owns

**The suite must own its backend process.** Not a preference — a requirement, for two reasons:

* `.env.local` currently sets `CAPTURE_USE_BROWSERBASE=true`. The code default is `False`
  (`src/backend/api/config.py:169`). Browserbase bills per browser-hour; local Chromium is $0 and
  is what every measurement in `TESTABLE-BOARDS.md` was taken with. The gate must force it off,
  and settings are read at process start — so the gate needs its own process.
* The owner's backend on `:8100` is his. Restarting it to change env is not on the table.

| Piece | Value | Notes |
|---|---|---|
| Backend | `http://127.0.0.1:8201` | `e2e/shared/stack/e2e_app.py` via uvicorn. **Not** `--reload`. |
| Frontend | `http://127.0.0.1:3201` | plain `vite dev` with an e2e config (see traps) |
| Database | `jobscraper_e2e` | separate database, same local Postgres |
| Worker | in-process | FastAPI lifespan starts both Procrastinate lanes (`src/backend/api/main.py:76-131`) |
| Browser | local headless Chromium | `CAPTURE_USE_BROWSERBASE=false` |

### `env.e2e` — the values that matter

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobscraper_e2e
CUSTOM_COMPANY_SOURCES_ENABLED=true
CUSTOM_COMPANY_DISCOVERY_ENABLED=true
CAPTURE_USE_BROWSERBASE=false        # ← the money line
BROWSERBASE_API_KEY=                 # explicitly blank, so an accidental `true` still cannot bill
BROWSERBASE_PROJECT_ID=
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}   # inherited from the shell / root .env.local
AUTH0_DOMAIN=e2e.local.test          # §4 — drives BOTH the JWKS URL and the expected issuer
AUTH0_AUDIENCE=https://job-visualizer-notifier.vercel.app/api
RESOLVE_RATE_LIMIT_MAX=100           # default is 10/60s; would bite the UI tier
INTERNAL_API_KEY=                    # must stay UNSET locally or every /api/* 401s
PORT=8201
```

### Two traps the implementation agent will hit

**Trap 1 — `vercel dev` cannot be pointed at port 8201 reliably.**
`api/utils/backendUrl.ts` honours `LOCAL_BACKEND_URL`, but root `CLAUDE.md` gotcha #3 says Vercel
Dev's cloud env vars override `.env.local` **and shell env vars** for `api/*.ts`. So use **plain
`vite dev`** with an e2e-only config that proxies `^/api` → `http://127.0.0.1:8201`.
*Honest cost of that choice:* the Vercel proxy layer (`api/users.ts`, `api/companies.ts`) is then
**not exercised**. Those proxies are thin and separately covered; say so in `CASES.md` rather than
pretending the suite covers them.

**Trap 2 — the checked-in Vite proxy does not cover `/api/companies`.**
`src/frontend/vite.config.ts:9-35` proxies only `/api/jobs`, `/api/users`, `/api/lever`, `/api/ashby`.
`POST /api/companies/resolve` would 404 under plain `vite dev`. The e2e config must proxy the whole
`/api` prefix, not a list.

### Database provisioning — `jobscraper_e2e`

The suite needs **real public company rows with real OPEN job titles**, because AC-06 compares the
discovered board's title set against every public company's (`published_board_match.py:259-292`).
An empty seed makes AC-06 vacuous.

* **Source**: `jobscraper_pr243` (131 public companies, 42,932 OPEN jobs, 724 MB). **Read-only.**
* **Method**: `pg_dump -Fc jobscraper_pr243 | pg_restore -d jobscraper_e2e`. Not `CREATE DATABASE …
  TEMPLATE` — that requires zero connections to the template and the owner's backend holds several.
* **When**: once, by `ensure_db.sh`, only if the database is absent. `--refresh` forces a re-clone.
* **Leaner alternative if the full clone is too slow**: schema-only dump + `COPY` of `companies`,
  `job_listings`, `job_freshness`, `company_scripts`. Untested — measure the full clone first.
* **After restore**: `alembic upgrade head` against the clone; the branch may carry migrations the
  dev DB is not stamped with.
* **Scrub the clone**: `TRUNCATE procrastinate_jobs`, and delete every `visibility='user'` row it
  inherited. Those nine rows are the owner's live experiments, not fixtures — two of them are wedged
  in `discovering` right now (§11.3).

**Hard guard, in `conftest.py` and in `stack_up.sh`:** refuse to start if the resolved database name
is not exactly `jobscraper_e2e`. A gate that *can* point at the owner's database once will point at
it at 2am.

---

## 3. Test tiers — and why a UI assertion for a non-UI fact is a lie

| Tier | Vehicle | What it is allowed to assert |
|---|---|---|
| **API** | pytest + `httpx` against `:8201` | status codes, response bodies, and **DB state** |
| **UI** | Playwright against `:3201` | only what a human can see: copy, chips, step ticks, dialogs |

**The rule:** if the UI does not render a fact, the UI test must not claim it.

| Fact | Visible? | Tier |
|---|---|---|
| "No discovery was enqueued" | **No** — the page shows an info notice either way | API (`procrastinate_jobs` count) |
| "The delete purged 244 job rows" | **No** — the row just disappears | API + `/api/jobs-qa/custom-company-integrity` |
| "The chip says *Successfully tracking*, not *Tracking part of this board*" | **Only** visible | UI |
| "The delete dialog warns that job history is destroyed" | copy | UI |
| "`posted_on` is NULL for every Atlassian job" | **No** | API |

---

## 4. Test-account provisioning — the risky part

**Investigated, not assumed.** Here is what is actually true.

| Fact | Evidence |
|---|---|
| All four endpoints use one dependency, `get_current_user` | `routers/user_companies.py:268,539,644`; `routers/companies.py:150` |
| It validates **RS256 against a remote JWKS** derived from `AUTH0_DOMAIN`, checking `aud` and `iss` | `api/auth/jwt.py:36,51-57` |
| **There is no dev/test bypass on the backend.** No `TESTING`, no `SKIP_AUTH`, no fake-token path | grep of `src/backend/api` outside `tests/` |
| Every endpoint hard-requires an **`email` claim** — a perfectly signed token without one is a 401 | `routers/user_companies.py:290-293` |
| `INTERNAL_API_KEY` is **not** user auth and is unset locally, so the backend is reachable directly | `api/auth/internal_key.py:33-66` |
| The frontend's signed-in state is **one localStorage key holding the raw JWT**, checked only for a future `exp` | `features/auth/GoogleCredentialContext.tsx:8,22-50` |
| `getToken()` returns that string verbatim as the `Bearer` header | `features/auth/useAuth.ts:60-62` |
| The Add Companies gate checks **only** `isAuthenticated` — no profile fetch, no user row | `pages/MyCompaniesPage/MyCompaniesPage.tsx:38,52-57` |
| `VITE_AUTH_BYPASS` exists but is **frontend-only by design** — the backend still 401s | `config/auth.ts:12-13,21` |
| Backend pytest fixtures use `dependency_overrides` — in-process only, useless against a live server | `api/tests/conftest.py:373-384` |
| **No Playwright/E2E infra exists.** `playwright` is in `package.json` but imported nowhere | `src/frontend/package.json:76` |

### The decision: mint our own RS256 token, patch one seam

`AUTH0_DOMAIN` drives **both** the JWKS URL and the expected issuer. So:

1. `shared/auth/keypair.py` generates an RSA keypair once, cached under `artifacts/`.
2. `shared/auth/mint.py` signs an RS256 token with
   `iss=https://e2e.local.test/`, `aud=<AUTH0_AUDIENCE>`, `sub=auth0|e2e-add-companies`,
   `email=e2e+add-companies@jvn.test`, `exp=now+8h`.
3. `shared/stack/e2e_app.py` imports `api.main:app` and monkeypatches
   **`api.auth.jwt._get_jwks_client`** to return that public key — the exact seam
   `api/tests/test_auth.py:99-102` already patches.
4. Playwright's `addInitScript` writes the **same token string** into
   `localStorage['jvn.googleCredential.v1']` before first paint.

**Why this shape and not something cheaper.** `jwt.decode` still runs for real — algorithm,
audience, issuer, expiry, and the `email`-claim requirement are all genuinely enforced, and
`get_or_create_user` runs unmodified. The only faked thing is where the public key came from.
One token serves both halves: the browser passes the frontend's `exp` check and the backend
accepts the same string.

**It cannot leak into production.** Prod's `AUTH0_DOMAIN` points at the real tenant, so a token
issued by `e2e.local.test` fails signature *and* issuer there. `e2e_app.py` lives under `e2e/`,
touches no production file, and is never imported by `api.main`.

**Two users, not one.** `e2e+add-companies@jvn.test` and `e2e+other@jvn.test` — the second exists
solely for AC-10 (ownership isolation).

**Do not use the Google issuer.** `validate_token` routes on `iss` (`api/auth/jwt.py:68-93`); a
Google-shaped issuer sends the token to `validate_google_token`, which checks a different JWKS and a
different audience. Use the Auth0 branch.

### Fallbacks, ranked, if the mint path fails

| # | Fallback | Cost | What it loses |
|---|---|---|---|
| 1 | Patch `api.auth.jwt.validate_token` instead of `_get_jwks_client` | ~10 lines | signature/aud/iss/exp no longer checked; the `email` requirement still is |
| 2 | Blanket `app.dependency_overrides[get_current_user]` in `e2e_app.py` | ~5 lines | the whole auth layer; **also breaks AC-10**, which needs two identities |
| 3 | One human login → Playwright `storageState` | 1 manual login | not autonomous; token expires; Auth0 refresh-token rotation may revoke on replay |

Fallback 2 is the emergency parachute. If it is used, `CASES.md` must say so **in its header** —
a suite that silently stopped testing auth is worse than one that never did.

### Risk, stated plainly

**This is the most likely thing to sink the implementation.** Three specific ways:

* **`PyJWKClient` may be constructed at import time rather than call time.** Read `api/auth/jwt.py`
  before patching; if the client is a module global built at import, the patch target is that global,
  not the factory.
* **The `email` claim on a real Auth0 access token is unverified.** The code requires it and Auth0
  does not include it by default — so either the tenant has an Action, or the Auth0 login half has
  been quietly broken and everyone signs in via Google One Tap. **This does not block us** (we mint
  the claim), but do not "fix" the requirement based on what the mint does.
* **The frontend reads the credential once at provider init.** `addInitScript` (before load) works;
  `page.evaluate` after load does not. This will present as a flaky signed-out page.

---

## 5. The case matrix

Six boards, **five different code paths**. Naming them is half the point.

| ID | Board / subject | Path exercised | Tier | Haiku call? | Expected |
|---|---|---|---|---|---|
| **AC-01** | Microsoft `jobs.careers.microsoft.com/global/en/search` | host-match → `already_public`; **nothing created, nothing enqueued** | API + UI | **No** | 🟢 (was red 4 h ago — §11.1) |
| **AC-02** | Amazon `www.amazon.jobs/en/search` | same | API | **No** | 🟢 (same) |
| **AC-03** | Cisco `jobs.cisco.com/jobs/SearchJobs/` | ATS resolver (**embedded** Workday) → probe → preview → explicit **Track this company** → first harvest | API + UI | **No** | 🟢 |
| **AC-04** | Atlassian `www.atlassian.com/company/careers/all-jobs` | no ATS → one-time discovery → 5-step checklist → first harvest. **No posted date.** | API | **Yes** | 🟢 |
| **AC-05** | Jane Street `www.janestreet.com/join-jane-street/open-roles/` | same as AC-04; payload has **no date field at all** | API | **Yes** | 🟢 |
| **AC-06** | Spotify `www.lifeatspotify.com/jobs` | discovery → first harvest → **title-overlap suggestion (Unit 10)**, and **never merges** | API + UI | **Yes** | 🔴 red today (§11.2) |
| **AC-06a** | seeded rows | the same matcher, deterministic and offline | API | No | 🟢 |
| **AC-07** | any tracked row | **delete → full purge** (company, script, jobs, harvests, runs) | API + UI | No | 🟢 |
| **AC-08** | AC-03 board | the **human journey**, end to end in a browser | UI | No | 🟢 |
| **AC-09** | flags | sources flag off → 503; discovery flag off → 422, nothing started | API | No | 🟢 |
| **AC-10** | two users | user B cannot list, read jobs from, or delete user A's company | API | No | 🟢 |
| **AC-11** | AC-04 board | **idempotent re-add** returns the existing row and spends nothing | API | **No** (that *is* the assertion) | 🟢 |
| **AC-12** | AC-01 board | `Track it separately anyway` → a private copy IS created | API + UI | Yes | 🟢 once AC-01 lands |

**Rate-limit note:** `POST /api/companies/resolve` is capped at 10/60s per user
(`services/rate_limit.py:104-107`). `POST /api/users/companies` runs its own resolve and is **not**
capped — so the API tier is unaffected. Only the UI tier calls `resolve`, and `env.e2e` raises the cap.

### Per-case detail

Every case has the same five parts: what it tests · preconditions · steps · assertions · cleanup.
`CASES.md` is this section expanded into the skill's contract.

---

#### AC-01 / AC-02 — a board we already publish is linked, not discovered

* **Tests**: the careers-host matcher (`services/careers_host_match.py`) short-circuits an
  `ats='script'` board **before** anything is created or spent.
* **Preconditions**: both flags on; `microsoft` and `amazon` rows present, `visibility='public'`,
  `enabled=true` (verified present in the dev DB); the test user owns nothing.
* **Steps**: `POST /api/users/companies {url}`.
* **Assertions** — the negative ones are the point:

  | # | Assertion | Where |
  |---|---|---|
  | 1 | `200` with `{status:'already_public', companyId:'microsoft', displayName:'Microsoft'}` | response |
  | 2 | **No new `companies` row** (`visibility='user'` count unchanged) | DB |
  | 3 | **No new `user_companies` row** | DB |
  | 4 | **No `procrastinate_jobs` row on `custom_discovery`** created by this call | DB |
  | 5 | `company_add_attempts` gains exactly one row: `outcome='already_public'`, `company_id='microsoft'`, **`resolved_ats='script'`** (that field is how the audit records *which half* of the dedupe answered) | DB |
  | 6 | `[data-testid=already-public]` renders, title `We already track Microsoft` | UI |
  | 7 | `[data-testid=track-anyway-button]` is present (the escape hatch survives) | UI |
  | 8 | a user who already owns a private copy (via AC-12) gets **their row back**, not the public notice — the `owned is None` guard | DB |
* **Cleanup**: none needed — nothing was created. **Assert that**, don't assume it.

---

#### AC-03 — the ATS path, with an explicit confirm

* **Tests**: resolve → probe → preview → **user consent** → create → immediate first harvest.
  Cisco resolves as an **embedded** Workday board (`tenant_slug=cisco`,
  `career_site_slug=Cisco_Careers` — confirmed against the dev DB), so it covers the embedded-detection
  branch, not just a bare ATS URL.
* **Steps (API)**: `POST /api/companies/resolve` → assert candidate → `POST /api/users/companies`.
* **Steps (UI)**: fill `getByLabel('Careers page URL')` → click `Add company` → wait for
  `[data-testid=resolve-headline]` → click `[data-testid=add-company-button]`.
* **Assertions**:

  | # | Assertion | Where |
  |---|---|---|
  | 1 | resolve returns `ats='workday'`, `boardToken='cisco'`, `jobCount > 0` | response |
  | 2 | headline matches `/^Found [\d,]+ open jobs on Workday$/` | UI |
  | 3 | **nothing exists in the DB between resolve and the confirm click** | DB |
  | 4 | add returns `201`; `companies` row `visibility='user'`, `health_state='unverified'` | DB |
  | 5 | `company_scripts` row `transport='ats_client'`, `oracle_kind='declared_probed'` | DB |
  | 6 | a `fetch_custom_company` job lands on **`custom_ats_first_fetch`** (interactive lane), not `custom_ats_fetch` | DB |
  | 7 | within budget: `open_job_count > 0`, `last_success_at` set | API |
  | 8 | Cisco jobs **do** carry `posted_on` — ~~measured 1246/1246~~ **CORRECTION (build-time measurement): 822 of 1214, ~68% — not 100%.** Confirmed via the backend log that this is Workday genuinely omitting `postedOn` for a real subset of Cisco's postings, not a parse failure (zero "unparseable postedOn" warnings). The shipped assertion is therefore `> 0`, not `== total`: asserting 100% would be asserting a live third party's data completeness, which §6/§13 already warn against for job counts. See `CASES.md` → "Where PLAN.md was wrong". | DB |
  | 9 | chip reads `Successfully tracking` | UI |
* **Cleanup**: AC-07.

---

#### AC-04 / AC-05 — one-time discovery, and boards with no posted date

* **Tests**: the whole capture pipeline — browser, one Haiku call, recipe synthesis, acceptance
  replay — plus the five-step checklist and the first harvest that closes step five.
* **Preconditions**: `CUSTOM_COMPANY_DISCOVERY_ENABLED=true`, `CAPTURE_USE_BROWSERBASE=false`, a live
  `ANTHROPIC_API_KEY`, the board reachable at pre-flight (§6).
* **Steps**: `POST /api/users/companies {url}` → expect `202 discovery_pending` → poll
  `GET /api/users/companies` until the row settles or the budget expires.
* **Assertions**:

  | # | Assertion | Where |
  |---|---|---|
  | 1 | `202` with `{status:'discovery_pending', id, finalUrl}` | response |
  | 2 | a provisional row exists **immediately**: `health_state='discovering'`, `enabled=false` | DB |
  | 3 | exactly **one** `custom_discovery` job, queueing lock `discover:{user_id}:{url}` | DB |
  | 4 | the row settles to `discovery.outcome='tracking'`, `health_state='unverified'` | API |
  | 5 | all five steps reach a terminal state; keys exactly `open_page`, `find_feed`, `verify_read`, `ready`, `first_scan` | API |
  | 6 | `company_scripts.transport='http_json'` | DB |
  | 7 | `open_job_count > 0` after the first harvest | API |
  | 8 | **`posted_on IS NULL` for every harvested job** — measured today: Atlassian 0 of 244, Jane Street 0 of 235 | DB |
  | 9 | `first_seen_at` is set for every job (it falls back to first sight) | DB |
  | 10 | Jane Street's mapped fields come from `{position, team, city, …}`; the payload has **no date key at all**, so #8 is correctness, not a gap | DB |
* **Cleanup**: AC-07.
* **Not asserted, deliberately**: the exact job count. Live boards drift. Assert `> 0` plus a loose
  sanity band (Atlassian ~250, Jane Street ~235 at last measure) and **report the actual number** in
  the run summary, so drift is visible without being fatal.

---

#### AC-06 — the title-overlap suggestion, and the guarantee that it never merges

**The only case that exercises Unit 10, and the only one that can prove the no-merge guarantee.**

* **Tests**: after a discovered board's first harvest, `published_board_match` compares its OPEN title
  set against every public company's and stores a **suggestion** — writing nothing else, ever.
* **Preconditions**: the e2e DB carries the real public `spotify` row with its OPEN titles.
  *This is why §2 clones rather than seeds.*
* **Steps**: as AC-04, with `https://www.lifeatspotify.com/jobs`, then wait for the first harvest.
* **Assertions**:

  | # | Assertion | Where |
  |---|---|---|
  | 1 | `companies.provider_config -> 'public_match'` exists on the new row | DB |
  | 2 | it names `companyId='spotify'`, `shared >= 20`, `shared / max(both sets) >= 0.70` | DB |
  | 3 | **`job_listings` for `company='spotify'` is identical before and after** (count + title-set checksum) | DB |
  | 4 | the new company's `visibility`, `ats`, `board_token` and its `user_companies` row are unchanged — **nothing was merged into anything** | DB |
  | 5 | banner `[data-testid=public-board-match]`, title `This looks like Spotify, which we already track` | UI |
  | 6 | the banner offers **link / Delete this board / Dismiss** — and **no accept-merge control exists anywhere in the DOM** | UI |
  | 7 | `Dismiss` sets `localStorage['publicBoardMatch:{companyId}:spotify:dismissed']` and the banner does not return on reload | UI |
* **Measured, for calibration.** Calling `find_published_match()` read-only against the dev DB's
  existing `lifeatspotify` row returns
  `BoardOverlap(company_id='spotify', shared=70, candidate_titles=79, matched_titles=80, ratio=0.875)`.
  **The matcher works. The pipeline never calls it.** See §11.2.
* **Cleanup**: AC-07 — **plus** clear the dismissal localStorage key, which survives a DB purge.

#### AC-06a — the same guarantee, deterministic and free

Seed a private company plus a copy of Spotify's OPEN title set directly, then call
`find_published_match` / `suggest_published_board`. Assert it qualifies, that the **only** write is the
suggestion blob, and that a 25-of-1,742 subset shape (the documented false-positive class) does **not**
qualify. No network, no browser, no LLM. This keeps the no-merge guarantee under test on days the live
path is red — and it is the case that stays green while AC-06 is red.

---

#### AC-07 — delete means gone, and the state is clean enough to re-add by hand

The owner's stated shape: *add a company, then delete it, leaving the state clean so he can add it
himself immediately afterwards.*

* **Tests**: `remove_owned_company` (`custom_companies_service.py:1023`) — the last owner leaving
  **purges** the company, its script, **every job row in its `custom:<id>` namespace**, its
  freshness / location / enrichment sidecars, its harvests and its scrape runs. One transaction.
* **Steps (UI)**: click the row's `[data-testid=my-company-remove]` (a text button labelled `Remove`)
  → confirm `[data-testid=my-company-remove-confirm]` (labelled `Delete`).
* **Assertions**:

  | # | Assertion | Where |
  |---|---|---|
  | 1 | dialog title reads `Delete this company and its job history?` | UI |
  | 2 | the body names the destruction — it must not read as a pause | UI |
  | 3 | `204`; the row is gone from `GET /api/users/companies` | API |
  | 4 | `companies`, `company_scripts`, `user_companies` rows all gone | DB |
  | 5 | **`job_listings WHERE source_id='custom:<id>'` is zero** | DB |
  | 6 | `/api/jobs-qa/custom-company-integrity` → `ownerlessCount` **unchanged from the pre-run baseline** | API |
  | 7 | re-adding the same URL immediately afterwards starts a **fresh** flow (new id, new discovery) — the owner's actual next action | API |
* **Baseline caution**: `ownerlessCount` was **1** in the dev DB when this was written
  (`u-6hkpc6fh0z`, then 10,020 orphan jobs — 12,437 by the time it was collected). It is **0**
  now: `_scrub.py` removes inherited `visibility='user'` rows from the clone, and
  `api.tasks.reap_ownerless_companies` collected the source row in `jobscraper_pr243`. **Assert
  the delta anyway** — the reaper is allowed to change this number mid-run, so an absolute
  assertion would be racing it.
* **UI timing note**: `confirmRemoval` closes the dialog **optimistically**, before the DELETE
  resolves (`MyCompaniesList.tsx:255-260`). Wait for the row to leave the list, not for the dialog to close.

---

#### AC-08 — the human journey (Playwright)

One spec, one board (Cisco), no shortcuts:

load `/add-companies` signed in → paste → `Add company` → preview → `Track this company` → the row
appears with a blue `Fetching all current jobs…` chip → it becomes green `Successfully tracking` with a
non-zero count → `Remove` → confirm → the list reads `No companies yet`.

This is the case that would have caught "you're just broken". Everything else is a component of it.

**Polling trap:** a fully-settled list **stops polling** (`pollIntervalFor`, `MyCompaniesList.tsx:110-118`
returns 0). Waiting on a settled list waits forever unless a mutation invalidates the `MyCompanies` tag.
Use `expect.poll` with an explicit `page.reload()`, not a bare `waitFor`.

---

#### AC-09 / AC-10 / AC-11 / AC-12 — the cross-cutting four

| ID | Assertion core |
|---|---|
| **AC-09** | `CUSTOM_COMPANY_SOURCES_ENABLED=false` → every route 503. Discovery flag off + a non-ATS URL → **422 `unsupported`**, no placeholder row, no queue job, **no Haiku call**. Needs a second short-lived backend on another port with the flags flipped. |
| **AC-10** | User B's `GET /api/users/companies` omits A's rows; `GET /api/users/companies/{A}/jobs` → 403; `DELETE {A}` → 404 **and A's row still exists**. |
| **AC-11** | Re-adding an already-discovered URL returns **200 with the existing id**, creates no second row, enqueues **no** `custom_discovery` job. This is the "a typo must never cost an LLM call" guarantee. |
| **AC-12** | `{url, trackAnyway:true}` on the AC-01 board **does** create a private row. Proves the escape hatch survives the dedupe. |

---

## 6. Deterministic vs live

| Case | Hermetic today? | Why |
|---|---|---|
| AC-01, AC-02 | **Almost** — needs one live resolve to reach `final_url`; mockable via the `_http_client` seam | the host table itself is pure and IO-free |
| AC-03 | **No** — Cisco's Workday must answer | the probe count comes off the live board |
| AC-04, AC-05, AC-06 | **No** — real Chromium, real Haiku, real board | this *is* the feature |
| AC-06a | **Yes** | `find_published_match` is read-only and callable directly |
| AC-07, AC-10, AC-11 | **Yes** — operate on rows a prior case created, or on seeded rows | pure DB/API |
| AC-09 | **Yes** | flags only |

**Hermetic replay of discovery is possible but is not designed.** `TESTABLE-BOARDS.md` records captures
being replayed from disk for the 2026-08-22 re-measurement, and `network_capture` drives its Chromium
out of process — so a fixture seam exists in principle. **Do not build it in this pass.** Note it as the
follow-up that would make AC-04/05/06 free, and be aware of the trap: a replay suite tests the fixture,
not the board.

### When a live board is down — a third-party outage must not read as our regression

Three-state outcome. **This is not optional polish; it is what makes the gate trustworthy.**

| State | Exit code | Meaning |
|---|---|---|
| `PASS` | 0 | the case ran and its assertions held |
| `FAIL` | 1 | **our** behaviour is wrong |
| `BLOCKED` | 2 | the case could not run — the board, the network, or the LLM was unavailable |

`preflight.py` probes all six board URLs before any case runs. A board that is unreachable, 403s a bot
wall, or times out is marked BLOCKED up front and its cases are **skipped, not failed**.

During a run these reasons demote FAIL → BLOCKED: DNS failure, connection refused/reset, HTTP 5xx from
the board, a capture timeout with **zero** JSON requests recorded, and any Anthropic API error.

A discovery **refusal** is different: the ladder ran and answered "no readable feed". For a board on
this list that is a real FAIL — all six were measured tracking.

---

## 7. Cost and runtime budget

### Cost

| Item | Per run |
|---|---|
| Haiku calls | **3 boards × 1–2 selection rounds** (`_MAX_SELECTION_ROUNDS = 2`, `capture/discover.py:274`) |
| Model | `claude-haiku-4-5-20251001` (`capture/request_selector.py:59`) |
| Browserbase | **$0 — forced off.** Blank `BROWSERBASE_API_KEY` is the second lock |
| Everything else | $0 |

**Do not carry a dollar figure forward from this document.** The Anthropic response carries a `usage`
block — have the run log input/output tokens per call and print the total in the summary. After the
first real run the budget is a *measured* number, and the gate can fail if it exceeds it. That number
belongs in `CASES.md`, filled in by the implementing agent.

### Runtime

| Phase | Budget |
|---|---|
| Pre-flight (6 probes) | ~10 s |
| Stack up (backend boot + migrations + vite) | ~30 s |
| AC-01, AC-02, AC-06a, AC-09–AC-12 | ~60 s total |
| AC-03 Cisco (resolve + probe + harvest ~1.2k jobs — 1,214 measured at build time) | 1–3 min |
| AC-04, AC-05, AC-06 discovery | 27–46 s each, measured (`TESTABLE-BOARDS.md`; the 24 s observation window is the floor, so nothing finishes fast) |
| Their first harvests | ~30–60 s each |
| AC-07, AC-08 UI | ~90 s |
| **Total** | **8–14 min** |

**A 40-minute gate is not a gate.** Two profiles:

* `--fast` (~2 min, $0): no browser capture, no LLM, no live-board *wait*. Run this on every commit.

  **CORRECTION (build-time):** the sentence that used to stand here — "everything except
  AC-03/04/05/06" — contradicts the runtime table directly above it, which puts AC-11/AC-12
  in the same ~60s hermetic bucket even though both spend an LLM call. As shipped, `--fast`
  is `pytest -m "not live"` plus skipping the UI tier entirely, and `live` marks anything
  that **waits on an async harvest or discovery to complete** — so the real exclusion list is
  **AC-03/04/05/06/07/11/12 and all three UI specs**. What stays in `--fast`: AC-01, AC-02,
  AC-06a, AC-09, AC-10. See `CASES.md` → "The `--fast` / `live` split" for the reasoning and
  the marker's own docstring in `api/conftest.py`.
* full (8–14 min): the **required** gate before "ready to test".

---

## 8. Cleanup and idempotency

**Re-runnable back-to-back with no manual reset, and it must not touch the owner's data.**

Four layers, in order:

1. **Separate database.** `jobscraper_e2e`, hard-guarded on the exact name (§2).
2. **Separate users.** Everything is scoped to `e2e+*@jvn.test`. No cleanup query ever matches on
   anything but those user ids.
3. **Per-case teardown *is* the product's own delete path.** `DELETE /api/users/companies/{id}`.
   Deliberate: AC-07 is the cleanup, so cleanup running is itself a test.
4. **Pre-run and post-run sweep.** `reset_user.py` calls `remove_owned_company` for every company the
   test users own, then asserts zero remain. It runs **before** the suite too — a run killed at Ctrl-C
   must not poison the next one.

**Two things the sweep must handle that a naive one will not:**

* A row stuck in `health_state='discovering'` with a job still on `custom_discovery`. Delete the row
  **and** the queue job, or the next run's worker resurrects a discovery against a company that no
  longer exists.
* The dismissal key `publicBoardMatch:{companyId}:{matchedCompanyId}:dismissed` lives in
  **localStorage**, not the database (`publicMatchDismissal.ts:3`), and is read **once on mount**.
  Playwright must clear origin storage in `beforeEach`, or AC-06's banner assertion passes on run 1 and
  fails on run 2.

**`remove_owned_company` deletes job rows.** Correct and intended — but it means a mis-scoped cleanup is
destructive, not merely untidy. Every cleanup statement goes through `remove_owned_company`, which is
scoped by `(user_id, company_id)` and refuses non-`visibility='user'` rows
(`custom_companies_service.py:1092-1098`).
**No hand-written `DELETE FROM job_listings` anywhere in this suite.**

---

## 9. The skill's shape

```
.claude/skills/e2e-gate/
├── SKILL.md                       # the gate: when to run, how to run, how to read the verdict
└── sections/
    └── add-companies.md           # this section's runbook + the case table
```

**`SKILL.md` instructs (it does not automate):**

* **When** — before any message containing "ready to test", and before opening a PR that touches
  `routers/user_companies.py`, `services/custom_companies_service.py`, `services/capture/**`,
  `services/careers_host_match.py`, `services/published_board_match.py`,
  `tasks/discover_custom_company.py`, `tasks/fetch_custom_company.py`, or
  `src/frontend/src/components/my-companies/**`.
* **What green means** — and that `BLOCKED` is **not** green.
* **What to do with a red** — read the failing case's artifact directory *before* changing code.

**It automates: one command.**

```bash
e2e/run.sh add-companies              # full gate
e2e/run.sh add-companies --fast       # the cheap subset
e2e/run.sh add-companies --case AC-06 # one case, for a fix loop
```

`run.sh` does stack-up → pre-flight → pytest → playwright → stack-down → summary, and **always tears
the stack down**, including on failure and on Ctrl-C.

**Invocation:** `/e2e-gate add-companies`, or the agent loads the skill when it is about to claim
something is ready.

**Section files carry the per-case instructions** the owner asked for — the "sub-skills". Each case's
entry says what it proves, how to run just it, its known-red status, and what to look at first when it
goes red.

---

## 10. How it fails usefully

A red X with no evidence does not survive contact with a real failure.

**Every run writes `e2e/add-companies/artifacts/<UTC timestamp>/`:**

```
summary.md            # human-first: one line per case — PASS/FAIL/BLOCKED, duration, the numbers
summary.json          # same content, machine-readable
stack/
  backend.log         # the e2e uvicorn + worker log for the whole run
  frontend.log
cases/AC-06/
  step.txt            # the exact step that failed, in words
  request.http        # request sent + response received, headers and body
  db-before.json      # the DB predicates this case asserts, before
  db-after.json       # ...and after, so the diff IS the evidence
  discovery.json      # the full discovery.steps + network blob off the list payload
  screenshot.png      # UI cases only, at the moment of failure
  trace.zip           # UI cases only, Playwright trace — retained on failure only
```

**Rules that make this actually useful:**

* **Name the step, not the assertion.** `AssertionError: False is not True` is useless. Write:
  `AC-06 FAILED at "wait for public_match": row settled to outcome=tracking, health=unverified,
  tracking_started_at=NULL after 180s — the board never graduated, so Unit 10 never ran.`
* **Dump the DB predicates on failure, always.** A before/after JSON pair of exactly the rows the case
  cares about turns "it broke" into "here is what changed".
* **Screenshots and traces on failure only.** A green run leaves `summary.md` and the two stack logs and
  nothing else — an artifacts directory nobody prunes stops being read.
* **`summary.md` carries the drift numbers even when green**: jobs harvested per board, discovery
  seconds, Haiku tokens. A board sliding from 250 jobs to 12 is a warning long before it is a failure.

---

## 11. What I found broken while planning

Three findings, all verified against the running stack and the current code. **One of them means AC-06
ships red** — that is the suite doing its job on day one, so do not weaken it. One was **fixed under me
mid-session** (§11.1) and is the reason §13 says to write assertions against intended behaviour.

### 11.1 The careers-host match was broken, and was fixed *while this plan was being written*

**Read this as a warning about the tree, not as an open defect.**

When I started, `services/careers_host_match.py` and
`custom_companies_service.find_public_company_for_careers_url` existed on disk but
**`routers/user_companies.py` never called them.** Live proof from `company_add_attempts` in the dev
DB, timestamped **today 23:03–23:05 UTC**:

| submitted_url | outcome |
|---|---|
| `https://jobs.careers.microsoft.com/global/en/search` | `discovery_pending` |
| `https://www.amazon.jobs/en/search` | `discovery_pending` |

Both started a discovery. Two rows are still sitting in `health_state='discovering'` with their jobs
stuck in `custom_discovery` `todo` — that is the wreckage of the bug, and `ensure_db.sh` scrubs it.

**It is now wired**, at `routers/user_companies.py:372`, inside the `result.candidate is None` branch:
after the `owned` idempotency lookup, guarded by `owned is None and not payload.track_anyway`, and
**before** the `custom_company_discovery_enabled` gate — so a published board costs nothing even with
discovery on. Both `payload.url` and `result.final_url` are checked.

**What this means for the suite:** AC-01/AC-02 are now expected **green**. Assert the *behaviour*, and
`resolved_ats='script'` in the audit row (the router records the sentinel, not the public row's ats).
**Verify it against the live endpoint before believing it** — this fix has not been exercised end to
end, only written.

**The wider lesson, and it applies to the whole build:** this tree moved three times in one planning
session. Write every assertion against **intended behaviour**, never against a snapshot of today's
bug, or the suite needs editing every time a sibling lands.

### 11.2 Unit 10 can never fire for the case it was built for

`published_board_match.suggest_published_board` is called **only when `graduated_this_run` is true**
(`tasks/fetch_custom_company.py:1082-1085`), and `graduated_this_run = is_first_verified` is set only inside
`if verdict == VERIFIED` (`:840-845`).

A board discovered as "whole board in one request" gets `oracle_kind='none'`, and `verify_harvest`
returns `UNVERIFIED, "no_oracle"` for it unconditionally (`services/harvest_verification.py:221-225`).
**It can never be VERIFIED → it can never graduate → Unit 10 never runs.**

That describes `lifeatspotify.com` — the exact case the module's own docstring opens with — plus
Atlassian, Jane Street, SpaceX and Rockstar.

Measured against the dev DB, on the row the owner added today:

| Fact | Value |
|---|---|
| `u-ibr09efe5d` "Lifeatspotify" — `oracle_kind` | `none` |
| `tracking_started_at` | `NULL` — never graduated |
| `last_success_at` | set — it **has** harvested, 87 open jobs |
| `provider_config ? 'public_match'` | **false** — no suggestion stored |
| `find_published_match()` called directly, read-only | **`spotify`, 70 shared of 79, ratio 0.875 — qualifies** |

So the matcher is right and the trigger is wrong.

The plausible fix is to trigger the check on the **first successful harvest** rather than the first
VERIFIED one: a completed `http_json` recipe read of a whole-board-in-one-request feed *is* a complete
title set, which is the property the docstring actually argues for. VERIFIED is a stronger claim, about
*closing* jobs. **That is a judgement for the owner, not for the test suite** — AC-06 asserts the
outcome and stays red until it is decided.

### 11.3 Local worker is dead, and the docs disagree with the code in two places

* `GET /health/worker` on `:8100` reports `heartbeat_gap_seconds: 52793` (**14.7 h**) against a 600 s
  threshold. Two `custom_discovery` jobs are stuck in `todo`; twelve `workday_fetch` and several others
  are stuck in `doing` (a killed worker leaves those — Procrastinate does not requeue them).
  Consistent with the sibling agent's in-flight fix, so **not a new finding** — but it is why nothing has
  drained. The e2e stack sidesteps it by running its own worker.
  *(The reserved interactive lane HAS landed: `_INTERACTIVE_QUEUES` = `custom_discovery`,
  `custom_ats_first_fetch`, `interactive_heartbeat` at `main.py:100-115`. AC-03 assertion #6 depends on it.)*
* **`src/frontend/CLAUDE.md:173-175` says "Discovery has its own server flag" and `:190-193` says
  "Two independent flags."** The code says **one**: `routers/user_companies.py:328-336` —
  *"It is one flag rather than the retired pair."* **Code wins.** The doc is stale, and so is
  `MEMORY.md`'s note that already supersedes it.
* **`src/frontend/CLAUDE.md:186-189` says the dedupe cannot catch `ats='script'` boards.**
  As of 11.1 the mechanism exists to catch them; only the wiring is missing. That doc line and
  `custom_companies_service.py:100-103` (already updated) disagree until the router lands.

---

## 12. Build order

Sequential. Each step is verifiable on its own; do not start the next until the current one is proven.

| # | Step | Done when |
|---|---|---|
| 1 | `shared/db/ensure_db.sh` — clone `jobscraper_pr243` → `jobscraper_e2e`, `alembic upgrade head`, scrub | `select count(*) from companies where visibility='public'` returns 131 and `visibility='user'` returns 0 |
| 2 | `shared/auth/` — keypair + mint | a minted token decodes with the right `iss` / `aud` / `email` |
| 3 | `shared/stack/e2e_app.py` + `stack_up.sh` | `curl :8201/health` → `OK`, **and** `GET /api/users/companies` with a minted token returns `{"companies":[]}` — **this is the gate on §4's risk** |
| 4 | `vite.e2e.config.ts` + the frontend half of `stack_up.sh` | `:3201/add-companies` renders signed-in after `addInitScript` |
| 5 | AC-09, AC-10, AC-11, AC-06a (cheap, hermetic) | green |
| 6 | AC-07 + `reset_user.py` | a hand-created company is purged; `ownerlessCount` delta 0 |
| 7 | AC-01, AC-02 | green — but **verify against the live endpoint**; the fix (§11.1) has never been run end to end |
| 8 | AC-03 Cisco | green |
| 9 | AC-04, AC-05 | green, with measured runtime + token counts written into `CASES.md` |
| 10 | AC-06 (live) | **red, carrying the §11.2 message** |
| 11 | AC-08 UI journey | green |
| 12 | `run.sh`, the `summary.md` writer, the artifact layout | a **forced** failure produces a directory an operator can act on without re-running |
| 13 | `.claude/skills/e2e-gate/` | `/e2e-gate add-companies` runs the whole thing |

---

## 13. Risk register — where I am least sure

| Risk | Likelihood | Impact | What to do about it |
|---|---|---|---|
| **The JWKS patch seam is not where I think it is** | Medium | Blocks everything | Step 3 is the checkpoint. If `PyJWKClient` is a module global built at import, patch the global. If that fails, take fallback 1 (§4) and say so in `CASES.md`. |
| **Cloning a 724 MB database is slower than tolerable** | Medium | Slows setup, not the gate | Measure it. If > 5 min, drop to schema-only + a four-table `COPY`. Only AC-06 needs real public jobs. |
| **Sibling work lands under the suite mid-build** | High | Case churn | `boards.py` is the single source of board truth. The §11.1 wiring will flip AC-01/02 green **with no test change** if assertions are written against intended **behaviour**, not against today's bug. |
| **Live boards drift** | Certain, over weeks | False reds | Assert `> 0` + a loose band; report exact counts. Never assert an exact job count. |
| **Discovery is genuinely flaky at the tails** | Medium | Intermittent red | The 24 s observation window is a floor, not a timeout. Budget 240 s per discovery (matching `_TASK_TIMEOUT_S`) and demote a zero-JSON-request capture to BLOCKED. |
| **`vercel dev` vs `vite dev` divergence** | Low | A proxy bug ships unseen | Stated as explicit non-coverage in `CASES.md`. The proxies are thin. |
| **The frontend reads the credential once at init** | Medium | Looks like flaky sign-out | `addInitScript` only. Never `page.evaluate` after load. |
| **A settled list stops polling** | Certain | UI test hangs to timeout | `expect.poll` + explicit `page.reload()`, never a bare `waitFor`. |
| **`ownerlessCount` baseline is not 0** | ~~Certain in the dev DB~~ — now 0 (scrub + the ownerless reaper) | Permanent false red | Scrub the clone, and assert the delta regardless: the reaper may move the number mid-run. |
| **A published dollar cost would be a guess** | Certain | Wrong budget | Measure it from the `usage` block on the first real run. |
| **Two `discovering` rows + stuck queue jobs exist in the dev DB right now** | Certain | The clone inherits them | `ensure_db.sh` truncates `procrastinate_jobs` and deletes inherited `visibility='user'` rows. |

---

## 14. What I decided without asking

Listed because a different call was defensible in each.

1. **The suite runs its own backend, worker and frontend** rather than reusing `:8100` / `:3000`.
   Forced by `CAPTURE_USE_BROWSERBASE=true` in the owner's `.env.local` and by "don't kill either server".
2. **A cloned database, not the owner's.** "Treat that database as read-only" was explicit. The clone is
   the only way to keep that promise *and* have real public titles for AC-06.
3. **Mint a real RS256 token rather than blanket-override the auth dependency.** More work; it keeps the
   auth layer under test and keeps AC-10 possible at all.
4. **Plain `vite dev`, not `vercel dev`.** Avoids a documented env-var trap at the cost of not exercising
   two thin proxies. Recorded as non-coverage.
5. **AC-06 ships red.** It encodes intended behaviour, not current behaviour. Weakening it to green
   would be the exact failure this suite exists to prevent. AC-01/AC-02 were written the same way and
   turned green on their own when the fix landed (§11.1) — which is the argument for the practice.
6. **No hermetic replay of discovery in this pass.** It is the right follow-up; building it now would
   delay the gate and risks testing the fixture instead of the feature.
7. **AC-06a was added** (not in the brief). Without it, the no-merge guarantee has no test at all on any
   day the live path is red — which, per §11.2, is every day right now.
