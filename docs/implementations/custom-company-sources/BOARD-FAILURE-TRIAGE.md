# Board failure triage — 11 boards, measured two ways

**Measured 2026-08-30.** Every row below has evidence from **two independent directions**:

- **Direction A** — the real pipeline. Either the live stack's own `company_add_attempts` +
  `companies.provider_config->'discovery'` rows (written by the human's adds through
  `:3000`/`:8100` against `jobscraper_pr243`), or a fresh in-process run of the real
  `discover()` from this worktree — same code the Procrastinate worker executes, real
  capture subprocess, real Haiku 4.5, real acceptance replay.
- **Direction B** — the live website, independent of our code. An unfiltered clone of
  `_capture_main.py` that records **every** response with its `resource_type` and
  `content-type`, plus plain `httpx` replays.

**Honesty note on Direction A.** `:8100` runs the real app with real Auth0 RS256
validation and there is no test-token path, so I could not mint a token and drive
`POST /api/users/companies` as a test user. I did not write to `jobscraper_pr243` at all.
Instead I read the rows the human's own attempts had already written, and re-ran the
identical `discover()` in-process. Where I did that, the ledger came back **byte-for-byte
identical** to the stored one (Oracle/JPMC, Citadel, Nintendo, JPMorgan) — so the
substitution is sound, but it is a substitution and is flagged here rather than buried.

**Environment fact that matters.** `capture_board` used **Browserbase**, not local
Chromium, on every run (`BROWSERBASE_API_KEY` is set in `.env.local`). This is
load-bearing for McKinsey — see that row.

---

## 1. The table

