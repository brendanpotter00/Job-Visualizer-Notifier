# Custom Company Sources — the plan, in one read

**Status:** approved 2026-08-09 and **built** — Phases 1–3 have shipped. This is the architecture and the evidence behind it; `BUILD-PLAN.md` has the phase-by-phase detail and `STACK-ORCHESTRATION.md` logs what actually happened. Two things below were later overtaken: the Browserbase-vs-local runtime question was settled by the capture pivot (discovery captures once in our own Chromium; replay is `http_json` or `browser_fetch`), and Phase 4 was dropped as subsumed.
**Evidence:** ~21 real careers sites harvested end-to-end 2026-08-08/09, one adversarial design review against the live repo code, and browser/CORS/cost claims measured today. $0 spent beyond ~22 free Browserbase minutes.

---

## The goal

> A user pastes a careers URL (or types a company name). We check it **every 24 hours** and show them that company's jobs — for them only — with open/close detection.

Your bar, in your words: **it works on nearly every board I try, and failures are loud — never silently wrong.**

---

## The one idea

**Every company is a stored script, authored once, replayed nightly with no agent.** There are no tiers and no fallback chain — just a table of scripts. Some are one line; some are nine. Every one runs the **same verification gate** every night.

```
   Duolingo's stored script                 Amazon's stored script
   ────────────────────────                 ──────────────────────
   1  ats_client(greenhouse, "duolingo")    1  fetch(amazon.jobs/search.json)
                                             2  paginate_offset(...)
   → 65 jobs. one primitive.                 3  partition_by_facet(country, state)
                                             4  extract_json_path("jobs")
   ← SAME GATE →                             5  dedupe_key("id_icims")
                                             6  oracle: facet_sum(single_valued)
                                             7  assert_page_advances
                                             8  assert_unique_ids_vs_total
                                             9  assert_cap_not_hit(10000)
                                             → 22,191 jobs. nine primitives.
```

This is the answer to *"why do you keep bolting on a T1?"* — **the ATS client is just primitive #1**, not a special path. Duolingo's script is short because Duolingo is easy, not because it skips anything. It faces the same gate as Amazon, nightly. There is no bypass.

> The review proved why the bypass had to die: your shipped Workday client **silently caps at 2,000 jobs** (`20 × 100 pages`) and returns a partial list instead of raising. Target has 11,960. The old "ATS shortcut" would have served 2,000-of-11,960 forever, looking perfectly healthy. Making the ATS client a *scripted primitive behind the gate* is what catches it.

---

## The gate — where the product lives or dies

Every harvest, every night, produces exactly one verdict. **Only a run that can prove it saw the whole board may close a job.**

```
   harvest ─→ ┌──────────── VERIFICATION GATE ────────────┐
              │  1. an oracle agrees with the count, OR    │
              │     the run is self-consistent, OR none    │
              │  2. no pagination cap was hit              │
              │  3. pages advanced, id-sets disjoint       │
              │  4. post-dedup unique ids == total         │
              │  5. wrong in BOTH directions is fatal      │
              │  6. if 0 rows: the zero is an oracle=0     │
              └───────────────────┬────────────────────────┘
                                  ▼
   VERIFIED ─────→ upsert · last_seen · miss++ · MAY CLOSE
   UNVERIFIED ───→ upsert · last_seen · ██ NEVER CLOSES ██ · badge
   FAILED ───────→ raise · writes nothing · retry once · then repair
```

**The load-bearing sentence, walked against all four real traps:**

> *A job is never closed by a run that could not prove it saw the whole board.*

| trap (all real, all measured) | what would go wrong | what catches it |
|---|---|---|
| **Marcus & Millichap** — Lever board `200 []` + polished "no openings", 204 real jobs on Workday | close 204 jobs | zero-proof needs a **canonical backlink** — the careers page must still name this board |
| **Target** — Workday declares 2,000, real 11,960, boundary probe passes | harvest 45%, look healthy | **independent oracle** (single-valued facet sums = 11,960); same partition trick harvests the rest |
| **Amazon** — 43 jobs no facet indexes; 0.998 passes a 1% tolerance | close 43 real jobs nightly | **tolerance > 0 ⇒ that run closes nothing.** Approximation may only *add* |
| **Intel** — offset past total wraps to page 1; 636 unique ids on a 663 board | dup rows pass naive checks | **post-dedup** unique-ids-vs-total + disjoint-page assert |

