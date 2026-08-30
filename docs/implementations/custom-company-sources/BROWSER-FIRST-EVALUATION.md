# Browser-first re-architecture — evaluated against 24 live boards

**Verdict: DO NOT BUILD IT AS PROPOSED. Build a much smaller modified version.**
**The invariant is false** — 4 of 23 boards render no usable job list, including Jane Street
(0 jobs in the DOM; 233 read perfectly by the API today) and Walmart (cards with a real id
and **no link**). **Click-to-paginate is worse** — only **3 of 17** boards swept to
completion through pagination, and **4 of 17 stopped early while signalling success**.
**IBM dropped 197 jobs between two back-to-back sweeps**, which at `MISSED_RUN_THRESHOLD = 2`
is 197 real jobs deleted. **Keep the API as the floor**; take the DOM as a *link*, *oracle*
and *id-set* source, and ship `http_html` — already written, never switched on.

---

## The number that decides it — DOM id-set symmetric difference

**Two full click-sweeps to exhaustion, back to back, separate browser sessions.** Identity
= the job's own href. This is the decisive test.

| board | sweep 1 | sweep 2 | **sym. diff** | gone | new | real size |
|---|---:|---:|---:|---:|---:|---:|
| **IBM** | 1,396 | 1,317 | **315** ❌ | **197** | 118 | 1,802 |
| Greenhouse/Anthropic | 571 | 571 | **0** | 0 | 0 | 571 ✅ |
| Goldman | 1,034 | 1,034 | **0** | 0 | 0 | 1,034 ✅ |
| Uber | 685 | 685 | **0** | 0 | 0 | ~690 ✅ |
| JPMorgan Oracle | 2,275 | 2,275 | **0** | 0 | 0 | 7,181 ⚠️ truncated |
| **Workday/Micron** | **417** | **417** | **0** | 0 | 0 | **2,781** ⚠️ *stably wrong* |
| Nintendo | 49 | 49 | **0** | 0 | 0 | 49 ✅ |
| Ashby/Notion | 133 | 133 | **0** | 0 | 0 | 133 ✅ |

And the page-1-only repeat, **11.8 minutes apart**, over all 22 boards: **symmetric
difference 0 on 21 of 22 — IBM 40 on 30** (a complete turnover of its first page). Five of
those zeros are boards that rendered nothing twice (Jane Street, Walmart, Bloomberg,
McKinsey-local, Lever/whoop-empty), which is a zero that means "no data", not "stable".

**Three conclusions, and they do not point the same way:**

1. **The href-derived id is stable.** No title-hashing, no churn. That half of the objection
   is answered — the proposal survives it.
2. **`IBM` breaks it outright.** 197 jobs present in one sweep and absent in the next,
   minutes apart, same code, same budget. At `MISSED_RUN_THRESHOLD = 2` that is **197 real
   jobs deleted** from a live product on any unlucky pair of runs — ~11% of the board.
3. **A symmetric difference of 0 does not mean the read was right.** Workday/Micron returned
   **the identical wrong 417 of 2,781 both times**. A stably-wrong sweep is *more* dangerous
   than a noisy one, because it looks healthy to `self_consistent` and sails through the
   history-delta band.

So the honest verdict on identity: **stable ids, untrustworthy enumeration.** Which is
exactly backwards from what the close rule needs.

---

## 1. Identity and enumeration — the decisive section

### 1.1 Does every rendered card carry a stable, extractable id?

**Yes, and this is the proposal's strongest ground.** All **19** boards that render a job
list expose a stable per-job identity **in the href itself** — numeric
(`/jobs/4094385009/`, `?jobId=129622`, `/job/210594721`), uuid
(`/notion/3f842011-eb04-…`) or slug (`/careers/details/trader-fixed-income-macro-intern-us/`).
**No title-hashing is needed anywhere**, so the churning-id failure the objection worries
about does not arise. Walmart is the exception that proves the point differently: no href at
all, but a real requisition id in `data-job-id="CP-9281-11013"` — the same shape as the
`CP-6054-11013` our API recipe stores.

**Where we have both, do the DOM id and the API id agree? On Nintendo — measured exactly:**

