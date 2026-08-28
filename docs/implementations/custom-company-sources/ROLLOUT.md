# E7 rollout — merge order, flags, verification, rollback

The plan is the owner's: **merge one PR at a time with the feature flags off, confirm
each deploy is healthy, then flip the flag.** This file is the operational detail.

Written 2026-08-28. If you are reading this after the rollout, it is history — check
`git log` before trusting any "current state" claim below.

---

## 1. The one thing that makes this non-trivial

Flags make the **feature** dark. They do **not** make the **deploy** inert.

PR #248 carries changes that are behind no flag and take effect the moment it ships.
The owner has explicitly accepted these staying in that PR rather than being split out:

| Change | Blast radius | Rollback |
|---|---|---|
| `first_seen_at` seeded from the board's posted date | **Every company.** Changes the column the charts sort on and the enrichment queue orders by | revert |
| Workday `"Posted 30+ Days Ago"` → no date | **2,730 of 6,461 open Workday rows** lose a fabricated date | revert |
| `department` denormalized column + backfill | ~5–15 s `ACCESS EXCLUSIVE` on `job_listings` (78k rows) during migration | revert + drop column |
| `job_freshness` trigger seeds `now()` | Required by the seeding change; makes brand-new jobs not born stale | revert |
| Worker lane split + per-lane heartbeats | Two workers instead of one; `/health/worker` now 503s if **either** lane is stale | revert |
| Vercel proxy allowlists | Closes a live anonymous-access hole. **You want this one live** | revert (do not) |

**So "flags off" is not "no change".** Section 5 verifies these specifically.

---

## 2. Merge order

The stack is three deep. Each must be merged and healthy before the next.

```
main
 └─ #243  feat/custom-company-sources-spike     E7 Phase 1 — private ATS companies, never-close gate
     └─ #247  feat/e7-phase2-gate-oracles       verification gate + ATS oracles
         └─ #248  feat/e7-phase3-discovery      capture/recipe engine + everything from 08-26/27
```

**Do not squash-merge #243 or #247 without checking the trailers** — ten pre-existing
commits carry `Co-Authored-By: Claude Fable 5`, which the owner does not want in `main`.

---

## 3. Migrations

Production is stamped `1d2d6c17acfc`. Merging the full stack runs **six**:

| # | Revision | What | Risk |
|---|---|---|---|
| 1 | `fb8467065dfc` | E7 Phase 1 schema — 4 tables, 7 `companies` cols, 2 `scrape_runs` cols | Catalog-only on PG 17.9. **No table rewrite** — matters, `scrape_runs` is 634k rows |
| 2 | `c4f0a91b2d73` | Data: raise legacy page budgets | **0 rows** — table created empty one step earlier |
| 3 | `9d2f7ae5c1b4` | Data: retire flat page ceiling | **0 rows** |
| 4 | `2633dd6348e4` | Empty merge revision | none |
| 5 | `7a4c1e93b6d8` | `job_freshness` trigger seeds `now()` | `CREATE OR REPLACE FUNCTION`. Verified byte-identical against the live function |
| 6 | `c1539fa03b23` | `department` column + backfill | **The only lock.** ~5–15 s `ACCESS EXCLUSIVE` on `job_listings` |
| 7 | `b4d17c2a9e51` | `lane` column on `worker_heartbeats` | trivial |

Migration 6 runs the backfill **inside the same transaction as the ADD COLUMN** — deliberately.
Splitting it was tried and **silently broke Alembic**: a mid-revision `conn.commit()` makes the
version-table UPDATE a no-op, leaving the data migrated and `alembic_version` unmoved. If the
lock window ever becomes unacceptable, the answer is a separate one-shot script, not a
cleverer migration.

`migrations.py` calls `command.upgrade(cfg, "head")` — **singular**. A second head does not
degrade, it fails the boot. Confirm `alembic heads` returns exactly one before each merge.

---

## 4. Flags — where they live and what they do

**Backend (Railway, `Job-Visualizer-Notifier`, production env). Runtime — a change redeploys.**

| Flag | Code default | Effect when off |
|---|---|---|
| `CUSTOM_COMPANY_SOURCES_ENABLED` | `False` | Every `/api/users/companies` route returns **503** |
| `CUSTOM_COMPANY_DISCOVERY_ENABLED` | `False` | Free ATS path works; a non-ATS URL returns **422**, spends nothing |
| `CAPTURE_USE_BROWSERBASE` | `False` | Discovery uses our own Chromium. **Costs money when on** |
| `CUSTOM_COMPANY_MONTHLY_ADD_LIMIT` | `20` | `0` = unlimited. **Fail-closed:** a typo'd name keeps the default, so the limit stays ON |

**Frontend (Vercel, `VITE_*`). BUILD-TIME — a change requires a REDEPLOY, not just an env edit.**

