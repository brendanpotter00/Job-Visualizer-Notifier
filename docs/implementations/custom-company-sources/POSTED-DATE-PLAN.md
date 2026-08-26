# Posted dates, fleet-wide — implementation plan

**ClickUp [7.6](https://app.clickup.com/t/wdwb1cbp8n) (`wdwb1cbp8n`) · epic `wdwb1cbnc2`**
Companion artifact: `.lavish/posted-date-accuracy.html` (decisions D1–D12).

**One question:** what date does the product show, and where does it come from — for every
source, published and custom alike.

**Pointers name the function or constant wherever one identifies the spot. Where a line number
survives, treat it as approximate — the symbol or quoted text beside it is authoritative.**

> **Supersedes** units 11–13 of `IMPLEMENTATION-PLAN.md` (enrichment/dedupe workstream). Its
> unit 13 predates D9 and recommends the opposite of what was decided. Units 11 and 12 are
> absorbed here as U6 and U1.

---

## 1. The decisions

**D9 — the recency sort follows the posted date.**

> "I don't care if it's new to you. I want to know if it's **new to the company that posted
> it**. The goal is to get the user to apply to jobs the company **just posted**."

**D10 — reuse `first_seen_at`. No new column.**

> "Why would you do that? Right now we use `first_seen_at`. Why can't we just reuse that field?"

**D12 — boards that never refresh their dates: not solving it.**

> "That doesn't matter. When we are first adding a company, we cannot fix that. That's fine …
> If a job board happened to reuse all their job listings from 2009, **that's their problem**.
> Ultimately we will iron this out by keeping the job board around and monitoring it every hour."

**Consequence, in one line:** a board that never refreshes its posting dates will show old
dates on jobs it re-lists, and we accept that.

**Deleted, not deferred** (D12): the per-row credibility ceiling, the two-sided age-spread
metric, per-company trust verdicts, the `source_date_quality` table, and the
`companies.posted_date_policy` column. All of it existed to solve one board.

**C1 — backfilling the 133 existing companies: DEFERRED**, tracked as
**[7.8](https://app.clickup.com/t/wdwb1cbq60)**. They keep their day-one spikes until it is
picked up. Nothing in this build depends on it.

**C2 — the enricher stays on `first_seen_at`** and its meaning changes with the column:
freshest-posted gets enriched first. A newly onboarded board's *old* jobs now sink in the queue
instead of jumping it — which **reinforces** the fairness brake that merged in `7340cfc`
(PR #266) rather than fighting it (`internal_enrichment.py:335-341`). `internal_enrichment.py`
is untouched.

### D12 verified — all three claims tested, not agreed with

> "I think `posted_on` is going to be more accurate at onboard time for most companies than for
> this edge case, and this doesn't matter. **Is that correct?**"

**Yes.** Measured fleet-wide: **96 of 108 companies (89%)** carry an accurate board-supplied date
at onboarding — median within one day of when we actually saw the job, under 5% stale.
**4 of 108 (3.7%)** recycle listings the way Palantir does.

| Claim | Verdict | Evidence |
|---|---|---|
| "We can't account for it" | ✅ **Confirmed** | Nothing at onboarding separates a genuinely-old-but-open job from a recycled one. The board asserts the date; on day one there is no second source. |
| "It solves itself by running the scraper a long time" | ✅ **Confirmed** for the part that matters | The onboarding batch decays with watch time — see below. The recycling *rate* on a bad board does not decay; it dilutes. |
| "`posted_on` is more accurate at onboard time for most companies" | ✅ **Confirmed** | 96 of 108 companies. |

**The onboarding batch really does wash out** — share of a board's currently-open jobs still
inherited from its onboarding day, by watch time:

| board | days watched | still inherited |
|---|---:|---:|
| google | 234 | **2.8%** |
| apple | 222 | **16.8%** |
| spacex | 101 | 21.6% |
| zoox | 98 | 37.2% |
| databricks | 101 | 46.2% |
| palantir | 98 | 55.8% |

**Board-supplied date vs. our own observation**, for rows that arrived *after* we were already
watching (so first sight is ground truth):

| source | rows | median lag | within ±1 day | >1y stale |
|---|---:|---:|---:|---:|
| greenhouse_api | 9,015 | 0.0 d | 94.9% | 1.1% |
| apple_scraper | 2,773 | 0.0 d | 88.3% | 0.2% |
| gem_api | 28 | 0.0 d | 89.3% | 0.0% |
| amazon_scraper | 294 | 0.8 d | 83.0% | 0.0% |
| ashby_api | 3,181 | 0.0 d | 78.7% | 1.9% |
| microsoft_scraper | 461 | 0.0 d | 70.7% | 0.0% |
| eightfold_api | 379 | 0.9 d | 56.5% | 0.8% |
| **lever_api** | 355 | 0.1 d | 63.4% | **16.6%** |
| workday_api *(the `30+` fabrication, not staleness — U5a removes it)* | 4,953 | −4.1 d | 44.8% | 0.0% |

`lever_api` is the only source with a meaningful stale rate, and it is **Palantir inside it** —
Zoox on the same ATS is clean.

### The residual we accept — bounded and named

| board | post-onboarding rows | >1y stale |
|---|---:|---:|
| **palantir** (lever) | 136 | 41.2% |
| merge (ashby) | 15 | 33.3% |
| astranis (greenhouse) | 44 | 20.5% |
| appliedintuition (ashby) | 302 | 15.9% |

*merge* and *appliedintuition* are two of the five boards PR #236 repointed, so part of their
number is a board switch rather than recycling.

**What we accept, in one line:** on these four boards a re-listed job will show the date the
board last stamped it, which can be over a year old. That is their data being wrong, not ours,
it affects 3.7% of companies, and it needs no code.

---

## 2. The shape

`first_seen_at` is written **once, at INSERT**:

```
first_seen_at = the provider's posted date, when the provider gives us a real one
              = now()                      otherwise          <- today's behaviour
```

It stays absent from `_UPSERT_ON_CONFLICT` (`scripts/shared/database.py`), so the
reopen guarantee is untouched and the value never moves after insert.

| Column | Means | Read by |
|---|---|---|
| **`first_seen_at`** *(repurposed)* | the **effective posted date** | everything a person sees, the keyset, the enricher — **all unchanged code** |
| `created_at` *(unchanged)* | when we inserted the row | the audit trail; makes seeding reversible |
| `posted_on` *(unchanged)* | the raw board value | diagnostics only |

**Why not a new column (D10).** The sort key must be NOT NULL and immutable, which rules out
`posted_on` (8.9% NULL, rewritten every upsert) — but `first_seen_at` already satisfies both
(**0 of 78,278** prod rows have ever had it move). Three objections were checked and none
survived:

| Objection | Verdict |
|---|---|
| The `job_freshness` trigger seeds `last_seen_at` from `NEW.first_seen_at` | **No.** Already overwritten two statements later — every upsert path calls `_upsert_freshness` in the *same transaction* (`_upsert_freshness`, called from both upsert paths in `scripts/shared/database.py`). Only full-scrape mode (`run_scraper.py`, `use_upsert=False`) relies on the trigger seed. And the close sweep is `consecutive_misses >= threshold` (`get_jobs_exceeding_miss_threshold`, `scripts/shared/database.py`) — **no time-based close exists**, so a stale `last_seen_at` cannot wrong-close anything. Fix = one line (U2). |
| The default ordering is `last_seen_at DESC` (`_LEGACY_ORDER_BY`, `src/backend/api/services/database.py`) | **No.** Purely downstream of the trigger. |
| The enricher claim sinks backdated rows | **Backwards** — today a new board's rows sort to the *front* and seize the queue. See C2. |

**What D10 deletes:** a migration on a 78k-row table, the entire keyset/cursor change (no new
index, no golden-SQL rewrite, no cursor versioning), the API field, and the whole frontend diff.
The eight surfaces #215 moved already read `firstSeenAt`; their tests stay true and green,
because the change is entirely write-side.

### What D9 costs, measured

Prod, open rows, excluding onboarding batches, newly seen in the last 7 days:

| | rows | share |
|---|---:|---:|
| Provider date also within 7 days — **sort identical either way** | 2,515 | 91.2% |
| Provider date NULL (all `google_scraper` + `tiktok_scraper`) | 195 | 7.1% |
| Provider date 8+ days older | 48 | 1.7% |

**48 rows a week move down.** A missing date is a property of the **source**, not the row —
zero NULLs for every ATS source.

### #215 is narrowed, not reversed

Its **backend half** (the enricher claim) survives — see C2. Its **frontend half** conflated
two populations, and #215's headline statistic is dominated by the first:

| Open rows | count | >180d older than first sight | >30d older |
|---|---:|---:|---:|
| Onboarding batch (source's first 2 days) | 9,247 | **17.1%** | **54.4%** |
| Steady state | 22,823 | 2.6% | 5.8% |

---

## 3. What counts as a date

**No measurement, no scoring, no allowlist, no trust table.** The rule is one sentence:

> **If the board gives us a bucket instead of a date, we do not have a date.**

That is enough because **the only board whose dates we distrust is one whose dates we fabricate
ourselves.** Workday's `_parse_workday_date` (`workday_client.py`) turns a relative
English string into a precise-looking timestamp. Its branches:

| Workday string | Today | Should be |
|---|---|---|
| `"Posted Today"` | today midnight | ✅ accurate — keep |
| `"Posted Yesterday"` | today − 1d | ✅ accurate — keep |
| `"Posted N Days Ago"` | today − N | ✅ accurate — keep |
| **`"Posted 30+ Days Ago"`** | **today − 31d** | ❌ **a bucket boundary, not a date → `None`** |

The `is_plus_range` branch already exists as a separate code path — the `+` capture group of `_DAYS_AGO_RE`. Making
it return `None` is the entire Workday fix — **three lines, one function** (U5a).

**Measured on prod:** 2,730 of 6,461 open Workday rows (**42.3%**) sit in the fabricated `30+`
bucket and fall back to first sight; the other **57.7%** keep genuinely accurate dates. That is
strictly better than distrusting Workday wholesale — and the population it keeps accurate is
exactly the recent one D9 cares about.

**The recipe path gets the same rule for free.** A humanized relative string already parses to
`None` (the `humanized` branch of `_parse_date_value`, `recipe_runner.py`). That was previously filed as a bug ("a declared no-op");
under this rule it is **correct as written** and needs no change.

**Everything else already behaves.** Google and TikTok return `None`. The five real-date clients
(Greenhouse, Ashby, Lever, Gem, Eightfold) store `NULL` on parse failure and never fall back to
`now()`.

---

## 4. Per-source behaviour

**Onboarding** = the first INSERT for a `(company, source_id)` pair — which also covers the
**board-switch** case (PR #236 stamped 403 rows across 5 companies).

**No first-run predicate is needed.** `first_seen_at` is only ever written at INSERT, so "seed
at insert, always" cannot rewrite an existing row. This removes ClickUp 7.6's HIGH-risk
first-run detection entirely. In steady state the provider date ≈ now anyway (median skew 0.0 d).

| Source | Provider field | Behaviour |
|---|---|---|
| **Greenhouse** | `first_published` ‖ `updated_at` (`greenhouse_client.py`, `posted_on_raw`) | provider date. *U5d records which field was used* |
| **Ashby** | `publishedAt` (`ashby_client.py`, `posted_on_raw`) | provider date |
| **Lever** | `createdAt` unix-ms (`lever_client.py`, `created_at_ms`) | provider date. Never refreshed — old dates pass through, accepted by **D12** |
| **Gem** | `first_published_at` ‖ `created_at` (`gem_client.py`, `raw_posted`) | provider date |
| **Eightfold** | `t_create` unix-s (`_parse_eightfold_epoch`, `eightfold_client.py`) | provider date. *U5c: only client that NULLs silently* |
| **Workday** | `postedOn`, relative English (`_parse_workday_date`, `workday_client.py`) | **57.7% accurate provider date; the `30+` bucket → first sight** (U5a) |
| **Google** (script) | none — hardcoded `None` (`transform_to_job_model`, `google_jobs_scraper/scraper.py`) | first sight |
| **Apple** (script) | list mode extracts `posted_date` but the transform reads `posted_on` and drops it (`_parse_job_element` in `apple_jobs_scraper/parser.py` vs `transform_to_job_model` in `apple_jobs_scraper/scraper.py`) | provider date. *U5b is the one-word fix* |
| **Microsoft** (script) | `postedTs` ‖ `postedDate` ‖ `createdTs` (`_get_first_of` in `microsoft_jobs_scraper/api_client.py`; normalized by `_normalize_posted_date` in `microsoft_jobs_scraper/scraper.py`) | provider date once U5e lands — two live bugs today, see §7 |
| **Custom / recipe** | `posted_at`, mapped but never normalised | provider date once **U6** lands; first sight today (0 of 7 stored recipes carry a `parse_date` step) |

---

## 5. The units

Eight. **#243 ← #247 ← #248** is the live stack; #248 already carries 50+ commits.

### U1 — `services/posted_date.py`: one parse helper
Absorbs sibling unit 12. Today only the custom path has a sanity window
(`_validated_posted_on`, `fetch_custom_company.py`); the six ATS clients have none.

**D5 settled as parse-safety only.** The window rejects what *cannot* be a date — unparseable
values, and dates in the future beyond a small clock-skew allowance. It is **not** a staleness
judgement (that was the deleted credibility ceiling). **The custom path keeps its shipped
`[now−365d, now+7d]` untouched** — it is tested, and re-tuning it is not this plan's business.
The published clients get no new floor.

- **Files:** new `src/backend/api/services/posted_date.py`; `fetch_custom_company.py` imports it
  and deletes its private copy.
- **Test:** an unparseable value → `None`, never `now()`; `now+30d` rejected; `now+3d` survives;
  naive timestamp read as UTC; **a rejected row never aborts the run.**
- **Depends on:** nothing. **Lands on: #248.**
- ⚠️ **never-wrong-close** — runs in the same task as the close sweep. Per-row degradation only.

### U2 — The `job_freshness` trigger seeds `now()`
The only real obstacle to D10, and it is one line.

- **Files:** Alembic migration, `CREATE OR REPLACE FUNCTION job_freshness_sync()` —
  `VALUES (NEW.source_id, NEW.id, now(), 0)` instead of `NEW.first_seen_at`. This makes the
  trigger agree with what `_upsert_freshness` already does two statements later.
- **Test:** `scripts/tests/integration/test_job_freshness.py:100`
  (`test_trigger_seeds_from_first_seen_at_not_last_seen`) is **renamed and inverted** — a
  backdated `first_seen_at` yields `last_seen_at ≈ now()`. `:121` and the anti-join tests
  (`:226-236`) stay green unchanged.
- **Depends on:** nothing. **Lands on: its own PR off `main`, before U3.**
- ⚠️ **never-wrong-close** — the close sweep is `consecutive_misses`-based, so this cannot change
  close behaviour. Say so in the PR and cite `get_jobs_exceeding_miss_threshold` in `scripts/shared/database.py`.

### U3 — Seed `first_seen_at` at insert: the **published** onboarding flow
- **Files:** `scripts/shared/batch_writer.py`, `BatchWriter.add_job` — `job.first_seen_at = provider_date or timestamp`;
  **`job.last_seen_at = timestamp` stays exactly as is**. The six backend ATS tasks need no
  change (they flow through `upsert_jobs_batch`). The script scrapers set
  `first_seen_at=created_at` in their constructors and move to the same helper.
- **Test:** a real provider date is stored; a `None` provider date stores the run timestamp;
  **a second upsert never changes it, even when the provider date moves** (the Workday-slide
  test); never NULL; a close→reopen cycle leaves it untouched; `created_at` always holds the
  true insert time. Five existing tests assert `first_seen_at == last_seen_at == created_at`
  (`test_greenhouse_client.py` and `test_gem_client.py`, both
  `test_first_and_last_seen_set_to_same_iso_string`; `test_workday_client.py`,
  `test_first_last_seen_share_now_value`; `test_amazon_scraper.py`,
  `test_timestamps_are_consistent`; `test_tiktok_scraper.py`, `test_timestamps_consistent`) — **update them to assert divergence
  when a provider date exists.**
- **Depends on:** U1, U2. **Lands on: its own PR off `main`** — shared write path, every company.
- ⚠️ **never-wrong-close** — `_UPSERT_ON_CONFLICT` must keep omitting `first_seen_at`.

### U4 — Seed `first_seen_at` at insert: the **custom** onboarding flow
- **Files:** `src/backend/api/tasks/fetch_custom_company.py` — the recipe's `posted_at` runs
  through `posted_date.py`, then seeds `first_seen_at` the same way U3 does.
- **Test:** a captured board with a real ISO date seeds real dates on the first harvest; a board
  publishing no date (or a humanized string) seeds first sight; **the harvest still returns rows
  and closes nothing** when every date fails to parse.
- **Depends on:** U1, U3. **Lands on: #248.**
- ⚠️ **never-wrong-close** and **RAISES-never-empty** both live in this task.

### U5 — Five provider-date fixes
| | Fix | Test |
|---|---|---|
| **a** | **Workday: the `30+ Days Ago` branch returns `None`.** The `is_plus_range` (`+`) branch of `_DAYS_AGO_RE` in `_parse_workday_date` (`workday_client.py`). **Three lines — this is the whole trust story (§3).** | `"Posted 30+ Days Ago"` → `None`; `"Posted Today"`, `"Posted Yesterday"`, `"Posted 3 Days Ago"` all still return their accurate dates; an ISO string still parses |
| b | **Apple list mode**: `transform_to_job_model` reads `posted_on`; `_parse_job_element` emits `posted_date`. Microsoft already does `posted_on or posted_date` (`transform_to_job_model`, `microsoft_jobs_scraper/scraper.py`). **One word.** | a list-mode card with a parseable date writes non-NULL `posted_on` |
| c | **Eightfold** logs at ERROR on an unparseable `t_create` — the only one of six that NULLs silently | an unparseable epoch emits one ERROR and writes NULL |
| d | **Greenhouse** records whether it used `first_published` or fell back to `updated_at` | `details` carries the provenance |
| e | **Microsoft** `_normalize_posted_date`: ms guard (`>1e11 → /1000`, as `_parse_eightfold_epoch` in `eightfold_client.py` already does), `""` → `None`, reject non-date strings instead of `str()`-ing them into a TIMESTAMPTZ | epoch-s and epoch-ms both land in 2026; `""` writes NULL rather than failing the batch; `"2 days ago"` writes NULL. **Fix `test_normalize_millisecond_timestamp`** — named for ms, passes seconds |

- **Depends on:** nothing. **Lands on: its own PR off `main`. Ship early** — (a) is the whole
  Workday answer and (e) fixes two bugs live on `main` today.

### U6 — The recipe path learns to produce a date
Absorbs sibling unit 11. `parse_date` is fully implemented (`_parse_date_value`, `recipe_runner.py`) and
completely dead: `discover.py`'s `synthesize_recipe` emits only `fetch` /
`paginate_*` / `extract_json_path` / `assert_no_inband_error` / `dedupe_key` / `assert_unique`,
and **never `parse_date`** — 0 of 7 stored recipes have one.

- **Files:** `services/capture/request_selector.py` — report the observed format of the sampled
  `posted_at`; `services/capture/discover.py` — emit a `parse_date` step from `synthesize_recipe` when the
  sample is not already ISO; `services/recipe_runner.py` — add `epoch_s` / `epoch_ms` to `_parse_date_value`;
  `services/recipe_schema.py` — widen `_v_parse_date`'s closed mode set.
- **`humanized` needs no change.** It returns `None` by design and, under §3's rule, that is
  correct. (Previously filed as a bug; D12's simplification retires that.)
- **Test:** a Microsoft-shaped payload writes a real date on ≥95% of rows; `1787617881` and
  `1787617881000` both land in 2026 — not 1970, not year 58,000; a board publishing no date
  writes NULL and **never `now()`**; an unparseable value writes NULL. **There are currently no
  behavioural tests for `_parse_date_value` or `_apply_shaping` at all** — this adds the first.
- **Depends on:** U1. **Lands on: its own PR on #248.**
- ⚠️ **RAISES-never-empty** (`test_inv5_zero_records_raises_never_empty` in
  `test_recipe_runner_invariants.py`; the `*_raises` cases in `test_recipe_runner_determinism.py`) and the **agent-free replay boundary**
  (`test_replay_path_closure_has_no_forbidden_import`, AST-enforced).

### U7 — Re-capture the stored recipes *(ops, no PR)*
Re-run capture so the 7 stored recipes gain their `parse_date` steps. **No Browserbase** — prod
has `CAPTURE_USE_BROWSERBASE` unset and runs its own Chromium.
**Depends on:** U6.

### U8 — Write the rule down where people will hit it

**a. `scripts/CLAUDE.md` — extend the Job Lifecycle section**, beside the reopen guarantee it
gained this session; together they are the whole story of what `first_seen_at` means:
- `first_seen_at` is **the effective posted date**, not literally "when we first saw it".
- Still written **only** at INSERT, still absent from `_UPSERT_ON_CONFLICT`.
- **`created_at` is the true insert time** and the audit trail.
- `posted_on` remains the raw board value.
- **A board that gives a bucket instead of a date gives us no date** (§3).
- Pointer from `src/backend/CLAUDE.md`; amend `src/backend/docs/database-schema.md`'s `posted_on` bullet,
  whose "posted_on is UNRELIABLE, do not use as a recency signal" note must match what ships.

**b. The `add-company` skill** (`.claude/skills/add-company/SKILL.md`) — so adding **Meta**
picks the date field deliberately:
1. **New Step 0.5** — check what the board publishes, using the same live URL Step 0 already
   hits. Informational: does it give a real posting date, a relative bucket, or nothing?
   **No stored policy column** — if a board's dates are junk, the fix belongs in the client or
   the recipe, not in a config toggle.
2. **A "Posted date" column on the per-ATS reference table**, with Workday annotated:
   *"relative English; the `30+` bucket is not a date."*
3. **Checklist item:** `[ ] confirmed what the board's posted date actually is`.
4. **New hard-won lesson:** *"A board that publishes a relative date ('Posted 30+ Days Ago',
   'about 12 hours') has not published a posting date. Do not synthesise one."*

**c. Health-tooling warm-up guards** (from ClickUp 7.6 §5). `scraper-health-watch` A1 and the
audit's B.1b both fire on `last_ok IS NULL … NULLS FIRST`, so a company whose seed migration
deployed but whose first tick hasn't landed sorts to the top of the degraded list and can drive
a repoint PR against a healthy new company. `companies.created_at` already exists for the
predicate. Also move the audit's **D.4 forensic query** from `first_seen_at` to `created_at` —
after U3, a uniform `first_seen_at` no longer means "bulk insert".

- **Files:** `scripts/CLAUDE.md`, `src/backend/CLAUDE.md`,
  `src/backend/docs/database-schema.md`, `.claude/skills/add-company/SKILL.md`,
  `.claude/skills/scraper-health-watch/SKILL.md` (**main checkout**),
  `.claude/skills/onesecondswe-backend-audit/SKILL.md`.
- **Depends on:** nothing. **Lands on: its own PR off `main`.**

---

## 6. Routing

| Unit | Lands on | Why |
|---|---|---|
| U1 · parse helper | **#248** | edits a leaf-task file #248 owns |
| U2 · trigger seeds `now()` | **own PR off `main`** | one line, must precede U3 |
| U3 · published seeding | **own PR off `main`** | shared write path, every company |
| U4 · custom seeding | **#248** | inside the leaf task #248 owns |
| U5 · five provider fixes | **own PR off `main`** | **ship early** — (a) is the Workday answer, (e) is live on `main` |
| U6 · recipe `parse_date` | **own PR on #248** | ClickUp 7.6's backend half |
| U7 · re-capture | **ops, no PR** | data, not code |
| U8 · the written rules | **own PR off `main`** | docs + skill |
| *backfill* | **deferred** | [7.8](https://app.clickup.com/t/wdwb1cbq60) |

**Nothing belongs on #243 or #247** — they are the Phase-1/2 foundations.

**Sequencing:** U2 → U3 is the only hard ordering. U6 alone ships dark on the recipe path; U3
alone changes only the published companies (defensible — say so in the PR). **There is no
read-side cutover to coordinate**, which was the riskiest constraint before D10.

---

## 7. Invariant risk register

| Invariant | Pinned by | Units |
|---|---|---|
| **Never-wrong-close** | `test_fetch_custom_company_close.py` (module), `test_runner_raise_is_failed_with_zero_closes_and_zero_misses`, `test_self_consistent_not_terminated_cleanly_is_unverified`, `test_inv1`–`test_inv3` in `test_recipe_runner_invariants.py` | **U1, U2, U3, U4, U6** |
| **RAISES-never-empty** | `test_inv5_zero_records_raises_never_empty`, the `*_raises` cases in `test_recipe_runner_determinism.py`, `test_browser_fetch_runner.py` | **U4, U6** |
| **Keyset pagination** | `test_jobs_keyset_pagination.py` — golden SQL `:744`, `:785`; EXPLAIN `:964`, `:988`; walk/tie/churn `:142-355` | **None.** No unit changes the keyset SQL. The only hazard is the deferred backfill (transiently mutates the sort key — single transaction), carried into [7.8](https://app.clickup.com/t/wdwb1cbq60). |
| **`first_seen_at` immutability after insert** | `scripts/CLAUDE.md`; `test_job_freshness.py`; `pagination.py` (the `first_seen_at` docstring); `test_freshness_churn_between_pages_does_not_perturb_the_walk` | **U3** — the value changes, the immutability does not |
| **Agent-free replay boundary** | `test_replay_path_closure_has_no_forbidden_import`, `test_leaf_task_tasks_closure_has_no_forbidden_import` (AST) | **U6** |

**The easiest way to break something quietly:** adding `first_seen_at` to
`_UPSERT_ON_CONFLICT`'s SET list. It compiles, passes most tests, silently imports Workday's
daily slide into the product, and destroys the reopen guarantee.

### Two live bugs on `main`, fixed by U5e
- **Microsoft rewrites posted dates** — 30.5% of dated rows claim a `posted_on` *after* we first
  saw them, drifting up to 214 days.
- **Microsoft silently drops jobs** — `_get_first_of` (`microsoft_jobs_scraper/api_client.py`) returns `""` rather than `None`; `""` into
  a TIMESTAMPTZ fails the batch, which retries row-by-row (`BatchWriter.flush`, `scripts/shared/batch_writer.py`) and loses
  exactly those rows.

---

## 8. Still open

**Nothing is blocked.**

| | Item | State |
|---|---|---|
| 1 | Backfilling the 133 existing companies | Deferred → [7.8](https://app.clickup.com/t/wdwb1cbq60) |
| 2 | **D3** — dateless boards fall back silently, so their day-one spike is *permanent* | Owner's call, already made. Reversible with a frontend change, no migration. Must be visible in the U3 PR description |
| 3 | Naming — `first_seen_at` no longer means "first seen" | **D8**, its own ticket; D10 raises its priority. `created_at` now carries the literal meaning |
| 4 | Should reopens resurface? | **No** (D9). Would need a new column; scope separately only if asked |

---

## See also

- `.lavish/posted-date-accuracy.html` — decisions D1–D12, the spike evidence, the reopen analysis
- `IMPLEMENTATION-PLAN.md` — enrichment/dedupe workstream. **Its units 11–13 are superseded here**
- `scripts/CLAUDE.md` — Job Lifecycle; U8a extends it
- `src/backend/docs/database-schema.md` — the `posted_on` bullet, the documented counter-position; U8a amends it
- `docs/incidents/2026-03-29-mass-job-closure.md` — why per-row degradation, never per-run
- ClickUp [7.6](https://app.clickup.com/t/wdwb1cbp8n) · [7.7](https://app.clickup.com/t/wdwb1cbq5t) · [7.8](https://app.clickup.com/t/wdwb1cbq60) · epic `wdwb1cbnc2`
