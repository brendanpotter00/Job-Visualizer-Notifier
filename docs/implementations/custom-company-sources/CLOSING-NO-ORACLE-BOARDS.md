# How a board with no oracle earns the right to close a job

**Measured 2026-08-29.** Thresholds come from 271,053 production runs and 8 recorded
custom harvests. Every number below came from a query, and the queries are named.

> *"Aren't we using some unique ID from the jobs? We just need to check that ID — if it
> isn't there for two subsequent scrapes, close the job."*

Both halves of that already existed. What did not exist was any way for a discovered
board to reach the run that consults them.

---

## The defect, stated once

`discover.synthesize_recipe` stores `oracle_kind = "none"` when a recipe declares no
total **and** does not paginate, on the stated grounds that

> a single request that returns page one of an unknown-length board is
> indistinguishable from one that returns the whole board.

`verify_harvest` then answered `UNVERIFIED / no_oracle` for such a board on every run it
would ever make. UNVERIFIED cannot increment a miss and cannot close, so **no discovered
board had ever closed a job, and none ever could.** Measured on the owner's live database:

| board | stored oracle | last verdict | why |
|---|---|---|---|
| Atlassian · Jane Street · Walmart | `none` | `UNVERIFIED` | `no_oracle` |
| Goldman | `declared_probed` | `UNVERIFIED` | `page_advance_failed` |

Filled roles stayed OPEN forever and job counts only drifted upward. The reasoning behind
`none` is correct — the ambiguity is real — but it had been resolved one way, permanently,
trading *"we might wrongly close a live job"* for *"we will definitely show dead jobs
forever"*, and nobody had weighed that trade against the product.

**The ambiguity is real about the RESPONSE. It is not real about the REQUEST, and the
request is stored in the same row.**

---

## The rule

`oracle_kind = "none"` now routes to a third oracle, **history-delta**, alongside
`declared_probed` and `self_consistent`. It is reachable only when the caller hands
`verify_harvest` the stored recipe — *no recipe, no completeness claim* — which is what
keeps the six public ATS crons and the custom ATS path byte-identical.

A `none` run is VERIFIED iff **all** of:

| # | check | refuses with |
|---|---|---|
| 5 | the sweep did not stop on a cap | `cap_hit` |
| 6 | no page re-served ids it already had | `page_advance_failed` |
| — | the loop ended on a short/empty page | `not_terminated_cleanly` |
| **13a** | the request carries **no page index / offset** while the recipe has no `paginate_*` step | `page_param_unpaginated` |
| **13b** | the request's explicit **page size**, if any, is not exactly the row count | `page_limit_reached` |
| **13c** | the row count is not a **round page size the board has been pinned to** | `page_limit_pinned` |
| **12** | the count sits inside the **delta band** of the trailing VERIFIED median | `delta_anomaly` |

And then, at close time in `fetch_custom_company`, on top of everything that was already
there (safety guard, fleet breaker, first-run, script-changed, two consecutive misses, the
1.5 × cadence wall-clock floor):

* **a full day of consecutive VERIFIED observation** — `_NO_ORACLE_STREAK_MIN_HOURS`,
  which is **24 runs at the shipped 1 h cadence**, against `self_consistent`'s flat 3;
* **the id-churn guard**, previously `self_consistent`-only: >50 % of prior-OPEN ids
  vanishing in one run refuses the close outright.

Nothing about `declared_probed` moved. `oracle_kind` in the database is unchanged — this
is a change to how `none` is *treated*, not to how it is *assigned*, so there is no
migration and `discover.py` is untouched.

---

## Where every threshold came from

### The delta band — 0.85, and an absolute drop of 15

Scored on prod `scrape_runs`, 2026-06-01 → 08-29, one run per company-hour (the custom
cadence is now 1 h), guard-skipped runs excluded, each run against the median of its own
preceding 14 runs. **n = 271,053.**

| p0.5 % | p1 % | p5 % | p50 | p99 | p99.9 |
|---|---|---|---|---|---|
| 0.9167 | 0.9504 | 0.9871 | 1.0000 | 1.0460 | 1.1555 |

A ratio threshold **alone is unusable**. 659 runs fall below 0.85, and the companies
supplying them are `slack` (median 16), `browserbase` (9), `posthog` (18), `gem` (11),
`light` (8). A nine-job board that posts six is Tuesday, not a truncation.

ANDing an absolute drop of ≥ 15 removes all of it:

| rule | runs tripped | of which `n = 0` |
|---|---|---|
| ratio < 0.85 | 659 | 414 |
| ratio < 0.85 **AND** drop ≥ 15 | 429 | 404 |

So the entire **new** population the band refuses is **25 runs in 271,053 (0.009 %)** —
and all 25 were inspected:

* **`apple` × 5** — 2460/3688, 2585/3577, 2722/3760, 2819/3774, 2859/3577. These *are* the
  real Apple truncations that `incremental.py`'s own calibration note names. Refusing
  them is the point.
* **`paypal` × 19, `airtable` × 1** — genuine step shrinks (87 from 112, 112 from 142,
  169 from 201), handled by the release below.

**0.85 and 15 are not new numbers.** They are `SCRAPER_GUARD_MIN_RATIO` and
`SCRAPER_GUARD_MIN_ABS_DROP` from `scripts/shared/incremental.py`, calibrated
independently against 455,317 runs, which landed on the same knee. This band is that
guard's rule shape pointed at a different baseline: the guard scores the harvest against
`active_count` (what the DB holds), this scores it against the trailing median (what the
*board* has been returning). They are ANDed at close time, never substituted.

The old `0.5` floor is **kept as well**, not replaced — a run trips on either rule. So the
band only ever tightened, and nothing previously refused is now allowed.

The high bound stays at `2.0`. An over-read cannot wrong-close: extra rows are upserted,
and a return to normal afterwards is itself a large down-move that the low side catches.

### The settled-step release — 4 prior runs, and 4 hours

Without a release, a VERIFIED-only median latches forever: a board that legitimately drops
1,074 → 600 is out of band, so it never VERIFIES, so no VERIFIED run ever enters the
median, so it is out of band forever. 19 of the 25 runs above are that shape, so
"accept the latch" would freeze most boards eventually.

**How a real layoff differs from a broken read is measured, not assumed:** a real shrink
*holds* its new number, a truncation *wanders*.

| | events | preceded by 4 runs of the identical count |
|---|---|---|
| `apple` (real truncations) | 5 | **0** |
| `paypal` (real step shrinks) | 19 | 6 |
| `airtable` | 1 | 0 |

So a run outside the band is admitted anyway iff the previous **4** harvests returned the
identical count — or, at any cadence other than hourly, however many runs cover **4 hours**,
whichever is more (`settled_prior_runs`). **Zero of the known-real truncations in 271,053
runs would be released by that rule.** It is a re-baseline, not a close — the released run
still faces the streak, the safety guard, the churn guard, two misses and the wall-clock
floor.

The real PayPal series, replayed as a test:

```
117 117 117 116 115 114 112 … 112 111 109 109  87  87  87  87  87  87  87  88 …
                                   └─ refused ──────┘ └── released ───┘
```

Refused for four runs, closing again on the fifth — about five hours at the 1 h cadence,
instead of never.

### The page-shape tells — read off the four real recipes

| board | request parameters | rows | verdict |
|---|---|---|---|
| **Walmart** | `job_page: 0`, `content_page`, `future_roles_page` | 10 | **refused** `page_param_unpaginated` |
| **Goldman** | `pageNumber`, `pageSize` — *but the recipe paginates* | 20 | out of scope for 13; refused by checks 5/6 and the declared total |
| **Atlassian** | none | 232 | verified |
| **Jane Street** | none | 233 | verified |

Walmart is the board this half exists for. It does not have ten open jobs; that is page
one. Its count is *perfectly stable*, so a delta band on its own would verify it and start
closing live jobs as page one rotated. Nothing in the response says so — the `job_page: 0`
in the request does.

13c covers the case with no parameter at all: a server-side default limit is the only
thing that pins a count to a round number run after run, and a real board's count drifts
off it. Its window is deliberately **the same length as the settled-step release**, so a
scraper that jams against a server default can never be re-baselined onto it.

### The streak — a day, not a run count

**Every threshold here that is counted in runs has been checked against the cadence, and
two of them are stated in hours instead.** The cadence moved from 24 h to 1 h in a
different file while this was being written; a bare integer would have been silently
divided by 24. `_NO_ORACLE_STREAK_REQUIRED = 5` was nearly shipped meaning "five days" and
would have arrived meaning "five hours".

