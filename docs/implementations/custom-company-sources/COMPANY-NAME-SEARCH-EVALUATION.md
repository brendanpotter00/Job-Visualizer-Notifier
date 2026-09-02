# Company-name search — measured, not guessed

**Verdict: GO WITH CONSTRAINTS.** Browserbase Search can power "type a company name",
but only with a **host-shaped query**, only if we score **all 25 results**, and only if
we **never auto-pick below the first rung**.

**The winning strategy — one search call:**

```
{COMPANY} jobs myworkdayjobs.com greenhouse.io ashbyhq.com lever.co jobs.gem.com eightfold.ai
```

`numResults=25`, then run **every** result through `resolve_ats_url`.
**Measured hit rate: 22/29 = 76%** on a ground-truth set where the correct board is
known. Add the free L1/L2 ladder we already own and it is **25/29 = 86% for that same
one call**. **Wrong-ATS rate: 4/30 ungated (13%), 0/30 pointing at a live board owned by
a different company once a $0 name gate is applied.**

**Browserbase Fetch is a NO.** It returned the byte-identical candidate set to plain
`httpx` on **15 of 15** pages, at 2.4× the latency, for money. It replaces nothing.

**Measured 2026-09-01.** 204 real Search calls, 30 Fetch(raw), 5 Fetch-Extract. Every
board claimed below was probed live against the real ATS API. No application source file
was changed.

---

## 1. What was measured

| | |
|---|---|
| **Ground truth** | 30 companies. Correct board taken from prod `companies` (read-only `SELECT`) and the verified rows in `ATS-BEHIND-CAREERS-PAGE.md` / `TESTABLE-BOARDS.md`. All six ATSs, the four documented traps (Cisco, Snap, GM, Discord), the documented negative (Spotify), four boards whose token shares nothing with the brand (`wehrtyou`, `optiverprivate`, `interaction`, `salesforce`/`Slack`), and six small/obscure companies (Workweave, Nominal, Belvedere Trading, Poke, Raindrop, Browserbase). |
| **Oracle** | `ats_link_resolver.resolve_ats_url` — pure, IO-free, free to call. A result counts only if it resolves to the **exact** board identity: `(ats, token)`, or `(workday, tenant, career_site_slug)`, or `(eightfold, domain)`. "Some ATS" is not a hit. |
| **Confirmation** | Every board named below — right or wrong — was fetched live from the real ATS API and its job count recorded. Nothing here is inferred from a URL looking plausible. |
| **Budget spent** | 204 Search (of the ~250 allowed, 1,000 free on the plan), 30 Fetch(raw), 5 Fetch-Extract. Every call cached to disk so no query was paid for twice. |

**Two ground-truth rows were wrong and Search is what proved it** — see §7. `Jane Street`
and `Raindrop` were entered as "no ATS in the six" on the strength of the repo's own
docs. Both have live boards. They are scored as hits, correctly.

---

## 2. The strategy comparison

Same 30 companies, same `numResults=25`, same oracle. `hit@25` = the correct board is
somewhere in the 25 results; `hit@1` = it is the first result.

| # | Strategy | Query | Calls | **hit@25** | hit@1 | hit@5 | wrong-ATS | aggregator % | p50 | p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 | Bare name | `Cisco` | 1 | **2/29 · 7%** | 0 | 0 | 0 | 13.2% | 1.80s | 2.72s |
| S2 | Naive natural | `Cisco careers job board` | 1 | **14/29 · 48%** | 3 | 10 | 2 | 11.9% | 1.74s | 2.26s |
| S3 | The 174-char prompt | *(from `ATS-BEHIND-CAREERS-PAGE.md`)* | 1 | **12/29 · 41%** | 4 | 9 | 3 | 3.9% | 2.07s | 2.97s |
| **S4** | **Host-shaped, combined** | *(the template at the top)* | **1** | **22/29 · 76%** | **11** | **21** | 4 | 7.6% | 1.87s | 2.98s |
| S5 | Host-shaped, 6-way fan-out | one query per ATS host | 6 | 8/11 · 73% † | 2 | 3 | — | 8.7% | 1.94s | 3.04s |
| | *S4 on that same 11* | | 1 | *6/11 · 55%* | | | | | | |

† S5 was run on a deliberately hard 12-company subset (budget), so its column is only
comparable to the italic row beneath it, not to the rest of the table.