| Board | What our system did | Where the jobs really live | Loss point | Category |
|---|---|---|---|---|
| **Uber** `uber.com/us/en/careers/list/` → `jobs.uber.com/en/jobs/` | Refused. `open_page done — recorded 0 JSON request(s)`; *"this page loaded its jobs without any JSON request we could record"*. Reproduced in-process. | Next.js RSC. List is **server-rendered into the navigation document** (`text/html`, 280,667 B, 11 `<a href="/en/jobs/<id>/">`, footer reads *"Prev 1 2 3 4 More pages 69 Next"* ⇒ **~690 jobs**). Pagination: `GET /en/jobs/?page=N` with header `RSC: 1` → **`text/x-component`**, `fetch`, 163,295 B, 10 job ids/page. One page load produced **42** `fetch` + `text/x-component` responses. | `_capture_main.py:366-370` drops all 42 (`"json" not in "text/x-component"`) **and** `sources.py:643` splits the 11 anchors into 11 singleton groups, so `anchor_candidate` (`sources.py:678-681`, `_MIN_HTML_RECORDS=8`) returns `None`. | **A + B** |
| **D. E. Shaw** `deshaw.com/careers/choose-your-path` | Live attempt #102 refused *"none of the **0** JSON request(s) … **is** a list"* — i.e. candidates existed and Haiku declined them. My re-run got `find_feed done — found 2 candidate feed(s)`, then `verify_read failed (ModuleNotFoundError)`. | **Zero XHR of any kind** (38 responses: script/image/css/font/document only). `__NEXT_DATA__` island: `props.pageProps.regularJobs` = **77**, `internships` 10, `internalJobs` 84. **87 job anchors** in the served HTML (`/careers/<slug>-<id>`, *no* trailing slash). Plain `httpx` GET → 200, 901,499 B. | Not the aperture. `document_candidates` correctly builds **two** candidates (`extract_embedded_island script#__NEXT_DATA__` → 77, `extract_css a[href*="/careers/"]` → 94). The board is lost to **nondeterministic model rejection**. The `bs4` crash is my venv only — `beautifulsoup4>=4.12.0` **is** in `src/backend/api/requirements.txt:13`. | **D** |
| **IBM** `ibm.com/careers/search` | First live attempt died at `open_page`: host-pin `Route.fetch: read ETIMEDOUT` (**transient — did not reproduce**). Re-run: `recorded 37 JSON request(s)`, refused *"none of the 37 … is a list"*. | `https://www-api.ibm.com/search/api/v2`, `xhr`, `application/json`, 23,990 B. Elasticsearch shape: **`hits.total.value = 1806`**, records at `hits.hits[]._source`, each carrying `url`/`title`/`description`. It **was** recorded (`prod_kept=true`). | `request_selector.py:274-286`. `_walk_record_arrays` scores only an array's **direct** elements. `hits.hits` element keys are `['_index','_id','_score','_source','sort']` → `_job_score = 1`, below `_MIN_JOB_SCORE = 2` (`request_selector.py:113`). The job objects one level down in `_source` score **3**. The walk returns **nothing**, so `prefilter_candidates` drops it at `request_selector.py:315-318`. | **C** |
| **Citadel** `citadel.com/careers/open-opportunities/` | Refused. `recorded 5 JSON request(s)` — all OneTrust consent — *"none of the 5 … is a list"*. Reproduced exactly (`attempts=1`). | WordPress, server-rendered. **10** `<a class="careers-listing-card" href="https://www.citadel.com/careers/details/<slug>/">` in the served document. Also an **`xhr` with `content-type: text/html`** (178,540 B) that re-fetches the listing page for filtering. | `sources.py:643` — `parts.path.rsplit("/", 1)[0] + "/"` does not strip a trailing slash, so `/careers/details/<slug>/` becomes its own directory. Proven: 10 job anchors → **10 groups of size 1**. Plus `_capture_main.py:368-370` drops the `text/html` xhr. | **B + A** |
| **Meta** `metacareers.com/jobsearch/` | Refused. `recorded 0 JSON request(s)`. | `POST https://www.metacareers.com/graphql`, `resource_type = **xhr**`, **`content-type: text/html`**, 186,957 B, body is pure JSON. `data.job_search_with_featured_jobs_v2.all_jobs` = **877 records**; a sibling call declares `job_count: 877`. **Verified replayable with plain `httpx`, no cookies, no referer → 200, 877 records.** | `_capture_main.py:368-370`, one line. `"json" not in "text/html"`. | **A** |
| **Nintendo (search)** `careers.nintendo.com/job-search/` | Refused. `recorded 12 JSON request(s)` — Sentry, Unleash (401), OneTrust, Qualtrics — *"none of the 12 … is a list"*. | **The page is a 404.** `<title>404 - Nintendo Careers Site</title>`. There are no jobs on it. | None. Refusing is right. The defect is the **sentence**: we blamed the board instead of saying the URL does not exist and pointing at `careers.nintendo.com/jobs/`. | **E** |
| **Sequoia** `jobs.sequoiacap.com/jobs/` | Got furthest of any failure: captured → selected → synthesised → acceptance replay `HTTP 412 … {"error":"INVALID_CSRF"}`. | Consider.com board. `POST /api-boards/search-jobs`, `xhr`, `application/json`, 288,158 B, **`total = 9968`** across **255 portfolio companies**. Express `csurf` double-submit: `x-csrf-token` must pair with the `session` + `session.sig` cookies from the *same* bootstrap. Derivation verified: `token = salt + "-" + b64url(sha1(salt + "-" + secret))`. | `_capture_main.py:185-188` — `_HEADER_DENYLIST` strips `cookie`, so the recipe stores the header but not its paired cookie. `_browser_fetch_main.py:378` then navigates fresh → **fresh cookie + stale token → 412**. Reproduced: same-session pair 200; cross-session pair 412; no cookie 412. | **F** |
| **McKinsey** `mckinsey.com/careers/search-jobs` (URL found by me) | **SUCCEEDS.** `ok=True`, accepted round 2, `transport=http_json`, `oracle=declared_probed`, `coverage=640/640`. | `GET https://gateway.mckinsey.com/apigw-x0cceuow60/v1/api/jobs/search?pageSize=20&start=1&lang=en`, `xhr`, `application/json`, 137,844 B, **`numFound = 586`**. No auth at all; `pageSize=1000` returns the whole board in one request. | No loss. **Correction to a plausible-but-wrong finding:** plain local headless Chromium cannot load `mckinsey.com` (`net::ERR_HTTP2_PROTOCOL_ERROR`, reproduced 3×, Akamai bot manager). Our capture goes via **Browserbase**, which loads it fine. This is exactly the kind of claim Direction B alone would have got wrong. | **none** |
| **JPMorgan Chase (pasted)** `jpmorganchase.com/careers/explore-opportunities/programs` | Refused. `recorded 11 JSON request(s)` — *"none of the 11 … is a list"*. Reproduced exactly. | **A marketing brochure.** `<title>Programs \| JPMorganChase</title>`, `<h1>Programs</h1>`, **0 individual job postings**. The 11 requests: 5 OneTrust, 1 Akamai mPulse, 2 Chase analytics, 3 real content APIs — the biggest, `careers/programs.US.en.json` (47,543 B), is **89 programme brochure entries** with no requisition id, no date, no apply URL. Pre-filter scored it `records=0`, correctly. | None. Refusing is right. Same message defect as Nintendo. **Real board:** `jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs`, reached from that very page via *"Join our team"* / *"Apply now"* → `/requisitions` → 302 → `/jobs`. | **E** |
| **Oracle HCM / JPMC** `jpmc.fa.oraclecloud.com/…/CX_1001/jobs` | Refused *"none of the 21 JSON request(s) … is a list of job postings"*. **Reproduced byte-for-byte.** That sentence is **false** — see §2. | `GET …/hcmRestApi/resources/latest/recruitingCEJobRequisitions?…&finder=findReqs;siteNumber=CX_1001,…,limit=25,sortBy=POSTING_DATES_DESC[,offset=N]`, `fetch`, **`application/vnd.oracle.adf.resourcecollection+json`** (contains `json`, so it **is** kept), 86,672 B. `items[0].requisitionList` = 25 records; **`items[0].TotalJobsCount = 7181`**; `PostedDate` present. `limit=200` works with no headers. Fires **on load**, no interaction. | The pagination lives **inside** the `finder=` composite value (`…,limit=25,…,offset=25`), not as a query param, so no `paginate_offset` step is synthesised (`discover.py:1600`). `_feed_reach = 25`; `_coverage` (`discover.py:953`) refuses at `discover.py:3015-3023` under `_COVERAGE_REFUSAL_RATIO = 0.10` (`discover.py:376`) — 25/7181 = 0.35%. Then `discover.py:2842-2846` **discards `last_error`** and reports the wrong cause. | **G + H** |
| **Nintendo** `careers.nintendo.com/jobs/` — *tracked, but wrong link* | `ok`, `healthy`. Stored recipe: `http_html`, `extract_embedded_island script#__NEXT_DATA__`, `records_path=props.pageProps.jobs`, **`fields.url = "absolute_url"`**. | Greenhouse feed, 49 jobs. Record carries `id=4295098009`, `internal_job_id=4173984009`, `absolute_url=https://careers.nintendo.com/?gh_jid=4295098009`. Working URL is `/jobs/{id}/`. **Verified live:** `?gh_jid=…` → 200, 64,408 B, title *"Careers at Nintendo - Join Our Team"*, **job title absent** (it serves the listing page). `/jobs/4295098009/` → 200, 82,962 B, title *"Brand Ambassador [Part-Time] - Peoria, IL"*. | `discover.py:2295-2296` — rung 1 returns the LLM's `field_map["url"]` **verbatim, fetching nothing**. `is_published_url_spec` (`request_selector.py:861-884`) only tests `startswith(("https://","http://","/"))` (`request_selector.py:891`) plus distinctness. | **I** |

