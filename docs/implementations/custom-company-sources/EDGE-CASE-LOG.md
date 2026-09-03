# Edge-case log — every board that failed, and why

A running catalogue. Rows are grouped by **root cause**, not by board, so a repeated shape is
visible at a glance. When board #40 breaks, scan the subheadings first.

Sources, most reliable first: `BOARD-FAILURE-TRIAGE.md` (every row measured two independent
ways), `e2e/add-companies/CASES.md`, the `company_add_attempts` table in `jobscraper_pr243`,
then the fix commits. Where a source disagreed with the conversation it came from, the
measurement won — several confidently-stated claims in that thread were later disproven, and
those are called out inline.

**Status key** — FIXED · REFUSES CLEANLY (working as intended) · OPEN · NOT A BUG · UNDER INVESTIGATION

---

## Shapes we now handle

- A jobs feed served with a non-JSON `content-type` (`text/html`, `application/vnd.oracle.adf…`)
- A jobs feed larger than the per-response body cap (2 MB → 4 MB)
- A jobs feed that lands after the observation window (8.4 s → 24 s)
- Job records wrapped one level deep — Elasticsearch `hits.hits[]._source`, Relay `edges[].node`
- Pagination hidden inside a composite query value (`finder=findReqs;…,limit=25,offset=N`)
- Pagination nested several levels down a POST body (GraphQL envelopes)
- A board whose first page is `0`, not `1`
- Job hrefs with a trailing slash (they used to split into groups of one)
- A board that ships its jobs in the served document, or in a `__NEXT_DATA__` island
- A board that ships its link template only in its JS bundle
- A published job link that is distinct, 200, and still serves the listing page
- A refusal message that named the wrong step (this misled two whole investigations)
- A pasted URL that is already one of our published boards (script rung, then name-in-domain rung)

---

## 1. The response never reached the pre-filter (capture aperture)

The board sent its jobs. Our recorder threw them away, then blamed the board.

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Meta | `metacareers.com/jobsearch/` | "this page loaded its jobs without any JSON request we could record" — recorded **0** requests | The `POST /graphql` reply is 186,957 B of pure JSON with `content-type: text/html`. The keep test was `resource_type in (xhr,fetch)` **and** `"json" in content-type` (`_capture_main.py:366-370`). | **OPEN** — recorded went 0 → 4, so it is visible now, but it refuses one step later: the GraphQL body is `application/x-www-form-urlencoded` (the recipe schema needs an object) and a bare-`httpx` replay of that exact request answers **400**. **The triage doc's "recovers Meta outright" is wrong.** | `1424058`; e2e AC-16 |
| Atlassian | `atlassian.com/company/careers/all-jobs` | "none of the 14 JSON request(s) this page made is a list of job postings" — and it looked like a *flaky board*, because 1 run in 11 worked | The feed (`/endpoint/careers/listings`, 1.85 MB, 268 postings) arrives **~10.6 s** after `goto` returns. The observation window was 6 s + 2×1.2 s = 8.4 s. Our clock, reported as the board's fault. | **FIXED** — 3/3 runs capture the feed; tracked and healthy since 2026-08-25 | `f97e915` |
| Binance | `binance.com/en/careers/job-openings` | Same sentence, from the other ceiling: "none of the 40 JSON request(s) …" | Its Lever export is **2,775,685 B**, 39 % over the old 2 MB per-body cap. Over the cap the child records an empty body + `truncated: true`, and the pre-filter drops it with the tracking pings. | **FIXED** — A/B on one page load: 2 MB → REFUSE, 4 MB → tracks. (It still binds narrowly: `records_path "4.postings"`, 81 of 279 postings.) | `85821b6` |
| Uber | `jobs.uber.com/en/jobs/` | Same "no JSON request we could record" | Next.js RSC: its 42 pagination responses are `text/x-component`, which nothing downstream can parse — so the aperture was **deliberately not** widened to admit them (`_MAX_RESPONSES` is 40, spent in arrival order; admitting RSC would evict real feeds and rescue none). Uber's real answer was in the served document. | See §4 | — |