| constant | counted in | why |
|---|---|---|
| `_NO_ORACLE_STREAK_MIN_HOURS` = 24 h | **hours** → `ceil(24/cadence)` runs (24 at the shipped cadence), floor 3 | below |
| `_SETTLED_MIN_RUNS` = 4 **and** `_SETTLED_MIN_HOURS` = 4 h | **both**, stricter wins | the measurement is "4 consecutive *hourly* observations" — both halves matter |
| `_DELTA_LOW_RATIO` = 0.85, `_DELTA_MIN_ABS_DROP` = 15 | per-run move | derived at the **hourly** stride above; already the shipped cadence |
| `compute_baseline(window=14)` | runs | pre-existing, and the band was scored against a 14-run trailing median at hourly stride — same window, same cadence |

**Why a day.** `declared_probed` proves completeness against an independent total and
needs no streak at all. `self_consistent` has a structural claim to fall back on — its
sweep ran to a genuinely short page without hitting a cap. `none` has **neither**: its only
completeness evidence is *"this board has been returning about this many rows"*, and that
sentence is worth nothing until the board has been observed across a period in which it
would actually have moved.

A job board's change rhythm is **daily** — postings appear and roles get pulled during
business hours, and overnight a board sits still. "The count did not change" observed
across five quiet night-time hours is not evidence of a stable read; it is evidence that
nothing was happening. 24 h is the shortest window guaranteed to contain the part of the
day when the board moves.

It doubles as the **settling period for a newly-added board**: the window in which a subtly
wrong recipe shows itself before anything is deleted. The user sees the board's jobs from
the first harvest either way — only *closing* waits, so the cost of the wait is invisible
and the cost of skipping it is a user's jobs.

The floor of 3 keeps `none` from ever being laxer than `self_consistent`: at a daily
cadence a single run already spans 24 h, and three independent confirmations is still the
right minimum.

---

## Simulation — every board, replayed

Recorded histories driven through the real `run_gate` / `verify_harvest`, with the
baseline rebuilt between runs exactly as `compute_baseline` does. Kept as a test
(`src/backend/api/tests/test_history_delta_oracle.py`), not a script that ran once.

| board | recorded series | would have closed | correct? |
|---|---|---|---|
| **Atlassian** | 232, 222 | nothing yet — both runs VERIFY; the board becomes close-eligible on its 24th | ✅ whole-catalogue single GET |
| **Jane Street** | 233 | same | ✅ same |
| **Walmart** | 10 (× 10 runs forced) | **nothing, ever** — `page_param_unpaginated` | ✅ page one of N |
| **Goldman** | 20 vs declared 1,074 (× 15 runs forced) | **nothing, ever** — `page_advance_failed`, and `count_mismatch` even with a clean page-advance | ✅ 1,054 jobs kept OPEN |
| **apple** (prod, replayed as a custom board) | 34 hourly runs incl. 1692 and 2460 | refuses exactly those two, verifies the other 32, closing again on the next run | ✅ |
| **paypal** (prod, replayed) | 45 hourly runs, 117 → 87 | refuses the first four 87s, releases the fifth | ✅ |

**Goldman is still refused, and by three independent gates.** Its stored evidence is 20
records against a declared 1,074 with `page_advance_ok = False`. Check 6 refuses it before
any history is consulted; strip that away and `declared_probed`'s exact-match ladder
refuses it as `count_mismatch`; strip *that* away and the safety guard sees 20 against
~1,074 active — 1.8 %, under the 10 % `empty_scrape` floor, which is never auto-released.
There is no single gate holding Goldman up.

The counterfactual that justifies moving 0.5 → 0.85 + 15, also kept as a test: Apple's
2,460-of-3,689 run is 66.7 %, **inside the old band**. Under the previous rule that run
would have VERIFIED and been free to start closing the ~1,200 jobs it never saw.

---

## Mutation results

Every guard was removed one at a time and the suite re-run. **27 mutations, 0
survivors.** The four that survived a first pass are named because what killed them is
the coverage that was missing, not the guard:

| survived first pass | what was missing | test added |
|---|---|---|
| `terminated_cleanly` not checked on the history-delta path | no `none`-board case for a sweep that ran out of page budget | `test_a_none_board_that_ran_out_of_page_budget_is_refused` |
| `recent_records` stops excluding FAILED runs | a FAILED run's zero could pose as a settled step change | `test_recent_records_excludes_failed_runs` |
| `recent_records` filtered to VERIFIED like the median | would blind check 13c on every board that has never verified — i.e. all of them today | `test_recent_records_is_not_verdict_filtered` |
| the recipe passed for **every** transport | an unrecognized ATS provider maps to `none`, and an `ats_client` "script" has no `steps`, so the tells read nothing off it | `test_an_unrecognized_ats_provider_is_never_handed_a_recipe` |
| `read_untruncated` stops excluding the check-13 reasons | Walmart's ten rows would go back to being compared against a published board | `test_a_page_shaped_refusal_is_not_a_comparable_read` |