### Controls

| Board | Result |
|---|---|
| **Walmart** `careers.walmart.com/results` | Refused `page_param_unpaginated` at `_STEP_SYNTHESIZE` (`discover.py:1729-1735`, `harvest_verification.py:337`). **Correct** — a 10-job read of a much larger board. |
| **Y Combinator** `ycombinator.com/companies/raindrop/jobs` | **Re-pulled 06:09 UTC after the other agent's fix: now `healthy`.** Stored `http_html` + `extract_css` on `a[href*="/companies/raindrop/jobs/"]`. Useful as a natural control for **Category B**: YC's job hrefs have **no trailing slash**, which is exactly why the anchor path works here and dies on Citadel and Uber. |

---

## 2. The finding that overturned two hypotheses

The refusal string **"none of the N JSON request(s) this page made is a list of job postings"
does not mean what it says.** It is emitted at `discover.py:2842-2846` whenever the round
loop exits with `NoJobsFeedError`, and it **throws away `last_error`** — the real reason,
which was set at `discover.py:3016`.

Oracle/JPMC is the proof. The in-process run's own logs:

```
discovery fan-out …: 6 of 6 candidate(s) answered yes
capture discovery REFUSED a replayable candidate …: reaches 25 record(s) against a published 7181
… (×6, once per candidate) …
discovery found no jobs feed … none of the 6 captured array(s) is a list of job postings
```