## 2. Recorded, but the record walk could not see the jobs

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| IBM | `ibm.com/careers/search` | "none of the 37 JSON request(s) … is a list of job postings" — while the feed *was* recorded and kept | `www-api.ibm.com/search/api/v2` is Elasticsearch: `hits.total.value = 1806`, records at `hits.hits[]._source`. `_walk_record_arrays` scored only an array's **direct** elements — `['_index','_id','_score','_source','sort']` scores 1, under `_MIN_JOB_SCORE = 2`. The job objects one level down score 3. (`request_selector.py:274-286`) | **REFUSES CLEANLY** — the feed now ranks first and the model picks it, but IBM's request carries `size: 30` and **no `from`/offset at all**, so no paging step can be synthesised and a 30-of-1,806 read stops at `page_limit_reached`. Inventing a paging parameter the board never sent is not a thing to do quietly. **The triage doc's "recovers IBM" is wrong.** | `a40bf96`; e2e AC-18 |
| *(Relay / GraphQL `edges[].node`)* | — | Same shape, element score 0 | Same walk. Fixed generically and parametrised over both dialects — it is an ATS family, not an employer. | **FIXED** | `a40bf96` |
| IBM (transient) | same | One attempt died at `open_page`: `host-pin: Route.fetch: read ETIMEDOUT` | `_capture_main.py:311` calls `route.fetch(max_redirects=0)` with **no explicit timeout**, and any exception there fails the whole capture closed. Not reproducible in 4 attempts. | **OPEN** — mechanism legible, rate unmeasured | — |

## 3. We could read page one and not page two

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| JPMorgan (Oracle Fusion) | `jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs` | "none of the 21 JSON request(s) … is a list of job postings" — **false**: the fan-out logged *6 of 6 answered yes* | Oracle carries its whole search in one query parameter: `finder=findReqs;siteNumber=CX_1001,…,limit=25,offset=75`. `offset` is not a parameter, it is a token *inside* one, so no paging step was synthesised; the coverage floor then refused all 6 candidates at 25 records against a declared `TotalJobsCount = 7181`; then `discover.py:2842-2846` discarded `last_error` and printed the wrong cause. | **FIXED** — added successfully 2026-08-30 14:06 UTC. Covers **every Oracle Fusion Recruiting board**, a large slice of enterprise employers. | `dfb84f6` + `2878837`; e2e AC-19 |
| Oracle (own board) | `careers.oracle.com/en/sites/jobsearch/jobs?location=United%20States&…` | "this board's own request asks for one page of results and we could not work out how to ask for the next one (`page_limit_reached`) — tracking it would show **14 job(s)** and silently miss the rest" | unknown. One early measurement only: the Fusion REST path on Oracle's own host returns a **5,453-byte SPA shell**, not JSON — Oracle fronts its own careers site differently from what it sells to tenants, so the JPMorgan fix did not carry over. | **UNDER INVESTIGATION** | — |
| Goldman Sachs | `higher.gs.com/roles` | "it only fetched 20 jobs" against a declared **1,074** | Two defects. (a) `pageSize`/`pageNumber` sit four levels down a GraphQL envelope (`variables.searchQueryInput.page.*`); a flat `body.items()` scan could not see them, so the page size was never raised. (b) The runner defaults to page **1** while Goldman's captured body says `pageNumber: 0`, so the sweep skipped the board's own first page. | **OPEN** — the merge/scan fixes landed, but its stored evidence is still 20 of 1,074 with `page_advance_ok = False`. Refused by **three independent gates** (check 6, `declared_probed` exact-match, the 10 % `empty_scrape` floor), so 1,054 jobs stay OPEN and nothing wrong-closes. Never re-added since. | `7dd3319`, `dfb84f6`; e2e AC-15 |
| Microsoft | `jobs.careers.microsoft.com/global/en/search` | Badge stuck orange, "tracking part of this board" — 1,000 of a declared 2,111 | **Our own constant, not the board.** `_MAX_HARVEST_PAGES = 100` was a flat *page* ceiling, which is a different *job* ceiling on every board: 10,000 jobs on amazon.jobs (100/page) but 1,000 on Microsoft's Eightfold board (10/page, hard — it ignores `num`/`limit`/`size`/`pageSize` alike). | **FIXED** — the budget is denominated in jobs now, bounded at runtime by a 600 s wall clock + a 50,000-row backstop; an unfinished sweep sets `cap_hit` → UNVERIFIED → closes nothing | `dfd7320` |
| Walmart | `careers.walmart.com/results` | "tracking it would show 10 job(s) and silently miss the rest" (`page_param_unpaginated`) | The pagination refusal is the correct downstream consequence of a deeper problem — see §7 for what we actually captured. | **REFUSES CLEANLY** | `f7733b7` |

