# The careers-page fallback — escalate to a second, plain query

**Verdict: SHIP IT, and widen the trigger while you are in there.**

| | today | with the fix |
|---|---|---|
| **Fallback is on the company's own domain** | **7/15 · 47%** | **14/15 · 93%** |
| Fallback is somebody else's site (a wasted paid run) | 2 | **1** (`Poke`) |
| We offered nothing at all | 6 | **0** |
| Companies that regressed | — | **0** |

Second query: **`{company} careers`**. Fires only on a miss, so a company that
resolves today spends **one** search and gets a **byte-identical** answer.

**Measured live 2026-09-02.** 22-company ground truth, **57 live Browserbase Search
calls** (of a 120 budget; 10 more served from the 2026-09-01 cache), 24 free live ATS
probes. No application source file was changed. Every row below is a real response on
disk; claims that are not measured are marked **[inferred]**.

---

## 1. The premise was right, and narrower than it looked

The Oracle probe generalises only partly. Of the 9 companies where the shipped
host-shaped query resolves **no board at all**, today's fallback is already on the
company's own domain **7 times**. `_rank_careers_urls`'s `owns_host` preference —
already shipped — is doing most of the work.

The two it misses are the interesting ones, and **re-ranking cannot fix either**:

| company | today's fallback | any own-domain URL anywhere in the 25 Q1 results? |
|---|---|---|
| **Oracle** | `resumeadapter.com/ats/workday/companies` | **no — 0 of 23** |
| **Tesla** | `findmejobs.co/companies/tesla` | **no — 0 of 22** |

The host-shaped query returns **zero** oracle.com and **zero** tesla.com URLs. There is
nothing to promote. A second query is the only fix.

### The bigger leak is a different one

`careersUrl` is shown only when `candidates.length === 0`
(`MyCompaniesPage.tsx:379`). **6 of 22 companies resolve a stranger's board in Q1**, so
the fallback is suppressed and the user is shown other people's job boards instead.
Every board below was probed live today:

| typed | board offered | rank | live jobs | who it actually is |
|---|---|---|---|---|
| **IBM** | `jobs.ashbyhq.com/Harvey` | #23 | **334** | Harvey, a legal-AI company |
| **SAP** | `jobs.ashbyhq.com/Harvey` | #15 | **334** | Harvey again |
| **Salesforce** | `jobs.ashbyhq.com/openai` | #20 | **770** | OpenAI |
| **Salesforce** | `jobs.ashbyhq.com/limble` | #19 | 12 | Limble CMMS |
| **Bolt** | `jobs.lever.co/shieldai` | #22 | **433** | Shield AI |
| **Walmart** | `walmart.wd5.myworkdayjobs.com/WalmartExternal` | #3 | **HTTP 422** | Walmart's own, dead |

The `_names_match` gate stops all of these being auto-added (5 of 6 fail it), but it
does not stop them **suppressing the fallback**. Fixing the trigger is worth more than
fixing the query.

---

## 2. Per-company results — every row measured

`brd` = boards `resolve_ats_url` found in Q1. `gate` = of those, how many pass
`_names_match`. Fallback classification is by registrable domain against the company's
own domains, and every URL is printed so it can be judged by eye.