**Read this table three ways.**

1. **The host-shaped query is the whole result.** S4 beats the 174-char instruction
   prompt by **35 points** for the same one call. The prompt asks a search index to
   reason about what sits behind a careers page; the host-shaped query asks it to find
   a string it has already indexed. It is a search engine, not an agent, and the
   measurement says so.
2. **The naive query fails the owner's own headline example, and so does the prompt.**
   Both return zero Cisco Workday results. S4 does not rescue Cisco either — the free
   L2 layer does (§3).
3. **S4 is a strict superset.** Unioning S4 with S1, S2 and S3 — four calls instead of
   one — recovers **exactly zero** additional companies. There is no cheap ensemble
   here; pay for one query and pay for the right one.

### Top-1 versus all-25 — this is the single cheapest decision in the doc

| | |
|---|---|
| Correct board present in the 25 S4 results | **22 / 29** |
| …and it was the **first** result | **11** |
| …present but **not** first | **11 — 50% of all hits** |
| Deepest rank a correct board was found at | **#6** (NVIDIA) |

Scoring only the top result would halve the feature. `resolve_ats_url` is pure and
IO-free, so scoring 25 instead of 1 costs **nothing** — no extra call, no extra
millisecond of network. Do it. `numResults=25` is also the API maximum, so there is no
further headroom to buy.

### Fan-out: +18 points, 6× the calls, and it is dangerous

On the shared 11-company subset the 6-way fan-out found 8 boards where the single
combined query found 6. It is the only thing that reaches Cisco (`Cisco myworkdayjobs.com`
→ correct board at rank 26) and Snap. But it is also where every catastrophic wrong
answer in this study came from (§4). **Use it as a confirm-only escalation, never as a
default and never as an auto-pick.**

---

## 3. The recommended resolution ladder

The name box is a **new front door onto the ladder we already have**, not a second
ladder. A pasted URL still enters at L0 exactly as it does today and nothing about that
path changes.

```
user types a name
     │
 ┌───▼──────────────────────────────────────────────────────────────────────┐
 │ RUNG A   1 Search call, host-shaped template, numResults=25              │
 │          score ALL 25 with resolve_ats_url (L0, pure, free)             │
 │          keep only candidates whose token NAMES the company (§4 gate)   │
 │          $0.007 · p50 1.9s / p95 3.0s                                    │
 └───┬────────────────────────────────────────────── 22/29 · 76% ──────────┘
     │ nothing resolved
 ┌───▼──────────────────────────────────────────────────────────────────────┐
 │ RUNG B   take the best non-aggregator careers URL from the SAME results │
 │          and hand it to the EXISTING ats_discovery.discover_ats         │
 │          (L1 redirect-following + L2 embedded-board sniff)              │
 │          $0 · ~1–3s · no new code, no new call                          │
 └───┬───────────────────────────────────── +3 ⇒ 25/29 · 86% ──────────────┘
     │ still nothing
 ┌───▼──────────────────────────────────────────────────────────────────────┐
 │ RUNG C   6-way per-provider fan-out, `{COMPANY} <ats-host>` ×6          │
 │          $0.042 · ~3s wall if issued in parallel                        │
 │          ⚠ SHOW CANDIDATES — NEVER AUTO-ADD FROM THIS RUNG              │
 └───┬───────────────────────────────────── +3 ⇒ 28/29 · 97% ──────────────┘
     │ still nothing
 ┌───▼──────────────────────────────────────────────────────────────────────┐
 │ RUNG D   the EXISTING Discovery tier, on the rung-B careers URL         │
 │          real browser + Haiku · ~45s · 4–8¢ · can fail                  │
 └──────────────────────────────────────────────────────────────────────────┘
```

**Measured, rung by rung, on all 29 companies with a known board:**

| After | Cumulative | Companies newly resolved | Marginal cost |
|---|---|---|---|
| Rung A | **22/29 · 76%** | 22 | 1 search · $0.007 |
| Rung B | **25/29 · 86%** | Cisco, Slack, Nominal | **$0** |
| Rung C | **28/29 · 97%** | Snap, Databricks, Retool | 6 searches · $0.042 |
| Never | 28/29 | — | Hudson River Trading only |

