# Name resolution — measured, not guessed

**Verdict.** A single Haiku call turns a company NAME into a usable careers URL **81% of
the time** (21/26) for **$0.00061 and ~0.9 s**, and it never once named the wrong company.
It turns an AGGREGATOR URL into one **46% of the time** — but that number splits hard:
**6/8 when the company is spelled in the URL, 0/5 when the URL is an opaque numeric id.**
**Wrong-and-expensive count: 0 of 156 trials.** Haiku is enough — Sonnet costs 3.2× and
scored *lower* (73%). Ship it, but the aggregator half of the problem is better solved by
a **$0 host check** than by an LLM.

**Measured 2026-08-30.** 4 configurations × 39 inputs = 156 real API calls, every proposed
URL then fetched live *and* run through our own `ats_discovery.discover_ats` +
`probe_candidate`. Total experiment cost **$0.97** (of which $0.83 was the web-search
config alone). No production source file was changed.

---

## 1. What was measured

| | |
|---|---|
| **Corpus A** | 26 company names — 5 famous, 9 boards we already track (ground truth from `TESTABLE-BOARDS.md`), 5 whose board lives on a vendor domain, 2 vanity careers domains, 3 non-US, **2 ambiguous between multiple real companies** (Bolt, Sierra) |
| **Corpus B** | 13 real LinkedIn / Indeed / Glassdoor URLs — **5 opaque** (`/jobs/view/3961389778/`, `?jk=523555b5…`), **8 name-bearing** (`…-at-stripe-3961389778`, `/cmp/Roblox/jobs`) |
| **Scoring** | Every answer was fetched live, then put through `discover_ats` + `probe_candidate` — the same code path an add uses. An answer counts only if the board is really there. |

### The four configurations

| # | Config | Model | Extra |
|---|---|---|---|
| 1 | `haiku_notools` | `claude-haiku-4-5-20251001` | none — pure parametric recall |
| 2 | `haiku_verify` | same | fetch the proposed URL; if it looks dead, one repair call with the evidence |
| 3 | `sonnet_notools` | `claude-sonnet-5` (thinking disabled) | none |
| 4 | `haiku_websearch` | same Haiku | server-side `web_search_20250305`, `max_uses: 2` |

**Web search is available on this API key** — it worked on the first try, so it is
measured rather than assumed.

### The outcome buckets

Scored by *what our pipeline would actually do with the answer*, not by whether the URL
looked plausible:

| Bucket | Meaning | Cost to us |
|---|---|---|
| **CORRECT — free** | `discover_ats` resolves it to an ATS board and `probe_candidate` returns >0 jobs, for the right company | **$0**, instant, tracked |
| **CORRECT — to discovery** | right company's own live careers page, no ATS behind it | one paid discovery run |
| **WRONG — harmless** | 404, dead DNS, empty board, bot-walled → 422, user told to paste the URL | **$0** |
| **WRONG — expensive** | passes our checks but is a **different company** | a wrong company gets tracked |

---

## 2. Corpus A — company name → careers page (26 items)

| Config | CORRECT free | CORRECT → discovery | **usable** | wrong-harmless | no answer | **wrong-expensive** |
|---|---|---|---|---|---|---|
| `haiku_notools` | 5 | 16 | **21/26 · 81%** | 2 | 3 | **0** |
| `haiku_verify` | 5 | 14 | **19/26 · 73%** | 1 | 6 | **0** |
| `sonnet_notools` | 5 | 14 | **19/26 · 73%** | 6 | 1 | **0** |
| `haiku_websearch` | **11** | 11 | **22/26 · 85%** | 1 | 3 | **0** |

### By difficulty bucket (usable / n)

| Bucket | haiku | haiku+verify | sonnet | haiku+search |
|---|---|---|---|---|
| easy (Cisco, Stripe, Databricks, Roblox, Notion) | 4/5 | 4/5 | 3/5 | 4/5 |
| boards we track | **9/9** | 8/9 | **9/9** | **9/9** |
| vendor-domain board (Crusoe, Ramp, WHOOP, Klarna, Discord) | **5/5** | 3/5 | 2/5 | **5/5** |
| vanity domain (Netflix, NVIDIA) | 1/2 | 2/2 | 2/2 | 2/2 |
| non-US (Toss, Grab, Kakao) | 2/3 | 2/3 | 2/3 | 2/3 |
| **ambiguous (Bolt, Sierra)** | 0/2 — both refused | 0/2 — both refused | 1/2 | 0/2 — both refused |

**Three things stand out.**

