# Custom Companies × the Enricher — trade-offs and decisions

**Status:** direction agreed, not yet built. Written 2026-08-25 from an owner review session on `feat/e7-phase3-discovery`.
**Ticket:** [7.7 — Custom-company jobs × the enricher](https://app.clickup.com/t/wdwb1cbq5t) (`wdwb1cbq5t`), a subtask of the E7 epic `wdwb1cbnc2`, beside 7.6.
**Evidence:** prod Postgres (read-only), dev DB `jobscraper_pr243` (read-only), a live re-probe of all five captured board endpoints, and the E7 source on this branch. No production code changed, no capture run.

> **This is the whole record now.** There used to be a companion `custom-company-enrichment.html` in this folder — a lavish review artifact, the surface the owner marked up. It was a review surface committed by mistake (`.lavish/` is gitignored for exactly this reason) and it has been deleted. Its unique evidence — the dedupe cohort data, the flag reference, the measured tick breakdown and the fleet inventory — was carried into **§9** below before it went.

---

## The problem, in one read

Custom-company jobs get **zero** enrichment rows. Not an allowlist. Not a company join. Not a different database.

The claim query has **no `source_id` filter at all**. Custom rows sit in the same table and satisfy every other predicate. Exactly one thing excludes them:

```sql
-- routers/internal_enrichment.py:181-196  (the claim)
UPDATE job_listings SET enrichment_status = 'claimed' ...
WHERE enrichment_status IS NULL AND status = 'OPEN'
  AND <DESCRIPTION_SQL> IS NOT NULL      -- ← the only thing excluding custom
ORDER BY CASE WHEN title ~* entry-level THEN 0 WHEN title ~* swe THEN 1 ELSE 2 END,
         first_seen_at DESC  LIMIT %s FOR UPDATE SKIP LOCKED
```

`DESCRIPTION_SQL` (`services/enrichment_monitor.py:40-44`) is a COALESCE over five JSONB keys — `description_html`, `content`, `content_html`, `description`, `about_the_job`.

Custom rows never populate any of them, because **the discovery prompt's field map is a closed 6-key object with no `description`** (`capture/request_selector.py`). **The blocker is the capture schema, not the runtime.**

> **Framing correction that matters:** prod has **zero** custom jobs today — the E7 flags are off there. This is a **design decision before launch**, not a live outage.

---

## The finding that decides the whole plan

**The descriptions are already in the list payloads we download and discard.**

| Board | Description-ish fields already in the list payload | Coverage | Avg chars | Verdict |
|---|---|---|---|---|
| **Atlassian** | `overview`, `responsibilities`, `qualifications`, `compensation` | 249/249 | **5,841** | **FREE** |
| **Amazon** | `description`, `description_short`, `basic_qualifications`, … | 10/10 | **4,528** | **FREE** |
| **Jane Street** | `overview` (HTML) | 231/231 | **2,753** | **FREE** |
| Microsoft | none — id, name, locations, postedTs, department, positionUrl | 0 | — | title-only |
| Spotify | none — id, text, categories, locations, job_type | 0 | — | title-only |
| Cisco, Intel | not recipes — `transport='ats_client'` → the shipped Workday client, which hard-codes `description_html: None` (`workday_client.py:499`) | 0 | — | needs Workday work |

Mapping them costs **zero extra requests**. `DESCRIPTION_SQL` already reads `details->>'description'`, so nothing downstream has to change to consume it.

---

## Decisions made

| | Decision | Call | Rationale |
|---|---|---|---|
| **Δ1** | Fairness mechanism for the claim query | **Option B — reserved share.** C and E **rejected**. | *"if we add E then it never will backfill everything."* C's reason was not recalled at the time; the reconstruction is in §9.2 and is still **awaiting confirmation**. |
| **Δ2** | `department` in the canonical recipe field set | **Dropped, then REVERSED** — the set now carries both it and `description`. | *"I don't think we need a department."* Traced every reader; cost was one hint field in the enricher payload. **The premise expired the same night** — see §3. |
| **Δ3** | Is title-only classification accurate enough to ship? | **Yes.** Agreement experiment **not** run. | *"I'm gonna say yes to this."* Closed by decision, not measurement — see the cost note below. |
| **Δ4** | The bugs found in passing | **Fold into this workstream**, not separate tickets. | *"Fold these fixes into your work."* They are units 6–9. |
| **Δ5** | Turn `enrichment_claim_without_description` on locally? | **No — deliberately not done.** | Nothing would change. No enricher points at the local DB; the flag only means anything in prod, where it is already on. |

### Δ1 has a consequence that is not yet accepted on the record

With **C and E both out, nothing bounds a single custom board.** Option B guarantees custom *gets* ~45 jobs/day; it says nothing about *which* custom jobs.

**A 47,000-job board would hold 100% of the custom slice for ~2.9 years**, and every other board would wait behind it.

That is not an argument to re-add E — E is a permanent ceiling, not a queue, and rejecting it was right. It is the honest statement of the trade:

> At 45 jobs/day you can have **"everything eventually"** or **"no board monopolizes"** — not both.

The cheapest thing that buys some of it back is **dedupe**: duplicates that never enter the queue cost nothing to drain.

### Δ3 does not remove work; it moves it

The labels are fine — `category` and `level` come out at **100%** coverage from a title alone. But title-only is the **more expensive** mode:

| Output | With description (16,693 rows) | Title-only (5,206 rows) | Meaning |
|---|---|---|---|
| `enrichment_category` | 100% | **100%** | no loss |
| `enrichment_level` | 100% | **100%** | no loss |
| `clean_description` | 0.3% empty | **99.9% empty** | gone — there is no text to clean |
| tags per job | 6.86 | **2.27** | −67%; 8.6% get zero tags vs 0.1% |
| `classify_confidence` | 0.85 | **0.50** | a hard clamp, not evidence |
| `needs_human` | 0.3% | **41–53%** | the real cost |

The 0.50 is `TITLE_ONLY_MAX_CONFIDENCE` in the enricher (`cli.py:36`), applied as `confidence = min(conf, 0.5)` — **5,016 of 5,055** title-only rows carry exactly 0.5. It tells you about the *policy*, not the *accuracy*.

And it has a cost you would not guess. The judge runs on `scope=low_confidence` with a ceiling of **0.85**. A clamped 0.50 is always below it, so **every single title-only row is force-judged** — an extra LLM pass at ~100 s, on a pipeline already busy 23–24 h/day. Fleet-wide only ~57% of rows get judged.

**Title-only rows burn more GPU while producing no `clean_description` and a third of the tags.** That is the strongest argument in this whole analysis for keeping custom second-class.

---

## Still open, ranked by what blocks the build

| # | Open item | Why it matters | Blocks |
|---|---|---|---|
| 1 | **Accept (or re-open) the unbounded-board consequence of Δ1** | A 47k board holds the slice for ~2.9 years | nothing — but it bites later |
| 2 | **D1 — the percentage for option B** | Unit 1 is a literal `LIMIT`; it needs a number. *Recommendation: 10%* (~45/day) | **unit 1** |
| 3 | **Confirm `enrichment_claim_without_description` is ON in prod** | Inferred from data, not read from env. Load-bearing for "ship the brake first" | **§ order of work** |
| 4 | **D3 — do title-only rows enter the needs-human queue?** | ~50% flag rate into a queue holding 1,725 rows against 68 ever corrected. *Recommendation: publish labels, exclude from queue* | shipping title-only |
| 5 | **Confirm the reconstructed argument against option C** | If wrong, the recorded rationale and the option-D upgrade path are wrong | accuracy of the record |
| 6 | **D4 — P2 dedupe first, or P1?** | *Recommendation: P2 alone, now* — P1 has zero users | **unit 2** |
| 7 | **D6 — can anything ever merge automatically?** | *Recommendation: no automatic merge, ever, at this stage.* The one least safe to reverse quietly | nothing yet |
| 8 | **D5 — what happens when the last owner leaves?** | Only meaningful under P1 (deferred). *Recommendation: orphan-and-keep* | deferred |
| 9 | **`CAPTURE_USE_BROWSERBASE=true` in the local env** | Unit 5 re-captures five recipes; each is a **billed** session | **unit 5** |

---

## The trade-offs, by axis

### 1. How to get a description

| Approach | Cost | Coverage | Verdict |
|---|---|---|---|
| **Map the list payload** | **zero extra requests** | 3 of 5 recipe boards | **chosen** |
| Per-job detail fetch (`lookup_join`) | see below | all boards | **rejected** |
| Title-only fallback | zero | the rest | **chosen** for Microsoft, Spotify, Workday boards |

**Why `lookup_join` is rejected.** Anchors are measured, not guessed: `HARVEST_TIME_BUDGET_S = 600`, `_TASK_TIMEOUT_S = 900` (`fetch_custom_company.py:96-120`). The Microsoft board is the worst case — **2,055 records, 206 pages, 61.5 s end to end**, ~0.30 s per request, serial.

| Strategy on the 2,055-job board | Extra requests | Added wall-clock | Total vs 600 s | Verdict |
|---|---|---|---|---|
| Today — list only | 0 | — | 61 s · **10%** | fits |
| Detail fetch, serial @ 0.30 s *(optimistic)* | +2,055 | +617 s | 678 s · **113%** | dies at deadline |
| Detail fetch, serial @ 0.60 s *(realistic)* | +2,055 | +1,233 s | 1,294 s · **216%** | dies at deadline |
| Detail fetch, 6-way concurrent @ 0.60 s | +2,055 | +206 s | 267 s · **45%** | fits, but… |
| Capped 300/night, serial @ 0.60 s | +300 | +180 s | 241 s · **40%** | fits (7 nights) |
| Steady state — only *new* jobs (~2%/night) | +40 | +24 s | 85 s · **14%** | trivial |

Two hard blockers on top of the arithmetic:

1. **browser_fetch boards are impossible** — `_SUBPROCESS_TIMEOUT_S = 90 s` for the *entire* Chromium subprocess. Not slow, not expensive: no room.
2. **The runner is synchronous** — `guarded_sync_client()` plus a sequential page loop. Concurrency means reworking the SSRF-critical guarded-client path, which is the last code in this system worth touching for a nice-to-have.

> **The trap to fix regardless.** `lookup_join` is declared-and-unbuilt: `_v_lookup_join` validates the shape (`recipe_schema.py:410-420`) but the op appears **nowhere** in `recipe_runner.py`, and `compile_plan`'s dispatch is an `if/elif` chain **with no `else`** (`recipe_runner.py:282-305`). A `lookup_join` step would validate cleanly on write, then be **silently discarded** at compile — a working scrape with no descriptions and no error anywhere. That is unit 6.

### 2. Fairness — how custom stays second-class

The capacity reality first: the enricher does **~450 jobs/day** (385–640 over 14 d) and is busy **23–24 h/day**. One tick claims 40, spends 2 h 10 m, returns 37. The public backlog is **16,269** OPEN unenriched rows and **never drains** at current throughput.

| Option | Mechanism | Starvation? | 47k-board blast radius | Outcome |
|---|---|---|---|---|
| **A. Strict priority** | one more arm in the `ORDER BY CASE` | **Total** — backlog never drains → 0 custom enriched, ever | none (nothing gets in) | not chosen — it is a non-feature |
| **B. Reserved share** | reserve `N%` of the batch for custom, filled by a second bounded pick | **None** — ~45/day at 10% | one board could eat the whole slice | **CHOSEN** |
| **C. Per-company round-robin** | `row_number() OVER (PARTITION BY source_id …)` | none | **bounded** | **rejected** |
| **D. Per-user quota** | partition by `user_id` via `user_companies` | none | bounded per user | over-engineering today (one account) — but it is the **upgrade path** for B+C |
| **E. Eligibility cap** | only the newest *K* OPEN jobs per company are claimable | partial by design | **hard ceiling** | **rejected** |

**Two things worth carrying into the implementation:**

- **The risk points the opposite way from the intuition.** The claim orders `first_seen_at DESC` within each tier, and a freshly added board's jobs are the **newest rows in the table** — so they sort to the **front**, not the back. Add a 12,000-job board tomorrow and on prod's current settings it takes the pipeline for **~27 days** while everything else waits. **Ship the brake before the accelerator.**
- **The original reason for excluding custom is stale.** `BUILD-PLAN.md:148` deferred it as an **API-spend** argument — *"they spend Claude Haiku per job."* The pipeline has since moved to local ollama/qwen3:32b, so the bill is gone. A different constraint replaced it — **wall-clock** — and it binds harder, because money scales and a single GPU does not.

**Implementation shape.** `source_id LIKE 'custom:%'` rather than a join: custom source ids are minted by `constants.custom()` with a validated id shape, so the prefix is exact. The `companies.visibility='user'` join is semantically purer and is what option D would use, but it costs a join on the hot claim path for zero behavioural difference today. **Index impact: none** — `idx_job_listings_enrichment_claim` is partial on `(first_seen_at) WHERE enrichment_status IS NULL AND status='OPEN'`, and both slices keep that predicate.

> **The symmetry already exists.** Custom companies are *already* second-class on the scrape side: 24-hour cadence vs the public 30-minute cron, a `*/15` claimer with `SKIP LOCKED`, and `oracle_kind='none'` meaning nothing they harvest can close a job. Making enrichment second-class in the same shape is consistent with the design, not bolted on.

### 3. Dropping `department` (Δ2)

Every claimed reader was traced, not assumed:

| Claimed reader | Reality | Cost of dropping |
|---|---|---|
| The jobs list API | **Does not read it.** The 2026-07-13 TOAST outage fix moved the list path off `details->…`; only `experience_level` and `is_remote_eligible` are denormalized (`db_models.py:73-85`) | none |
| The frontend Department filter | **Does not read it either** — `backendScraperTransformer.ts:36` maps `department: details.experience_level`. The UI's "department" has been showing seniority all along | none (and it is a bug in its own right) |
| The enricher's `/pending` payload | **The only real reader** — `internal_enrichment.py:69` ships it as a classifier hint | one hint field, custom rows only |
| `_cap_details` fallback | `fetch_custom_company.py:144` keeps it in the last-resort branch | none |

**The surgical version:** drop `department` from the **capture** schema so the LLM stops being asked to find it. **Leave the `details->'department'` read in `/pending` alone** — it is a no-op when the key is absent, and public ATS rows still populate it.

#### 3a. …and why Δ2 was reversed a few hours later

The table above is the whole argument, and row 2 is the load-bearing one: the Department filter **did not read this field**, so dropping it cost nothing a user could see. That row was true when it was written and false by the end of the same night.

Fixing the bug it names ("and it is a bug in its own right") is what changed the answer. The transformer was repointed at the real department, which exposed a second layer — `/api/jobs` builds `details` from denormalized columns only, so the key never reached the browser at all, `selectAvailableDepartments` returned `[]`, and the control hid itself. The fix denormalized a `job_listings.department` column (**migration `c1539fa03b23`**), fed from `details['department']` by the one job-write path. Prod: 20,671 of 32,014 open rows carry a real department across 120 companies.

So the reader row now reads **"a user-facing filter"**, and a recipe that maps no department writes NULL into that column on every upsert (`_UPSERT_ON_CONFLICT`: `department = EXCLUDED.department`). Measured on the dev DB after the first re-capture under the six-key set:

| board | rows with `department`, before → after |
|---|---|
| Microsoft | 2,217 → 139 |
| Atlassian | 244 → 13 |
| Jane Street | 235 → 4 |
| Spotify | 86 → 9 |

The set now carries **both**. This is not a revert of the `+description` half — that stands, and `description` is still the field that wins any conflict over the `details` byte budget (`fetch_custom_company._DEPARTMENT_MAX_BYTES` bounds the cheap one so it can never shrink the expensive one).

### 4. Deduplication — two problems wearing one name

| | Problem | Today | Fix |
|---|---|---|---|
| **P1** | Two users add the same board | 2 `companies` rows, 2 scrapers, 2 `custom:<id>` job sets, no shared history | shared row + many owners. **Hard** — privacy, deletion and merge-safety all move |
| **P2** | You add a board you already publish | exactly what happened with Spotify: a private copy alongside a public company with **55 days** of history | **resolve → link.** One lookup against the 129 public rows. No schema change |

**P2 first.** P1 is designed but deferred: there is exactly **one account** in the database, so every claim about two users sharing a board is reasoned from the schema, not measured.

**The URL is not the identity** — the Spotify row proves it. And **no automatic merge** (D6): two identical captured endpoints may link *at add time, with the user watching*; everything else is a suggestion.

---

## Order of work

> **Superseded by `IMPLEMENTATION-PLAN.md` (2026-08-25).** The table below is the order as first proposed. The plan is the one scoped to the live PR stack — it drops the units that have since shipped, routes each remaining unit to a specific PR, and carries Δ6–Δ8 (dedupe confirmed as the priority, last-owner delete, local config mirrors production). Build from the plan; keep this table for the reasoning behind each unit.

Each unit is independently shippable and independently revertable. Units 6–9 are the Δ4 fixes.

| # | Unit | Why here | Size |
|---|---|---|---|
| 1 | **Fairness — Option B in the claim query** | Ship the brake before the accelerator. On prod settings the description guard is already off, so enabling E7 without this lets custom claim at full priority. **B only** — no round-robin, no cap | ~25 lines + tests |
| 2 | **P2 dedupe — resolve-and-link to a published company** | One `SELECT` against the 129 public rows on the add path, plus a UI branch. Best value-per-line in the plan | ~1 day |
| 3 | **`_cap_details` learns about `description`** | Must land before recipes emit descriptions, or the first ones are eaten by the 8 KB fallback. HTML-strip, truncate, never silently drop | ~30 lines |
| 4 | **Capture schema: `+description`, `−department`** | The value. Turns Atlassian / Amazon / Jane Street into first-class-quality enrichment for free | ~7 lines |
| 5 | **Re-capture the 5 existing recipes** | Ops, not code. **Each is a billed Browserbase session** | ops |
| 6 | **Fix the `compile_plan` silent drop** — `else: raise` | A valid-but-unrunnable op vanishes without a trace today | ~3 lines |
| 7 | **HTML-unescape mapped recipe fields** | 19 of 85 custom Spotify titles carry a literal `&amp;`. Breaks dedupe comparison and renders wrong | ~5 lines |
| 8 | **Map `location`; fix the dropped `posted_at`** | 0 of 2,055 Microsoft rows have either, though the payload carries both. Coordinate with the location branch | investigate first |
| 9 | **Frontend `department` mis-mapping + `details_scraped` + taxonomy drift** | Three one-liners (see below) | ~10 lines |

**Sizing the description cap:** Atlassian's combined text averages 5,841 chars but tops out at **10,368** — over the 8 KB blob budget. Stripping HTML typically halves it. Budget ~6 KB of *plain text* and **truncate rather than drop**; the classifier's signal is overwhelmingly in the first few hundred words.

---

## Found in passing (folded in, per Δ4)

| Kind | Finding |
|---|---|
| Data | **Microsoft recipe maps `posted_at`, gets nothing.** The recipe maps `posted_at: "postedTs"` and the payload carries `postedTs` — yet **0 of 2,055** rows have `posted_on`. Something between mapping and `_validated_posted_on` drops it |
| Data | **Two boards map no location at all.** Microsoft carries `locations`, Atlassian carries `locations[0]`, neither recipe maps it → **0/2,055** and **0/235** |
| Trap | **`details_scraped = true` lies.** True for all 1,200 Cisco, 613 Intel and 11,901 Workday rows whose `description_html` is JSON `null` |
| Drift | **The taxonomy has drifted between the two repos.** JVN's writer allowlist has **7** categories including `project_manager` (`enrichment_writer.py:29-39`); the enricher's taxonomy (v6) has **6**. Documented as needing to match exactly |
| Data | **Recipe titles keep raw HTML entities.** 19 of 85 custom Spotify titles stored as `Client Partner, Emerging &amp; Scaled` |
| Bug | **The UI's "Department" is really the experience level** (`backendScraperTransformer.ts:36`) |
| Hygiene | **A custom company with 100 jobs and zero owners** — `u-6hkpc6fh0z` has no `user_companies` row. Every add path creates ownership with the company, so this should be unreachable |
| Waste | **~3 jobs per tick die on a timeout.** Every recent tick logs `ollama call failed (qwen3:32b): timed out` at the 300 s ceiling — `claimed=40 → classified=37`. ~7% of a saturated pipeline spent twice |

---

## What we could not determine

| Open question | Why it is open | How to settle it |
|---|---|---|
| Is title-only actually accurate? | Closed by **decision** (Δ3), not by measurement. The number was never produced | 16,693 prod rows already carry both a description and a description-backed label. Sample ~300, re-run title-only, compute agreement. Offline |
| Is `enrichment_claim_without_description` definitely ON in prod? | **Inferred** from data (Workday: 0 OPEN rows with a description, 139 enriched in 24 h), not read from Railway env | One direct env check. Worth doing **before unit 1** |
| Does the 70% title-overlap dedupe bar hold beyond Spotify? | n = 1. One duplicate pair measured at 86%; no idea what a genuine near-miss scores | Pairwise comparison across the 129 public companies; look at the *false*-pair distribution |
| Everything about two users sharing a board | Exactly **one account** exists. All P1 reasoning is from the schema | Cannot be settled without a second user. Main reason P1 is deferred |
| Does the enricher use the `department` hint? | The classify prompt is laptop-side, not in this repo | One grep on the enricher repo. Low stakes either way |
| How much does HTML-stripping shrink these? | Raw char counts only (Atlassian max 10,368); never run through a stripper | Strip the 249 Atlassian records, take the p99. Trivial during unit 3 |
| Whether D3's fix belongs in JVN or the enricher | The clamp and judge routing are both **laptop-side** (`cli.py:36`, `judge_confidence_ceiling: 0.85`) | Decide D3 first. If the answer is "don't judge title-only rows", it is a **knob in the enricher**, not code here |
| Whether qwen3:32b is being silently truncated | `num_ctx` is **never set** on the ollama call (`engines/ollama.py:36-45`), so the model default applies. A 6,000-char description plus a ~160-line taxonomy is well past a 4K default | Print the effective context and compare against a rendered prompt. If it *is* truncating, description-backed quality is worse than it looks and the title-only gap narrows — which would change D3 |

---

## Feature flags in play

There is **no flag service.** All backend flags are plain `pydantic-settings` booleans read from the environment at process boot (`src/backend/api/config.py`). Changing one requires a restart.

| Flag | `config.py` | Default | Owner's local | Gates |
|---|---|---|---|---|
| `scraper_detail_scrape` | `:14` | **True** | not set | Per-job detail fetching in the legacy scrapers. **The only flag on by default.** |
| `enrichment_use_external` | `:60` | False | — | **Master.** Gates `/pending` only — with it off the enricher is handed nothing |
| `enrichment_require_judge_pass` | `:72` | False | — | `/results` holds judge-flagged rows as `needs_human` instead of publishing |
| `enrichment_claim_without_description` | `:79` | False | — | Drops the `<DESCRIPTION_SQL> IS NOT NULL` predicate. **Inferred ON in prod** from the data (Workday: 0 OPEN rows with a description, 139 enriched in 24 h) — never read back from Railway env |
| `custom_company_sources_enabled` | `:88` | False | — | The whole E7 feature. Off → routes 503 |
| `custom_company_discovery_enabled` | `:105` | False | — | Capture discovery — the **single** discovery flag |
| `capture_use_browserbase` | `:119` | False | **true** | **Costs money.** Runs discovery capture in Browserbase instead of our own headless Chromium. Bills per browser-hour; buys a stealth profile and the live-view URL the progress UI embeds. Sessions TTL-capped at 300 s |

Frontend (Vite):

| Flag | Value | Gates |
|---|---|---|
| `VITE_CUSTOM_COMPANIES_ENABLED` | true | The "Add Companies" nav item and the `/add-companies` routes. Off → no route registered at all |
| `VITE_DISCOVERY_PROGRESS_ENABLED` | true | The 4-step discovery checklist UI instead of a bare "Setting up…" badge |

---

## 9. Evidence carried over from the deleted review artifact

The `custom-company-enrichment.html` review artifact was removed from the repo (a lavish
review surface is not repo content). Everything below existed only there. Two of its
recorded decisions have since been **overturned and must not be read as live**:

- **Δ2 "drop `department`" was REVERSED.** The Department filter was found silently dead
  hours later and fixed with a denormalized `job_listings.department` column
  (migration `c1539fa03b23`). See §3a. Cost measured before the re-capture:
  Microsoft 2,217 → 139 rows with a department, Atlassian 244 → 13, Jane Street 235 → 4,
  Spotify 86 → 9.
- **D5 "orphan-and-keep" was OVERRULED** by Δ7 in `IMPLEMENTATION-PLAN.md`, which says
  **DELETE**. P2 dedupe has also since shipped (`services/published_board_match.py`,
  `AlreadyPublicNotice.tsx`, `outcome='already_public'`).

### 9.1 The measured shape of one enrichment tick (prod tick 3043)

The enricher claims `enrich:per_tick_limit = 40` jobs, spends **2 h 10 m**, and sends back
**37**. Classify is **153 s/job**, judge **100 s/item**; cleaning and write-back are noise
(**2 ms** and **1.4 s**). About **3 jobs per tick** are lost outright to the 300 s ollama
timeout and retried later. **37 classified → 21 judged** in that tick. So a 10% custom
share = 4 jobs per tick ≈ **44/day**.

Fleet shape at the time: **129 public companies · 8 custom** (7 owned, 1 orphan) ·
**9 public `source_id`s · 7 custom**. The dev DB held **4,523 custom jobs across 7 boards,
zero with any description key**; prod held **21,899** enrichment rows and **0** custom jobs.
**2,610 of 4,523 (58%)** custom rows carried a `department` — Microsoft, Atlassian, Jane
Street and Spotify have it; Cisco, Intel and Amazon do not. `details_scraped = true` lies on
**13,714** rows in total.

Already running in prod: `enrichment_claim_without_description` is ON, and Workday +
Eightfold (0% description) are classified title-only at **~130 jobs/day, about 28% of total
output** — **5,206** title-only rows against **16,693** description-backed ones.

Backfill shape, if per-job detail fetching were ever built: only new jobs need a
description, so backfill is a one-time O(N) spike and steady state is O(Δ). A 2,055-job
board backfills in **a week**; a **47,000-job board takes 157 nights**. A detail page is
HTML, typically **5–10× the bytes** of a list row, so 0.3 s/request is the optimistic floor
and 0.6 s the realistic case.

Four sampled title-only classifications — the only qualitative evidence behind Δ3:

| Title | Category | Level | Confidence |
|---|---|---|---|
| Sr. Office Manager | `business_ops` | senior | 0.50 |
| Business Analysis Manager — EP Strategy & Analytics | `business_ops` | manager | 0.50 |

(Both land on the `TITLE_ONLY_MAX_CONFIDENCE` clamp of 0.50 rather than on evidence.)

### 9.2 Why option C was rejected — the reconstruction

Recorded because Δ1's rationale for rejecting C was not recalled at the time.

> C spreads the slice across boards, but every board belongs to one person — you. Four jobs
> a tick split seven ways means no board is ever finished; all seven sit permanently
> half-labelled. **And a half-labelled board is worse in the UI than an unlabelled one,
> because the category and level filters silently drop the unlabelled half without saying
> so.** Finishing Spotify in two days and then starting Atlassian is strictly better for a
> single user. C only starts paying when there are many users — and then the right partition
> key is `user_id` (option D), not `source_id`.

Two more options were killed outright and are not in the §5 matrix:

- **"Off-peak only" does not exist.** The enricher runs 23–24 hours a day; there is no
  off-peak window to schedule into.
- **"Opt-in" does not solve fairness**, it just renames who gets starved. The public backlog
  never drains at current throughput, so strict priority means custom jobs are enriched
  **never** — not "eventually", not "slowly". Zero.

### 9.3 Deduplication — the one-board-many-owners problem

**What deduping exists today.** Everything is inside one harvest of one company. Nothing
compares two companies, and nothing compares two users.

| Mechanism | What it does | Scope | Where |
|---|---|---|---|
| `dedupe_key` | Recipe op declaring the record key. Validated on write; one field only. | one harvest | `recipe_schema.py:423` |
| Gate check 7 | The real dedupe — walks rows in document order, keeps the first occurrence of each id, records `id_dedup_dropped`. | one harvest | `harvest_verification.py:183-191` |
| `assert_unique` / check 8 | Backstop: re-checks uniqueness after the dedupe, raises `HarvestGateError`. A logic-error tripwire, not a data path. | one harvest | `harvest_verification.py:193` |
| `id_dedup_dropped` | Persisted per harvest. Observability only — nothing reads it back. | one harvest | `db_models.py:810` |
| `(source_id, id)` composite PK | Says the *opposite* of dedupe: a job id is not globally unique and two boards may legally carry the same one. | one source | `db_models.py:96` |
| `UNIQUE(user_id, canonical_source_key)` | The only idempotency that exists — one user re-adding a board resolves to their existing row. | one **user** | `db_models.py:749-752` |
| `find_owned_company_by_source_key` | The lookup behind it; its WHERE is `uc.user_id = %s AND uc.canonical_source_key = %s`. | one **user** | `custom_companies_service.py:43-59` |
| Across users / across companies | Nothing. Not a table, not a column, not a query. | — | — |

This is deliberate, and `db_models.py:726-729` states it: two different users who add the
same board get two DISTINCT company rows (and two `custom:<id>` `source_id`s). Commit
`7a5a57b` left the door open on purpose — `remove_owned_company` already counts remaining
owners and returns `'unlinked'` without purging when any remain
(`custom_companies_service.py:936-943`).

**The URL is not the identity — the Spotify pair proves it.**

| Signal | Public Spotify | The custom Spotify | Match |
|---|---|---|---|
| Row | `lever_api/spotify` — 191 jobs, 89 OPEN, history from 2026-07-01 | `custom:u-ibr09efe5d` — 85 jobs, 85 OPEN, from 2026-08-25 | — |
| Host | `jobs.lever.co` | `www.lifeatspotify.com` | ✕ |
| Registrable domain | `lever.co` — the *vendor's* | `lifeatspotify.com` | ✕ |
| Jobs feed | `api.lever.co/v0/postings/spotify` | `api.lifeatspotify.com/wp-json/animal/v1/job/search` | ✕ |
| Job id shape | UUID — `a0fa7da3-4c3c-4fa2-…` | slug — `senior-backend-engineer-podcast` | ✕ |
| `display_name` | Spotify | Lifeatspotify (auto-derived from the host) | ✕ |
| OPEN title set | 81 unique | 77 unique | **70 · 86%** |

`lifeatspotify.com` and `lifeatspotify.com/jobs` were fetched and grepped for every ATS host
the L2 sniffer knows (`lever.co`, `greenhouse.io`, `ashbyhq`): **zero hits in 52 KB of
HTML**. No link, no script tag, no embedded reference — **L2 can never connect these two**,
no matter how many sub-paths are added to `_SNIFF_SUBPATHS`.

The four ways URL identity fails, each with a real example:

| Failure | Real example | What breaks |
|---|---|---|
| Vendor domain vs own domain | `boards.greenhouse.io/spotify` · `lifeatspotify.com/jobs` · `spotify.com/careers` | One string is the vendor's domain, so the registrable domain carries no company information. Host-based grouping puts every Greenhouse customer in one bucket. |
| Boards move hosts | ByteDance → `joinbytedance.com`; Microsoft → `apply.careers.microsoft.com`; Shopee → `careers.shopee.sg` | Yesterday's key is today's dead URL. L1 redirect-following fixes the forward direction only while the redirect lives. |
| Overlapping but not equal | The Jane Street row: `?type=experienced-candidates&location=new-york`, 235 jobs | A filtered board and the full board are not the same source even on one host. **Query-stripping is not a normalization improvement here — it is a correctness bug.** Merge them and the full board's harvest gate starts closing jobs the filtered board never claimed to see. |
| One host, two boards | Two Greenhouse tokens (eng + sales), or two Workday slugs on one tenant | Same origin, different board. Origin alone is too coarse; the token/slug is the identity and lives in the path. |

**The captured endpoint as identity.** The Spotify row's
`provider_config.discovery.network.requests[]` holds **14 recorded URLs**, exactly one marked
`"state": "chosen"` (`api.lifeatspotify.com/wp-json/animal/v1/job/search`, status 200,
85 records). It beats the entry URL because it is what the board *is* rather than what a
marketing page links, it is proven by replay rather than guessed, it survives a front-end
host move, and it is already persisted. It still fails on: the Spotify case itself (two
different, both-real endpoints); two tenants behind one multi-tenant feed host (the tenant is
in a query param and which param is tenant-bearing is not derivable); an API version bump
(`/v1/` → `/v2/`) reading as a brand-new board; and ATS-resolved boards, which have no
captured endpoint at all and use `ats:token` anyway. **Verdict: a P1 key, not a merge
oracle.**

**The four mechanisms, and why only two are acceptable:**

| Option | Mechanism | Cost of a wrong merge | Verdict |
|---|---|---|---|
| 1. Shared row, many owners (P1) | Drop "one `companies` INSERT per `user_companies` INSERT"; a second owner is one INSERT. | **High** — one shared job history, corrupted for everyone, no undo. | Build next, gated behind the confidence bar. |
| 2. Canonical-identity table | Add `board_identities` + `company_id → identity_id`; scrape once per identity, fan rows out per company. | Low — un-merging is one UPDATE. | **Argued against hardest.** It buys back 33 seconds of browser time and leaves every duplicate row in the enrichment queue — the expensive half. It also adds *writers*, which is the real reason to prefer 1. |
| 3. Resolve-and-link (P2) | Pasted URL resolves via L0/L1/L2 to `(ats, board_token)`; look it up in `companies WHERE visibility='public'`. On a hit, return a link and create nothing. | **None** — worst case the user clicks "track it anyway". | **Always, and first.** No schema change, no privacy question, no deletion question. |
| 4. Merge-on-detect | Background job compares job sets across companies and merges above a threshold. | **Highest** — merges happen unobserved, at 3am, on data nobody is looking at. | **Never.** No un-merge, no merge audit, no way to tell afterwards which rows came from which board. |

**The privacy leak that row-sharing would open.** `provider_config.discovery` is returned to
the owner and contains the first user's Browserbase `live_view_url`, their full **14-entry**
captured request log, and a raw job sample. Under sharing that blob would go to *every*
owner. Also never expose the owner list, or `company_add_attempts` (it carries `user_id` +
the raw submitted URL). **Fix the `provider_config` projection before sharing ships.**
What legitimately becomes a shared fact: `open_job_count`, `health_state`, `last_success_at`,
`tracking_started_at` — B learns somebody tracked it, not who.

**What dedupe is actually worth** — measured against the real Spotify duplicate. Browserbase
is the *smallest* line; the money is in the enrichment queue.

| Cost avoided | Per duplicate board | Spotify, measured |
|---|---|---|
| Browserbase session at add | one capture — **33–95 s** measured (Spotify 33 s, Atlassian 33 s, Microsoft 95 s) | 33 s |
| LLM spend at add | one request-selection call | 1 call |
| Recurring browser time | **zero** — all 7 boards replay as `http_json` or `ats_client` | 0 |
| Recurring harvest | one extra board on the 24 h cadence, forever | 85 rows/night |
| Duplicate rows in the enrichment queue | = board size, one-off | 85 |
| Custom slice consumed | at 10% of a 40-job tick ≈ 45 jobs/day | **~1.9 days of the entire custom budget** |
| GPU wall-clock | 153 s classify + 100 s judge per title-only row | **~6.0 h** |

And duplicates go to the **front**, not the back: the claim orders `first_seen_at DESC`
within each tier (`internal_enrichment.py:187-193`), so a duplicate board's rows are by
construction the newest rows in the table.

**Row inventory at the time:** Microsoft 2,055 · Cisco 1,200 · Intel 613 · Atlassian 235 ·
Jane Street 235 · Amazon 100. Plus the orphan `u-6hkpc6fh0z` ("Amazon (live check)") with
100 jobs and zero owners — a state the model says cannot exist, produced by a test path,
`enabled=false` so nothing scrapes it.

---

## See also

- `BUILD-PLAN.md` — where custom enrichment was originally deferred (line 148, on the now-stale API-spend argument)
- `CAPTURE-IMPLEMENTATION-PLAN.md` — the capture pipeline whose field map is the blocker
- `IMPLEMENTATION-PLAN.md` — **the build order**, scoped to the live PR stack
- `TESTABLE-BOARDS.md` — the boards the coverage table was measured against