**Rung B is the best value in the feature and it is code we already own.** Three
companies — including the owner's headline Cisco example — are recovered by the free
`httpx` layer that already exists, given nothing but a careers URL the search call
already handed us. Cisco's Workday link lives on `careers.cisco.com/global/en/search-results`,
which `_SNIFF_SUBPATHS` already probes. **`ATS-BEHIND-CAREERS-PAGE.md` lists Cisco as a
trap that falls through to Discovery; measured today, L2 resolves it.** That doc checked
only `/global/en`. The trap table needs a correction.

**Do not put Search in front of `resolve_ats_url`.** L0 on a pasted URL is exact, free
and instant. Search only ever fires when the input is a name.

---

## 4. Failure modes, ranked

### 1. Wrong-ATS — a live board belonging to a *different company* ⚠ THE ONE THAT MATTERS

This silently creates a scraper for someone else's jobs. It passes every automated check
we have, because the board **is** real and **does** return jobs. Every row below was
probed live today.

| Typed name | Board returned | Rank | Live jobs | Who it actually is | Rung |
|---|---|---|---|---|---|
| **Databricks** | `guidehouse.wd1.myworkdayjobs.com/External` | **#1** | **794** | Guidehouse, a consulting firm | C |
| **Retool** | `generalmotors.wd5.myworkdayjobs.com/careers_gm` | #14 | **820** | General Motors | C |
| **Snap** | `jobs.ashbyhq.com/gc-ai` | #19 | 26 | GC AI, a legal-AI startup | A |
| **Hudson River Trading** | `jobs.ashbyhq.com/turn-river` | #70 | 11 | Turn/River Capital | C |
| **Hudson River Trading** | `jobs.ashbyhq.com/river` | #99 | 4 | River, a bitcoin company | C |
| **Poke** | `jobs.lever.co/poki` | #10 | 2 | Poki, a Dutch games site | S3 |
| **Poke** | `job-boards.greenhouse.io/pokemoncareers` | #65 | 27 | The Pokémon Company | C |
| **Slack** | `boards.greenhouse.io/embed/job_board/js?for=automated` | #30 | 3 | an HVAC contractor | C |
| **Poke / Nominal** | `boards.greenhouse.io/embed/job_board/js?for=d3` | #32 / #43 | 6 | some company called D3 | C |

The last two rows are their own small horror: those URLs are **Greenhouse's own embed
JavaScript asset**, indexed by the search engine. `_greenhouse_candidate` reads `?for=`
exactly as designed and hands back `automated` and `d3` — real board tokens for real
unrelated companies.

**The $0 mitigation, measured.** Accept a candidate automatically only when the board
token *names the company* — `norm(token)` contains `norm(typed_name)` or vice versa,
checking the Workday tenant **and** the career-site slug. Containment only; **no edit
distance** (edit distance 1 would accept `poki` for `Poke`).

| | Ungated "first ATS-resolvable URL" | **With the name gate** |
|---|---|---|
| **Rung A** auto-correct | 21 | 20 |
| **Rung A** auto-**wrong** | 4 | **3** |
| **Rung A** wrong *and live* *and* a different company | **1** (Snap → GC AI) | **0** |
| **Rung C** auto-correct | 7 | 9 |
| **Rung C** auto-**wrong** | 7 | **4 — still 31%** |

The gate's three remaining rung-A "wrong" answers are all harmless: NVIDIA's *own*
Eightfold board (right company, other board — NVIDIA runs two), `jobs.lever.co/nominal`
(**0 jobs**, caught free by `probe_candidate`), and `walmart.wd5.myworkdayjobs.com/WalmartExternal`
(**HTTP 422 / 500**, dead, caught free). It costs one correct auto-add: Poke, whose real
token is `interaction`, is suppressed to "confirm this" rather than added silently.

**The gate does not save rung C.** Even gated, the fan-out auto-picks a wrong company
4 times in 13. That is the evidence, and it dictates the UI.

### What the UI must do — supported by the numbers above

* **Rung A, gate passes, probe returns >0 jobs → add it.** 20 auto-adds, **0** of which
  point at another company's live board. This is safe.
* **Rung A, gate fails, or any candidate from rung C → show the user the candidates and
  make them pick.** Show at most 3–5, and show **the board's own name and live job
  count**, not just the URL. "Guidehouse · 794 jobs" under a search for Databricks is
  instantly obviously wrong to a human and invisible to every check we own.