1. **The ambiguous names refused themselves.** Every config except Sonnet returned
   `careers_url: null`, `ambiguous: true`, `confidence: low` for both *Bolt* and *Sierra*.
   Sonnet answered Bolt — but flagged `ambiguous: true` and named which one
   (`"Bolt (Bolt Technology OÜ, ride-hailing/delivery)"` → `bolt.eu/en/careers/`). The
   model's own `ambiguous` flag is a usable signal, not decoration.
2. **The vendor-domain cases are where plain Haiku shines and Sonnet fails.** Haiku
   returned `jobs.ashbyhq.com/crusoe` (377 jobs) and `jobs.ashbyhq.com/ramp` (139 jobs) —
   both free, instant, correct. Sonnet invented `job-boards.greenhouse.io/crusoeenergy`
   (404) and `jobs.lever.co/klarna` (404). More capability, more confident fabrication.
3. **Nobody gets the *depth* right without search.** Restricted to answers that would go
   to paid discovery, and compared against the URL `TESTABLE-BOARDS.md` measured as
   working:

   | Config | answers that named the measured board URL |
   |---|---|
   | `haiku_notools` | **0 / 10** |
   | `haiku_verify` | **0 / 9** |
   | `sonnet_notools` | 4 / 10 |
   | `haiku_websearch` | 4 / 6 |

   Haiku gives the careers **hub** — `spacex.com/careers` not `/careers/jobs`,
   `atlassian.com/company/careers` not `/company/careers/all-jobs`,
   `binance.com/en/careers` not `/en/careers/job-openings`. This is the JPMorgan
   `/programs` shape: right company, right domain, no job listings on the page we hand to
   capture. It does not produce a wrong company — it produces a discovery run with worse
   odds.

---

## 3. Corpus B — aggregator URL → careers page (13 items)

| Config | CORRECT free | CORRECT → discovery | **usable** | wrong-harmless | no answer | **wrong-expensive** |
|---|---|---|---|---|---|---|
| `haiku_notools` | 2 | 4 | **6/13 · 46%** | 2 | 5 | **0** |
| `haiku_verify` | 3 | 4 | **7/13 · 54%** | 1 | 5 | **0** |
| `sonnet_notools` | 2 | 4 | **6/13 · 46%** | 2 | 5 | **0** |
| `haiku_websearch` | 3 | 4 | **7/13 · 54%** | 3 | 3 | **0** |

### The split that actually matters

| URL shape | n | haiku | haiku+verify | sonnet | haiku+search |
|---|---|---|---|---|---|
| **opaque id** (`/jobs/view/3961389778/`, `?jk=523555b5…`) | 5 | **0** | **0** | **0** | **0** |
| **name-bearing** (`…-at-stripe-…`, `/cmp/Roblox/jobs`, `Working-at-Databricks-…`) | 8 | 6 | 7 | 6 | 7 |

**This is structural, and it is the headline of Corpus B.** A LinkedIn job id and an
Indeed `jk` hash carry no information about the employer. Parametric recall cannot
resolve them and did not pretend to: all three no-tool configs returned
`careers_url: null, confidence: low` on **all 5** opaque inputs. That is the correct
behaviour and it is worth saying out loud — the model knows it does not know.

Web search does not fix it either. It answered 2 of the 5 opaque inputs: one right
(Roblox), one **fabricated** (§4). LinkedIn and Indeed both serve their job pages behind a
login/bot wall, so even a fetch tier would not recover the employer.

**Name-bearing aggregator URLs are a solved problem** — 6–7 of 8, every config, and three
of those land straight on a live ATS board (`job-boards.greenhouse.io/anthropic` 571 jobs,
`jobs.ashbyhq.com/notion` 133, `jobs.ashbyhq.com/crusoe` 377) at zero further cost.

---

## 4. Wrong-and-expensive: **0 of 156**. But quote the near-miss.

No answer, in any configuration, passed our verification while naming a different
company. The free verification did exactly what the premise predicted: every fabricated
board token was caught by `probe_candidate` returning 0 jobs or the URL 404-ing.

| Fabricated answer | Config | Caught by |
|---|---|---|
| `https://job-boards.greenhouse.io/notion` | sonnet, haiku+search (agg) | 404 / probe = 0 jobs (Notion is on Ashby) |
| `https://job-boards.greenhouse.io/crusoeenergy` | sonnet | 404 / probe = 0 jobs |
| `https://job-boards.greenhouse.io/whoop` | sonnet | 404 / probe = 0 jobs |
| `https://jobs.lever.co/klarna` | sonnet | 404 / probe = 0 jobs (Klarna is on Deel) |
| `https://nvidia.wd5.myworkdayjobs.com/en-US/nvidia` | haiku | probe = 0 jobs (real site is `/NVIDIAExternalCareerSite`) |
| `https://www.crusoe.energy/careers` | haiku (agg) | DNS failure |
| `https://jobs.grab.com` | sonnet | DNS failure |