## 4. The board ships its jobs in the document, not in JSON

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Uber | `jobs.uber.com/en/jobs/` (also `uber.com/us/en/careers/list/`) | "this page loaded its jobs without any JSON request we could record" | Two things. The list is **server-rendered into the navigation document** (280,667 B, 11 `<a href="/en/jobs/<id>/">`, footer claims ~690 jobs). And `sources._anchor_rows` grouped anchors by `path.rsplit("/",1)[0] + "/"`, so a **trailing slash** in the href put every posting in its own group of one, all below `_MIN_HTML_RECORDS = 8`. (`sources.py:643`) | **FIXED (anchor grouping); OPEN end-to-end** — A/B'd live on that one character: 10 groups of 1 → **one group of 10**, 1 document candidate. The full add has not been re-run since. | `2a28a3c`; e2e AC-17 |
| Y Combinator / Raindrop | `ycombinator.com/companies/raindrop/jobs` | "none of the 3 JSON request(s) this page made returned a list of job postings". Earlier still, discovery *guessed* a JSON API and 404'd instead of reading the embedded island | Server-rendered JSON island plus anchors; no XHR to capture. Discovery had no path that let the document itself become a candidate. | **FIXED** — healthy since 2026-08-30 06:09 UTC; stores `http_html` + `extract_css` on `a[href*="/companies/raindrop/jobs/"]`. Also the **control** for §4's trailing-slash bug: YC's hrefs carry no trailing slash, which is why the same code always worked here. | `1757370` |
| Raindrop (own site) | `raindrop.ai/careers/` | "none of the 5 JSON request(s) this page made returned a list of job postings" | Presumed the same shape as YC, but **not measured**. | **OPEN** — refused 2026-08-29 21:23 UTC, never retried after document candidates landed | — |
| D. E. Shaw | `deshaw.com/careers/choose-your-path` | "none of the **0** JSON request(s) … **is** a list" — i.e. candidates existed and the model declined them | **Zero XHR of any kind** (38 responses: script/image/css/font/document). The `__NEXT_DATA__` island holds `regularJobs` = 77; the served HTML has 87 job anchors. `document_candidates` correctly builds **two** candidates. The board is lost to the model saying no. | **OPEN** — an identical in-process re-run produced 2 candidates and got further. Flaky, not broken. Deliberately called *unresolved*, not *nondeterministic*: the rate was never measured. | — |
| Jane Street | `janestreet.com/join-jane-street/open-roles/` | Tracked, but the pasted page renders **0** job anchors — in raw HTML *and* in the rendered DOM after the full 24 s window | The pasted page is a **chooser** ("Experienced Candidates" / "Students and New Grads"). It fetches all 233 roles as `jobs/main.json` and renders none of them, so anchor-scraping had nothing to score. Link consequences in §8. | **FIXED** | `f7733b7` |

## 5. The board blocks us

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Citadel | `citadel.com/careers/open-opportunities/` | "none of the 5 JSON request(s) … is a list of job postings" — the 5 are all OneTrust cookie-consent JSON | Measured through the real `capture_board`: `citadel.com` answers our host-pin fetch with a **5,939-byte Cloudflare interstitial** ("Just a moment…"), and its rendered DOM carries 102 links, **none** under `/careers/details/`. The ten `careers-listing-card` anchors an independent browser saw are not served to us. **The triage doc's "the trailing-slash fix recovers Citadel" is wrong** — that fix is real, it is just not Citadel's problem. | **OPEN** | — (shape kept as a shape in e2e AC-17) |
| McKinsey | `mckinsey.com/careers/search-jobs` | Reported as failing | **It succeeds** — `ok=True`, `http_json`, `oracle=declared_probed`, coverage 640/640, no auth at all. Plain *local* headless Chromium cannot load `mckinsey.com` (`net::ERR_HTTP2_PROTOCOL_ERROR`, reproduced 3×, Akamai bot manager) — but our capture runs on **Browserbase**, which loads it fine. | **NOT A BUG.** One real caveat: the payload has **no posting date** (`postedToLinkedInDate` on 478/586, and stale), so its hiring-*trend* line will be wrong. | — (e2e AC-23 spec) |