* **Never present a rung-C result as the answer.** Present it as a question.
* This is the same conclusion `NAME-RESOLUTION-POC.md` reached about the JK Renewables
  fabrication, arrived at independently and from harder evidence: *"the only thing that
  catches this class is the user reading the company name we resolved before we spend
  anything."*

### 2. Right company, wrong board

Not dangerous, but it silently tracks the wrong population.

* **NVIDIA** — S4's top ATS hit is NVIDIA's **Eightfold** board; prod tracks the
  **Workday** one (2,000 jobs). Both are NVIDIA's. Rank 6 has the Workday board.
* **Hudson River Trading** — this one is a **pre-existing L2 bug this feature inherits**.
  `hudsonrivertrading.com/careers` embeds `boards.greenhouse.io/hrttalentcommunity`,
  which is a *talent-community* shell: **3 jobs**, titled "HRT Talent Community". The
  real board is `wehrtyou` — **74 jobs**. L2 returns the wrong one today, and a naive
  `jobs > 0` probe waves it through. HRT is the only company in this study that no rung
  resolves.

### 3. The token that shares nothing with the brand name — the structural ceiling

The three companies Search never finds are exactly the three whose board identifier is
not derivable from, and not co-indexed with, their name: `salesforce`/`Slack` (Slack),
`wehrtyou` (HRT), and — before rung C — `Cisco_Careers` behind a Phenom SPA. A search
index cannot return a string that is neither in the query nor on the page. **Two of the
three are recovered by L2 for free**, which is the strongest argument in this document
for keeping the name box wired into the existing ladder rather than beside it.

### 4. Aggregator pollution — real but small, and the fallback is good

| Strategy | Aggregator results (of 750) |
|---|---|
| S1 bare name | 99 · **13.2%** |
| S2 naive | 89 · 11.9% |
| S3 174-char prompt | 29 · **3.9%** |
| **S4 host-shaped** | 57 · **7.6%** |

Naming ATS hosts halves the LinkedIn/Indeed/Glassdoor noise versus a bare name.

**Careers-page fallback quality is high.** For the 8 companies where S4 found no ATS in
25 results, the top non-aggregator result was a genuine company careers or job page in
**7 of 8** — `careers.snap.com/jobs`, `slack.com/careers`, `retool.com/careers`,
`nominal.io/careers`, `hudsonrivertrading.com/careers`, a real Cisco job page,
`careers.walmart.com/us/en/jobs/…`. **Zero** were LinkedIn, Indeed or Glassdoor. The one
miss was `scoutify.com/companies/databricks` (a job aggregator not on our block list —
add it). Rung B and rung D both get a fair shot.

### 5. Eightfold needs `?domain=` and search does not always supply it

`resolve_ats_url` only emits an Eightfold candidate when the URL carries `?domain=`
(the module docstring explains why, and it is right). Netflix resolved because S4
happened to return `app.eightfold.ai/careers?domain=netflix.com`. A bare
`explore.jobs.netflix.net` would have resolved to `None`. **n=1** — one Eightfold company
in the set — so treat this as a known sharp edge, not a measured rate.

---

## 5. Fetch — evaluated on its own merits, and it is a NO

### (a) Can Fetch recover an ATS link that Search missed?

Head-to-head on 15 pages: Browserbase `Fetch(format:"raw")` versus plain `httpx` with
our existing User-Agent, both scanned with the existing `_EMBEDDED_ATS_PATTERNS`.

| | |
|---|---|
| Pages where Fetch found the **same** candidate set as `httpx` | **15 / 15** |
| Pages where Fetch found **more** than `httpx` | **0** |
| Fetch(raw) latency | p50 **2.58s**, p95 4.36s |
| `httpx` latency | p50 **1.09s**, p95 3.12s |

**Fetch is 2.4× slower than the free thing we already do, and never once saw more.**

Cisco specifically, as asked: `careers.cisco.com/global/en` returns **176,896 bytes with
zero occurrences of any of the six host strings** through Fetch, through
`allowRedirects:true`, and through `httpx`. It is a Phenom SPA and Fetch does not run
JavaScript, exactly as predicted. But the sub-path `/global/en/search-results` **does**
carry `cisco.wd5.myworkdayjobs.com/Cisco_Careers` in its static HTML — and `httpx` finds
it just as well as Fetch does. Cisco is an L2 win, not a Fetch win.