**The one identity error — 1 of 125 answers given (0.8%), and it is worth reading:**

> Input: `https://www.indeed.com/viewjob?jk=68de4b411865e640` (a real Roblox
> *Senior Software Engineer Engine Harmony* posting)
> `haiku_websearch` answered:
> `{"company": "JK Renewables", "careers_url": "https://www.jkrenewables.com/careers",`
> `"confidence": "high", "ambiguous": false}`

The model searched the opaque `jk=` hash, pattern-matched the parameter name **`jk`** to a
company called JK Renewables, and reported **high confidence, not ambiguous**. It was
caught only because `jkrenewables.com` does not resolve in DNS. Had that domain been live,
the answer would have gone to paid discovery under a Roblox posting and produced a row for
an unrelated company. Nothing in our verification would have objected — the domain would
have been real, the page would have been a real careers page. The only thing that catches
this class is **the user reading the company name we resolved before we spend anything.**

Two supporting facts: **no config ever returned an aggregator URL as its answer** (0 of the
125 answers given — the instruction held), and `haiku_websearch` reported `confidence: high` on **33 of 39**
inputs, including this one. Its confidence field is not usable as a gate; the `ambiguous`
flag is.

---

## 5. Real cost and latency (from the SDK `usage` object)

| Config | calls/input | input tok | output tok | searches | **$ / search** | p50 | p90 |
|---|---|---|---|---|---|---|---|
| `haiku_notools` | 1.00 | 289 | 65 | 0 | **$0.00061** | 0.91 s | 1.55 s |
| `haiku_verify` | 1.13 | 344 | 71 | 0 | **$0.00070** | 0.99 s | 1.81 s |
| `sonnet_notools` | 1.00 | 386 | 54 | 0 | **$0.00197** | 1.23 s | 2.01 s |
| `haiku_websearch` | 1.00 | **10,334** | 132 | 40 | **$0.02125** | 2.97 s | 4.07 s |

Priced at list ($1/$5 per MTok Haiku 4.5, $3/$15 Sonnet 5, $10 per 1,000 web searches).
Sonnet 5's intro pricing (through 2026-08-31) would make it $0.00131 — still 2.1× Haiku,
for a *lower* hit rate. Web search is **35× the price of plain Haiku** and 3× the latency;
the searches ($0.40 of the $0.83) dominate, not the 10k-token inputs.

**The experiment itself cost $0.97**: $0.024 + $0.027 + $0.077 + $0.829, plus ~$0.01 of
smoke tests.

### What the `haiku_verify` fetch tier actually bought

5 repairs fired out of 39. The fetch check was **5/5 correct about the URL being bad** —
including a soft-404 that HTTP status alone would have missed
(`spotify.com/careers` returned **HTTP 200** with the title *"Page not found - Spotify"*).
But the second Haiku call rarely produced anything better:

| Input | 1st answer | fetch said | 2nd answer | Net |
|---|---|---|---|---|
| Spotify | `spotify.com/careers` | 200, title *"Page not found"* | `spotifyjobs.com` ✅ | **win** |
| NVIDIA | `…myworkdayjobs.com/en-US/nvidia` | 404 | `nvidia.com/en-us/careers/` (also 404) | neutral |
| Jane Street | `janestreet.com/careers/` | 404 | `null` | **gave up** |
| Crusoe | `crusoe.energy/careers` | DNS fail | `null` | **gave up** |
| WHOOP | `whoop.com/careers` | 403 *"Just a moment…"* | `null` | **false refusal** |

That last row is the trap: **a Cloudflare bot wall is indistinguishable from a dead URL by
fetch alone.** `whoop.com/careers` and `cisco.com/…/careers.html` are both real pages that
returned 403 to us. Using the fetch result as a hard gate turned 3 right-company answers
into "we couldn't find it" and dropped the config from 81% to 73%.

---

## 6. Net cost effect — the aggregator saving, measured

**The premise checks out, and it is worse than described.** I ran all 13 aggregator URLs
through the real `discover_ats`:

> **13 of 13 returned `no_ats_detected`.**

Not one was refused earlier. LinkedIn's login wall, Indeed's bot wall and Glassdoor all
return *something* readable, so the resolver reads it, finds no board, and answers with
the one reason that **charges**: `no_ats_detected` goes to one-time discovery, spends a
browser capture, spends ≤2 Haiku selection calls, and burns **1 of the user's 20 monthly
add slots** (`user_companies.py` — the `unreachable` branch explicitly does *not* cover
`no_ats_detected`). `_NEVER_MATCH_DOMAINS` already lists `linkedin.com`, `indeed.com`,
`glassdoor.com`, `ziprecruiter.com`, `wellfound.com`, `builtin.com`, `otta.com` — but only
guards the name-match rung, so none of that stops this.