## 6. The request is bound to the session that made it

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Sequoia | `jobs.sequoiacap.com/jobs/` (and `/jobs/vanta?…`) | Got further than any other failure — captured, selected, synthesised — then `HTTP 412 {"error":"INVALID_CSRF"}` on the acceptance replay | Consider.com board using Express `csurf` double-submit: `x-csrf-token` must pair with the `session` + `session.sig` cookies **from the same bootstrap**. `_capture_main.py:185-188` `_HEADER_DENYLIST` strips `cookie`, so the recipe stores the header but not its paired cookie; replay navigates fresh → fresh cookie + stale token → 412. Reproduced: same-session pair 200, cross-session 412, no cookie 412. | **REFUSES CLEANLY** — and should stay refused for a second reason: it is a talent-network aggregator, **9,968 jobs across 255 portfolio companies**, not Sequoia's own roles. Tracking it as "Sequoia" would be wrong data, well fetched. | — (e2e AC-22 spec) |

## 7. We captured the wrong thing

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Walmart | `careers.walmart.com/results` | "Now tracking" — **10 jobs of 48,800** | **We captured Walmart's AI chat-assistant endpoint, not its catalogue.** The stored fetch body carries `thread_id: "S-1788038636412-<uuid>"`, whose embedded epoch-ms decodes to six seconds after the company row was created — minted inside that one discovery browser session. It returns *real* Walmart job ids, so every id-overlap check passes. The catalogue API is **not in the JSON network list at all**. Discovery separately *read* 48,800 off the payload and rendered it to the user, where it drove nothing. **This was not a pagination miss.** | **REFUSES CLEANLY** — `page_shape_refusal` is now called at synthesis (`job_page: 0` → `page_param_unpaginated`), so that capture is refused rather than stored. Its sitemap gives an independent count (15,660 job `<loc>` of 16,210) for a coverage check. | `f7733b7`, `a86e5bf`; e2e AC-15 |

## 8. The job link was a guess, and the guess was wrong

13 of 19 corpus boards take rung 1 — the board's own `field_map["url"]`, trusted verbatim,
fetching nothing. It is the highest-exposure rung there is.

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Goldman Sachs | `higher.gs.com/roles` | Every "view job" link led to a blank page — `…/roles/182980_GS_MID_CAREER` where the real link is `…/roles/181782` | Goldman publishes **two** ids per role: `roleId` (`181783_GS_NOTICE_OF_FILING_LCA`) and `externalSource.sourceId` (`181783`). Only the second routes. The board is a Next.js SPA answering **200 for every path**, so the wrong URL served a 23-char shell identical on every job and no status check could see it. | **FIXED** — `repair_url_template` scores placeholder fields against URLs the capture recorded on the board's host; post-repair the three sampled jobs serve 4,003 / 3,383 / 4,713 chars, each with its own title | `7dd3319` |
| Goldman Sachs | same | Every row stored `location = NULL`, at 100 %, silently | The selector wrote `locations[0].city`; `dig` split on `.` only, so the bracket lookup raised and `render_field` swallowed it | **FIXED** — `dig` retries a bracketed index as `.0`. A strict superset, so no stored recipe changes meaning. | `7dd3319` |
| Jane Street | `janestreet.com/join-jane-street/open-roles/` | `janestreet.com/jobs/8755768002` → **404**, on all 233 jobs | We invented `…/jobs/{id}`. `_prove_job_link` is verification-only — it can show a template is wrong and cannot find the right one — so the board fell to `_board_page_link`, a `listing-page#{id}` fragment: 233 jobs all linking to the same page. Its rendered page has no anchors to derive from either (§4). | **FIXED** — a new derivation reads the `href="…${…}…"` literal out of the JS bundle the page loads. Measured live, it now stores `…/join-jane-street/position/{id}/` — 200, each job's own title on the page. | `f7733b7` |
| Walmart | `careers.walmart.com/results` | A dead link shipped the whole time and nobody clicked it | `/job/{job_id}` → 200 with a 1,606-char shell identical for every job; `careers.walmart.com` answers 200 for *every* path | **REFUSES CLEANLY** — the two-real-jobs proof rejects it, so no link is stored | `f7733b7` |
| Nintendo | `careers.nintendo.com/jobs/` | Tracked and healthy — with a **wrong link on every job** | Greenhouse *embed*. The board publishes `absolute_url = "https://careers.nintendo.com/?gh_jid=4295098009"`: distinct per job, link-shaped, HTTP 200 — and it serves the **listing page** to every one of them (64,408 B, job title absent). All identity is in the query string, which the SPA shell ignores. The working URL is `/jobs/{id}/` (82,962 B, its own title). | **FIXED** — a no-fetch guard rejects a published spec whose rendered path is `/`. Measured on the corpus: **10 of 10** publicly fetchable rung-1 boards unchanged (SpaceX, Figma, Roblox, Anthropic, Stripe, Palantir, Binance, Amazon, Atlassian, Microsoft); only Nintendo moves. | `34a1b5d`; e2e AC-20 |
| Kakao | `careers.kakao.com` | No link storable | Every path returns the same 60-char shell — nothing can be proved on it | **REFUSES CLEANLY** | `f7733b7` |
| Atlassian | `atlassian.com/company/careers/all-jobs` | *Suspected* dead link | Not a defect — `portalJobPost.portalUrl` is a real published iCIMS link. One consequence: its job pages render in an **iframe** and weigh 478,8xx chars each with no title, which is byte-for-byte the shape of a dead shell — so the "page carries its own title" check cannot be applied to it. | **NOT A BUG** | — |