`allowRedirects` does matter and defaults to `false`: `jobs.intel.com` with it off
returns a **301 with a 0-byte body**, and the `location` header pointing at
`corpredirect.intel.com`; with it on, the full 6,712-byte page and the correct Workday
candidate. If Fetch were ever used, it must be `allowRedirects: true`. It should not be.

Two pages behaved differently, neither usefully: `capitalonecareers.com` returned
**502** from Fetch (and failed for `httpx` too), and `tesla.com/careers/search/` returned
200 to Fetch where `httpx` got 403 — but the 200 was a 2,510-byte shell with no ATS
link in it. **Bot-wall bypass is the only thing Fetch could plausibly have offered, and
it did not deliver a single usable candidate that way.** `whoop.com/careers` returned
403 to both.

### (b) Can Fetch replace part of the browser Discovery tier?

**No, and the reason is structural.** Discovery's job is to run a real browser and
capture the **XHR/JSON feed** a careers SPA fetches after load. Fetch does not execute
JavaScript, so it cannot observe a request that JavaScript makes. The only part of
Discovery it could stand in for is "read a static page and look for a link" — which is
precisely what L2 already does, with `httpx`, for **$0**. Fetch is strictly dominated.

### (c) Fetch Extract (`markdown` / `json`) — pricier, and it fabricates

Five calls, deliberately. `format:"json"` with a schema asking for the ATS board URL:

| Page | Extract returned | Verdict |
|---|---|---|
| `slack.com/careers` | `salesforce.wd12.myworkdayjobs.com/Slack` ✅ | correct — **and the free regex on the raw body returned exactly the same thing** |
| `discord.com/careers` | `""` | honest empty |
| `databricks.com/…/open-positions` | `""` | honest empty |
| `careers.cisco.com/global/en` | **`https://careers.cisco.com/`** as `ats_board_url` | **fabricated** — it invented the careers page as the "ATS board"; it did correctly name the vendor as "Phenom People" |

**Extract buys nothing over `raw` + the regex we already have, at 4× the price, and it
fabricates.** Cost of this whole sub-experiment: **5 calls**, one `markdown` and four
`json`.

---

## 6. Cost model

Rates read from Browserbase's own pricing page, 2026-09-01:

| | Free allowance | Overage |
|---|---|---|
| Search | 1,000 (Free/Dev/Startup) | **$7 / 1k** = **$0.007** per call |
| Fetch (raw) | 1,000 Dev / 10,000 Startup | $1 / 1k ($4 / 1k with proxies) |
| Fetch Extract | — | **$4 / 1k** ($7 / 1k with proxies) |

**Per name-add, blended over the ground-truth set** (rung C fires for the 4/29 = 14%
that survive rungs A and B):

