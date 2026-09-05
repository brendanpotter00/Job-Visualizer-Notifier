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
| `job_freshness` trigger seeds `now()` | Required by the seeding change; makes brand-new jobs not born stale | revert |
| Worker lane split + per-lane heartbeats | Two workers instead of one; `/health/worker` now 503s if **either** lane is stale | revert |
| Vercel proxy allowlists | Closes a live anonymous-access hole. **You want this one live** | revert (do not) |
| `details.department` dropped from the `details` JSONB by all 8 producers | **20,778 open rows** lose a populated key on their next tick (greenhouse 13,050 / ashby 5,034 / amazon 1,363 / eightfold 501 / tiktok 429 / lever 349 / gem 52) | revert — `details` is rebuilt wholesale from the raw payload on every upsert, so one tick restores it |
| `details_scraped` becomes truthful (`has_description(details)` instead of hard-coded `True`) | **7,047 open rows flip `true` → `false`** (workday 6,546, eightfold 501). It is in `_UPSERT_ON_CONFLICT`'s SET list, so existing rows move, not just new ones | revert — same self-healing shape |
| The enricher's `/pending` payload drops `details.department` | **Cross-repo contract.** Nothing in THIS repo reads it; the job-enricher might | revert |

⚠️ **The last three were not in this table until 2026-08-30 and are not in §5 either.** All
three are recoverable-by-revert and none has a reader in this repo — that is why they are
listed rather than blocking. The counts above were measured against prod on 2026-08-30.

⚠️ **One of them needs an answer from outside this repo before the merge:** confirm the
**job-enricher** does not read `details.department` in its prompt or its parser. If it does,
classification quality changes silently for every published company and nothing here will
say so.

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

Production is stamped `1d2d6c17acfc` (re-checked against prod 2026-08-30). Merging the
full stack runs **eight**, none of which locks a table:

| # | Revision | What | Risk |
|---|---|---|---|
| 1 | `fb8467065dfc` | E7 Phase 1 schema — 4 tables, 7 `companies` cols, 2 `scrape_runs` cols | Catalog-only on PG 17.9. **No table rewrite** — matters, `scrape_runs` is 634k rows |
| 2 | `c4f0a91b2d73` | Data: raise legacy page budgets | **0 rows** — table created empty one step earlier |
| 3 | `9d2f7ae5c1b4` | Data: retire flat page ceiling | **0 rows** |
| 4 | `a5cf3aed5f15` | Empty merge revision — rejoins Phase 1 with main | none |
| 5 | `2633dd6348e4` | Empty merge revision — rejoins that with the Phase 3 line | none |
| 6 | `7a4c1e93b6d8` | `job_freshness` trigger seeds `now()` | `CREATE OR REPLACE FUNCTION`. Verified byte-identical against the live function |
| 7 | `b4d17c2a9e51` | `lane` column on `worker_heartbeats` | trivial |
| 8 | `fe69ff596030` | `user_display_name` on `companies` (the owner rename) | Nullable `TEXT`, **no server default** → catalog-only, no rewrite. Every existing row is NULL = "never renamed", so it cannot change a name that renders today |

That order is not hypothetical. It is the replay of this branch's chain against a throwaway
database built from `main`'s models and stamped `1d2d6c17acfc`, exactly as prod is; it ends
with `alembic_version` holding one row, `fe69ff596030`.

Two empty merge revisions rather than one, because the fork is real and predates this branch.
`fb8467065dfc` was authored off `b4e1c9d77a02` while `main` advanced along that same parent
(`-> c7a41b93e5d2 -> d8b52c04f6e3 -> 1d2d6c17acfc`), so Phases 1 and 2 each sat on two heads
and failed CI on `MultipleHeads` out of `command.stamp(cfg, "head")`. `a5cf3aed5f15` closes
that fork down at Phase 1, where it belongs; `2633dd6348e4` already existed here and was
repointed onto it, which is what keeps this branch at one head.

