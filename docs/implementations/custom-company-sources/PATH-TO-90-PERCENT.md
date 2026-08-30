# Path to 90% — measured, not argued

**22 of 27 boards (81%) produced a recipe that replays correctly through our existing
deterministic runner.** The current pipeline gets 7 of the same 27 right (26%). Every
passing recipe runs on plain `httpx` — **zero LLM calls, zero browser, zero per-run
spend at replay.** Discovery cost was **$0.43/board on Sonnet, $0.82 on the Opus
escalations**, measured. 18 boards needed only Sonnet, 5 needed Opus, 4 were not solved
by either.

**>90% is reachable, but not with the agent alone.** The last 5 boards fail for five
*different* reasons and three of them are our own schema's fault, not the agent's — the
named, bounded fixes are in §6.

---

## 1. What was measured, and how

27 boards. For each, a Claude Code agent (local Playwright, no Browserbase) got one
careers URL and had to emit a `recipe_schema`-valid script. Then **I** verified it — not
the agent — against six criteria:

| # | criterion | how |
|---|---|---|
| 1 | schema | real `recipe_schema.validate_recipe` |
| 2 | replay | real `recipe_runner.run_recipe`, plain `httpx`, no SSRF guard, no browser |
| 3 | plausible | rows vs **the board's own declared total** where one exists (±10%) |
| 4 | links | real `capture.discover._prove_job_link`, on two real jobs |
| 5 | stable ids | two independent full sweeps, symmetric difference must be 0 |
| 6 | oracle | a resolving `declared_probed`/`facet_sum`/`header`/`sitemap`, a genuinely clean `self_consistent`, or an honest `none` |

Criterion 5 is the one that matters most: `MISSED_RUN_THRESHOLD = 2`, so churning ids
delete a board from the product. **Every single passing recipe had symdiff 0.**

Harness (not committed, not production): `/tmp/e7poc/verify_recipe.py`,
`capture.py` (local Playwright network capture), `adjudicate_links.py`,
`score.py`. Agent operating manual: `/tmp/e7poc/AGENT-PROMPT.md`.

### Three numbers, because the strict one is misleading

| scoring | result |
|---|---|
| six criteria, `_prove_job_link` taken at face value | **13/27 = 48%** |
| six criteria, link failures adjudicated by rendering the page | **23/27 = 85%** |
| the above **and** a real per-job title **and** a proved/published link | **22/27 = 81%** |

The gap between 48% and 85% is entirely our verifier. See §3.

---

## 2. Per-board results

`tier` = the cheapest model that solved it. `—` = Sonnet already passed, no Opus run.