So, in order: the capture recorded it, the pre-filter selected it (`items.0.requisitionList`,
score 25, 6/6), **Haiku said yes with high confidence 6/6** — and then the *coverage floor*
killed every candidate. Round 2 re-asked with that failure as feedback, the model
reasonably said no, and the user was told the board has no jobs feed.

Three separate hypotheses died on this board:

1. **Not the content-type aperture.** `application/vnd.oracle.adf.resourcecollection+json`
   contains `json`, so `_capture_main.py:369` keeps it.
2. **Not passive capture.** The requisitions calls fire **on page load** with no
   interaction; 13 of them were recorded. No search needs triggering.
3. **Not the model.** I ran the real `classify_candidate` against these exact bytes:
   **yes, `confidence=high`, 6 of 6**, with a complete field map.

**Citadel does not share Oracle's signature either**, despite the identical refusal
sentence. Citadel's five recorded requests are genuinely all cookie-consent JSON; its jobs
are in the served HTML. Same sentence, unrelated cause — which is the whole reason that
sentence has to stop being emitted for anything but its literal meaning.

**Two smaller bugs found on the way**, both worth recording:

- `_prove_job_link` rejected Oracle's **correct** `/job/{Id}` template — derived from the
  board's own anchors with 20/20 agreement — because plain-`httpx` fetches of an SPA
  return an identical 30-character shell: *"two different jobs served the same page
  (30 vs 30 chars)"*. Rung 1 trusts too much; rung 3 distrusts too much, and for the
  same underlying reason: neither renders the page.
- `sources.py:722-725` appends the anchor candidate **last** and then truncates to
  `_MAX_HTML_CANDIDATES = 2`. D. E. Shaw fills both slots exactly; a page with two JSON
  islands would silently lose its anchor candidate.

---

## 3. Commonality — grouped by root cause, ranked by boards recovered