**No migration in this deploy takes a lock.** There used to be one — `c1539fa03b23` added a
denormalized `department` column and backfilled 78k rows in a single transaction, ~5–15 s of
`ACCESS EXCLUSIVE` on `job_listings`. The owner then removed the Department filter entirely
(measured cardinality: Stripe 46 jobs → 39 departments, Anduril 377 → 195 — roughly one job
per option, which is a list rather than a filter), so the column had no reader and the
migration was **deleted outright** rather than reversed. It had never shipped; prod is stamped
`1d2d6c17acfc` and never had the column. `b4d17c2a9e51` was repointed to `7a4c1e93b6d8`.

Worth keeping the lesson even though the migration is gone: splitting the ADD from the backfill
was tried and **silently broke Alembic** — a mid-revision `conn.commit()` makes the
version-table UPDATE a no-op, leaving the data migrated and `alembic_version` unmoved. If a
future migration ever needs a long backfill, the answer is a separate one-shot script, not a
cleverer migration.

⚠️ Local dev databases that already ran `c1539fa03b23` (`jobscraper_pr243`, `jobscraper_e2e`)
keep an **orphaned nullable `department` column**. Boot and Alembic resolution are unaffected
and nothing reads or writes it. Drop it by hand if it bothers you. **Production never had it.**

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
| `COMPANY_NAME_SEARCH_ENABLED` | `False` | `/api/companies/search-by-name` returns **503**. NOTE this alone does *not* make the box URL-only — the box's copy is the frontend flag's job, and with that one on while this is off the UI still invites a name and gets a 503. **Costs money when on** (~$0.007/name, 1,000 free searches on the plan). Needs `BROWSERBASE_API_KEY`. INDEPENDENT of `CAPTURE_USE_BROWSERBASE` — that one buys Browsers for discovery, this one buys the Search API; different products, priced separately |
| `CUSTOM_COMPANY_MONTHLY_ADD_LIMIT` | `20` | Adds allowed per user per month. **`0` allows NONE** — a kill switch, not "unlimited" (see §4c). **Fail-closed both ways:** a typo'd *name* keeps the default 20, and a typo'd *value* landing on `0` blocks adds |

**Frontend (Vercel, `VITE_*`). BUILD-TIME — a change requires a REDEPLOY, not just an env edit.**

| Flag | Effect when off |
|---|---|
| `VITE_CUSTOM_COMPANIES_ENABLED` | No nav entry, **no route registered at all**, zero network calls |
| `VITE_DISCOVERY_PROGRESS_ENABLED` | Bare "Setting up…" badge instead of the checklist. Nested under the flag above |
| `VITE_COMPANY_NAME_SEARCH_ENABLED` | The add box is labelled "Careers page link" and a typed name goes to the add endpoint unchanged — exactly what shipped before. Nested under `VITE_CUSTOM_COMPANIES_ENABLED` |

⚠️ **The name-search pair must be flipped together, backend first.** The frontend flag's real
job is the COPY: with it on the field invites a company name, and if the backend flag were off
that name would come back a 503. On alone, the box promises something the server refuses.

⚠️ **The frontend flag is the stronger gate** — with it off the page does not exist, so nothing
can reach the backend even if the backend flag is on. Flip the backend first, frontend second.

✅ **Flag state IS verifiable from an agent — read the NAMES, not the values.** This section
used to say reading Railway variables was blocked, and that is wrong for the path that
matters. The **claude.ai Railway integration** (OAuth) answers `list-variables` with
`valuesRedacted: true` and returns **variable names only** — no secret ever crosses the
wire, and "is this flag set?" is a name question, not a value question. The CLI-backed
`railway` MCP is the one that returns plaintext, and it is separately gated behind
`railway login`.

Verified this way on 2026-08-31 against `onesecondswe` → `Job-Visualizer-Notifier` →
`production`: **all four E7 flags are ABSENT**, so every one of them sits on its compiled
default — sources off, discovery off, Browserbase off, add limit 20. That is the intended
pre-merge state and it is now a checked fact rather than an assumption.

Two caveats that keep the old advice alive in part:

- **Absent ≠ knowing the value of a var that IS present.** If a flag ever shows up in the
  name list, this method proves only that it is set, not to what. Then fall back to
  behaviour (§6) or read it in the dashboard.
- **Setting** a variable is still a write to production config, and the OAuth app is not
  the tool for it — do it in the dashboard, or with the CLI after `railway login`.

---