```
stored `id` column (API recipe) : 49  ['4063892009', '4063945009', '4064114009']
stored url's gh_jid             : 49  ['4094385009', '4094467009', '4094751009']
DOM  /jobs/<id>/                : 49  ['4094385009', '4094467009', '4094751009']
DOM ∩ gh_jid    = 49/49         DOM ∩ stored `id` = 0/49
```

**The DOM id matches the board's public id 49/49 and our stored id 0/49.** Greenhouse
publishes two id spaces (`id` and `internal_job_id`); the page links one, our recipe stored
the other. This is not a Nintendo quirk — it is what "API fast path, DOM fallback"
*means* in practice:

> **A fallback from API to DOM is a full-board identity change.** Every job goes missing
> and an equal number of strangers appear. With `MISSED_RUN_THRESHOLD = 2`, two fallback
> runs close the entire board and re-open it as duplicates.

The proposal's ordering (§3, "replay tries the API; on failure falls back to browser +
DOM") is therefore **not self-healing — it is self-destroying**, unless the recipe pins one
id space and the DOM extractor is *proven* to reproduce it. That proof is a per-board
obligation the proposal does not budget for.

Other id-set comparisons against what our stored recipes actually hold:

| board | stored recipe | DOM page 1 | DOM ∩ stored | note |
|---|---:|---:|---:|---|
| Nintendo (`http_html`) | 49 | 49 | **0** (49/49 vs the board's public id) | two id spaces |
| Y Combinator (`http_html`) | 9 | 3 | 3 | **the rendered DOM sees fewer than the served HTML** |
| Jane Street (`http_json`) | 233 | **0** | 0 | the DOM has no jobs on it |
| Walmart (`http_json`) | 10 | **0** | 0 | cards have ids, no links |
| JPMorgan Oracle (`http_json`) | 7,124 | 25 | — | DOM ids are `/job/210594721`, a third id space again |

### 1.2 How does a DOM sweep know it has seen everything?

It has exactly two signals, and **I observed both fire wrongly**:

| stop signal | fired correctly | fired **wrongly** |
|---|---|---|
| "the next control is gone / disabled" | Goldman (1,034/1,034), Greenhouse/Anthropic (571/571), Uber (685/~690) | **Uber, on my first detector** — the Tailwind utility class `disabled:pointer-events-none` contains the substring `disabled`, so a live, enabled Next link read as disabled and the sweep stopped at **10 of ~690** and called it complete |
| "N steps produced no new ids" | Ashby/Notion, Nintendo, D. E. Shaw, Lever/ro (all genuinely single-page) | **Workday/Micron 417 of 2,781 after 74 clicks · Meta 11 of 877 · Y Combinator 3 of 9 · Citadel 6 of ~10** — all four reported the clean stop |

The Uber miss was **my bug, not Uber's property** — I verified the control reports
`disabled=false, aria-disabled="false"` and re-ran with a corrected detector to get 685.
I am reporting it anyway because it is the entire argument: a generic "is the list
exhausted?" predicate is a *heuristic over someone else's CSS*, and its failure mode is a
silent, confident, wrong "complete".

A third failure I did not design for: on SpaceX my "next" regex matched a **job titled
"Manufacturing Engineer, Next-Gen Compute Systems"** and clicked it.

**Contrast with an API read**, which carries `pages_fetched`, `terminated_cleanly`,
`cap_hit` and usually a declared total — all *structural*, none of them a guess about
markup (`recipe_runner.py`, `harvest_verification.py:504-581`).

### 1.3 How does it know a job is MISSING rather than not-rendered?

**It cannot, and the measurements say this is common, not exotic.**

- **IBM dropped 197 jobs between two back-to-back full sweeps** (1,396 → 1,317, symmetric
  difference 315), and turned over 30 of 30 first-page ids across an 11.8-minute gap. Its
  default search is relevance-ordered and reshuffles. Even a 7-minute sweep reached only
  **1,396 of 1,802**, so truncation is the normal case, not the edge case — and a truncated
  read of a reshuffling list is a different arbitrary subset every night. **This one board,
  on its own, would close ~197 real jobs.**
- **Workday/Micron returned 233, then 247, then 417 and 417** across four sweeps at three
  budgets — every one of them reported as a clean, complete read of a 2,781-job board.
- Meta, Y Combinator and Citadel each reported a *clean, complete* sweep while holding
  1.3%, 33% and ~60% of the board.

The critical property is that **a short sweep and a complete sweep are indistinguishable
from inside**. Goldman's honest 1,034-of-1,034 and Micron's 417-of-2,781 produced the same
`no more pages` signal, and both reproduced exactly on a second run.

Under the current rule set a wrong-close needs `verdict == VERIFIED` plus eight other
conditions (`fetch_custom_company.py:874-979`). **The danger is not that today's code
closes on a bad DOM read — it is that "make the DOM the floor" requires inventing a way to
call a DOM sweep VERIFIED, and the measurements say no honest way exists.**

The codebase already reached this conclusion independently. `_verify_history_delta` step
13d (`harvest_verification.py:776-781`):

> `transport == HTTP_HTML` → `UNVERIFIED "html_no_sweep_evidence"`

and the local DB agrees — both Nintendo `http_html` harvests: `UNVERIFIED |
html_no_sweep_evidence`. **A DOM-derived board already can never close, by design.** The
proposal's real content is therefore "please remove that guard", and §1.2 is why not.

### 1.4 What the e2e suite would have to add

The suite is strong on refusal and mute on exactly this axis.

| guarantee | today | a DOM-first world needs |
|---|---|---|
| job id stable across runs | **0 assertions.** No case harvests the same company twice (`conftest.py:144-155` purges after each) | a two-harvest case asserting id-set equality |
| a job goes OPEN → CLOSED | **0 cases.** `MISSED_RUN_THRESHOLD` appears nowhere in `e2e/`. The only closure assertion is that the *first* run closes nothing (`test_discovery.py:130-138`) | a case that removes a job and proves exactly that job closes |
| DOM extraction end-to-end | AC-17 asserts `anchor_candidate` **proposes** an `extract_css` candidate (`test_board_defects.py:739-837`); `_run_css` is never executed in `e2e/` | a discovered-and-harvested-via-DOM board |
| `browser_fetch` / `http_html` | **zero e2e coverage** | the whole tier |

**Finding worth reporting on its own:** the suite is 22 cases / 69 items / 384 s, and it
proves neither identity nor closure. Browser-first would be shipped onto a test base that
cannot see its two most dangerous failure modes.

---

## 2. Is the invariant true? — DOM extractability, 24 boards

"Every job board renders jobs to a human in a browser." Measured page-1, local headless
Chromium, with a Browserbase retry wherever local failed, so an infrastructure failure is
never scored as a board property.

| board | local | page-1 job cards (local) | Browserbase retry | renders jobs? |
|---|---|---:|---|---|
| **Jane Street** | 200 | **0** | 200 → **0** (nav items only) | ❌ **no** |
| **Walmart** | 200 | **0 anchors** | 200 → 0 anchors; cards carry `data-job-id`, **no href** | ❌ **no link** |
| **Bloomberg** (Avature) | 403 bot wall | 0 | 200 but **redirected to `/company/what-we-do/`** — never reaches the board | ❌ **no** |
| **Oracle careers** | 200 | 7 facet links, 0 jobs | — | ❌ **no** (on the entry URL) |
| **JPMorgan Oracle** | 200 | 25 links, **0 anchor text** | — | ⚠️ links yes, title needs a card selector |
| **Y Combinator** | 200 | 3 (served HTML has **9**) | — | ⚠️ under-reads |
| Meta | 200 | 11 (of 877) | — | ✅ |
| IBM | 200 | 30 (of 1,802) | — | ✅ |
| Uber | 200 | 10 | — | ✅ |
| Citadel | 200 | 6 | 200 → 7 | ✅ |
| Sequoia | 200 | 3 | 200 → **15** grouped results | ✅ |
| Nintendo | 200 | 49 (whole board) | — | ✅ |
| **McKinsey** | **ERR_HTTP2 (local only)** | — | **200 → 20 cards** | ✅ *local infra failure* |
| **Tesla** | **403 Access Denied** | 0 | **200 → 8 cards** | ✅ *local infra failure* |
| D. E. Shaw | 200 | 87 (whole board) | — | ✅ |
| Goldman | 200 | 20 | — | ✅ |
| Greenhouse/Anthropic | 200 | 50 | — | ✅ |
| Ashby/Notion | 200 | 133 (whole board) | — | ✅ |
| Lever/ro | 200 | 50 (whole board) | — | ✅ |
| Workday/Micron | 200 | 4 | — | ✅ |
| SpaceX | 200 | 2,236 (whole board) | — | ✅ |
| Amazon | 200 | 8 | — | ✅ |
| Apple | 200 | 15 | — | ✅ |
| *Lever/whoop* | 200 | 0 — *"No job postings currently open"* | 200 → same | *excluded: empty board* |

**Score: 17 of 23 clean · 2 qualified · 4 render nothing usable = 83% at best, 74% clean.**

**That is a good rate. It is not an invariant**, and the exceptions are not a random tail:

- **Jane Street is the single cleanest success our API path has** — 233 jobs, one static
  JSON GET, `VERIFIED history_delta_ok` nightly — and renders **zero** jobs at the URL a
  user pastes. Its page is a chooser ("Experienced Candidates" / "Students and New Grads").
  Independently confirmed: `BIRTH-DEFECTS-PLAN.md §0` measured 0 job anchors in both the
  raw HTML and the rendered DOM after the full 24 s window. My Browserbase render agrees.
- **Walmart is the largest board in the corpus (48,887)** and its card is a `div` with a
  click handler. `CANONICAL_REQUIRED_FIELDS = (id, title, url)` — a linkless card cannot
  become a job row.
- **Bloomberg is unreachable, not unrendered** — even on Browserbase it is redirected off
  the board.

**Local-vs-Browserbase is load-bearing and cuts both ways.** McKinsey and Tesla render
fine and fail *only* locally. That matters for §4: today's browser replay tier runs
**local Chromium on Railway**, not Browserbase.

---

## 3. Is click-to-paginate universal? — per board

Two budgets: **40 steps / 300 s** across 18 boards, then a more generous **90 steps / 420 s**
on the eight that had not finished. The generous run is reported where it differs, so the
proposal is scored at its best. "Real size" is the board's own printed count or our stored
harvest.

| board | page 1 | swept | real size | stop reason | trustworthy |
|---|---:|---:|---:|---|---|
| **Goldman** | 20 | **1,034** | 1,034 | `control_disabled: Next` (51 clicks, 127 s) | ✅ **complete via pagination** |
| **Greenhouse/Anthropic** | 50 | **571** | 571 | `control_disabled: Next page` (11 clicks, 33 s) | ✅ **complete via pagination** |
| **Uber** *(fixed detector)* | 10 | **685** | ~690 | `control_disabled: Next` (68 clicks, 159 s) | ✅ **complete via pagination** |
| Ashby/Notion | 133 | 133 | 133 | `no_new_ids_x3` | ✅ single page |
| Nintendo | 49 | 49 | 49 | `no_new_ids_x3` | ✅ single page |
| D. E. Shaw | 87 | 87 | 87 | `no_new_ids_x3` | ✅ single page |
| Lever/ro | 50 | 50 | 50 | `no_control` | ✅ single page |
| SpaceX | 2,236 | 2,236 | ~2,236 | `click_no_new_ids_x3` — **after clicking a job titled "…Next-Gen Compute Systems"** | ✅ by luck |
| **Workday/Micron** | 3 | **417** | **2,781** | `click_no_new_ids_x3` after 74 clicks | ❌ **false complete (15%)** |
| **Meta** | 11 | **11** | **877** | `no_new_ids_x3` | ❌ **false complete (1.3%)** |
| **Y Combinator** | 3 | **3** | **9** | `no_new_ids_x3` | ❌ **false complete (33%)** |
| **Citadel** | 6 | **6** | ~10 | `no_new_ids_x3` | ❌ **false complete (~60%)** |
| **Uber** *(first detector)* | 10 | **10** | ~690 | `control_disabled` (**false**) | ❌ **false complete (1.4%)** |
| JPMorgan Oracle | 25 | 2,275 | 7,181 | cap (90 steps, 220 s) | ⚠️ incomplete, honest |
| IBM | 30 | 1,396 | 1,802 | 420 s budget (50 clicks) | ⚠️ incomplete **and reshuffles between renders** |
| Apple | 15 | 613 | thousands | cap | ⚠️ incomplete |
| Amazon | 8 | 281 | 22,492 | 300 s budget | ⚠️ incomplete |
| Walmart | 0 | **0** | 48,887 | `no_group` | ❌ nothing |

17 distinct boards (Uber appears twice — once per detector).
**8 of 17 swept to completion — but only 3 of those exercised pagination at all**
(Goldman, Anthropic, Uber; the other five are single-page boards the API also handles).
**4 of 17 (24%) stopped early while reporting a clean stop**, and Uber's first detector
makes a fifth.
**4 of 17 were still incomplete when the budget ran out; 1 rendered nothing.**

**Workday/Micron is the worst case and the most instructive.** It clicked Next **74 times**,
accumulated **417 of 2,781** jobs, then three consecutive clicks yielded no new ids and the
sweep declared itself finished at **15% of the board**. Nothing about that outcome is
distinguishable, from inside the sweep, from Goldman's genuine 1,034-of-1,034.

Every pagination style in the brief was found, and each broke differently:

| style | boards | outcome |
|---|---|---|
| numbered / Next page | Anthropic, Uber, Goldman, IBM, Apple, Amazon | works when the control is honest; **the "is it disabled?" test is the weak link** |
| "next" on a virtualised list | Workday/Micron | 74 clicks, then a silent stop at 15% — the DOM recycles nodes and the sweep cannot tell recycling from exhaustion |
| infinite scroll | JPMorgan Oracle (+25 ids/scroll) | works and is honest, but needs ~287 scrolls; never finishes inside a sane budget |
| "load more" / "Show more" | Meta, Amazon | Meta's *Show more* produced **0 new ids** — the sweep read it as the end |
| no pagination | Ashby, Nintendo, D. E. Shaw, SpaceX, Lever/ro | fine — and these are the boards the API also handles trivially |
| no cards at all | Walmart | 0 |

---

## 4. Cost — real numbers, working shown

**Browserbase list pricing** (fetched from browserbase.com/pricing): Developer $20/mo,
100 browser-hours, **$0.12/hr** over, 25 concurrent. Startup $99/mo, 500 hours,
**$0.10/hr** over, 100 concurrent. Proxy $10–12/GB.

**What the 2¢/board/month estimate implies.** 2¢ ÷ $0.12/hr = 0.167 browser-hours ÷ 30
renders = **20 seconds per render**. That is the whole assumption. Measured against it:

| board | measured full sweep | render/mo (30×) | $/board/month @ $0.12 | vs 2¢ |
|---|---:|---:|---:|---:|
| Nintendo / Ashby / D. E. Shaw (single page) | 14–16 s | 0.12–0.13 h | **$0.015** | ✅ **1×** |
| Greenhouse/Anthropic (571) | 33 s | 0.28 h | **$0.033** | 1.7× |
| **Goldman (1,034, 51 clicks)** | **127 s** *(measured, complete)* | 1.06 h | **$0.13** | **6.4×** |
| **Uber (685, 68 clicks)** | **159 s** *(measured, complete)* | 1.32 h | **$0.16** | **8×** |
| median tracked board (~1,088 jobs) | ~130–160 s | ~1.2 h | **$0.14** | **7×** |
| JPMorgan Oracle (7,181) | ~693 s *(extrapolated: 2,275 ids in 90 scrolls / 220 s → 2.44 s per 25 ids)* | 5.8 h | **$0.69** | **35×** |
| Amazon (22,492) | ~2 h *(extrapolated)* | 60 h | **$7.20** | **360×** |
| Workday/Micron (2,781) | **never completes** — stops at 417 | — | — | n/a |

> **The 2¢ estimate is defensible only for boards that need no pagination at all.** For the
> boards that motivate this rewrite it is off by **one to two orders of magnitude**.

**Fleet cost at 20 boards/user, daily cadence**, using the median board (~1.2 browser-h/mo
→ ~24 h/user/mo). Per-board figures above use the Developer rate ($0.12/hr); the fleet table
uses the Startup plan, since every row below is past its 500 included hours:

| users | browser-hours/mo | Browserbase bill | today |
|---:|---:|---:|---:|
| 25 | 638 | $99 + 138×$0.10 = **$113/mo** | **$0** |
| 100 | 2,550 | $99 + 2,050×$0.10 = **$304/mo** | **$0** |
| 500 | 12,750 | **$1,324/mo** | **$0** |
| 1,000 | 25,500 | **$2,599/mo** | **$0** |

**The free alternative does not work.** Today's browser tier runs **local Chromium on
Railway** — `_browser_fetch_main.py:394-401` — and the child's env is an *allowlist* that
deliberately strips `BROWSERBASE_API_KEY` (`browser_fetch/runner.py:198-223`), while the
AST guard forbids `browserbase` anywhere in the replay closure
(`test_recipe_runner_import_guard.py`, `FORBIDDEN_MODULES`). So:

- **Stay local + free** → you are running the exact configuration measured to fail on
  **Tesla (403), Bloomberg (403), McKinsey (ERR_HTTP2) and Citadel (403)** — from a
  *datacenter* IP, which is worse than my residential one. The fallback dies on the boards
  it exists for.
- **Move to Browserbase** → you pay the table above *and* dismantle an AST-enforced
  boundary.

**Two hard limits the proposal collides with**, both load-bearing for reasons already
documented in the code:

- `_SUBPROCESS_TIMEOUT_S = 90.0` (`browser_fetch/runner.py:84`). The median sweep is
  **1.7× over**; JPMorgan Oracle is **8.7× over**. The 90 s cap exists because it must stay
  below the leaf task's 900 s `wait_for` or a Chromium is orphaned on Railway
  (`runner.py:69-83`).
- `BROWSER_FETCH_MAX_PAGES = 25` (`recipe_schema.py:82`). Uber needs 68, JPMorgan 287.

**One genuine point in the proposal's favour:** dropping to daily cadence makes closure
*safer*, not just cheaper — `min_seen_age_hours = 1.5 × cadence_hours` becomes 36 h and a
`none`-oracle board needs 3 days of agreement. But it costs the product 24× of its
temporal resolution, on a hiring-**trend** visualiser, to fund a transport that is slower
and less complete than the one being replaced.

---

## 5. Brittleness — and why API-first/DOM-fallback does not neutralise it

The ordering sounds free. It is not, for three measured reasons.

1. **The fallback changes identity** (§1.1): Nintendo's DOM id and our stored id have
   **0/49 overlap**. A fallback event is a full-board churn, and the close rule turns churn
   into deletion.
2. **The fallback rots unobserved.** A path exercised only on failure is a path never
   tested. The repo already knows this shape — `TESTABLE-BOARDS.md`: *"tier 1b is still
   unproven against a live board that only it can read"*, and no board in a 70-URL sweep
   ever landed `browser_fetch`. Adding a second unexercised tier below it makes that
   worse, not better.
3. **Both paths rot, and the DOM rots faster.** A JSON contract breaks when the vendor
   ships a breaking API change; a selector breaks on a *visual* redesign, a CSS-framework
   bump, or an A/B test. I hit three selector-class failures in a single afternoon of
   measurement (`disabled:` utility class, a job title containing "Next", a card whose
   link is not inside the card). None of those is a redesign — they are Tuesday.

**Quantified as far as the evidence allows** — and the comparison is asymmetric, so treat
it as directional rather than decisive:

| | API path | DOM path |
|---|---|---|
| observed contract breaks | **0 in 10 days across 17 tracked `http_json` boards** (`TESTABLE-BOARDS.md` re-measurements 08-20 → 08-30; the only change was SpaceX drifting 2,188 → 2,187 *jobs*, not schema) | **3 selector-class failures in one afternoon** of building one extractor |
| failure signature | `HTTP 400/412`, missing path → `RecipeExecutionError` → **FAILED run, writes nothing** | fewer cards, well-formed → **a smaller answer that looks fine** |
| detectable by | the transport itself | only an independent oracle |

The honest framing: **API brittleness is loud. DOM brittleness is quiet.** Loud failures
are the ones a never-wrong-close system survives; quiet ones are the ones that delete
boards. This is the whole reason `html_no_sweep_evidence` exists.

---

## 6. The completeness oracle in a DOM-first world

**Yes — the sitemap is most of the answer, and it is already built.** `_oracle_sitemap`
(`recipe_runner.py:1169-1213`) fetches the sitemap with a plain GET at harvest time, counts
`<loc>` matching a pattern, follows one level of `<sitemapindex>`, and is compared at
tolerance 0 by `_verify_oracle_total`. It is schema-admitted for **any** transport
(`recipe_schema.py:600-603`) — **it needs no API whatsoever**. Walmart: one 294 ms GET,
2.0 MB, **15,660** job URLs.

Its two limits are both real:

- **Hit rate ≈ 1 in 4** (measured in `MULTI-SOURCE-DISCOVERY-PLAN.md §0`): Jane Street 404,
  Amazon 404, Goldman 404, Atlassian is an index naming eight non-job children.
- **A `<loc>` has no title.** `CANONICAL_REQUIRED_FIELDS` needs `(id, title, url)`, so a
  sitemap can *enumerate* a board perfectly and never *be* it. It is an oracle and an
  id-set, never a record source.

**A second oracle the DOM can carry, which I measured and have not seen proposed: the
board prints its own total.** From the page text on the first render:

| exact, parseable | rounded / unusable |
|---|---|
| JPMorgan `7181 OPEN JOBS` · IBM `of 1,802` · Goldman `of 1,034` · Anthropic `571 jobs` · Workday/Micron `2781 JOBS` · Nintendo `49 roles` · Walmart `48,887 open roles` · Sequoia `9,971 jobs` | Amazon `500+ jobs` · Apple `600+ Result` · **Meta `88 Job`** — a facet count, not the 877 total |

**8 of 22 boards print an exact total** (36%). That is a real `dom_declared` oracle with the
same shape as `declared_probed` — *and* Meta shows the trap: a plausible number next to the
list that is not the total would make an 11-job read look like it needed 88.

Note the two boards this would have saved: **Workday/Micron prints `2781 JOBS` next to the
417 its sweep collected**, and **Walmart prints `48,887 open roles` next to zero.** A
printed-total oracle turns both silent failures into loud refusals — which is the strongest
argument in this document *for* reading the DOM, just not for reading records from it.

**So the honest DOM-first oracle picture:** sitemap on ~25%, printed-total on ~40% (with a
misread risk), **`none` on the rest → `UNVERIFIED` forever → never closes.** Which is
precisely where `html_no_sweep_evidence` already puts every HTML-derived board today. A
DOM-first world does not remove that problem; it generalises it to the whole product.

---

## 7. What survives an inversion, and the staged path

**What an inversion would throw away:** the six-source design, the fan-out, the referee's
C12/C13 model-interpreted checks, `page_shape_refusal` (13a/13b), `_limit_pinned` (13c),
`declared_probed`/`facet_sum`/`header` computation and verification, the coverage floor,
`_prove_job_link`, and the reason most of the 3,122 backend tests exist. That is not a
transport swap; it is the safety system.

**What survives unchanged:** `finalize_harvest`, the id/dedupe/uniqueness gates, the close
ladder, the SSRF guard, the AST replay boundary, the sitemap oracle. Those are transport-
agnostic already — which is exactly why the DOM can be added *alongside* rather than
underneath.

### Ship it in stages. Stage 0 is free and should go first.

| stage | what | cost | measured payoff |
|---|---|---|---|
| **0** | **Emit `http_html` + `extract_css` from discovery.** It is fully implemented (`recipe_runner._run_css`) and `discover.py:1874-1877` says it *"has never been emitted"* | **$0, no browser, no new infra** | Served HTML beats the rendered DOM on **Y Combinator (9 vs 3)** and ties it on Nintendo 49, D. E. Shaw 87, Anthropic 50, Uber page-1 10. Stays `UNVERIFIED` → **cannot wrong-close** |
| **1** | The triage's four one-line API fixes: content-type aperture, anchor trailing slash, `_source` unwrap, composite-param paging | days | **Meta 877** (vs 11 from the DOM) · IBM 1,806 · Citadel · **Oracle/JPMC already landed — 7,124 of 7,181 in the DB right now** |
| **2** | DOM as an **oracle / id-set** source, not a record source — `MULTI-SOURCE-DISCOVERY-PLAN §1.3` | $0, 0 added wall clock | makes Meta's 11-of-877 and Walmart's 10-of-48,887 *detectable* instead of storable |
| **3** | Wire the sitemap oracle into discovery for boards whose oracle is `none` | ~7 GETs at discovery | Walmart gets a 15,660 oracle with no API at all |
| **4** | *Only then*: a `browser_dom` transport, gated to boards that (a) prove an exhaustive stop signal twice, (b) carry an independent oracle, (c) fit under a size cap | the §4 bill | **candidate set after stages 0–3: Uber and Citadel.** Roughly two boards |

**The smallest useful increment is Stage 0.** It is already written, costs nothing, changes
no invariant, and is the only part of "the rendered page is a record source" that the
measurements actually support.

---

## 8. The better third option

**Stop treating this as "API vs DOM" and treat it as "records vs enumeration".**

The unbounded problem is not *reading* a board — it is *proving you read all of it*. Every
failure in §3 is an enumeration failure, and the DOM makes enumeration **worse** (a
heuristic stop signal) while making records only slightly better.

So: **let the cheapest source that can produce records produce them, and let a
*different*, independent source certify completeness.** That is already the shape of
`MULTI-SOURCE-DISCOVERY-PLAN` — this evaluation is evidence for finishing it rather than
replacing it. Concretely:

- records ← JSON XHR, served-HTML island, or served-HTML anchors (Stage 0)
- enumeration ← sitemap `<loc>` count · the board's own printed total · the rendered DOM's
  per-job href count as a **floor** · facet sums
- and where no source can certify, the board is `UNVERIFIED` and **shows every job it sees
  and closes none** — which is the correct product behaviour and already implemented.

The one thing genuinely worth borrowing from the proposal: **the rendered DOM is a
first-class evidence source that discovery currently under-uses.** It is just evidence
about *how many* and *where they link*, not evidence about *what the jobs are*.

---

## 9. What I would NOT change

1. **The agent-free replay boundary and its AST guard.** Three independent tests, a runtime
   assert on every call, subprocess isolation. Nothing here is worth spending it.
2. **The verdict-first close ladder** (`fetch_custom_company.py:874-979`) and
   `MISSED_RUN_THRESHOLD = 2`. Ten conditions gate a close; every measurement in this doc
   argues for keeping all ten.
3. **`http_html` may not carry a pagination step** (`recipe_schema.py:740-745`). Its comment
   is exactly right: a paginating HTML recipe would VERIFY and close everything past page
   one.
4. **`html_no_sweep_evidence`** (`harvest_verification.py:776-781`). This guard is the
   single most correct line of code relative to what I measured.
5. **`_prove_job_link`.** One interpretation, works, leave it.
6. **Hourly cadence.** The 24× resolution loss is real, and daily is only needed to fund a
   transport that stages 0–3 make unnecessary.

---

## 10. What I could not determine

- **Whether a *complete* JPMorgan Oracle sweep terminates cleanly.** It was still producing
  25 new ids per scroll at the 90-step cap; ~693 s is an extrapolation from the measured
  per-step rate, not an observed completion. The cost table says so.
- **Whether Micron's 417 is a hard ceiling or a timing artefact.** It reproduced exactly
  twice at the 90-step budget, which is suggestive but not proof that a longer budget could
  not go further.
- **Whether IBM's reshuffle is relevance-ranking, an A/B test, or session-scoped.** I
  measured the turnover twice (40 on 30 at 11.8 min; 315 on ~1,350 back-to-back); I did not
  establish its cause, and I did not measure whether a fixed sort parameter removes it —
  **that is the first thing to check if anyone wants to rescue this.**
- **Whether Browserbase changes the pagination results.** All sweeps ran on local Chromium.
  The extractability column was re-run on Browserbase where local failed, but the *sweeps*
  were not, so Citadel's and Meta's false-completes are local-only observations.
- **Real per-board bandwidth**, so the proxy line ($10–12/GB) is absent from the fleet
  table. If proxies are needed for the bot-walled boards it is a material addition.
- **Walmart's card click target.** I proved the card has `data-job-id` and no `href`; I did
  not establish whether a click yields a stable, derivable URL.

---

### Provenance

Measured 2026-08-30 from this worktree. Local Chromium = Playwright 1.62 headless, 1440×1000,
Chrome 140 UA, residential US IP. Browserbase = a fresh session per board via the same
credentials the capture path uses. Board sizes are the board's own printed count or the row
count in `jobscraper_pr243`. Stored recipes and harvest verdicts were read from that database
read-only; nothing was written to it.