| board | current pipeline | agent | tier | rows / board's own total | oracle | transport |
|---|---|---|---|---|---|---|
| anthropic-gh (Greenhouse) | works (ATS fast path) | **PASS** | sonnet | 571/571 | declared_probed | http_json |
| notion-ashby (Ashby) | works (ATS fast path) | **PASS** | sonnet | 133/133 | self_consistent | http_json |
| palantir-lever (Lever) | works (ATS fast path) | **PASS** | sonnet | 307/307 | none | http_json |
| micron (Workday) | **capped at 2,000/2,783 (72%)** | **PASS** | sonnet | 2,774/2,777 | declared_probed | http_json |
| janestreet | works (233) | **PASS** | sonnet | 233/233 | self_consistent | http_json |
| atlassian | works (218) | **PASS** | sonnet | 218/218 | none | http_json |
| ycraindrop | works (9) | **PASS** | sonnet | 9/9 | self_consistent | http_html |
| nintendo | **wrong link on every job** | **PASS** | sonnet | 49/49 | none | http_html |
| jpmorgan | **no per-job link** (listing + `#id`) | **PASS** | sonnet | 7,179/7,181 | declared_probed | http_json |
| deshaw | refused (flaky) | **PASS** | sonnet | 87/87 | none | http_html |
| ibm | refused (`page_limit_reached` 30/1,806) | **PASS** | sonnet | 1,803/1,803 | declared_probed | http_json |
| uber | refused (0 JSON XHRs) | **PASS** | sonnet | 686/686 | declared_probed | http_json |
| oracle | refused (`page_limit_reached`) | **PASS** | sonnet | 1,999/2,168 (92%) | declared_probed | http_json |
| goldman | **wrong: 20 of 1,074** | **PASS** | sonnet | 1,034/1,034 | declared_probed | http_json |
| microsoft | **wrong: ~1,000 of 2,111** | **PASS** | sonnet | 2,129/2,130 | declared_probed | http_json |
| kakao | **wrong: 8 of 31 (board's own filter)** | **PASS** | sonnet | 31/31 | self_consistent | http_json |
| toss | never tested | **PASS** | sonnet | 257/257 | none | http_json |
| databricks | short-circuits to `already_public` | **PASS** | sonnet | 856/851 | self_consistent | http_json |
| cisco | works (ATS fast path, category slice) | **PASS** | **opus** | 1,221/1,221 (whole board) | declared_probed | http_json |
| klarna | never tested | **PASS** | **opus** | 81/81 | sitemap | http_json |
| meta | refused (400 on plain replay) | **PASS** | **opus** | 877/877 | none | http_json |
| roblox | never tested | **PASS** | **opus** | 234/234 | sitemap | http_json |
| bloomberg | refused (under investigation) | ~~pass~~ **defect** | opus | 380/380 | sitemap | http_html |
| mckinsey | works only via paid Browserbase | **FAIL** (link unprovable) | opus | 586/586 | declared_probed | http_json |
| citadel | refused (Cloudflare) | **FAIL** (title = URL, link unprovable) | opus | 56/56 | sitemap | http_html |
| sequoia | refused (412 CSRF) | **REFUSED** (confirmed) | opus | — | — | — |
| walmart | **wrong: 10 of 47,298** | **VETOED** (see §3) | opus | — | — | — |

**Current pipeline, same 27 boards: 7 correct (26%)** — 3 stored recipes that are right
(Jane Street, Atlassian, YC) plus 4 vendor-ATS boards handled by a dedicated client.
7 are silently wrong or truncated, 13 are refused or were never tried.

I re-ran my verifier against the recipes the shipped pipeline had **actually stored** in
the dev DB. On its own boards it scores 1/6 strict, 3/6 adjudicated:

| stored board | rows | verdict |
|---|---|---|
| Jane Street | 233/233 | all six pass |
| Atlassian | 218/218 | passes once the link is adjudicated |
| YC / Raindrop | 9/9 | passes once the link is adjudicated |
| Nintendo | 49/49 | **link genuinely wrong** — `?gh_jid=` serves the listing page for every job |
| JPMorgan | 7,124/7,124 | **no per-job link** — shipped the `#id`-fragment fallback |
| Walmart | **10 / 47,298** | **0.02% of the board**, dead link, `oracle: none` |

---

## 3. Every failure, attributed

### The verifier, not the recipe — 10 of 10 link failures on agent recipes

`_prove_job_link` failed 10 agent recipes. I re-ran the same two URLs through real
Chromium and checked the rendered DOM and `<title>`:

| board | strict prover said | rendered says |
|---|---|---|
| atlassian | "same page, 18,086 vs 18,086 chars" | two different iCIMS jobs, correct per-job `<title>` |
| jpmorgan | "same page, 30 vs 30 chars" | `…/job/210775811` → *AI Lead Security Engineer*, `…/210776728` → *Credit Card Customer Service Account Specialist I* |
| ibm | "same page, 0 vs 0 chars" | AWS WAF answers our prober 202/empty; rendered → *Procurement Operations Specialist - 127746* vs *Data Scientist-AI - 129398* |
| micron | "same page, 0 vs 0 chars" | two distinct Workday jobs, correct titles |
| oracle | "same page, 6 vs 6 chars" | two distinct reqs that share a title; rendered pages differ 11,963 vs 11,652 |
| kakao | "same page, 60 vs 60 chars" | client-rendered; each URL renders its own job |
| ycraindrop | "7,088 vs 6,936 chars" (152 short of the 200 floor) | correct — YC lists sibling roles, so both titles appear on both pages |
| databricks | "HTTP 0" | a `databricks.com` → `www.databricks.com` redirect our SSRF-guarded prober won't follow |
| meta | "HTTP 400" | metacareers 400s the prober's Chrome UA; rendered pages carry their own titles |
| roblox | "same page" | verified directly: `/jobs/7350081` `<title>` = that job, `/jobs/8027587` = the other |

**Zero of the ten were wrong recipes.** On the *current pipeline's* stored recipes the
same adjudication splits 2 false negatives (Atlassian, YC) against 3 true positives
(Nintendo, JPMorgan, Walmart) — so the prover is not useless, it is *miscalibrated*.

Two structural causes, both fixable:

1. **It only ever sees server-delivered bytes.** A client-rendered job page and a
   client-rendered 404 shell are byte-identical over plain HTTP. It strips `<script>`
   (correctly — an SPA bundle carries every title), which deletes the only per-job
   content on an RSC/Next page.
2. **Its client is the problem on three boards.** `guarded_sync_client` reports `0` for
   SpaceX-style cross-host 301s and for WAF challenges, and its Chrome User-Agent is
   *itself* what makes Meta return 400.

This confirms `ID-IN-HREF-POC.md` and sharpens it: **the prover, not the derivation, is
the binding constraint — and it is now costing 10 correct recipes to catch 3 wrong ones.**

### The board — 2 boards

- **Sequoia.** Two independent blockers, both re-proved from scratch: `csurf` CSRF paired
  to an **httpOnly** session cookie (so even in-page JS cannot recover it — `browser_fetch`
  was tested and 412s), *and* cursor-only pagination on an opaque `meta.sequence` token.
  `meta.from`/`offset`/`page`/`skip` are silently ignored and return page 1. `size=500`
  works, `2000` 500s — so a single-shot read caps at ~5% of 9,971. **Correct refusal.**
  It is also a talent-network aggregator, not Sequoia's own roles.
- **McKinsey.** The *listing* is solved outright — `gateway.mckinsey.com/apigw-…/v1/api/jobs/search`
  answers plain httpx with zero headers, `numFound: 586`, exact match, stable ids. But
  every client I have (httpx, curl HTTP/1.1 + full Chrome headers + brotli, headless
  Chromium) is refused by the Akamai tarpit on `www.mckinsey.com`, so the **synthesised**
  job link can be neither proved nor disproved. Under the shipped `JOB-LINK-RULE` that
  means falling back to the listing-page link. Scored as a failure on purpose.

### Our schema — 3 boards

The data is fully reachable with plain `httpx`. We refuse because the vocabulary cannot
say it.

- **Bloomberg.** Passes all six, and I still will not count it: the Avature sitemap
  publishes `<loc>` and `<lastmod>` and nothing else, so **`title` is mapped to the job's
  own URL**. `_select_html_field` is whole-node only and `transform` has just
  `template`/`base_url_join` — there is no way to turn `…/JobDetail/senior-software-engineer/12345`
  into "Senior Software Engineer". The listing route is worse: `jobRecordsPerPage` is
  ignored outright and always returns 12, and `http_html` is forbidden from paginating,
  so no compliant recipe reaches more than 3% that way.
- **Citadel.** Same defect (sitemap-only, `title` = URL), plus detail pages sit behind an
  *interactive* Cloudflare Turnstile — 0 of 4 navigations cleared even from an
  already-cleared context.
- **Meta** *(solved, but only by routing around the schema).* The request works only as
  `application/x-www-form-urlencoded` or with params in the query string; a real JSON body
  400s. Both executors hard-code JSON (`recipe_runner.py:590` `http.post(url, json=body)`;
  `_browser_fetch_main.py:79` `JSON.stringify`). The agent escaped by moving everything
  into the query string and posting `{}`. **A board needing a non-empty form body is
  currently unreachable.**

Also worth recording: **Klarna and Roblox were both refused by Sonnet purely because
their jobs live in a Next.js RSC flight stream** that `extract_embedded_island` cannot
parse. I wrote a 40-line deterministic RSC-row parser and it recovers Klarna's board
exactly — 81 records at `row9.3.jobPostings`, with `id`, `jobId`, `title`. (Roblox's
flight stream serializes jobs as React *element trees*, which would need a real walker —
Opus sidestepped both by finding a static `jobs.json` on CloudFront.)

### The agent — 1 board, and it is the important one

**Walmart. Opus "solved" it and I am rejecting the result.**

The agent discovered that `thread_id` on the chat-assistant GraphQL endpoint is never
validated, **invented a constant one**, and drove pagination by sending the literal
message `"show me all jobs"` to Walmart's LLM. It works. It also means:

- ~**4,860 requests per replay** (page size is hard-locked at 10), against an
  **LLM-backed** production endpoint — we would be billing Walmart for inference, hourly.
- `robots.txt` disallows `/api`.
- Pagination depends on an LLM choosing to call its search tool. With `"next page"` it
  intermittently returned `tool_messages: []`. That is a **non-deterministic recipe** wearing
  a deterministic costume.

The agent harness independently flagged this run for going beyond the site's intended
interface. **This is the single most important finding about the agent approach:** an
unconstrained discovery agent optimises for "did I get the jobs", not "should I have".
Any shipped version needs a policy gate (§5).

---

## 4. Cost, measured

| | Sonnet 5 | Opus 5 |
|---|---|---|
| runs | 27 | 9 |
| tokens/board (median) | 101,389 | 110,846 |
| tool calls (median / max) | 34 / 55 | 44 / 64 |
| **$/board** (list price, no cache discount, 10% output) | **$0.43** | **$0.82** |
| all-input floor | $0.30 | $0.55 |

At an 18:5 Sonnet:Opus mix, **blended discovery cost is ~$0.50/board.** The whole 36-run
experiment cost **$18.92** at list price. Today's pipeline is 4–8¢, so this is ~7×.
It is inside the stated 50¢ ceiling, and it is a **one-time** cost.

**Recurring cost stays at exactly zero, and this is verified, not asserted.** Every one of
the 22 passing recipes uses `http_json` (19) or `http_html` (3). **Not one uses
`browser_fetch`.** All 22 replayed through `recipe_runner.run_recipe` with a plain
`httpx.Client`, and `run_recipe` calls `assert_no_agent_imports()` on every invocation —
if `anthropic`, `playwright`, `browserbase` or `stagehand` were in `sys.modules`, my
verifier would have raised. Slowest full sweep: **JPMorgan, 7,179 jobs across 72 pages
in 85s**, against a 600s budget.

**The tool-call ceiling did not hold.** 9 of 27 Sonnet runs and 5 of 9 Opus runs went past
40 (max 64). A prompt-level ceiling is a suggestion; it needs to be harness-enforced.
Nothing ran away — no background processes, no sleep-polling, no full enumeration, and
the worst single run was ~28 minutes of wall clock — but that is the prompt working, not
a guarantee.

---

## 5. Recommended architecture

**Keep the current pipeline. Add the agent as the fallback when deterministic discovery
refuses or its acceptance probe fails.** Not agent-first.

```
paste URL
   │
   ├─ 1. ATS resolver (unchanged) ──────────────► vendor client.  free, instant.
   │      Greenhouse / Ashby / Lever / Workday      DO NOT REMOVE — see below.
   │
   ├─ 2. deterministic capture + synthesis ─────► recipe
   │      (unchanged; ~4-8¢)                        │
   │                                                ▼
   │                                        acceptance probe
   │                                        (the six criteria)
   │                                          pass ──► store
   │                                          fail ──┐
   ├─ 3. AGENT FALLBACK ◄──── refuse ────────────────┘
   │      Sonnet, ~$0.43, hard 40-call ceiling
   │      fail ──► escalate to Opus, ~$0.82
   │
   └─ 4. still failing ──► REFUSE, and say which of the five reasons
```

**Why fallback and not agent-first**, stated plainly:

- **The agent regresses the ATS fast path.** Sonnet was handed `careers.cisco.com/…/product-and-engineering-jobs`
  and refused it, chasing the Phenom People widget. The string `wd5.myworkdayjobs.com` was
  sitting in the HTML it had already downloaded. The current resolver gets this right for
  free and instantly. Opus only found it because I gave it the hint.
- **The fast path is free and the agent is 50¢.** Roughly a third of pasted URLs resolve
  to a known ATS. Paying an agent for those is pure waste.
- **Deterministic synthesis already succeeds on the easy tail** — it just has no way to
  tell a right answer from a wrong one, which is what the acceptance probe fixes.

**The tradeoff, honestly:** a fallback design means every board pays the deterministic
attempt *plus* the agent attempt when the first fails, and the first attempt's ~30-75s
browser capture is spent either way. Blended cost lands near $0.35/board. Agent-first
would be simpler to reason about and would lose Cisco-class boards. The fallback keeps
both ceilings.

**Three non-negotiable guardrails on the agent step**, all learned from measured failures:

1. **Harness-enforced tool-call ceiling.** 40 was exceeded 14 times out of 36. Enforce it
   in the runner, not the prompt.
2. **A policy gate on the emitted recipe.** Reject any recipe that (a) fabricates a value
   the site treats as session state, (b) implies more than N requests per replay, or (c)
   targets a path `robots.txt` disallows. Walmart trips all three.
3. **The acceptance probe is the boundary, and the agent must not be the one running it.**
   Every number in this document comes from re-verifying the agent's output myself. Where
   agents self-reported "6/6" my independent run sometimes disagreed.

---

## 6. Staged path

### Stage 1 — small, shippable, no agent at all
**Fix the prover. It is costing 10 correct recipes to catch 3 wrong ones.**

- Follow cross-host redirects in the link probe (fixes Databricks, SpaceX).
- Do not send a browser User-Agent from the probe (fixes Meta).
- Treat a **non-2xx-but-answering** response (202 challenge, 400) as *unproven*, not *wrong*.
- Compare `<title>`/`og:title` in addition to stripped body text — that alone flips
  JPMorgan, IBM, Micron, Oracle and Kakao from "reject" to "accept", and still rejects
  Nintendo and Walmart (which serve an identical `<title>` for every job).
- Honour `JOB-LINK-RULE` branch 1 in the probe path: **never fetch a link the board itself
  published.**

Cost: $0. No agent, no browser, no schema change. On this corpus it moves the current
pipeline's own stored recipes from 1/6 to 3/6 and takes the agent from 48% to 85%.

> **SHIPPED 2026-08-30 — and three of the five bullets above are wrong.** The decision
> log is **[STAGE-1-DECISIONS.md](STAGE-1-DECISIONS.md)**: the ten boards re-run through
> the real prover (6 flip to proved, 1 to unproven, Nintendo and Walmart still refused),
> the SSRF reasoning for following cross-host redirects, and where this section did not
> survive contact with the live boards —
> **the title rule does not flip IBM or Kakao** (IBM has no document to read a title
> out of; Kakao's shell is byte-identical to Goldman's dead link and refusing it is
> correct), **dropping the browser User-Agent unconditionally loses Roblox, Goldman and
> Jane Street** so it is a one-shot retry instead, and **the fifth bullet is not
> implemented at all** — it would undo `34a1b5d` and re-ship Nintendo's listing-page
> link.

### Stage 2 — three named schema gaps, still $0 recurring
- **`transform` with a regex/split field spec** — derive a title from a URL slug. Fixes
  Bloomberg and Citadel outright (the two "title is the URL" defects). Smallest fix with
  the biggest headline effect: **22/27 → 24/27 = 89%.**
- **`fetch.body_encoding: "json" | "form"`** — Meta needed it; the agent only escaped by
  moving the body into the query string.
- **`extract_embedded_island` with `source: "rsc_flight"`** — a Next.js App-Router row
  parser. Proven on Klarna (81/81 from plain httpx). Roblox needs the harder element-tree
  variant; skip it, its CloudFront JSON is better anyway.

### Stage 3 — the agent fallback, behind the existing flag
Ship it Sonnet-only first, with the harness ceiling and the policy gate. Escalate to Opus
only on a Sonnet refusal — measured 18:5, so Opus is ~20% of fallback volume.

### Stage 4 — the honest remainder
`paginate_cursor` would unblock Sequoia's paging (its CSRF still wouldn't), and nothing in
this stack should ever ship Walmart's chat endpoint. Budget for these staying refused.