## 4c. ⚠️ BREAKING ON DEPLOY — `CUSTOM_COMPANY_MONTHLY_ADD_LIMIT=0` flipped meaning

**Not flag-gated. Ships with the code.** `0` used to mean **unlimited**; it now means
**zero adds allowed**.

| | Before | After |
|---|---|---|
| `CUSTOM_COMPANY_MONTHLY_ADD_LIMIT` unset | 20/month | 20/month (unchanged) |
| `…=20` | 20/month | 20/month (unchanged) |
| **`…=0`** | **unlimited** | **every add refused, 422 `monthly_limit_reached`** |

**Any environment currently sitting on `0` flips from unbounded to fully blocked the
moment this deploys.** That is the intended direction — a guard on money should fail
closed, and the old shape meant a typo, a bad template, or an empty string coerced to an
int silently handed every signed-in user unbounded headless-browser and LLM spend — but
it is a real behaviour change, not a refactor.

### ✅ ACTION REQUIRED BEFORE THIS DEPLOYS — only Brendan can do this

**Confirm `CUSTOM_COMPANY_MONTHLY_ADD_LIMIT` is UNSET in Railway production.** It is
*expected* to be unset, so the compiled-in default of `20` applies and nothing changes.
**This has NOT been verified**: reading Railway variables is blocked by the permission
classifier (see the warning above), so no agent can check it. If it turns out to be set
to `0`, either delete the variable or set it to a number **before** merging — otherwise
every user's next add returns 422.

Two things that make the new state visible rather than silent:

- A boot at `0` logs a WARNING naming the state
  (`services/add_quota.warn_if_adds_disabled`) — kept from the old code, inverted.
- The UI stops hiding it. `limit: 0` renders **"0 of 0 adds left this month"** with the
  submit disabled, instead of rendering no counter at all.

**Local and e2e keep their freedom with a large number, never `0`:** `.env.local` uses
`10000`, and `e2e/shared/stack/env.e2e` uses `100000`. `ge=0` is deliberately retained,
so `0` is still legal — it is now a genuine per-user kill switch, one env var that stops
every add without a deploy.

### Admins are exempt from this limit — no config, nothing to set

**Not flag-gated, no migration, no env var.** An admin (a row in `admins`, the same grant
`require_admin` reads — grant it at `/admin/users`) is never refused for the monthly cap.
Nothing else about the add path changes for them.

| | Non-admin | Admin |
|---|---|---|
| 20/month cap | enforced | **never refused** |
| 10/60s burst limiter | enforced | **enforced** — it is an abuse guard, not a budget |
| `company_add_attempts` row per add | written | **written** (the audit and the admin dashboard stay complete) |
| `quota` on `GET /api/users/companies` | `{used, limit, resetsAt}` | **absent** |
| The counter above the form | "17 of 20 adds left this month" | **no counter, submit never disabled** |

The exemption lives in `services/add_quota.get_quota`, not at the call site, because that
one function is also what the counter reads — an exemption applied only at the refusal
would leave an admin counting down to "0 of 20 adds left" above a form that never refuses.
"No cap for you" is sent as an **absent** `quota` block, which is the frontend's existing
"no cap in force" case (`addsRemaining` answers `null` → no counter, nothing disabled). It
is deliberately not `limit: 0`, which means the opposite.

**It fails CLOSED.** The admin lookup is a database read; if it raises, the caller is
treated as a non-admin and the cap applies (logged as an exception). A database error must
never become an exemption on a spend guard — that is the same fail-open shape `0`-means-
unlimited had, which is what the section above removed.

---

## 4b. Custom-company cadence — 24 h → 1 h, and what that does to closes

`DEFAULT_CADENCE_HOURS` (`services/custom_companies_service.py`) is now **1**, not 24.

**Why 1.** Every published board is re-read every **30 minutes** — all six
`enqueue_*_fan_out` tasks are on `*/30 * * * *`. `companies.cadence_hours` is an INTEGER
column, so 30 minutes is not expressible; 1 h is the nearest legal value and it errs slow.
"Every 15 minutes" was not available either way: 0.25 is not an integer, the claim tick's
backpressure ceiling only clears 3 fetches per `*/15` tick (**12 harvests/hour**), and a
single harvest is allowed 900 s before `fetch_custom_company` kills it — a 15-minute
cadence is shorter than one harvest's own timeout. 24 h was chosen when a harvest meant a
Browserbase session; a stored board now replays as one HTTP request.