| Flag | Effect when off |
|---|---|
| `VITE_CUSTOM_COMPANIES_ENABLED` | No nav entry, **no route registered at all**, zero network calls |
| `VITE_DISCOVERY_PROGRESS_ENABLED` | Bare "Setting up…" badge instead of the checklist. Nested under the flag above |

⚠️ **The frontend flag is the stronger gate** — with it off the page does not exist, so nothing
can reach the backend even if the backend flag is on. Flip the backend first, frontend second.

⚠️ **Reading Railway variables is blocked** by the permission classifier (values return in
plaintext and may contain secrets). Setting them is possible. So **verify flag state by
behaviour, not by reading config** — see §6.

---

## 5. Per-merge verification

### After #243 and after #247

Both are schema + gated code. Confirm:

- `/health` 200, `/health/worker` `status: ok` with `stale_lanes: []`
- `alembic_version` advanced as expected, exactly one head
- **`GET /api/users/companies` returns 503** (the feature is off — a 200 here means a flag is on)
- Scrapers still running: `scrape_runs` accruing, no spike in `error_count`
- No mass closure: compare OPEN counts per source against the previous day

### After #248 — the un-flagged changes are the point

Everything above, plus:

1. **`first_seen_at` did not move on existing rows.** It is absent from `_UPSERT_ON_CONFLICT`
   by design; confirm with a spot check that a known row's value is unchanged after a tick.
2. **New rows seed correctly.** After one Greenhouse tick, new rows should carry a
   `first_seen_at` near their `posted_on`, not near `now()`.
3. **Workday rows lost the fabricated date, and only those.** Expect ~42% of open Workday
   rows to have `posted_on IS NULL`; the `"Posted N Days Ago"` values must survive.
   Most affected: capitalone, blueorigin, nvidia, gm, disney, adobe, snap, paypal.
4. **The department backfill completed** — `count(department)` non-zero on `job_listings`,
   and the Department filter renders on a Greenhouse company (it will stay hidden on
   Workday/script companies, which publish none — that is correct, not a regression).
5. **Both worker lanes are ticking.** `/health/worker` reports `lanes.bulk` and
   `lanes.interactive` separately. A single stale lane now 503s the probe by design —
   that tag is the thing that stopped a 14-hour silent worker death going unnoticed.
6. **The proxy fix is live**: `GET /api/feedback?path=..%2Finternal%2Fenrichment%2Fhealth`
   must return **404**, and the legitimate paths must still work
   (`/api/companies`, `/api/features`, `/api/jobs`, `/api/jobs/facets`, `/api/locations/search`).
   `/api/jobs` must still re-emit `x-next-cursor`.

**Do not proceed to the flag flip until a full nightly cycle has run cleanly.** The seeding
change only shows itself on inserts, and the close path only exercises on a real tick.

---

## 6. The flag flip

Only after #248 has been healthy through at least one full scrape cycle.

⚠️ **Step 1 is not the cheap step.** It is the one that exposes `/resolve` to every signed-in
account, and `/resolve` is the widest surface in the feature. A final review confirmed all
four of these, and none of them costs the caller an add-quota slot or writes an audit row,
because `/resolve` persists nothing:

| | |
|---|---|
| **Outbound amplifier** | One call is up to 5 HEAD hops + 5 GET hops + 4 sniff GETs × 5 hops, reading up to 512 KiB per sniff target. The limiter is 10/60s **per user**, in-memory, single-process — there is **no global cap and no per-destination cap**. One account sustains ~300 outbound requests/min from our IP |
| **DNS-pool starvation** | `url_guard` submits blocking `getaddrinfo` to a **4-worker** pool, and cancelling the future does **not** interrupt the thread. 10 req/min × ~30 lookups against 4 uninterruptible threads is 75:1. A host whose nameserver blackholes UDP stalls everything else using `guarded_get` — **including the add path and in-process harvests** |
| **Existence oracle** | Resolve failure codes are surfaced verbatim, so a signed-in user learns per hostname whether it fails DNS, resolves private, or resolves publicly and fails at connect. Enough to enumerate `*.railway.internal`. `hops` also echoes any site's full redirect chain |
| **Wrong-board adoption** | The L2 embedded sniff regex-scans a whole page body and picks the most frequent ATS URL — so **a lone link wins with a count of 1**. A portfolio widget or parent-company link pointing at someone else's board becomes the candidate. If that board is published the notice is **terminal with no way past it in the UI** |

None of this blocks the merge — it is all behind the flag. It is the reason step 1 deserves the
same scrutiny as step 4, rather than being treated as the safe warm-up.

1. **Backend first**, on Railway: `CUSTOM_COMPANY_SOURCES_ENABLED=true`.
   Verify by behaviour: `GET /api/users/companies` with a valid bearer stops returning 503.
   Then watch outbound volume and the DNS pool for a day before going further.