| Rank | Group | Boards | The one place a change fixes the group |
|---|---|---|---|
| **1** | **A — content-type aperture** | **Meta** (outright), **Citadel** (enabling), **Uber** (enabling) | `_capture_main.py:366-370`. Drop the `"json" in content-type` test and let `prefilter_candidates`' own `json.loads` (`request_selector.py:309-314`) be the arbiter — it already is for everything that gets through. Keep the `xhr`/`fetch` resource-type test. |
| **2** | **B — anchor directory trailing slash** | **Citadel** (outright), **Uber** (partial) | `sources.py:643`. Strip a trailing `/` before taking the directory. One line. YC is the control that proves the rest of the path works. |
| **3** | **C — per-element wrapper** | **IBM** (1,806 jobs) | `request_selector.py:274-286`. When an array's elements score below the floor but each element has exactly one dict-valued key (`_source`, `node`, `fields`, `attributes`), score and offer the unwrapped path. Covers **every Elasticsearch and Relay/GraphQL `edges[].node` board**, not just IBM. |
| **4** | **G — pagination inside a composite parameter** | **Oracle/JPMC** (7,181 jobs, declared total) — and **every Oracle Fusion Recruiting board**, one of the largest enterprise ATSs | `discover.py:1600` + the synthesiser's page-param search. Teach it to look inside `;`/`,`-delimited composite values such as `finder=findReqs;…,limit=25,offset=N`. One ATS family, very large boards, each carrying its own `TotalJobsCount` oracle. |
| **5** | **E — the pasted page is not a board** | **Nintendo `/job-search/`** (404), **JPMorgan `/careers/…/programs`** (brochure) | Not in the capture at all — in the copy and the suggestion. Detect (a) a 404/empty document at `open_page`, (b) a document with no job-shaped anchors *and* no job-shaped JSON, and say *"this page doesn't list open roles"* plus a suggested URL, rather than *"none of the N JSON requests is a list of job postings"*. **2 of 11 boards, and the cheapest group to fix.** |
| **6** | **H — the refusal message lies** | Recovers **0** boards; makes every other row honest | `discover.py:2842-2846`. When `last_error` is set, report *that* step and reason. This one change is why this investigation needed a day: four boards wore the same sentence for four different reasons. |
| **7** | **I — rung-1 verbatim job link** | **Nintendo `/jobs/`** wrong today; **13 of 19 boards (68%) take rung 1** (`JOB-LINK-RULE.md:46-58`), including every Greenhouse `absolute_url` board — SpaceX, Figma, Roblox, Anthropic, Stripe | `discover.py:2295-2296`. A **no-fetch** guard is available and sufficient: reject a published spec whose rendered URL has **zero path segments** (`urlsplit(...).path == "/"`), i.e. all identity in the query string. Every one of the 13 corpus boards is path-bearing, so the guard is free on all of them. The codebase already states this exact insight on the derivation side (`request_selector.py:1118-1142`: *"the QUERY IS DROPPED … a board that keys its jobs by query parameter alone cannot be derived"*); it simply has no counterpart on the published side. Falling through to rung 3 then reaches `derive_url_templates_from_links`, which would emit `/jobs/{id}/` from the page's own anchors with ≥3-record agreement. |
| **8** | **F — session-bound credential** | **Sequoia** (9,968) — and every Consider/`csurf` board | `_capture_main.py:185-188` + the recipe schema. Either carry the `session`/`session.sig` cookies alongside the header, or (better) support a two-step bootstrap: GET the board page, scrape `"csrfToken":"…"`, keep the cookie jar. **But see §4** — this board should probably refuse anyway. |

**The single highest-leverage change** is **#1, the content-type aperture at
`_capture_main.py:366-370`.** It is one line; it recovers Meta outright (877 jobs,
declared total, replays with bare `httpx` — nothing else needed); and it is a
precondition for Citadel's `text/html` listing XHR and Uber's 42 RSC responses. Nothing
else in the batch is that cheap for that much.

**The change with the best cost-to-truth ratio** is **#6**, the refusal message. It
recovers no board and should still ship first, because it is what makes the other seven
diagnosable from production instead of from a day of local re-runs.

### Explicitly killed hypotheses

- **The `text/x-component` / aperture hypothesis is real but narrow.** It fully explains
  Meta and is necessary for Uber and Citadel. It explains **nothing** about Oracle, IBM,
  D. E. Shaw, Sequoia, McKinsey, Nintendo, Walmart or JPMorgan. Eight of eleven boards
  are not aperture failures.
- **The "our capture is passive / a search must be triggered" hypothesis is false for
  every board in this batch.** Oracle, IBM, Meta, McKinsey and Sequoia all fire their
  jobs request on load with no interaction; Uber, Citadel and D. E. Shaw server-render.
  Not one board needed a click.
- **"Headless Chromium is bot-walled" is true of local Chromium but not of our pipeline**,
  because we run on Browserbase. McKinsey succeeds end-to-end.