None of those 13 discovery runs can succeed. There is no company board behind a LinkedIn
job URL.

| | today | with a Haiku pre-filter (`haiku_notools`) |
|---|---|---|
| paid discovery runs | **13** | **4** (all on the right company's own page) |
| free ATS adds | 0 | **2** |
| refused for $0 | 0 | **7** |
| monthly slots burned | 13 | 4 |
| LLM cost | 13 × (≤2 selection calls) | 13 × $0.00061 = **$0.0079** |

**One discovery run's LLM half** is ≤2 Haiku calls (`request_selector.py`:
`MAX_TOKENS = 1024`, `_MAX_CANDIDATES = 6`, `_SAMPLE_RECORDS = 2` × `_SAMPLE_RECORD_CHARS
= 700`, `_MAX_SELECTION_ROUNDS = 2`) ≈ **$0.004–0.018** — 7× to 30× one resolution call.
Nine avoided runs is **$0.04–0.16 of tokens, 9 headless-Chromium captures, and 9 monthly
slots**. The browser time and the slots are worth more than the tokens.

**But the cheapest version of this saving needs no LLM at all.** A pure host check against
the aggregator domains already sitting in `_NEVER_MATCH_DOMAINS` stops **13/13** futile
discovery runs for **$0 and 0 ms**. The LLM only earns its keep on the 8 name-bearing URLs
it can actually resolve — and 0/5 on the opaque ones no matter what we spend.

---

## 7. Where this belongs in the flow

**Recommended, in order:**

1. **A free aggregator host gate, before anything else.** If the registrable domain is in
   `_NEVER_MATCH_DOMAINS`, never start discovery on it. This is the entire measured
   saving, costs nothing, and cannot be wrong. Do this whether or not any LLM ships.
2. **Haiku name resolution as the "type a name" entry point**, not as a rewrite of pasted
   URLs. A user who types `Cisco` today gets nothing; with one $0.00061 call they get
   `jobs.cisco.com` → 1,222 jobs, free and instant.
3. **Haiku resolution after the free gate, for a name-bearing aggregator URL** — 6–8 of 8,
   and it converts a guaranteed-futile discovery run into a real add.
4. **Only after `no_ats_detected` for anything else.** The ATS fast path is exact and free;
   an LLM in front of it can only add latency and a chance to be wrong.
5. **Show the resolved company name and URL to the user before spending.** This is the only
   defence against the JK Renewables class, and it costs nothing. Reuse the existing
   `match_kind='name'` correction affordance ("This isn't the same company").

**Escalation, not a default:** run web search only when the first Haiku answer fails
verification. It doubles free-ATS hits (5 → 11 of 26) and is the only config that finds
the *listings* URL rather than the careers hub — but at 35× the price it is worth paying
for the ~20% that need it, not the 80% that don't.

---

## 8. What I would NOT do

* **Do not put an LLM in front of `resolve_ats_url`.** It is free, exact, and IO-free.
  Every ATS URL a user pastes already works; an LLM there is pure downside.
* **Do not let an opaque aggregator id reach an LLM at all.** 0/5 parametric, and the one
  time web search "solved" one it invented JK Renewables at `confidence: high`. Refuse
  and ask for the company name — the model's own no-tools behaviour on these inputs
  (`null`, `low`) is already the right answer.
* **Do not use the fetch check as a hard gate.** A 403 bot wall reads identically to a
  dead page; it cost 3 correct answers here and dropped the hit rate 8 points. Use it to
  *inform* a retry, never to veto.
* **Do not use `confidence: high` as a green light.** `haiku_websearch` reported it on 33
  of 39 inputs including its one fabrication. `ambiguous: true` is the field that carries
  real signal — it fired on exactly the two genuinely ambiguous names, in three of four
  configs.
* **Do not pay for Sonnet here.** 3.2× the cost, a *lower* hit rate (73% vs 81%), and it
  fabricated four ATS board tokens that Haiku did not.
* **Do not auto-create a company from a resolved name without a human reading the name.**
  Our verification proves a board is *real*, never that it is *theirs*.

---

## Appendix — harness

Throwaway, uncommitted, in `/tmp/nrpoc/`: `corpus.py` (both corpora with ground truth),
`run.py` (4 configs, 6-way parallel, records `usage` per call), `verify.py` (live fetch +
`resolve_ats_url` + `probe_candidate`), `pipeline.py` (full `discover_ats` on every
proposed URL), `agg_pipeline.py` (what today's pipeline does with the 13 aggregator URLs),
`final_score.py` / `breakdown.py` / `extra.py` (scoring). Raw per-call JSON in
`/tmp/nrpoc/results/`.