**⚠️ Closes get faster, by design and with the owner's sign-off.**

| | Before (24 h) | After (1 h) |
|---|---|---|
| Harvest interval | 24 h ± 90 min | 1 h ± 15 min, +≤15 min tick lag |
| `MISSED_RUN_THRESHOLD` misses | 2 | 2 (unchanged) |
| Wall-clock floor (`1.5 × cadence`) | 36 h | 1.5 h |
| **A vanished job closes after** | **≈ 48 h** | **≈ 2 h** (bounded 1.5 h – 3 h) |
| Published companies, for comparison | | ≈ 1 h (2 × `*/30`) |

Nothing else about closing moved. Every gate is still ANDed exactly as before — VERIFIED
verdict, the safety guard, the fleet breaker, first-verified-run, script-changed, the
`self_consistent` streak and id-churn guards. **No close can now happen that would not
have happened before; the same closes happen sooner.**

**Jitter had to change with it.** It was a flat ±90 min, which is *larger than a 1 h
cadence*: `now() + 1 hour − 90 minutes` is in the past, so roughly half of all reschedules
would have left the row immediately due, and the `*/15` tick would have re-claimed it at
once. That is not a slow cadence — it is the loss of the primary interlock against two
concurrent harvests of one board. The jitter is now **a quarter of the cadence, capped at
90 min**: ±15 min at 1 h, and *bit-for-bit the old ±90 min* for any row still carrying an
explicit `cadence_hours = 24`.

**One manual step if you have pre-existing rows.** Production has none — checked
2026-08-29: `companies` there has no `visibility` column at all, so the E7 migrations have
not run and no `visibility='user'` row can exist. This is a strict no-op in prod. A
local/dev database that already has custom companies stored `cadence_hours = 24` at insert
time and keeps it — there is deliberately **no migration**, because a second Alembic head
is a worse risk than a one-line UPDATE:

```sql
UPDATE companies SET cadence_hours = 1 WHERE visibility = 'user' AND cadence_hours = 24;
```

**Capacity, stated so it is not a surprise later.** 3 fetches per `*/15` tick = 12/hour, so
an hourly cadence is genuinely hourly for roughly the first **12** tracked boards. Beyond
that the claim's `ORDER BY next_run_at` degrades it fairly to ≈ `ceil(N/12)` hours —
later runs, never earlier ones, so nothing closes sooner than it should. Raising
`_QUEUE_BACKPRESSURE_CEILING` is the lever if the fleet grows; it was left at 3 because
that is a load decision, not part of this change.

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
4. **There is NO department COLUMN check to run — but there IS a department JSONB
   change.** This step used to read "confirm the department backfill completed". §3
   removed that migration and the Department filter outright; `job_listings` has no
   `department` column on this branch and prod never had one, so `count(department)` is a
   `column does not exist` error, not a failed deploy.
   What DID change is the `details` **JSONB key**, and that one is live (see §1):
   ```sql
   -- expect this to fall from 20,778 toward 0 as each board takes its next tick
   SELECT count(*) FROM job_listings
    WHERE status='OPEN' AND details->>'department' IS NOT NULL;
   ```
   Falling is correct. Verified against prod 2026-08-30.
5. **Both worker lanes are ticking.** `/health/worker` reports `lanes.bulk` and
   `lanes.interactive` separately. A single stale lane now 503s the probe by design —
   that tag is the thing that stopped a 14-hour silent worker death going unnoticed.

   ⚠️ **Detection is per-lane; AUTO-RESTART is not.** `main` gained a worker watchdog in
   #268 (the 2026-08-29 61-hour wedge) that `os._exit`s on a stale heartbeat so Railway
   brings up a fresh container. It reads `MAX(worker_heartbeats.at)` across **all** lanes,
   so after this merge it only fires when **both** lanes are dead. One dead lane keeps
   `MAX(at)` fresh from its survivor: the probe goes 503 and says which lane, and nothing
   restarts. That is a monitoring gap, not a regression — before the lane split there was
   one lane and the watchdog covered it. **So after #248, treat a 503 naming a single
   stale lane as something YOU restart**, not something the box heals. Closing it means
   grouping the watchdog query by `lane`, which is deliberately not part of this merge.