**The new piece the review forced:** for boards that publish no total (YC, Jane Street, Blackburn's), `oracle:none` used to mean *never closes* — which makes their job counts climb forever, and a monotonic line is wrong data, not missing data. So we add a **self-consistency oracle**: a run is complete if pages advanced monotonically with disjoint ids, the last page was short, nothing errored, and the count sits within X% of the trailing 14-run median. That lets those companies close on 3 consecutive complete runs instead of never.

---

## Where scripts run

**Every script runs in a browser page context** — that's the uniform substrate you wanted. HTTP-style primitives run as `fetch()` from the page after navigating to the board's origin (**measured working today**: Amazon same-origin, Duolingo cross-origin to Greenhouse's `ACAO:*` API); DOM-style primitives run natively; WAF-gated pagination (CBRE) runs as in-session GETs.

**Discovery** (once per add) is an agent driving a browser, watching network + DOM, authoring the script. **Replay** (nightly) is the stored script with no agent.

**One honest open decision — where the browser lives:**

- **Browserbase runtime** (recommended): keeps Chromium out of our Railway deploy entirely. The 2026-03-29 mass-closure was a base-image change silently breaking our own Chromium — that isolation is worth real money, and you already said you're fine landing here.
- **Local Playwright on a worker**: the spike's own committed verdict was "don't adopt Browserbase — only ~1 in 14 URLs truly needs a browser," and local Chromium cleared CBRE's WAF. But in-process browsers caused two prior incidents (OOM, pthread exhaustion), and a separate browser service reintroduces exactly that ops burden.

The review's synthesis, which I'm adopting: **transport is a declared field on each script** (`page_fetch` / `page_request` / `dom`), the gate is identical regardless, and http-only scripts can even run on plain `httpx` — so the browser vendor is swappable, not load-bearing. Default to Browserbase; keep `replay.py` (already written, 10/10 invariant tests green) as the discovery smoke-tester and the plain-HTTP fallback.

---

## When discovery or replay fails

```
   discovery fails 2×  →  REFUSE loudly. "We can't track this site." Nothing half-created.
   replay FAILED       →  retry once → auto-repair: ONE agent re-discovery pass
                          ├─ same host + same tenant  →  hot-swap (no human)
                          └─ host or tenant changed   →  admin approval, always
```

**Repair uses board identity, not job identity.** The review killed my Jaccard-overlap idea: a Greenhouse→Ashby migration changes every id (Jaccard 0) yet is the *most common* real repair, while a parent-company board that's a superset shares ids and passes by coincidence. So the gate is **canonical backlink + tenant/eTLD+1 stability**, and **the first run after any script change closes nothing** — a bad swap can then only add rows, never delete them.

---

## Every terminal state a URL can reach

| state | real example | what the user sees |
|---|---|---|
| **Live** | Duolingo, Amazon, Cisco | jobs + trend graph, updated nightly |
| **Live, can't-close** | YC, Jane Street | jobs shown; badge: *"We track new postings here, but can't yet confirm when one closes."* |
| **Refused** | Tesla (Akamai, non-replayable) | *"We can't reliably track this site."* — and this is a **success** of the design, not a failure |

---

## Closure safety — the 2026-03-29 lesson, generalized

A job closes only when **all** hold: exact coverage (tolerance 0), 2 missed runs, **and** >36h since `last_seen_at`. Plus two rules the review added:

- **A run that didn't execute is not a miss.** Misses increment only inside a VERIFIED harvest — so a Browserbase outage can't close anything.
- **Fleet circuit breaker:** if >20% of the night's companies FAIL, nobody closes that night. This is the check that would have made 2026-03-29 a non-event.

---

## Cost — and the real constraint

| | |
|---|---|
| ATS-shortcut scripts (Duolingo etc.) | **$0** — plain HTTP |
| Discovery (one-time per add) | **~$0.25–1** (Sonnet, ~50–200k tokens) |
| Browser replay, 100 companies daily | **~25–50 browser-hr/mo** (I'd earlier said 10–25 — that was my own inputs halved; corrected) |
| Developer plan | **$20/mo, 100 browser-hr** — cliff at ~200 companies |

**Dollars are not the limit. Repair throughput is.** At ~3% board churn per month, ~300 companies means **~9 human-approved repairs a month, forever — and you are the human.** That number, not cost, is what breaks at scale, and it's stated here on purpose.

---

## Honest coverage & the falsifier

- **Your named list: 7 of 10 fully verified**, 3 live-but-can't-close, 0 failed.
- **Arbitrary input: ~60–70%.** Of 9 tech employers tested, 0 were hard; of 16 non-tech, 6 were. Small non-tech employers thin out — many publish no machine-readable board at all.
- **The week-1 falsifier that kills this design:** *if >15% of real adds land UNVERIFIED, then close-detection doesn't exist for them and we should refuse those URLs rather than badge them.* Measure it before trusting the badge.

---

## What the review changed (so you can see the diff)

Corrected against the live code, not asserted:

- **Killed the ATS bypass.** It routed Target into the Workday 2,000-cap trap. ATS clients are now scripted primitive #1, behind the gate. *(This also means the Workday client's silent 2,000 ceiling must be fixed to raise, not return partial.)*
- **Tolerance>0 ⇒ no closes.** A tolerated gap was silently closing Amazon's 43 hidden jobs nightly.
- **Added the self-consistency oracle** so no-total boards close in 72h instead of never.
- **Added the fleet circuit breaker** and "a non-executed run is not a miss."
- **Repair keys on board identity (canonical backlink), not Jaccard.** First-run-after-change closes nothing.
- **Cut `click_sequence` from v1** — scripted clicks on a user URL replayed nightly is an unbounded security surface for ~0% measured coverage.
- **Primitive count is ~21–25, not 12** — and "agent asked for a capability we don't have" becomes a logged REFUSE reason that *is* the roadmap for the next primitive.
- **Execution-time SSRF + `ignoreCertificateErrors:false`.** Our `url_guard` runs at add-time only; nightly fetches need CDP-enforced host pinning, and Browserbase accepts any cert by default.
- **Correction of record:** I'd written that a recalibrated `0.85` safety guard was committed. It exists on `main`, **not** in this worktree — and even on main it's inert on a company's first run and tuned for 30-min cadence, so it can't catch a wrong day-one baseline. Daily companies need a per-company learned baseline. *(A subagent asserted this; I wrote it down without verifying. Fixed.)*

`BUILD-PLAN.md` carries the phase-by-phase detail; `STACK-ORCHESTRATION.md` carries the log of what was built, in what order, and which decisions were reversed on the way.
