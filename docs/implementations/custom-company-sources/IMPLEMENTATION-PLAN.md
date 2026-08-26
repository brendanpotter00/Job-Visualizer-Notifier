# Custom company sources — implementation plan

**Scoped to the live PR stack, not to the planning artifacts.** Written 2026-08-25 on `feat/e7-phase3-discovery`.

**The stack:** `main ← #243 ← #247 ← #248`. Nothing is merged. Anything that lands on #248 reaches production only after three PRs merge — that fact decides half the routing below.

**Source of the work:** [7.7 — Custom-company jobs × the enricher](https://app.clickup.com/t/wdwb1cbq5t) and [7.6 — First-run dates](https://app.clickup.com/t/wdwb1cbp8n), both subtasks of the E7 epic `wdwb1cbnc2`. The reasoning lives in `ENRICHMENT-TRADEOFFS.md` and the two annotated artifacts; **this file is the build order**.

> **Read this before planning anything into it.** Every unit below was checked against the source on this branch, not against the artifacts — which were written at different times and describe work that has since shipped. The list of what is already done is in §1 and it is longer than the list of what is left.

---

## 1. Already shipped — do not re-plan

Verified by reading the code, with commits named. If a planning doc asks for one of these, the doc is stale.

| Thing | Where it lives now | Commit |
|---|---|---|
| `browser_fetch` replay tier (agent-free, SSRF-pinned child) | `services/browser_fetch/runner.py`, `_browser_fetch_main.py` | `5e3a65b`, `b5a05a8` |
| Capture discovery — record the API once, prove it replays, store it | `services/capture/discover.py` (1,949 L) | `d71ddb1` |
| Discovery-progress checklist, 5 named steps | `services/discovery/progress.py`, `DiscoveryChecklist.tsx` | `d410409`, `09744cc` |
| Live view on the row while the run is happening, retracted when the browser dies | `discover.py:1440-1469`, `DiscoveryChecklist.tsx:203` | `fb491ad`, `4846056`, `d034ee9` |
| Request stream + which request we picked | `DiscoveryNetworkLog.tsx` (394 L), `progress.py:199-216` | `c0c1534`, `fb0c0a7` |
| Custom jobs reach the Recent Jobs feed | `routers/user_companies.py:486`, `jobsApi.ts:90/133`, `recentJobsSelectors.ts:10` | `6e419a0`, `e584221` |
| **Remove deletes the jobs** — last owner purges everything | `custom_companies_service.py:1007`, returns `'purged'` :1032 | `7a5a57b` |
| Page cap retired — a harvest is bounded by time and rows | `recipe_runner.py:101` (600 s), `:109` (50,000 rows); migration `9d2f7ae5c1b4` | `dfd7320` |
| Immediate first harvest on **both** add paths | `claim_custom_companies.py:209`, `user_companies.py:205`, `discover_custom_company.py:187` | `853457f`, `75e1fa5` |
| Evidence panel / badge / accordion rework, `/add-companies` route | `MyCompaniesList.tsx`, `companyHealth.ts`, `routes.ts:16` | `2bea9a1`, `a6e1139`, `34fe180` |
| **A list-valued `location` is no longer pruned** | `request_selector.py:597` renders through `render_row_field` | `916d351` |
| 4 MB capture body, 24 s page watch | `network_capture.py` | `85821b6`, `f97e915` |
| **"Last fetched", replacing the "Last checked" lie** (7.6 D6) | `companyHealth.ts:249`, `MyCompaniesList.tsx:191` | `3d70ae2` |

**Two more, so nobody plans them:**

- **Δ7 (last owner deletes) needs no code.** `remove_owned_company` already purges on the last owner and already returns `'unlinked'` when others remain (`custom_companies_service.py:887-1035`), with named tests at `test_user_companies_router.py:334,381,404,429`. The decision **confirms today's behaviour**; the only work it creates is unit 5.
- **"Last checked" → "Last fetched" (7.6 D6) shipped** as `3d70ae2`, mid-write of this plan (`companyHealth.ts:249` `describeLastFetched`, `MyCompaniesList.tsx:191`). Done, not a plan item.

**Also retired, and a stale note to correct:** `BROWSER_AGENT_ENABLED` no longer exists — it went with Stagehand, and `test_recipe_runner_import_guard.py:240` asserts the package is gone. `custom_company_discovery_enabled` is now the single discovery gate (`config.py:105`). Any note claiming discovery needs *two* flags is out of date.

---

## 2. Decisions this plan is built on

Recorded in the enrichment artifact's Decisions log. Δ6–Δ8 are new; D1/D3/D5 and the chart split are my calls under *"use your best judgment on everything else."*

| | Decision | Call | Whose |
|---|---|---|---|
| Δ1 | Enricher fairness mechanism | Option B, reserved share. C and E rejected | owner |
| Δ2 | `department` in the capture field set | Dropped, then **reversed** — the set carries both it and `description` (ENRICHMENT-TRADEOFFS §3a) | owner |
| Δ3 | Ship title-only labels | Yes | owner |
| **Δ6** | **Dedupe a pasted URL against boards we already publish** | **Confirmed — and it is the priority. P2 first, P1 deferred** | owner |
| **Δ7** | **Last owner leaves** | **DELETE.** Overrules the orphan-and-keep recommendation | owner |
| **Δ8** | **Local environment** | **Mirror production** | owner |
| D1 | Size of the custom slice | **10%**, shipped as a setting, not a literal | mine |
| D3 | Title-only rows in the needs-human queue | **Publish the labels, exclude them from the queue** | mine |
| D5 | Posted-date sanity window | **`[2015-01-01, now + 7d]`, one shared helper** | mine |
| — | Chart / sort split | **Chart on `posted_on`, recency sort stays on `first_seen_at`** | mine (confirming) |
| D6 | Automatic merge | **Never, at this stage** | as recommended |

**The one-line overrules**, so none of my four costs a redesign:

- D1 → `ENRICHMENT_CUSTOM_SHARE_PCT` in the environment. Restart, no deploy.
- D3 → one branch in `/results`; the clamp and the judge routing are laptop-side anyway.
- D5 → two constants in one helper.
- Chart split → one expression in `timeBucketing.ts:93`.

**Δ7's cost, stated once:** deleting on last-owner-leaves destroys that company's history permanently. The next person to add the same board pays for a fresh scraper and starts at zero. That is the price of a database where every `visibility='user'` row is a row somebody is actually using.

**Δ8, settled against Railway rather than inferred.** Production's variable list (names only, values redacted): `ENRICHMENT_CLAIM_WITHOUT_DESCRIPTION` and `ENRICHMENT_USE_EXTERNAL` **are set**; `CAPTURE_USE_BROWSERBASE`, `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` and both E7 rollout flags are **not set at all**. So production captures in its own Chromium (`src/backend/Dockerfile:24` installs it; `network_capture.py:518` degrades to it), and mirroring production means turning the billed path **off** locally. See unit 2.

---

## 3. Routing — what lands where

| Unit | Lands on | Why |
|---|---|---|
| 1 · Enricher fairness brake | **its own PR, off `main`** | Nothing in it depends on E7. Trapping the brake behind three unmerged PRs is exactly how the accelerator ships first |
| 2 · Local env mirrors prod | **no PR** | `.env.local` is gitignored; one doc note in `src/backend/CLAUDE.md` |
| 3 · HTML-unescape mapped fields | **#248** | Recipe-runner surface #248 already owns |
| 4 · `compile_plan` raises on an unknown op | **#248** | Three lines in a file #248 rewrote |
| 5 · Orphan-company guard | **#248** | Small, and it is the Δ7 follow-through |
| 6 · `_cap_details` learns `description` | **#248** | Leaf-task file #248 already owns |
| 7 · Capture schema `+description −department` | **#248** | Same |
| 8 · Re-capture the stored recipes | **no PR — ops** | Data, not code |
| 9 · P2 resolve-and-link | **#248** | Sits inside the add router #248 owns |
| 10 · Title-overlap suggestion | **its own PR, on #248** | New service + new UI + a new stored dismissal. Too much to bury in #248 |
| 11 · `parse_date` emission + epoch dates | **its own PR, on #248** | Ticket 7.6's backend half |
| 12 · One shared posted-date window | **same PR as 11** | Useless apart |
| 13 · Chart reads `posted_on` | **its own PR** | **Widest blast radius in the plan** — it changes every public company's chart |
| 14 · The three one-liners | **#248** | Independent, tiny |

**#248 is already 50+ commits.** The rule I applied: a unit lands on #248 only if it edits a file #248 already rewrote *and* is small enough to review as one more commit. Everything that adds a surface gets its own PR.

---

## 4. The units, in order

### Unit 1 — Reserved share for custom rows in the enrichment claim

Ship the brake before the accelerator. Production has `ENRICHMENT_CLAIM_WITHOUT_DESCRIPTION` set, so the description guard that accidentally excludes custom rows today is **already off there**. The moment E7 turns on in production, custom rows are claimable — and because the claim orders `first_seen_at DESC` within its tier, a newly added board's jobs are the *newest rows in the table* and sort to the **front**, not the back. A 12,000-job board added tomorrow takes the pipeline for ~27 days.

**Changes**

- `src/backend/api/config.py` — new `enrichment_custom_share_pct: int = 10`.
- `src/backend/api/routers/internal_enrichment.py:181-196` — split the claim into two bounded picks inside the one transaction: a public slice (`source_id NOT LIKE 'custom:%'`, today's tiering and ordering untouched) and a custom slice capped at `ceil(limit × pct / 100)`. Option B only: **no** `row_number()`, **no** per-company cap.

**The test that proves it** — `src/backend/api/tests/test_internal_enrichment.py`:
1. With 500 custom rows all newer than every public row, a 40-job claim returns **at most 4** custom rows — the fairness property, asserted against the exact case that breaks it.
2. With zero custom rows, the claimed set is byte-identical to today's — no regression on the public path.
3. With `pct = 0`, no custom row is ever claimed.
4. `FOR UPDATE SKIP LOCKED` still holds across both slices under a concurrent claim.

**Dependency:** none. This is the first thing built and the first thing merged.

**Invariants:** none of the four named ones. It does touch the hot claim path — `idx_job_listings_enrichment_claim` is partial on `(first_seen_at) WHERE enrichment_status IS NULL AND status='OPEN'` and both slices keep that predicate, so the index still serves them. Assert the plan in the test if you want the guarantee to survive.

---

### Unit 2 — Make the local environment mirror production (Δ8)

**Changes** — `.env.local`, which is gitignored, so this is an ops step with a doc note:

| Var | Now | Set to | Why |
|---|---|---|---|
| `CAPTURE_USE_BROWSERBASE` | `true` | **`false`** | Prod has no Browserbase credentials at all. Capture degrades to our own Chromium (`network_capture.py:518`), which is what prod will do — and the per-browser-hour billing stops |
| `ENRICHMENT_CLAIM_WITHOUT_DESCRIPTION` | unset | **`true`** | Set in prod. Without it a local test of unit 1 passes for the wrong reason |
| `ENRICHMENT_USE_EXTERNAL` | unset | **`true`** | Set in prod |
| `CUSTOM_COMPANY_SOURCES_ENABLED` | `true` | **leave on** | Rollout flag, not runtime config. Off in prod because it has not launched |
| `CUSTOM_COMPANY_DISCOVERY_ENABLED` | `true` | **leave on** | Same |

**The distinction to write down** (in `src/backend/CLAUDE.md`): **mirror the runtime config, not the rollout switches.** A rollout flag differs between local and prod on purpose; a runtime flag differing is a bug waiting to be discovered in production.

**The consequence, and it is not small:** the live-view URL is a Browserbase-only artefact (`_fetch_live_view`, `network_capture.py:413`). With Browserbase off, `liveViewUrl` is always null — the frontend already handles that (`DiscoveryChecklist.tsx:113` retracts it), so nothing breaks. But it means **the live-view UI shipped on #248 has no production path today** unless credentials are added to Railway. Decide that deliberately; do not discover it after launch.

**The test that proves it:** none — it is configuration. The proof is a local discovery run that completes with `liveViewUrl: null` and still reaches VERIFIED.

**Dependency:** none. Do it before unit 8, which is where the bill would otherwise land.

---

### Unit 3 — HTML-unescape mapped recipe string fields

19 of 85 custom Spotify titles are stored as `Client Partner, Emerging &amp; Scaled`. Two effects: the entity renders literally in the job list, and exact-match comparison silently fails — it cost a wrong measurement (56/81 instead of 70/81) during the dedupe analysis.

**Changes** — `src/backend/api/services/recipe_runner.py`, in `map_records` (:222) / `_apply_shaping` (:682), so every consumer benefits. `recipe_rows.py` is the alternative site; **pick one, not both**, or a double-encoded `&amp;amp;` unescapes twice.

**The test that proves it:** `&amp;` in a source title stores as `&`; `&amp;amp;` stores as `&amp;` — unescaped exactly once; a title with no entity is byte-identical.

**Dependency:** none, but **unit 10 depends on this** — the title-overlap comparison is wrong by 14 points without it.

**Invariants:** none, but it changes stored `id` values if a board's id carries an entity. Assert that the dedupe key stays stable, or exclude `id` from the unescape.

---

### Unit 4 — `compile_plan` raises on an op it cannot run

`_v_lookup_join` validates a well-formed `detail_fetch` shape (`recipe_schema.py:410-420`), but `lookup_join` appears **nowhere** in `recipe_runner.py`, and `compile_plan`'s dispatch is an `if/elif` chain **with no `else`** (`recipe_runner.py:282-305`). A `lookup_join` step validates cleanly on write and is then **silently discarded** at compile — a working scrape with missing data and no error anywhere.

**Changes** — `recipe_runner.py:282-305`: `else: raise RecipeError(f"unrunnable op: {op}")`.

**The test that proves it:** a recipe carrying a `lookup_join` step raises at compile; every op the runner *does* implement still compiles; the error names the op.

**Dependency:** none.

**Invariants — flag this one.** It is the RAISES-never-empty family: the whole point is that an incomplete harvest must raise rather than return a plausible partial. Put the test beside `test_recipe_runner_invariants.py:106` (`test_inv5_zero_records_raises_never_empty`) so it is read as part of that contract, not as a stray unit test.

---

### Unit 5 — A `visibility='user'` company with no owner cannot exist

Δ7's actual requirement: *"I want to be able to read the database and know how many are active, being used by users."* Today `u-6hkpc6fh0z` ("Amazon (live check)") holds **100 jobs and zero `user_companies` rows** — a state the model says is unreachable, produced by a test path. It is `enabled=false`, invisible to the UI, and un-deletable through the API.

**Changes** — one of:
- a `NOT EXISTS` consistency check surfaced through the existing health/monitor path, plus a small internal cleanup route; **or**
- a foreign-key/trigger that makes the state unrepresentable.

Prefer the check first: the reaper is a delete path and Δ7 already gives deletes teeth.

**The test that proves it:** a company with `visibility='user'` and zero owners is reported by the check; a company with one owner is not; the check ignores `visibility='public'` rows entirely.

**Dependency:** none.

**Invariants:** none, but it is a **delete path** — anything that removes rows here must reuse `remove_owned_company`'s ordering (`job_locations` with its `NOT EXISTS` guard → `job_tags` → `job_enrichment` → `job_listings` → the company tables), not invent a second one. `test_purge_is_one_transaction` (`:429`) is the shape to copy.

---

### Unit 6 — `_cap_details` learns about `description`

`_DETAILS_MAX_BYTES` is 8 KB and `_cap_details` (`tasks/fetch_custom_company.py:120-150`) only knows how to drop `content`. A large `description` falls through to the structured-essentials branch and is **silently dropped**. This must land before unit 7 or the first descriptions we ever map get eaten.

**Changes** — `src/backend/api/tasks/fetch_custom_company.py`:
- strip HTML → plain text,
- truncate to a ~6 KB plain-text budget rather than dropping,
- keep `description` ahead of the last-resort branch. *(Written when Δ2 had `department` gone, so that branch kept nothing a custom recipe produced. Δ2 was reversed — the branch now keeps both, and `department` is byte-bounded so it can never shrink the description.)*

**The test that proves it:** a 10 KB HTML description survives as truncated plain text and `details->>'description'` is **non-null** — the exact predicate `DESCRIPTION_SQL` (`enrichment_monitor.py:40-44`) reads; a 500-byte description is stored untouched; a record with *both* a huge `description` and a huge `content` still fits the blob budget.

**Dependency:** none, but **unit 7 depends on it**.

**Sizing note:** Atlassian's combined text averages 5,841 chars and tops out at 10,368. Stripping HTML typically halves it, but that has never been measured — measure the p99 over the 249 Atlassian records during this unit and set the constant from the number, not the estimate.

---

### Unit 7 — Capture schema: `+description`, `−department` *(the `−department` half was reversed — see the note at the end of this unit)*

The single reason custom jobs get zero enrichment rows. The discovery LLM's structured output is a **closed** 6-key object (`request_selector.py:386-417`, `additionalProperties: false`) — the model *cannot* return a description mapping even when it is looking straight at one. Three of five captured boards already return 2.7–5.8 KB of description text per record in the list payload, which we download nightly and discard.

**Changes**

- `services/capture/request_selector.py` — add `description` to `_FieldMap` (:295) and `_SELECTION_SCHEMA` (:386); remove `department` from both; extend `SYSTEM_PROMPT` (:356) to ask for a description/summary/overview field when the record carries one.
- `services/recipe_schema.py:107` — `CANONICAL_OPTIONAL_FIELDS` gains `description`, loses `department`. Documentation only; `_v_fields` already accepts extra keys.
- **Leave `internal_enrichment.py:69` alone** — it reads `details->'department'` as a classifier hint, which is a no-op when the key is absent and still populated by public ATS rows. Dropping the *capture* is Δ2; dropping the *read* would degrade Greenhouse/Lever/Ashby/Gem/Eightfold for nothing.

**The test that proves it:** a real capture fixture through `select_request` produces a `description` mapping that survives `_prune_non_scalar_optionals` (:590); a stored recipe captured under the **old** field set still validates unchanged; a container-valued description is still pruned. Model on `test_request_selector.py`, which already has the Atlassian fixture from `916d351`.

**Dependency:** unit 6.

> **`−department` reversed.** Δ2 rested on "nothing reads it", and that stopped being true hours after this unit shipped: the Department filter was found silently dead and fixed with a denormalized `job_listings.department` column (migration `c1539fa03b23`), so the field now has a user-facing reader and an unmapped recipe NULLs the column on every upsert. The set carries **both** — the `+description` half stands unchanged, tie-break prompt included, and `description` still wins any conflict over the blob budget because `_DEPARTMENT_MAX_BYTES` bounds the cheap field. Cost, measured before the second re-capture: Microsoft 2,217 → 139 rows with a department, Atlassian 244 → 13, Jane Street 235 → 4, Spotify 86 → 9. Full note in ENRICHMENT-TRADEOFFS §3a.

---

### Unit 8 — Re-capture the stored recipes (ops)

The five stored recipes were captured under the old field set, so they carry no `description`. Two of them also carry no `location`: `916d351` fixed the prune but was explicitly forward-looking — Atlassian's `locations` and Microsoft's `standardizedLocations` have no key left to fold, confirmed in the dev DB.

**This is why unit 2 comes first.** With `CAPTURE_USE_BROWSERBASE=false`, re-capture runs in local Chromium and costs nothing. With it on, each of the five is a billed session (33–95 s measured).

**Alternative if a board refuses a fresh capture:** patch `company_scripts.script`'s field map directly. It is a JSON edit and it is reversible.

**The test that proves it:** post-re-capture, query the dev DB — Atlassian and Microsoft have a non-null `location` on >95% of rows, and Atlassian / Amazon / Jane Street have a non-null `details->>'description'`.

**Dependency:** units 2, 6, 7.

---

### Unit 9 — P2 dedupe: resolve-and-link to a company we already publish (Δ6 — the priority)

*"If someone tries Spotify or Microsoft we should just point them to that published job board."* The add path already resolves a pasted URL to `(ats, board_token)` before discovery ever runs, and `companies` already stores exactly those two columns `NOT NULL` for all 129 public rows. One `SELECT` turns the add into a link.

**Changes**

- `src/backend/api/routers/user_companies.py` — after `discover_ats` returns a candidate and **before** the ATS add path (around :252-457): `SELECT id, display_name FROM companies WHERE visibility='public' AND ats=%s AND board_token=%s`. On a hit, create **nothing** — no `companies` row, no `user_companies` row, no scraper, no capture — and record a `company_add_attempts` row with a new `outcome='already_public'` so the audit stays complete.
- `src/backend/api/models.py` — a response variant carrying the public company's id and display name.
- Frontend `ResolveResultDisplay.tsx` / `resolveErrors.ts` — *"We already track **Spotify** — open its hiring trend →"*, linking to `/companies` with that company selected, plus a secondary, **non-default** "Track it separately anyway".

**The test that proves it:** pasting a Lever URL for a published company returns the link response and leaves `companies`, `user_companies` and `job_listings` **unchanged** — assert on row counts, not on the response shape; the attempt is recorded as `already_public`; "track it anyway" still produces a normal private company; a URL that resolves to an ATS we do *not* publish is unaffected.

**Dependency:** the ATS resolution ladder (shipped, #243/#247) and the add router (#248).

**The honest limit, and it matters:** this catches a pasted Greenhouse / Lever / Ashby / Gem / Workday / Eightfold URL. It does **not** catch `lifeatspotify.com`, because that URL resolves to no ATS at all — 52 KB of its HTML contains zero references to any ATS host we know. **So unit 9 would not have caught the case that actually prompted this.** Unit 10 is that case.

---

### Unit 10 — The title-overlap suggestion (the case that actually bit)

Neither the URL nor the captured endpoint links `lifeatspotify.com` to `lever:spotify` — they are two real, different feeds. The only signal left is the job set. Use it, cheaply, and **never to merge**.

**Changes**

- New `src/backend/api/services/published_board_match.py`: after a discovered board's **first VERIFIED** harvest, take its OPEN title set, normalize (lowercase, strip punctuation, HTML-unescape — hence unit 3), and intersect against each `visibility='public'` company's OPEN title set. 129 set-intersections, offline, once per new board.
- Threshold: **≥70% of the smaller set, minimum 20 titles.** Above it, store a dismissible suggestion on the company. Do not merge, do not modify anything.
- Frontend banner on the company row: *"This looks like **Spotify**, which we already track — 70 of 81 roles match. Use the public page instead?"* One button that removes the custom board, and a dismiss that persists.

**The test that proves it:** the measured Spotify pair (70 of 81 unique OPEN titles, 86%) produces a suggestion; **a merge is never performed** — assert zero writes to `companies` and `job_listings` from this path, which is the D6 guarantee in executable form; a 50%-overlap pair produces nothing; dismissal survives a reload.

**Dependency:** unit 3 (or the comparison is wrong by 14 points, measured).

**Named uncertainty:** the 70% bar rests on **n = 1**. Two competitors hiring the same 40 generic roles could plausibly clear 50%. Before shipping the banner, run the comparison pairwise across all 129 public companies and look at the *false*-pair distribution — offline, minutes. If the false pairs cluster above 70%, raise the bar; do not lower it.

**D6, in the code:** two identical captured endpoints may link **at add time, with the user watching**. Everything else is a suggestion. There is no un-merge path in this codebase, no merge audit, and no way to reconstruct which rows came from which board — so a false merge is permanent and silent, while a false suggestion is one dismissible banner. Never symmetric, never automatic.

---

### Unit 11 — Emit `parse_date`, and teach it epochs

**Root cause found, and confirmed against the stored capture.** The Microsoft recipe maps `posted_at: "postedTs"` and the payload really does carry it — the recorded sample is `"postedTs": 1787617881`, a **Unix epoch in seconds**. Discovery emits only `fetch` / `paginate_*` / `extract_json_path` / `assert_no_inband_error` / `dedupe_key` / `assert_unique` steps (`discover.py:1054-1090`) — it **never emits `parse_date`**, though the runner has supported it since forever (`recipe_schema.py:401`, `recipe_runner.py:292,704`). So the raw string `"1787617881"` reaches `_validated_posted_on` (`fetch_custom_company.py:152`), `datetime.fromisoformat` raises, and the function returns `None`. **That is the whole of the 0-of-2,055 mystery.**

**Changes**

- `services/capture/request_selector.py` — have the selector report the observed format of the mapped `posted_at` value (ISO / epoch-s / epoch-ms / relative-English / unknown).
- `services/capture/discover.py` — emit a `parse_date` step when the sampled value is not already ISO.
- `services/recipe_runner.py:704` `_parse_date_value` — epoch-seconds and epoch-milliseconds modes.

**The test that proves it:** a Microsoft-shaped payload writes a real `posted_on` on ≥95% of rows; epoch-s `1787617881` and epoch-ms `1787617881000` both land in 2026, not 1970 and not the year 58,000; a board publishing no date still writes NULL and **never** `now()`; an unparseable value still writes NULL rather than a guess.

**Dependency:** none, but **useless on its own** — see the sequencing note below.

**Deliberately out of scope:** `posted_at` is excluded from `_MULTI_VALUE_FIELDS` on purpose (`recipe_runner.py:167`, argued in `916d351`) — a posting has one publish date, so a list there is a mis-map. Do not fold it.

---

### Unit 12 — One shared posted-date sanity window (D5)

The two paths disagree today. The custom path uses `[now − 365d, now + 7d]` (`fetch_custom_company.py:168`); ticket 7.6 proposes `>= 2015-01-01` plus reject-future. There is no `2015-01-01` floor anywhere in the code today.

**My call: `[2015-01-01, now + 7d]`, in one helper both paths import.**

Why the wider floor: under D1 the date is frozen at insert, so a stale-but-real posted date is a *fact about the board*, not corruption. Production has genuine Greenhouse rows from 2019 — a 365-day floor NULLs them, and a NULL falls back to first-sight, which puts them straight into the day-one spike this whole workstream exists to remove. Keeping `now + 7d` rather than a hard reject-future absorbs clock skew and genuinely scheduled postings, and it is already the tested value.

Workday's fake sliding date is **not** handled here. It is handled by the per-company mapping decision — Workday, Google, Apple and TikTok map to first-sight — because a window cannot tell `today − 31 days` from a real date.

**Changes** — move `_validated_posted_on` to a shared `services/posted_date.py`; both paths import it. Repurpose the 365-day number: not a per-row delete, but a **per-harvest count of rows older than a year, recorded on `company_harvests`** as a company-level signal.

**The test that proves it:** a 2019 date survives (today it is NULLed — this is the behaviour change); a 2001 date is rejected; `now + 30d` is rejected; `now + 3d` survives; a naive timestamp is read as UTC; the stale-row counter increments without the row being dropped.

**Dependency:** pairs with unit 11 — same PR.

---

### Unit 13 — The chart reads `posted_on`; the recency sort does not

**Confirming the split.** They answer different questions, and that is the entire argument: `posted_on` is *"when did the company post this?"* — the chart's x-axis. `first_seen_at` is *"what's new to me?"* — the recency sort. Putting the sort on `posted_on` re-creates precisely the bug `8e71fad` (#215) fixed, where a job first seen an hour ago but posted years ago sinks to the bottom of "most recent".

**Changes**

- `src/frontend/src/lib/timeBucketing.ts:93` — bucket on `postedOn ?? firstSeenAt`.
- **Leave alone**, all of them: `graphFiltersSelectors.ts:42` (list sort), `recentJobsSelectors.ts:79`, `JobListingCard.tsx:33` ("Posted X ago"), `useTimeBasedJobCounts.ts:32-36`, `jobFilteringUtils.ts:390` (time-window filter), `date.ts:111`.

**The test that proves it:** a job with `postedOn` 60 days before `firstSeenAt` **buckets** on `postedOn` and still **sorts first** in "most recent" — one test asserting both halves, because the split is the thing being protected; a job with null `postedOn` buckets on `firstSeenAt`; the existing #215 regression tests stay green untouched.

**Dependency:** units 11 + 12 for the *recipe* path.

**This has the widest blast radius in the plan and that is why it gets its own PR.** `posted_on` is already populated for 91.1% of rows in production, so this changes every published company's chart the day it merges — before a single custom company exists. Review it on that basis, not as an E7 unit.

**Carry 7.6's D3 forward:** boards that publish no date fall back silently, so their day-one spike becomes *permanent* — in a year the chart still shows 235 Atlassian jobs "posted" 2026-08-25. That is the owner's call, it is reversible with a frontend change and no migration, and it should be visible in the PR description rather than discovered later.

---

### Unit 14 — The three one-liners

Folded in per Δ4, kept together because each is independently revertible and none is worth its own PR.

| | Change | Test |
|---|---|---|
| a | `backendScraperTransformer.ts:36` maps `department: details.experience_level`. The UI's Department filter has been showing **seniority** all along, and `details.department` reaches no screen | the transformer maps `department` from `details.department`, and a row with only `experience_level` gets no department |
| b | `details_scraped = true` lies — it is true for all 1,200 Cisco, 613 Intel and 11,901 Workday rows whose `description_html` is JSON `null` | the flag is true only when a description key is actually present |
| c | The enrichment writer's allowlist has **7** categories including `project_manager` (`enrichment_writer.py:29-39`); the enricher's taxonomy (v6) has **6** | the drift surfaces on the existing `warnings[]` channel rather than sitting silent |

**Dependency:** (a) is independent of everything. Do it whenever.

---

## 5. The sequencing trap

**The capture work and the chart work are separable but useless apart.** Units 11+12 alone ship *dark on the recipe path* — better `posted_on` values that nothing plots. Unit 13 alone has no recipe-path dates to plot. They must ship together, or unit 13 ships first and knowingly changes only the public companies (which is defensible, and is why it is its own PR — just say so).

The other ordering rule, in one line: **unit 1 merges before E7 turns on in production**, whatever else happens to the stack.

---

## 6. Invariant risk register

Four invariants in this system have named tests. Any PR touching one must name it in the description and must not weaken its test.

| Invariant | Where it is pinned | Units that go near it |
|---|---|---|
| **Never-wrong-close** | `test_fetch_custom_company_close.py` (whole module), `test_harvest_gate.py`, `test_recipe_runner_invariants.py:81-93` | 8 (re-capture changes what a harvest sees), 11 (touches the leaf task) |
| **RAISES-never-empty** | `test_recipe_runner_invariants.py:106`, `test_recipe_runner_determinism.py:123-208` | **4 (directly — put its test here)**, 11 |
| **Agent-free replay boundary** | `test_recipe_runner_import_guard.py:153,162`, `assert_no_agent_imports` (`recipe_runner.py:117`) | 7, 11 — both edit capture-side modules; keep the import direction one-way |
| **SSRF** | `test_url_guard.py:410`, `test_guarded_client.py:194,226` | 9 (new lookup on the add path — it must not become a new fetch), 10 (no outbound calls at all; it compares rows we already hold) |

**The two easiest ways to break something quietly here:**
1. Unit 10 fetching anything. It must read only rows already in the database — the moment it fetches a public board to compare, it is a new SSRF surface.
2. Unit 7 importing a capture module into the replay path. The boundary is enforced by an AST guard, not by convention, and `test_ast_guard_would_catch_a_planted_forbidden_import` (:303) exists because someone already worried about this.

---

## 7. Deliberately not in this plan

| | Why |
|---|---|
| **P1 dedupe — shared company rows, many owners** | Deferred by Δ6. There is exactly **one account** in the database, so every claim about two users sharing a board is reasoned from the schema, not measured. Δ7 also now constrains its design: under sharing, "Remove" means *stop showing me this* for every owner but the last, and the last one still deletes — the confirm-dialog copy has to change or it lies |
| **`lookup_join` / per-job detail fetch** | Costs ~10 min serial on the 2,055-job Microsoft board against a 600 s budget, and is flatly impossible on `browser_fetch` boards (90 s Chromium subprocess ceiling). Unit 6 covers 3 of 5 boards for zero extra requests. Unit 4 removes the trap it leaves behind |
| **Per-company round-robin (C) and eligibility cap (E)** | Rejected by the owner (Δ1). The consequence, on the record: **nothing bounds a single custom board.** At 10% you can have "everything eventually" or "no board monopolizes", not both. The cheapest thing that buys some of it back is units 9 and 10 — duplicates that never enter the queue cost nothing to drain |
| **The title-only agreement experiment** | Dropped by Δ3. If title-only quality is ever questioned, 16,693 production rows already carry both a description and a description-backed label; sample ~300, re-run title-only, compute agreement. Offline, no production change |
| **Workday `description_html`** | Hard-coded `None` (`workday_client.py:499`). Cisco and Intel are `transport='ats_client'`, not recipes, so unit 7 cannot reach them |

---

## See also

- `ENRICHMENT-TRADEOFFS.md` — the reasoning behind Δ1–Δ5 and the option matrix
- `custom-company-enrichment.html` — the annotated review artifact, with the full Decisions log
- `BUILD-PLAN.md:148` — where custom enrichment was originally deferred, on an API-spend argument that is now stale
- `TESTABLE-BOARDS.md` — the boards every coverage number here was measured against
- ClickUp [7.7](https://app.clickup.com/t/wdwb1cbq5t) · [7.6](https://app.clickup.com/t/wdwb1cbp8n) · epic `wdwb1cbnc2`