6. **The proxy fix is live**: `GET /api/feedback?path=..%2Finternal%2Fenrichment%2Fhealth`
   must return **404**, and the legitimate paths must still work
   (`/api/companies`, `/api/features`, `/api/jobs`, `/api/jobs/facets`, `/api/locations/search`).
   `/api/jobs` must still re-emit `x-next-cursor`.

### The gate before the flag flip — what to observe, not how long to wait

This used to read *"do not proceed until a full nightly cycle has run cleanly"*. That was
wrong on both halves and is replaced by the table below.

- **There is no nightly cycle to wait for.** With the flags off there are **zero
  `visibility='user'` companies in production**, so nothing is on the custom schedule at
  all. A day of waiting observes an empty set.
- **A day would prove the wrong harvest anyway.** When the flag does flip, the first
  harvest fires within seconds — `claim_custom_companies.start_first_harvest`, called by
  both add paths — not on a scheduled tick. Waiting a cadence would only demonstrate that
  the *second* harvest works.
- **The changes that are actually live are on the public crons**, and all six
  `enqueue_*_fan_out` tasks run `*/30 * * * *`. That is the clock this gate runs on.

Each row names the signal that proves that specific change, and the earliest it can
appear. **The gate is the rightmost column, not a duration** — a change whose trigger has
not fired yet is unproven no matter how long you waited.

| Change | Fires on | Earliest proof | Gate |
|---|---|---|---|
| Migrations | container boot | first `/health` 200 | `alembic_version` = `fe69ff596030`, exactly one head. **No `department` check** — the column does not exist; see §5.4 |
| Worker lane split | immediately | first `/health/worker` | `status: ok`, `stale_lanes: []`, **both** `lanes.bulk` and `lanes.interactive` present and fresh |
| Vercel proxy allowlists | immediately | one curl | the `..%2Finternal%2F…` probe 404s; the five legitimate paths still 200; `/api/jobs` still re-emits `x-next-cursor` |
| `first_seen_at` **not** moved on existing rows | every tick's UPSERT | **one tick, ≤ 30 min** | a known row's `first_seen_at` byte-identical after a tick that re-saw it |
| Workday `"Posted 30+ Days Ago"` → NULL | the Workday tick's UPSERT | **one Workday tick, ≤ 30 min** | ~42% of open Workday rows `posted_on IS NULL`; `"Posted N Days Ago"` values intact |
| `first_seen_at` **seeded** from the board's posted date | **INSERT only** | **the first tick that actually inserts a row** | ≥1 new row exists with `first_seen_at ≈ posted_on`, not ≈ `created_at`. Across the whole Greenhouse fleet this usually lands within the hour, but it is a **content** condition, not a clock one — if nobody posted, you have not tested it yet |
| `job_freshness` trigger seeds `now()` | **INSERT only** | same insert as above | the new row's `job_freshness` is fresh, i.e. it is not born stale |
| The close sweep | a tick where a job is missing, twice | **two consecutive ticks, ≈ 1 h** | `scrape_runs.closed_jobs` accrues normally and Check B (`closed_24h >= 50 AND > open_rows`) stays empty |

**So the real timescale is about an hour, plus however long it takes to see an insert** —
not twenty-four. The one row that cannot be forced is the seeding proof; if no board posts,
say so and hold, rather than converting the wait into a duration and calling it done.

---

## 6. The flag flip