The mutation that matters most is **M16 / M18**: letting a Goldman-shaped run through, and
removing the streak. Both die.

---

## What this still cannot catch

Stated plainly, because a rule whose limits are not written down gets trusted past them.

1. **A small board's partial read.** The absolute-drop floor means a board with fewer
   than ~15 jobs can never trip the band. A 12-job board that returns 9 closes 3 jobs, and
   if those 3 were truncated rather than filled, that is a wrong close. The churn guard
   catches the catastrophic version (>50 % gone); the mild version is invisible. This is
   the same trade `SCRAPER_GUARD_MIN_ABS_DROP` already made fleet-wide, for the same
   reason: without it, small boards trip constantly and never close anything.
2. **A page-limited endpoint whose limit is invisible.** A board that fetches 100 and
   post-filters to 87 returns a non-round number from a truncated read. 13a sees no
   parameter, 13c sees no round number, and if 87 is stable the band is satisfied. Nothing
   here detects it.
3. **A board that is wrong from its very first harvest.** The median is built from the
   board's own history, so a board that has only ever returned half of itself has a
   perfectly self-consistent history of returning half of itself. What protects the user
   is that the other half was never inserted, so there is nothing to close — unless the
   visible half rotates, which is what the churn guard is for.
4. **A genuine shrink that never settles.** A board bleeding jobs a few at a time past the
   band, never holding one number for four runs, stays refused indefinitely. It shows
   every job it has; it just stops closing. That is the safe direction and it is
   deliberate — **"this board can never close" is an acceptable outcome for some boards.**
5. **A board pinned to a round count forever** (13c) never closes, even if that count is
   its real size. Cost is near zero by construction: a board whose count and id set both
   sit still has nothing to close anyway.

---

## Consequences the owner should read as stated, not discover

* **Atlassian and Jane Street can now close jobs. They never have, in their existence.**
  The number that matters:

  | | wall clock at the shipped 1 h cadence |
  |---|---|
  | board added → **earliest possible first close** | **≈ 24 h** — the 24th consecutive VERIFIED harvest is the first close-eligible one, and a job that left the board early in that window already carries its two misses by then |
  | thereafter, role leaves board → closed | **≈ 2 h** (two consecutive misses; the 1.5 h floor is already satisfied) |

  Both are ± the scheduler's ¼-cadence jitter (±15 min per run) and ≤ 15 min of tick lag. For comparison:
  published companies close in ≈ 1 h with no floor at all, and a `declared_probed` custom
  board closes in ≈ 2 h from day one — custom-with-no-oracle stays the most conservative
  path in the system, which is the intent.
* **Walmart will never close a job** in its current form, and its harvest verdict is now
  `page_param_unpaginated` rather than `no_oracle`. Re-discovering it against an endpoint
  that paginates is the fix; there is no threshold to loosen.
* **The published-board matcher stops comparing Walmart-shaped boards.** `read_untruncated`
  excludes the three check-13 reasons. Before this change Walmart's ten rows were being
  offered to the matcher as if they were the whole board. That is a deliberate behaviour
  change, not a side effect.
* **`self_consistent` boards get the tightened band too** — one band, one derivation, one
  set of tests. It only tightens: the 0.5 floor is intact and the 0.85 + 15 rule is added
  on top.

---

## Where it lives

| | |
|---|---|
| the rule | `src/backend/api/services/harvest_verification.py` — checks 12 and 13, `_verify_history_delta` |
| the baseline it reads | `src/backend/api/services/custom_baseline.py` — `median_records` (VERIFIED only) + `recent_records` (unfiltered) |
| the close ladder | `src/backend/api/tasks/fetch_custom_company.py` — `_NO_ORACLE_STREAK_MIN_HOURS` / `_required_streak`, the churn guard, `_DISCOVERED_TRANSPORTS` |
| unit + simulation | `src/backend/api/tests/test_history_delta_oracle.py` |
| e2e, the refusing half | `e2e/add-companies/api/test_verification_refusal.py` (AC-15) |
| e2e, the verifying half | `e2e/add-companies/api/test_discovery.py` (AC-04 / AC-05) |