### Category key

**A** aperture · **B** anchor directory · **C** record-array walk · **D** model
nondeterminism on a document candidate · **E** not a board · **F** session-bound
credential · **G** composite-param pagination + coverage floor · **H** misleading
refusal · **I** rung-1 verbatim link

---

## 4. What is genuinely unfixable, and should refuse cleanly

| Board | Why refusing is correct |
|---|---|
| **Nintendo `/job-search/`** | The URL 404s. There is nothing to read. Refuse — but name the 404 and suggest `careers.nintendo.com/jobs/`, which we already track successfully. |
| **JPMorgan `/careers/explore-opportunities/programs`** | A brochure with 0 postings. Its only JSON is 89 marketing entries with no requisition id, no date, no apply link. Refuse — and suggest the Oracle board the page itself links to. |
| **Walmart `careers.walmart.com/results`** | Already refuses correctly. A one-page read of a much larger board would show 10 jobs and silently miss the rest. The refusal is the product working. |
| **Sequoia `jobs.sequoiacap.com/jobs/`** | Technically fixable (§3 #8), but it is a **talent-network aggregator: 9,968 jobs across 255 portfolio companies**, not Sequoia's own roles. Tracking it as "Sequoia" would be wrong data, well fetched. Recommend refusing with *"this board lists jobs at 255 companies, not at Sequoia"* — and treat the CSRF work as a separate decision. |
| **McKinsey — a caveat, not a refusal** | It succeeds, but the payload has **no posting date**. The only date-ish field is `postedToLinkedInDate`, present on 478/586 and stale (doc[0] = `2023-05-26`). For a hiring-*trend* product that is a real gap; it will land `oracle_kind` fine but its trend line will be wrong. Worth an explicit decision before it is offered. |

Everything else in the batch is recoverable.

---

## 5. E2E backfill plan

Named in the existing `AC-NN` style of `e2e/add-companies/CASES.md`; board URLs belong in
`e2e/add-companies/boards.py`; live-vs-fast follows the `live` marker convention. **These
are specifications, not tests — nothing here is written yet.**

| ID | Board / fixture | Tier | Marker | What it pins, and the root cause it would have caught |
|---|---|---|---|---|
| **AC-16** | Meta — `metacareers.com/jobsearch/` | API | live (LLM) | **Category A.** Assert the *mechanism*: `provider_config->'discovery'->'network'->>'recorded' > 0`, the chosen request is `metacareers.com/graphql`, and the stored recipe replays to ~877 rows over plain `httpx`. Today `recorded` is **0** — the assertion fails at the first clause, which is exactly the signal wanted. |
| **AC-17** | Citadel — `citadel.com/careers/open-opportunities/` | API | **fast, hermetic** + live | **Category B.** The hermetic half is the valuable one and mirrors AC-06a/AC-13a: save the served document as a fixture and assert `sources._anchor_rows` yields **one** `/careers/details/` group with ≥8 rows, not N singletons. Add the live add as the integration half. A trailing slash in a job URL must never split the group. |
| **AC-18** | IBM — the real `www-api.ibm.com/search/api/v2` payload as a fixture | API | **fast, hermetic** (no network, no LLM) | **Category C.** Assert `prefilter_candidates` returns a candidate whose `records_path` resolves to the 30 `_source` objects, not nothing. Pin the *shape*, not IBM: parametrise over an Elasticsearch `hits.hits[]._source` fixture **and** a Relay `edges[].node` fixture, so the fix is proven general. |
| **AC-19** | Oracle Fusion — `jpmc.fa.oraclecloud.com/…/CX_1001/jobs` | API | live (LLM) | **Categories G + H, and the most important new case.** Two assertions: (a) *the refusal names the step that actually failed* — it must **not** say "none of the N JSON request(s) is a list of job postings" when the fan-out logged `N of N answered yes`; (b) once composite-param pagination lands, the stored recipe carries `TotalJobsCount` as a declared oracle and reaches ≥90% of it. Clause (a) is assertable **today** and fails **today**. |
| **AC-20** | Nintendo — `careers.nintendo.com/jobs/` | API | live (harvest wait) | **Category I.** Extend `_assert_two_job_links_resolve` (`e2e/add-companies/api/test_discovery.py:286-334`) so a **published** spec is verified too: fetch the stored job URL and assert the body contains **that job's own title**. Today the helper returns early for published specs (`if "{" not in url_spec: return`, `:328-329`) and Nintendo's broken URL answers a clean 200 — so the existing case passes on a link that does not work. This is the single case that would have caught the wrong-link bug. |
| **AC-21** | Two non-boards: `careers.nintendo.com/job-search/` (404) and `jpmorganchase.com/careers/explore-opportunities/programs` (brochure) | API | fast (network, no LLM) | **Category E.** Assert the refusal is a *named* "this page doesn't list open roles" — not the jobs-feed sentence — and that an obvious 404 costs **no LLM call and no monthly slot** (`company_add_attempts` outcome + the AC-14 accounting). |
| **AC-22** | Sequoia — `jobs.sequoiacap.com/jobs/` | API | live | **Category F.** Assert the refusal names the CSRF/session cause at `verify_read`, and — the load-bearing half — that **no recipe is stored** that would 412 on every nightly run. |
| **AC-23** | McKinsey — `mckinsey.com/careers/search-jobs` | API | live (LLM) | The **success** control for this batch, and a regression guard on Browserbase: assert `outcome='tracking'`, `oracle_kind` declared, ~586 jobs. Also assert the known gap explicitly — that posted-date coverage is recorded as low — so the trend-data caveat cannot be forgotten silently. |
| **AC-24** | D. E. Shaw — `deshaw.com/careers/choose-your-path` | API | live (LLM) | **Category D.** Assert `find_feed` reports **2 candidate feed(s)** and that one is accepted. This board is currently *flaky*, not broken — it is the case that will tell us whether document candidates need a deterministic accept path rather than a model vote. Mark it explicitly as a flake-watch case, in the style of the existing "Known drift" section. |

**Also worth pinning outside `add-companies`:** `sources.py:722-725` truncates to
`_MAX_HTML_CANDIDATES = 2` **after** appending anchors last — a unit case with three
document candidates would prove the anchor candidate is not the one dropped.

---

## 6. What I could not determine

- **Why live attempt #102 (D. E. Shaw) produced no accepted candidate while my identical
  re-run produced two.** Both ran the same worktree code (all `capture/*.py` mtimes
  predate the backend's `00:05:29` start), both went via Browserbase, both saw
  `server_html` (I verified the host-pin's `route.fetch` body is byte-identical to the
  browser's document — 900,275 B both ways). The refusal verb (`is`, not `returned`)
  proves candidates *did* reach the model in production. The most probable explanation is
  **Haiku answering differently on the two runs**, but I did not run it enough times to
  measure a rate, so I am calling this *unresolved*, not *nondeterministic*.
- **IBM's `Route.fetch: read ETIMEDOUT`.** I could not reproduce it in four attempts
  (pinned and unpinned probes, plus a full `discover()`). The mechanism is legible —
  `_capture_main.py:311` calls `route.fetch(max_redirects=0)` with **no explicit timeout**,
  and any exception there fails the whole capture closed (`_capture_main.py:334-340`) —
  but I cannot show it is more than a transient network fault, and I did not measure a
  failure rate. Worth noting that this doubles every navigation into a second, non-browser
  request that a WAF may treat differently; I could not demonstrate that it does.
- **Uber's true job count.** The footer says 69 pages × 10 = ~690, but `?page=N` only
  server-renders page 1 (page 2 renders *"Loading jobs…"* with 0 anchors). The `RSC: 1`
  header does return `text/x-component` with 10 job ids for `?page=2`, so it is
  enumerable — but I did not walk all 69 pages, so ~690 is the board's own claim, not a
  count I made.