Only once every row of the §5 gate table has its proof — in particular the two
INSERT-only rows, which no amount of waiting produces on its own.

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
   - confirm `CUSTOM_COMPANY_MONTHLY_ADD_LIMIT` is **unset (default 20) or set to a
     positive number**. `0` is no longer "unlimited" — it now refuses every add (§4c),
     so the old wording of this step ("or intentionally `0`") would have you flip the
     spend gate on with the add endpoint dead. If you want adds off, `0` is the switch;
     if you want them on, `0` is the one value that must not be there.
   - confirm the Anthropic Console spend cap is in place — the owner keeps ~$20 there as the
     backstop, and accepts that hitting it kills AI features rather than costing money
   - leave `CAPTURE_USE_BROWSERBASE` **off**; our own Chromium is proven and free

   ⚠️ **THE CAPTURE BROWSER'S SUB-RESOURCES ARE UNFILTERED, AND THIS IS THE FLAG THAT
   EXPOSES THEM.** Money is not the only thing step 4 turns on. The host-pin in
   `capture/_capture_main.py` scopes itself to NAVIGATIONS — `if not
   request.is_navigation_request(): await route.continue_()` — and Chromium is launched
   with only `--no-sandbox --disable-blink-features=AutomationControlled`: no proxy, no
   `--host-resolver-rules`, no egress filter. So the pasted page's own JavaScript runs
   with our Railway network position and may fetch `*.railway.internal`, RFC1918 or
   `169.254.169.254` and POST what it reads back to its own origin. That is a READ SSRF
   against any internal service with permissive CORS, not a blind one.

   The module comment says the risk "is closed on the PARENT side" by
   `validate_public_url` over every surviving candidate. That is true of what can become
   a RECIPE; it is not true of the request being made, and the two are different claims.
   Navigation redirects, the in-page `fetch()` of the `browser_fetch` tier, and the
   candidate list are all genuinely guarded — sub-resources are the gap.

   Reachable by any signed-in account the moment this flag flips, bounded only by 10
   adds/60 s and 20/month. **Not a merge blocker — nothing runs with the flags off — but
   it belongs to step 4, not to a later cleanup.** The cheap containment is a resolver
   rule plus a route handler that drops sub-resources resolving to non-public IPs.
5. **Watch the first real add end to end** before telling anyone the feature exists.

**Rollback at any step is the flag, not a revert** — except for the §1 changes, which are
revert-only.

---

## 7. What the flags do NOT protect

Stated plainly so nobody is surprised:

- The eight migrations run regardless — including `fe69ff596030`, which adds the
  `user_display_name` column even though the rename endpoint that writes it is behind
  `CUSTOM_COMPANY_SOURCES_ENABLED`.
- Every change in §1 is live regardless.
- **`CUSTOM_COMPANY_MONTHLY_ADD_LIMIT=0` means zero regardless — see §4c.** No flag gates
  it, and an environment sitting on `0` goes from unlimited to fully blocked on deploy.
- The proxy fix is live regardless — **this is desirable**; it closes an anonymous path to
  the internal-key routes.

---

## 8. Known-open items at time of writing

Not blockers, but they should not be discovered during an incident:

- **`add_company` commits the placeholder before deferring**, so a broker failure returns 500
  *and* leaves a `discovering` row with no job. The reconciler recovers it in ~40 min.
- **A refused board cannot be retried by re-adding** — the user must Remove first. Correct for
  a genuine refusal (discovery is deterministic), wrong for a swept row.
- **`http_html` recipes ignore their pagination step. NO LONGER LATENT — and now guarded.**
  This entry used to end "discovery only emits `http_json` and `browser_fetch` today; it arms
  the moment `http_html` ships". `http_html` shipped, in `1757370` (sources 2 and 6 — the
  document becomes a candidate), so the entry was wrong by the time you read it.
  `synthesize_recipe` drops the pagination step for a document candidate because
  `validate_recipe` forbids paging on that transport, and `_run_http_html` then reports
  `terminated_cleanly=True` from a single request it never swept. A paginating careers page
  therefore stores a page-one-forever recipe whose truncated counts are perfectly stable — and
  the history-delta oracle, which hedges entirely on `terminated_cleanly`, VERIFIES it. Jobs
  that merely rotated onto page two then close while still open.
  **Fixed** by check 13d in `harvest_verification._verify_history_delta`: `http_html` cannot
  earn the EMPIRICAL oracle. It can still close on a trusted total
  (`declared_probed`/`facet_sum`/`header`/`sitemap`), each of which demands `n ==
  declared_total` exactly — proof a page-one read cannot fake. Still open, and deliberately:
  such a board is tracked as a **sliver** with no notice saying so, unless the coverage
  refusal (`_COVERAGE_REFUSAL_RATIO = 0.10`) catches it. It will not close wrongly; it will
  under-report.
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