| # | company | bucket | brd | gate | correct board? | **CURRENT fallback** | | **PROPOSED fallback** (`{c} careers` + trust gate) | | searches |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Cisco | board | 0 | 0 | no (L2 finds it) | `careers.cisco.com/global/en/job/CISC…` | own | `careers.cisco.com/global/en` | **own** | 2 |
| 2 | Anthropic | board | 14 | 14 | **yes** `greenhouse/anthropic` | *not shown* | — | *not shown* | — | **1** |
| 3 | Databricks | board | 0 | 0 | no | `databricks.com/company/careers/eng…/staff-fullstack-…` | own | `databricks.com/company/careers` | **own** | 2 |
| 4 | Figma | board | 4 | 4 | **yes** `greenhouse/figma` | *not shown* | — | *not shown* | — | **1** |
| 5 | Ramp | board | 16 | 16 | **yes** `ashby/ramp` | *not shown* | — | *not shown* | — | **1** |
| 6 | Raindrop | board | 9 | 9 | **yes** `ashby/raindrop` | *not shown* | — | *not shown* | — | **1** |
| 7 | Spotify | board | 13 | 13 | **yes** `lever/spotify` | *not shown* | — | *not shown* | — | **1** |
| 8 | Netflix | board | 17 | 17 | **yes** `eightfold/netflix.com` | *not shown* | — | *not shown* | — | **1** |
| 9 | **Oracle** | none | 0 | 0 | n/a | `resumeadapter.com/ats/workday/companies` | **JUNK** | `oracle.com/careers/` | **own** | 2 |
| 10 | **IBM** | none | 1 | 0 | n/a | *suppressed by `ashby/harvey`* | **none** | `ibm.com/careers` | **own** | 2 |
| 11 | **SAP** | none | 1 | 0 | n/a | *suppressed by `ashby/harvey`* | **none** | `jobs.sap.com/?locale=en_US` | **own** | 2 |
| 12 | **Walmart** | none | 1 | 1 | n/a (board dead, 422) | *suppressed by dead board* | **none** | `careers.walmart.com/us/en` | **own** | 2 |
| 13 | **Deloitte** | none | 0 | 0 | n/a | `apply.deloitte.com/…/JobDetail/Workday-HCM-…` | own | `deloitte.com/global/en/careers.html` | **own** | 2 |
| 14 | **Tesla** | none | 0 | 0 | n/a | `findmejobs.co/companies/tesla` | **JUNK** | `tesla.com/careers` | **own** | 2 |
| 15 | **Zingerman's** | none | 0 | 0 | n/a | `zingermanscommunity.com/jobs/` | own | `zingermanscommunity.com/jobs/listing/` | **own** | 2 |
| 16 | **King Arthur Baking** | none | 0 | 0 | n/a | `kingarthurbaking.com/jobs` | own | `kingarthurbaking.com/jobs` | **own** | 2 |
| 17 | Slack | hard | 0 | 0 | no (board is on the parent's tenant) | `slack.com/careers` | own | `slack.com/careers` | **own** | 2 |
| 18 | Accenture | hard | 0 | 0 | no | `accenture.com/us-en/careers/jobdetails?id=R00331119_en` | own | `accenture.com/us-en/careers` | **own** | 2 |
| 19 | Salesforce | hard | 3 | 0 | n/a | *suppressed by `ashby/openai`* | **none** | `salesforce.com/company/careers/` | **own** | 2 |
| 20 | Bolt | hard | 1 | 0 | n/a | *suppressed by `lever/shieldai`* | **none** | `bolt.eu/en/careers/` | **own** ⚠ | 2 |
| 21 | Sierra | hard | 17 | 17 | **yes** `ashby/sierra` (210 jobs, is sierra.ai) | *not shown* | — | *not shown* | — | **1** |
| 22 | **Poke** | hard | 3 | 0 | `ashby/interaction` — **404 today** | `jobs.generalcatalyst.com/companies/poke-2-…` | **JUNK** | `poke.house/careers` | **JUNK** | 2 |

⚠ **Bolt is the honest caveat.** Today's fallback is `bolt.com` (Bolt Financial); the
second query returns `bolt.eu` (Bolt the ride-hailing app). Both are real companies
called Bolt, both pass every host test we own. The design cannot disambiguate a
genuinely ambiguous name — which is why the URL must stay visible and the click
explicit, as it already is.

**Ground truth sources:** boards from `ATS-BEHIND-CAREERS-PAGE.md` (Cisco 206, Spotify
218, Walmart 219, Accenture 244, Databricks 256, Netflix 258, Anthropic 259) and
`COMPANY-NAME-SEARCH-EVALUATION.md` (Ramp, Raindrop, Slack, Poke). Figma, Anthropic,
Databricks, Ramp, Raindrop, Spotify, Sierra, Netflix and every wrong board were
**re-probed live 2026-09-02** against the real ATS APIs.

---

## 3. The four questions, answered with the numbers

### Q1 — Does the second query recover the company's own careers page?

**Yes. 15 of 15 escalating companies get an own-host result at rank 1** — up from 7 of
15. Both true junk fallbacks (Oracle, Tesla) become the company's real careers landing
page. The one remaining miss is `Poke`, whose name is a common word and whose top
`Poke careers` result is a poke-bowl restaurant (`poke.house`). No host-based rule can
fix that one.

| escalation set (n=15) | own-domain | junk | nothing offered |
|---|---|---|---|
| CURRENT — Q1 fallback, no trust gate | **7/15 · 47%** | 2 | 6 |
| CURRENT + trust gate (no second query) | 7/15 · 47% | **0** | 8 |
| **PROPOSED — second query + trust gate** | **14/15 · 93%** | 1 | **0** |

Restricted to today's narrower trigger (zero boards resolved, n=9): **7/9 → 9/9**, junk
**2 → 0**.

### Q2 — Does it ever hurt a company that works today?

**No — verified three ways, not assumed.**

1. **Structural.** Q1 is unchanged, byte for byte (`build_query`). The second query
   fires only *after* Q1 has already failed to produce an acceptable candidate, and its
   results feed **only** `careersUrl`.
2. **The escalation never fires for a working company.** All 7 companies with a live,
   name-matching board (Anthropic, Figma, Ramp, Raindrop, Spotify, Netflix, Sierra)
   spend **1** search and return the identical candidate list.
3. **The second query cannot introduce a wrong board.** Across **45** Q2 result sets
   (15 companies × 3 wordings, 1,125 results), `resolve_ats_url` matched **zero**
   times. A plain careers query returns careers pages, never ATS hosts — so it can
   neither find a board Q1 missed nor smuggle a stranger's board in.

Point 3 also caps the upside: `Cisco careers` still does not find
`cisco.wd5.myworkdayjobs.com`. That stays the free L1/L2 ladder's job.

### Q3 — Best wording for the second query

Three candidates, all 15 escalating companies, same `numResults=25`. All measured.

| wording | own-host **@1** | own-host in **top 5** | top hit is a single job posting (bad) | aggregator results |
|---|---|---|---|---|
| **`{company} careers`** | **15/15** | 74/75 | 1/15 | **46** |
| `{company} careers jobs` | 15/15 | **66/75** | **5/15** | 42 |
| `{company} official careers site` | **15/15** | **75/75** | **0/15** | **55** |

**Recommend `{company} careers`.**

* All three tie on the metric that decides the offered URL (own-host@1 = 15/15).
* `careers jobs` is **measurably worse**: it lands on a single job posting 5 times in 15
  (`accenture.com/…/jobdetails?id=R00353368_en`, `careers.salesforce.com/en/jobs/jr321042/…`)
  and drops 9 own-host results out of the top five. It also produced the only own-domain
  result that is not a careers page at all — `blogs.oracle.com/jobsatoracle/internship-to-impact…`.
  This matches the brief's own probe. **Do not use it.**
* `official careers site` is a hair cleaner on landing-page quality (0 vs 1 deep job
  page; 75/75 vs 74/75 in the top five) but pulls **20% more aggregator results**
  (55 vs 46), and both advantages are single-item differences at n=15 — **[inferred]**
  that they are noise. Two extra words buy nothing decisive; the shorter query ships.

Latency of the second call: **p50 0.80 s, max 1.25 s** (measured, n=15) against a 20 s
route budget (`_SEARCH_BUDGET_S`).

### Q4 — How do we decide a fallback URL is trustworthy?

The shipped rule (`owns_host` inside `_rank_careers_urls`) is **correct in substance and
used in the wrong way**. It currently only **sorts**; it never **rejects**. When nothing
matches, the top-ranked stranger is handed over anyway — exactly the Oracle failure.

**Measured accuracy across all 22 Q1 careers lists (76 URLs accepted):**

| | count | verdict |
|---|---|---|
| Accepted, on the company's own registrable domain | **72** | correct |
| Accepted, on a **vendor** domain carrying the company's name | 4 | **also correct** — `kingarthurbaking.hrmdirect.com` is King Arthur's real recruiting site |
| Accepted, belonging to a **different company** | **0** | — |
| Companies where it accepted **nothing** | 4 (Figma, Spotify, Oracle, Tesla) | correct — no own-domain URL was present |

**The one hole it had was fixed mid-study, by someone else, and the fix is exactly the
rule this POC would have recommended.** Measured against the pre-fix code, `owns_host`
accepted `gmail.com` for "GM", `hpe.com` for "HP" and `boxycharm.com` for "Box" — a short
identity used as a *prefix*, the very thing `_names_match` already refuses via
`_MIN_PREFIX_CHARS`. Commit **`a80fd2e7`** (2026-09-02, this branch) applies that floor:
exact label match at any length, prefix only from 4 characters up.

**Re-scored against the fixed code: every headline number in this document is
unchanged** — 0 of the 15 escalating companies' picks move, `zingermanscommunity.com`
for `Zingerman's` included (a 10-character prefix, well over the floor). The only
observable change on this corpus is that `ibmglobal.avature.net` is no longer accepted
for "IBM". Nothing left to do here.

#### The exact rule to ship

```python
# 1. Q1: unchanged. build_query(name), numResults=25, score all 25 with resolve_ats_url.
# 2. If ANY candidate is auto_addable (names the company AND probes live, >0 jobs):
#       done. one search. no fallback is offered.
# 3. Otherwise, ONE more search:  f"{name} careers", numResults=25
#       drop is_aggregator hosts
#       drop anything resolve_ats_url recognises      (measured: never fires)
#       take the FIRST remaining URL that is TRUSTED
# 4. If none is trusted, fall back to the first TRUSTED url from Q1's careers list.
#       (measured: never needed - Q2 succeeded 15/15. belt and braces.)
# 5. If still none:  careers_url = None.
#       The UI already says "Try pasting the URL of their careers page."
#       NEVER hand back an untrusted host. An untrusted host the user accepts is a
#       paid discovery run plus one of their 20 monthly adds, spent on a stranger.

# TRUSTED = the `owns_host` closure in `_rank_careers_urls`, unchanged as of a80fd2e7:
#   exact host-label match at any length, or a prefix from _MIN_PREFIX_CHARS up.
# The change is WHERE it is used: today it only sorts. It must also reject.
```

**Two decisions inside that, each with its number:**

| decision | why |
|---|---|
| **Trigger on `auto_addable`, not on `candidates == []`** | Widens the escalation from 9 to **15** of 22 and closes the IBM/SAP/Salesforce/Bolt/Walmart hole — 5 companies that today see a stranger's board and **no** careers page. `auto_addable` is already computed in `companies.py:_probe_shown`; no new work. |
| **Return `None` rather than a guess** | The only thing that stops a paid run on a stranger's site. `_rank_careers_urls` sorts but never rejects, so today the top-ranked stranger is handed over when nothing owns the host. Applied to today's data alone it converts 2 junk offers into 2 honest "paste a URL"s. |

Do **not** also add an "exact label first" re-ordering: measured, it flips
`Zingerman's` from `zingermanscommunity.com/jobs/listing/` to
`zingermans.iapplicants.com/jobflyer.php`. Both are genuinely Zingerman's, so it is not
wrong — it is a change with no evidence behind it. Leave search rank as the tie-break.

**Residual risk the host rule cannot close [inferred].** `applebees.com` still passes for
"Apple" and `metabase.com` for "Meta" (verified by direct call), because `normalize_name`
strips the separators a word-boundary test would need — and tightening to exact-label-only
would reject the legitimate `zingermanscommunity.com`. The mitigation is the one already
shipped: show the host and require an explicit click.

### Q5 — Cost

Search bills **$0.007 per call** flat, regardless of result count
(`COMPANY-NAME-SEARCH-EVALUATION.md` §6, rates re-checked 2026-09-02).

| escalation rate | extra searches / 100 name-adds | extra $ / 100 adds |
|---|---|---|
| **68%** — measured on this corpus (`auto_addable` trigger, 15/22) | 68 | **$0.48** |
| 41% — measured, narrow trigger (9/22) | 41 | $0.29 |
| ~24% — **[inferred]** realistic mix, from the 29-company set where rung A found the correct board 76% of the time | 24 | $0.17 |

**This corpus is deliberately adversarial** — 8 of 22 companies were chosen to have no
board on any of the six, and 6 more are common-word or vendor-domain hard cases. A real
name box will escalate far less often than 68%.

**It pays for itself.** One accepted junk fallback costs a discovery run at **$0.04–0.08**
plus one of the user's **20 monthly adds**, which is the scarcer resource and has no
dollar price. Break-even is a junk-prevention rate of **$0.007 / $0.06 ≈ 12%**. Measured
prevention on the narrow trigger: **2 of 9 = 22%**, i.e. roughly **1.8× value for cost**,
before counting the add slot or the 6 dead ends the wider trigger converts into a usable
action.

---

## 4. Surprises

1. **The junk-fallback problem is narrower than the Oracle probe implied** — 7 of 9 of
   today's fallbacks are already on the right domain. The shipped `owns_host` sort is
   why. The fix is worth shipping anyway, because the 2 it misses are unfixable by
   re-ranking (zero own-domain URLs anywhere in Q1's 25 results) and because the
   *trigger* is leaking 5 more companies.
2. **`jobs.ashbyhq.com/Harvey` is offered for both IBM and SAP.** 334 live jobs, a
   legal-AI company, at ranks 23 and 15 of a query containing the words "IBM" and "SAP".
   Salesforce is offered OpenAI's 770-job board. Bolt is offered Shield AI's 433-job
   board. All are suppressing the careers fallback today.
3. **Poke's board is gone.** `jobs.ashbyhq.com/interaction` — the ground-truth answer
   recorded on 2026-09-01, live then — returns **HTTP 404** on 2026-09-02. Q1 still
   returns the URL at rank 3, and `resolve_ats_url` still resolves it. Ground truth from
   search results goes stale in **one day**.
4. **`Sierra` resolves correctly and was never tested.** `jobs.ashbyhq.com/sierra` is
   live with **210 jobs** and is sierra.ai. `COMPANY-NAME-SEARCH-EVALUATION.md` §7 lists
   Sierra as an untested ambiguous name; it is a clean rung-A hit.
5. **The second query never returns a board.** Zero ATS-resolvable URLs in 1,125 Q2
   results. That is what makes the change safe, and it is also its ceiling.
6. **Walmart's own Workday board passes the name gate and is dead** (HTTP 422 —
   independently reproduced from 2026-09-01). It suppresses the fallback but can never
   be added, which is exactly the case the `auto_addable` trigger fixes.
7. **The trust rule's short-name hole was fixed by a parallel commit while this study
   was running** (`a80fd2e7`, from a CodeRabbit finding). It is byte-for-byte the rule
   the measurement pointed at, and re-scoring against it moved **no** number in this
   document. Recorded because it means Q4's remaining recommendation is only "use the
   rule as a filter, not just a sort" — the rule itself is already right.

## 5. What I could not verify

* **Result stability.** One snapshot, 2026-09-02. The Poke 404 shows a day is enough to
  move ground truth. Nothing was measured twice.
* **Whether the `Poke` class of ambiguity is common.** n=2 (`Bolt`, `Poke`) — both
  defeated the host rule, in different ways. Its real frequency is unmeasured.
* **The `applebees.com`-for-`Apple` class.** The tightened rule still accepts it
  (verified), because `normalize_name` strips the separators a word-boundary test would
  need. No cheap fix found; the UI showing the host and requiring a click is the
  mitigation.
* **The 24% realistic escalation rate is [inferred]** from a different corpus
  (29 companies, all with a known board) and is not a controlled measurement of a real
  name box.
* **`is_aggregator` coverage on Q2.** `findmejobs.co`, `resumeadapter.com`,
  `openjobradar.com`, `jobs.generalcatalyst.com`, `jobs.weekday.works` and
  `dreamworkhq.com` all appear as top non-ATS results and none is on the denylist. The
  trust gate makes the denylist much less load-bearing, so extending it was not tested.
* **Two "no board on the six" rows are [inferred], not probed**: SAP (SuccessFactors is
  SAP's own product) and Deloitte. Every other ground-truth row is either cited to a
  verified repo doc or was probed live today.

---

**Harness.** Throwaway, uncommitted, in `/Users/bpotter/.claude/jobs/35e63068/tmp/fallback/`:
`corpus.py` (ground truth), `bb.py` (client + shared disk cache + hard 120-call budget,
never logs the key), `run.py` (the sweep), `analyze.py` (scoring — imports the real
`resolve_ats_url` / `_names_match` / `_rank_careers_urls`), `tighten.py` (trust-rule
comparison), `probe_boards.py` / `probe_wrong.py` / `probe_netflix.py` (free live ATS
probes). Raw per-call JSON in `/Users/bpotter/.claude/jobs/35e63068/tmp/cns/cache/`.