2. **Confirm the add path is refused cheaply** while discovery is still off — paste a non-ATS
   URL, expect **422**, and confirm no `company_add_attempts` row with a spend and no
   Chromium session.
   **Paste `https://www.microsoft.com/en-us/careers/` and `https://www.apple.com/careers/us/`
   specifically.** Both are companies we have published for years, and both still buy a full
   discovery. Neither is fixed, and the reasons differ:

   - **Microsoft** — the locale sits between the host and `/careers`, and the matcher anchors
     its prefix at the start of the path. Catching it needs a segment-aware match, which
     changes the matcher's contract rather than adding a table row.
   - **Apple** — `apple.com/careers/` 301s to `apple.com/careers/us/` and stops there. It is
     Apple's careers **marketing** page, not the `jobs.apple.com` board the table names, and
     `test_careers_host_match.py` deliberately lists it as a near-miss. Adding it was tried and
     reverted: a careers-host hit is **terminal with no escape hatch**, so a wrong match
     hard-blocks a user — worse than the ~$0.03 the discovery costs.

   **This is a product decision, not a bug to fix quietly.** The question is whether pasting a
   company's careers *marketing* page should link to our published page or start a discovery.
   Answering yes means the terminal notice fires on pages that are not the board; answering no
   means we keep paying for duplicates of boards we already publish.
3. **Frontend**, on Vercel: `VITE_CUSTOM_COMPANIES_ENABLED=true` **and redeploy** — it is
   build-time. Optionally `VITE_DISCOVERY_PROGRESS_ENABLED=true` for the checklist.
4. **Then, and separately**, `CUSTOM_COMPANY_DISCOVERY_ENABLED=true`. This is the one that
   starts spending money. Before flipping it:
   - confirm `CUSTOM_COMPANY_MONTHLY_ADD_LIMIT` is set (or intentionally `0`)
   - confirm the Anthropic Console spend cap is in place — the owner keeps ~$20 there as the
     backstop, and accepts that hitting it kills AI features rather than costing money
   - leave `CAPTURE_USE_BROWSERBASE` **off**; our own Chromium is proven and free
5. **Watch the first real add end to end** before telling anyone the feature exists.

**Rollback at any step is the flag, not a revert** — except for the §1 changes, which are
revert-only.

---

## 7. What the flags do NOT protect

Stated plainly so nobody is surprised:

- The six migrations run regardless.
- Every change in §1 is live regardless.
- The proxy fix is live regardless — **this is desirable**; it closes an anonymous path to
  the internal-key routes.

---

## 8. Known-open items at time of writing

Not blockers, but they should not be discovered during an incident:

- **`add_company` commits the placeholder before deferring**, so a broker failure returns 500
  *and* leaves a `discovering` row with no job. The reconciler recovers it in ~40 min.
- **A refused board cannot be retried by re-adding** — the user must Remove first. Correct for
  a genuine refusal (discovery is deterministic), wrong for a swept row.
- **`http_html` recipes ignore their pagination step** — validated, never read. A page-1-only
  sweep reports `terminated_cleanly`, which a `self_consistent` oracle would verify, and it
  would then close everything past page one. **Latent**: discovery only emits `http_json` and
  `browser_fetch` today. It arms the moment `http_html` ships.
- **Discovery cost is not recorded.** `DiscoveryOutcome.cost_note` exists in memory and is
  never written, so "did this attempt cost anything" is unanswerable from the database.
- **The company-name matcher discards the TLD and cannot see the Public Suffix List's private
  section.** Run against the live 137-company list, it answers **vercel** for
  `acme-careers.vercel.app`, **notion** for `acme.notion.site`, **retool**, **supabase**,
  **gitlab**, **squarespace**, **sentry** for the equivalent tenant subdomains — every one of
  those platforms is a company we publish. It also answers **clear** for `clear.co` and
  **ramp** for `careers.ramp.network`, which are genuinely different organisations. All are
  `match_kind='name'`, so the "This isn't the same company" escape hatch survives: the cost is
  friction and a wrong `already_public` audit row, not data loss. `*.vercel.app` is the one
  that will actually happen.
- **`microsoft.com/en-us/careers/` still buys a paid discovery** — see §6 step 2.

---

## 9. Verification commands

Local, before any merge:

```bash
# backend — BOTH env vars are required, or you get 134 phantom failures because
# procrastinate_app binds its connector at import time from .env.local
TEST_DATABASE_URL=<url> DATABASE_URL=<url> PYTHONPATH=src/backend:. \
  .venv/bin/python -m pytest src/backend/api/tests

# the throwaway DB needs the procrastinate schema first:
#   app.schema_manager.apply_schema()

# frontend
npm run type-check && npm run lint && npx vitest run --root src/frontend

# end-to-end gate — spins its own stack and database
bash e2e/run.sh add-companies
```