## 9. The pasted page is not a job board

Two of the eleven boards in the triage batch, and the cheapest group to handle.

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Nintendo (search) | `careers.nintendo.com/job-search/` | "none of the 12 JSON request(s) … is a list of job postings" (the 12 are Sentry, Unleash, OneTrust, Qualtrics) | **The page is a 404.** `<title>404 - Nintendo Careers Site</title>`. There are no jobs on it. Refusing is right; the defect was the *sentence*, which blamed the board instead of naming the 404 and pointing at `careers.nintendo.com/jobs/`, which we already track. | **NOT A BUG** (refusal correct; message fixed) | `2878837`; e2e AC-21 spec |
| JPMorgan (programs) | `jpmorganchase.com/careers/explore-opportunities/programs` | "none of the 11 JSON request(s) … is a list of job postings" | **A marketing brochure.** `<h1>Programs</h1>`, **0** individual postings. Its biggest content API (`careers/programs.US.en.json`, 47,543 B) is 89 programme entries with no requisition id, no date, no apply URL — the pre-filter scored it `records=0`, correctly. The real board is the Oracle Fusion site in §3, linked from that very page via "Join our team". | **NOT A BUG** | `2878837`; e2e AC-21 spec |

## 10. Not the board at all — our plumbing, or already published

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Amazon, Microsoft | `amazon.jobs/en/search`, `jobs.careers.microsoft.com/global/en/search` | Both **hung at "Opening the page"** and never moved | Nothing to do with either board: **the Procrastinate worker had been dead for 14 hours.** `run_worker_async` defaults `install_signal_handlers=True`, which overwrote uvicorn's SIGTERM handler; one restart signal went to Procrastinate, which stopped its worker and returned *normally*. uvicorn kept the port, the replacement died on "address already in use", and the survivor ran with no worker. It served 200s the whole time. | **FIXED** — `install_signal_handlers=False`, a normal return from the worker is now an error + restart, and watched work gets its own lane | `9ad4f09` |
| Cisco | `careers.cisco.com/global/en/c/product-and-engineering-jobs` | "it finds Workday but it does not run a scrape after adding it" | ATS-resolved boards were left for the next 15-minute cron tick, so a just-added board showed 0 jobs | **FIXED** — measured on the owner's real Cisco board: **14 m 49 s → 24 s** from add to jobs landing | `853457f` |
| Duolingo | `careers.duolingo.com/jobs/8656959002` | Resolved to no ATS at all, on a board that is plain Greenhouse | The resolver's host allowlist covered `boards.greenhouse.io` and `job-boards.greenhouse.io` but **not `boards-api.greenhouse.io`** — which is what a SPA careers page on its own domain names. The reference was sitting in a plain 3 KB GET the whole time. A second bug fell out: the sniffer built candidate sub-paths by blind concatenation, producing `/jobs/8656959002/jobs` and `/jobs/jobs`. | **FIXED** | `324c4a6` |
| Amazon, Apple, TikTok | `amazon.jobs/en/search`, `jobs.apple.com/en-us/search`, `lifeattiktok.com/search` | Pasting them started a paid one-time discovery of a board this repo already scrapes | Not a failure — a missing short-circuit. These are first-party Python scrapers. | **NOT A BUG** — now `already_public` via the declared-careers-host rung. Creates nothing, enqueues nothing, spends nothing; terminal in the UI. | `de92159` |
| SpaceX, Databricks, Instacart | `spacex.com/careers/jobs/`, `databricks.com/company/careers/open-positions`, `instacart.careers/` | Same | Not a failure — all three are already published (Greenhouse). Matched by **company name in the domain**, the third and only *guessing* rung, so the answer is hedged and the user keeps an escape hatch. | **NOT A BUG** — `already_public`, `resolved_ats='name_guess'`. Guarded against directory hosts (`job-boards.greenhouse.io` names none of its tenants) and against `dropbox`≠`box`, `figma`≠`gm`. | `cac7db2`, `c09c1c4` |
| Speechify, Crusoe, Fluidstack | `job-boards.greenhouse.io/speechify?gh_src=…`, `jobs.ashbyhq.com/Crusoe`, `jobs.ashbyhq.com/fluidstack?ashby_jid=…` | Nothing — all three added first try through the ATS fast path, tracking query junk and all | — | **NOT A BUG** — useful controls | — |
| Crusoe (logo, not board) | `jobs.ashbyhq.com/Crusoe` | The board's declared favicon is **Ashby's "A"**, not Crusoe's mark | On all 15 vendor-hosted boards measured, `rel=icon` / `apple-touch-icon` / `/favicon.ico` is the **ATS vendor's** logo, byte-identical across tenants (proven by hash). The company's own mark lives in `og:image` — and on Ashby, in a JSON blob in the document. On company-hosted boards it is exactly inverted. | **OPEN** — logo-from-board is a proposal, not shipped | — (`LOGO-FROM-BOARD-POC.md`) |