| Path | Calls | Search $ | Latency | Free-ATS rate |
|---|---|---|---|---|
| **Paste a URL (today, unchanged)** | 0 | **$0** | 0 ms (L0) / 1–3s (L1–L2) | n/a |
| **Type a name — rungs A+B** | 1 | **$0.0070** | p50 1.9s, p95 3.0s | **86%** |
| **Type a name — full ladder A+B+C** | 1 + 0.14×6 = **1.84** | **$0.0129** | p95 ~6s | **97%** |
| **Discovery (today's fallback)** | — | **$0.04–0.08** | ~45s | — |

**Against the LLM alternative already measured in `NAME-RESOLUTION-POC.md`** — the
honest comparison, because that doc's "usable" number counts careers pages that still
cost a Discovery run. What matters is the **free-ATS** rate:

| Approach | $ / name | free-ATS rate | **Expected total, incl. the Discovery runs it fails to avoid** |
|---|---|---|---|
| `haiku_notools` | $0.00061 | 5/26 · **19%** | 0.00061 + 0.81 × $0.06 = **$0.049** |
| `haiku_websearch` | $0.02125 | 11/26 · **42%** | 0.02125 + 0.58 × $0.06 = **$0.056** |
| **BB Search, rungs A+B** | $0.0070 | **86%** | 0.0070 + 0.14 × $0.06 = **$0.016** |
| **BB Search, full ladder** | $0.0129 | **97%** | 0.0129 + 0.03 × $0.06 = **$0.015** |

Browserbase Search costs **11× a Haiku call** and is **3× cheaper overall**, because the
only cost that matters is the browser sessions it prevents. It is also **3× cheaper and
twice as accurate** as Haiku-with-web-search. The 1,000 free searches cover the first
~540 name-adds on the full ladder.

Different corpora, so the row-to-row comparison is directional, not a controlled A/B —
but a 19% → 86% gap does not close on corpus differences.

---

## 7. Surprises, and what I could not verify

### Two things in our own docs are wrong, and both cost us money today

**Jane Street has a live Greenhouse board.** `job-boards.greenhouse.io/janestreet` —
**231 jobs**, and every posting's `absolute_url` is
`janestreet.com/join-jane-street/apply/<id>?gh_jid=<id>`. That is conclusive. This repo
tracks Jane Street through the browser-capture tier as a custom `http_json` feed
(233 jobs, `TESTABLE-BOARDS.md`). **S4 found the free board at rank 2.** Same board,
one is free and instant.

**Raindrop — the single company in prod on the paid Discovery tier — has a live Ashby
board.** `jobs.ashbyhq.com/raindrop`, **9 postings**, titles matching prod's stored
discovery preview one for one (Sales Development Representative, Forward Deployed
Engineer (FDE), Founding Recruiter, Security Engineer…). **S4 found it at rank 2.** The
one live example of "there genuinely is no ATS to find" in `ATS-BEHIND-CAREERS-PAGE.md`
turns out to have one.

Neither was a lucky guess: both were found by the same one query, and both were probed
live. If a single search call had run before that Discovery session, we would have a free
Ashby board instead of a nightly browser capture. **That is the strongest single argument
in this document for shipping the feature.**

### A real bug in L2, found by accident

`retool.com/careers` contains `https://jobs.gem.com/retool` at **byte 575,143** of a
**591,062-byte** page. `ats_discovery._SNIFF_MAX_BYTES` is **524,288**. The link is
50 KB past the cap, so L2 returns `no_ats_detected` on a page that plainly names the
board. Reproduced twice. This is independent of the name feature and worth its own fix.

### Other surprises

* **The 174-char instruction prompt is worse than a naive query** (41% vs 48%) and half
  as good as naming the hosts. Writing better English at a search index does not help;
  writing hostnames does.
* **A bare company name is almost useless** — 2/29. Whatever the box does, it must
  rewrite the query.
* **The correct board is not first half the time.** 11 of 22 S4 hits ranked #2–#6.
* **Aggregator pollution went *down* when we named ATS hosts** (13.2% → 7.6%).
* **`scoutify.com`, `landearly.com`, `tryjeremy.com`, `resumeadapter.com` and
  `jobs.generalcatalyst.com`** all appeared as top non-ATS results and none are in
  `_NEVER_MATCH_DOMAINS`. That list needs extending.

### Could not verify

* **Search result stability over time.** Every number here is one snapshot on
  2026-09-01, from a cached run. Search rankings drift; a re-run in a month may differ.
  Nothing was measured twice on different days.
* **Whether Search is Exa-backed in a way that changes with query length or locale.**
  Not probed.
* **Concurrency limits and 429 behaviour on Search.** Every call was throttled to
  ~109/min under the documented 120/min ceiling, so no rate limit was ever hit and its
  behaviour is unobserved.
* **Fetch's `proxies: true` path** — not exercised. The two bot walls (WHOOP, GM) were
  tested without proxies only, so "Fetch cannot beat a bot wall" is measured for the
  default configuration and **inferred** for the paid proxy configuration.
* **The name gate's false-negative rate at scale.** It suppressed exactly one correct
  answer here (Poke → `interaction`). n=29 is too small to put a number on that.
* **Eightfold coverage.** One company. The `?domain=` sharp edge is real but its
  frequency is unmeasured.
* **Ambiguous company names.** `NAME-RESOLUTION-POC.md` found Bolt and Sierra to be the
  hard cases. Neither was in this set, so how Search behaves on a genuinely ambiguous
  name is **untested** — and given the wrong-ATS evidence in §4, it is the first thing
  to test before shipping.

---

## Appendix — per-company results

Rank of the **correct** board in each strategy's 25 results (`—` = absent). `Rung` is
where the recommended ladder resolves it.

| Company | ATS | Correct board | S1 | S2 | S3 | **S4** | fan-out | L1/L2 | **Rung** |
|---|---|---|---|---|---|---|---|---|---|
| General Motors | workday | `generalmotors` / `Careers_GM` | — | — | — | **1** | — | — | **A** |
| Capital One | workday | `capitalone` / `Capital_One` | — | — | — | **1** | — | — | **A** |
| Blue Origin | workday | `blueorigin` / `BlueOrigin` | — | — | — | **1** | — | — | **A** |
| NVIDIA | workday | `nvidia` / `NVIDIAExternalCareerSite` | — | — | 16 | **6** | — | — | **A** |
| Discord | greenhouse | `discord` | — | 2 | 2 | **1** | 26 | — | **A** |
| Anthropic | greenhouse | `anthropic` | — | 5 | 1 | **2** | — | — | **A** |
| Stripe | greenhouse | `stripe` | — | 13 | 13 | **3** | — | — | **A** |
| Optiver | greenhouse | `optiverprivate` | — | — | — | **2** | 28 | — | **A** |
| Reddit | greenhouse | `reddit` | — | 4 | — | **1** | — | — | **A** |
| Jane Street | greenhouse | `janestreet` ‡ | — | 3 | — | **2** | — | — | **A** |
| OpenAI | ashby | `openai` | — | — | — | **4** | — | — | **A** |
| Notion | ashby | `notion` | — | — | — | **3** | — | — | **A** |
| Ramp | ashby | `ramp` | — | 12 | 8 | **2** | — | — | **A** |
| Applied Intuition | ashby | `applied` | 24 | 3 | 1 | **1** | 43 | — | **A** |
| Poke | ashby | `interaction` | — | — | — | **3** | 51 | — | **A** ⚠ gate suppresses |
| Workweave | ashby | `workweave` | — | 4 | — | **1** | — | — | **A** |
| Browserbase | ashby | `browserbase` | — | 11 | 5 | **1** | — | — | **A** |
| Raindrop | ashby | `raindrop` ‡ | — | 11 | 4 | **2** | — | — | **A** |
| Palantir | lever | `palantir` | — | 1 | 2 | **1** | — | — | **A** |
| Spotify | lever | `spotify` | — | 1 | 1 | **1** | 26 | — | **A** |
| Belvedere Trading | lever | `belvederetrading` | 12 | 1 | 2 | **1** | — | — | **A** |
| Netflix | eightfold | `netflix.com` | — | 2 | 1 | **2** | 1 | — | **A** |
| **Cisco** | workday | `cisco` / `Cisco_Careers` | — | — | — | — | 26 | ✅ | **B** |
| **Slack** | workday | `salesforce` / `Slack` | — | — | — | — | — | ✅ | **B** |
| **Nominal** | gem | `nominal` | — | — | — | — | — | ✅ | **B** |
| **Snap** | workday | `snapchat` / `snap` | — | — | — | — | **25** | ✗ | **C** |
| **Databricks** | greenhouse | `databricks` | — | — | — | — | **50** | ✗ | **C** |
| **Retool** | gem | `retool` | — | — | — | — | **125** | ✗ § | **C** |
| **Hudson River Trading** | greenhouse | `wehrtyou` | — | — | — | — | — | ✗ ¶ | **never** |
| *Walmart* | *none* | *no board in the six* | — | — | — | — | — | — | *D* |

‡ Ground truth corrected during this study — see §7. Both boards probed live.
§ L2 fails only because of the 512 KB body cap (§7), not because the link is absent.
¶ L2 returns `hrttalentcommunity` (3 jobs) instead of `wehrtyou` (74 jobs) — §4.2.

**Harness.** Throwaway, uncommitted, in `/Users/bpotter/.claude/jobs/35e63068/tmp/cns/`:
`corpus.py` (ground truth), `bb.py` (client + disk cache, never logs the key),
`run_sweep.py` / `run_fanout.py` / `run_escalate.py` (Search), `run_fetch.py` /
`run_extract.py` (Fetch), `score.py` / `analyze.py` / `final.py` / `gate.py` (scoring),
`probe.py` / `verify_identity.py` / `wrongats.py` (live ATS probes). Raw per-call JSON in
`cache/` and `results/`.