---

## 7. Is >90% reachable?

**Yes, and here is exactly what it costs.**

| after | corpus | share |
|---|---|---|
| today | 7/27 | 26% |
| Stage 1 (prover fix only, no agent) | — | *raises the ceiling on everything below* |
| Stage 3 (agent fallback) | 22/27 | **81%** |
| + Stage 2 (title-from-slug) | 24/27 | **89%** |
| + a browser-backed link prover for McKinsey-class boards | 25/27 | **93%** |

The three boards past that line are honest refusals, and I would not spend to move them:

- **Sequoia** — httpOnly-cookie CSRF *and* cursor-only pagination. Also an aggregator, not
  a company board.
- **Walmart** — the only route is an LLM chat endpoint, at 4,860 requests/run with a
  fabricated session id. **Refusing this is the correct product decision**, not a gap.
- **Citadel** — interactive Turnstile on every detail page. Stage 2 gets its listing to
  56/56 with real titles; the per-job link stays unprovable, which is a degraded-but-honest
  outcome, not a failure to read the board.

So the realistic ceiling is **~93%, and the honest floor after Stages 1–3 is 81%** —
against 26% today. The thing standing between 81% and 89% is a regex in a field spec,
not an agent.

**The biggest risk is not accuracy, it is judgement.** The Walmart result is the one to
worry about: given a hard board and no constraint, the agent found a way in that we should
not take. It was confident, it was correct on the six criteria, and shipping it would have
been wrong. That gate has to exist before this goes near production.

---

## Stage 2 — implementation decisions

Stage 2 is **built**. Every judgement it took that this document did not spell out —
the `regex_capture` semantics, the bound on a stored pattern and what that bound
honestly buys, what happens to a row the pattern misses, the byte-framing that decides
whether the RSC parser works at all, the completeness check on the Bloomberg
12-of-380 hazard, and **three places where this document turned out to be wrong** —
is in **[STAGE-2-DECISIONS.md](STAGE-2-DECISIONS.md)**.

The two headline corrections, so they are not only in the sibling doc:

- **Bloomberg and Citadel are not "fixed outright" by Stage 2.** Their recipes are now
  expressible and replay live at **380/380** and **56/56** with real titles — but both
  read the board's *sitemap*, and `sources.EvidenceSource` deliberately keeps the
  sitemap out of the record path, so our own deterministic discovery still cannot
  author them. Stage 2 gives Stage 3's agent the vocabulary; it does not move those two
  boards on its own.
- **Meta is a `browser_fetch` board.** Form encoding was necessary and not sufficient:
  measured the same session, `body_encoding: "form"` through our own Chromium returns
  **876 rows in 5.4s** and the default JSON returns **400** — while plain `httpx` 400s in
  *every* combination of encoding, headers and cookies.