## 11. The refusal named the wrong cause

Recovers zero boards, and still mattered more than most fixes: **four boards wore one identical
sentence for four unrelated reasons**, and sent two investigations down the wrong path.

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| JPMorgan (Oracle), Citadel, D. E. Shaw, Atlassian, Nintendo `/job-search/`, JPMorgan `/programs` | — | All shown "none of the N JSON request(s) this page made is a list of job postings" — for, respectively, a coverage-floor refusal, a Cloudflare wall, a model decline, a 10.6 s feed, a 404 and a brochure | Round two re-asks the model with **our own measured failure attached as feedback**, so its "no" is often an echo of that failure rather than a verdict on the bytes — and `discover.py:2842-2846` printed the filter-step sentence regardless, throwing away the `last_error`/`last_step` that were already being carried for exactly this. | **FIXED** — when something was measured, that is now the refusal. The old sentence survives only where it is literally true. | `2878837`; e2e AC-19 clause (a) |

## 12. Under investigation

| Board | URL | What went wrong | Root cause | Status | Fix / commit |
|---|---|---|---|---|---|
| Oracle | `careers.oracle.com/en/sites/jobsearch/jobs?location=United%20States&locationId=300000000149325` | Refused at synthesis: `page_limit_reached` — "would show **14 job(s)** and silently miss the rest" | unknown. Early measurement only: the Fusion REST path on Oracle's own host returns a 5,453-byte SPA shell, not JSON, so it is not exposed where JPMorgan's is. | **UNDER INVESTIGATION** | — |
| Bloomberg | `bloomberg.avature.net/careers/SearchJobs?…` | "none of the 8 JSON request(s) this page made is a list of job postings" — logged 2026-08-30 14:18 UTC, **after** the refusal-message fix, so that sentence is now literal: nothing was tried, the model saw no jobs in the captured requests | unknown | **UNDER INVESTIGATION** | — |

---

## Still unsolved

- **Citadel** — Cloudflare serves us an interstitial; the job anchors never reach us.
- **Meta** — visible now, but its GraphQL POST is form-urlencoded and cookie-bound; a bare replay 400s.
- **IBM** — visible now, but the board sends `size: 30` with no `from`, so it cannot be paged.
- **Goldman Sachs** — reads 20 of 1,074. Refused by three gates, so it never closes a job.
- **Oracle's own board** and **Bloomberg / Avature** — root cause not yet established.
- **D. E. Shaw** — two valid candidates, and the model declines them. Rate never measured.
- **Raindrop's own site** — refused before document candidates landed, never retried.
- **Uber** — anchor grouping is fixed and A/B-proven; the end-to-end add has not been re-run.
- **Sequoia** — technically fixable (carry the session cookie), but it is 255 companies' jobs under one name. A product decision, not a bug.
- **McKinsey** — succeeds, and publishes no posting date. Its trend line will be wrong.
- **Vendor-hosted logos** — the favicon is the ATS's mark on every vendor board measured.
