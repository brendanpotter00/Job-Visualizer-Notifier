# Testable Boards — measured, not guessed

**Measured 2026-08-20.** Every row below was produced by calling
`api.services.capture.discover.discover()` for real — real headless Chromium, real Haiku
call, real acceptance replay. Nothing here is a guess. **Live boards drift** — a ✅ can
become a ❌ the week a company redesigns its careers page.

**70 URLs measured. 15 tracked · 45 refused · 10 never reached discovery (ATS fast path).**
The refusal tables below list **43** of those — Google and Bloomberg were each measured at
two different URLs and refused identically both times.

**No board landed `browser_fetch`.** See [The browser_fetch hunt](#the-browser_fetch-hunt).

---

## How to test

1. **Both flags must be on.** `CUSTOM_COMPANY_SOURCES_ENABLED=true` **and**
   `CUSTOM_COMPANY_DISCOVERY_ENABLED=true`. With only the parent flag on, a non-ATS URL
   returns the plain 422 "unsupported" — it looks like a bad board, not a dark feature.
2. **Don't test with an ATS link.** Greenhouse, Ashby, Lever, Gem, Workday and Eightfold
   URLs resolve on the free path and **never run discovery** — no checklist, no browser,
   instant add. The resolver also detects *embedded* ATS boards, so `jobs.nike.com` and
   `www.palantir.com/careers/` are ATS too. [Full list below](#dont-test-these--ats-fast-path).
3. **Discovery takes 10–75 s.** The checklist ticks through 4 steps. Most boards land in
   ~15 s; the slow ones are slow pages, not slow code.
4. **Job counts appear ~15 min later, not immediately.** The harvest is a Procrastinate
   periodic task on `*/15 * * * *`
   (`api/tasks/claim_custom_companies.py`). A freshly-added company shows its
   preview jobs right away and its real count after the next claim tick.

---

## ✅ Tracked — 15 boards

Paste the **URL** column verbatim. "Probe read" is what the acceptance replay actually
returned (capped at 2 pages); "nightly budget" is the stored ceiling the harvest sweeps to.

| Board | URL | Transport | Oracle | Probe read | Nightly budget | Surprise |
|---|---|---|---|---|---|---|
| **SpaceX** | `https://www.spacex.com/careers/jobs/` | `http_json` | `none` | **2,188** | 1 request | Whole board in one static CDN file |
| **Jane Street** | `https://www.janestreet.com/join-jane-street/open-roles/` | `http_json` | `none` | 233 | 1 request | — |
| **Spotify** | `https://www.lifeatspotify.com/jobs` | `http_json` | `none` | 87 | 1 request | — |
| **Rockstar Games** | `https://www.rockstargames.com/careers/openings` | `http_json` | `none` | 68 | 1 request | Persisted GraphQL query replays fine |
| **Amazon** | `https://www.amazon.jobs/en/search` | `http_json` | `self_consistent` | 200 | 100 × 100, **window cap 10,000** | Its own `hits: 10000` is distrusted — facets say 22k |
| **TikTok** | `https://lifeattiktok.com/search` | `http_json` | `declared_probed` | 200 | 43 × 100 (~4,300) | — |
| **Shopee** | `https://careers.shopee.com/jobs` | `http_json` | `declared_probed` | 200 | 29 × 100 (~2,900) | Redirects to `careers.shopee.sg`; feed is `ats.workatsea.com` |
| **Tencent** | `https://careers.tencent.com/en-us/search.html` | `http_json` | `declared_probed` | 200 | 25 × 100 (~2,500) | — |
| **ByteDance** | `https://jobs.bytedance.com/en/position` | `http_json` | `declared_probed` | 200 | 16 × 100 (~1,600) | Resolver rewrites to `joinbytedance.com/search` first |
| **Goldman Sachs** | `https://higher.gs.com/roles` | `http_json` | `declared_probed` | 20 | 58 × 20 (~1,160) | GraphQL POST |
| **Didi** | `https://talent.didiglobal.com/social` | `http_json` | `declared_probed` | 32 | 68 × 16 (~1,088) | Chinese-language titles |
| **Microsoft** | `https://jobs.careers.microsoft.com/global/en/search` | `http_json` | `declared_probed` | 20 | 100 × 10 → **hard-capped at 1,000** | Resolves to a different host, `apply.careers.microsoft.com` |
| **Meituan** | `https://zhaopin.meituan.com/web/position` | `http_json` | `declared_probed` | 10 | 100 × 10 → **hard-capped at 1,000** | Chinese-language titles |
| **Kakao** | `https://careers.kakao.com/jobs` | `http_json` | `declared_probed` | 8 | 1 page only | Captured request is **pre-filtered** to `part=TECHNOLOGY` |
| **Walmart** | `https://careers.walmart.com/results` | `http_json` | `none` | 10 | 1 page only | **Tracks 10 jobs** on a board with tens of thousands |

### What each group demonstrates

**Whole board in one request** — `oracle: none`, no pagination step, permanently
`UNVERIFIED` by design (shows every job, closes nothing).
→ **SpaceX** (2,188 — the biggest), **Jane Street** (233), **Spotify** (87), **Rockstar** (68).

**Paginated with a trusted total** — `oracle: declared_probed`, page size raised to 100
and *proven* against the board. The clean demo of the whole capture idea.
→ **TikTok, Shopee, Tencent, ByteDance**.

**Big and window-capped** — the Amazon case the code is built around: the board's own
`hits: 10000` is contradicted by its facets, so it is stored as a `window_cap`, not an
oracle, and the harvest can never confidently wrong-close.
→ **Amazon**.

**Page size the board would not raise** — no identifiable page-size parameter, so the
recipe pages 10 at a time and hits the 100-page ceiling at 1,000 jobs. Both have
`declared_probed` oracles, so if the real board is bigger than 1,000 they will sit at
`UNVERIFIED` forever. Correct, just partial.
→ **Microsoft, Meituan**.

**Accepted but narrow — good bug bait.** Both pass every gate and still track a sliver:
Walmart's GraphQL response paginates in a way the selector did not spot, and Kakao's
captured XHR carried the page's own `part=TECHNOLOGY&company=KAKAO` filter into the
stored recipe. Neither is *wrong* — they read exactly the list the browser saw — but
neither is the whole board.
→ **Walmart** (10 jobs), **Kakao** (8 jobs).

---

## The browser_fetch hunt

**Result: no board in this sweep needed tier 1b.** Every one of the 15 accepted boards
replayed cleanly over plain `httpx` on the first try.

**Ubisoft** (`https://www.ubisoft.com/en-us/company/careers/search`) is the only board
that reached the `browser_fetch` tier at all — and it failed there too. Its Algolia feed
rejected the synthesized pagination parameter identically over both transports:

```
http_json    → RecipeExecutionError: HTTP 400 … {"message":"invalid key 'page'. Expected: requests, apiKey, …"}
browser_fetch → RecipeExecutionError: HTTP 400 from the in-browser fetch on page 0 … (same body)
```

It then burned its second selection round and refused at the feed step. So the ladder
*works* — it tries 1a, falls through to 1b, and refuses honestly — but **tier 1b is still
unproven against a live board that only it can read.**

Boards I expected to force it and which did not: ByteDance, Shein, Alibaba, Binance,
Tencent, Meituan, Didi, Baidu, NetEase, JD, Xiaomi, Naver, Kakao. The origin-checked
Chinese/Korean family either replays fine over plain HTTP (Tencent, ByteDance, Meituan,
Didi, Kakao) or never exposes a JSON jobs feed at all (Baidu, Alibaba, Xiaomi, Naver).

**Caveat that matters here:** this was measured from a residential US IP. Production
replays from Railway. A board that gates on datacenter IP or geo would pass here and
fail — or land `browser_fetch` — there.

---

## ❌ Refused — with the exact text the UI shows

Every string below is the literal `refuse_reason` the owner will see.

### 1. Nothing to capture (12 boards)

> `finding the jobs feed: this page loaded its jobs without any JSON request we could record — it renders them on the server or blocks automated browsers`

Zero JSON XHRs recorded. Two different underlying causes, both ending here:

| Board | URL | What actually happened |
|---|---|---|
| **Tesla** | `https://www.tesla.com/careers/search/` | Page title came back **"Access Denied"** — bot wall |
| **Salesforce** | `https://careers.salesforce.com/en/jobs/` | Redirects to `www.salesforce.com/…`, title **"Access Denied"** — bot wall |
| **Starbucks** | `https://www.starbucks.com/careers/find-a-job/` | Title **"Server Error"** — bot wall |
| **Meta** | `https://www.metacareers.com/jobs` | Renders server-side (confirms the earlier finding) |
| **Uber** | `https://www.uber.com/us/en/careers/list/` | Resolves to `jobs.uber.com/en/jobs/`, **0 JSON** — the *correct* Uber URL fails the same way the pasted `jobs.uber.com` did |
| **Airbnb** | `https://careers.airbnb.com/positions/` | Server-rendered WordPress archive |
| **Pinterest** | `https://www.pinterestcareers.com/jobs/` | Server-rendered |
| **Naver** | `https://recruit.navercorp.com/rcrt/list.do` | Server-rendered |
| **Xiaomi** | `https://hr.xiaomi.com/social` | Interstitial page, no feed |
| **Baidu** | `https://talent.baidu.com/jobs/social-list` | Ended on `about:blank` — navigation never completed |
| **Alibaba** | `https://talent.alibaba.com/off-campus-position` | Blank title, no feed |
| **D. E. Shaw** | `https://www.deshaw.com/careers/choose-your-path` | Redirects to `/careers/benefits`, server-rendered |

### 2. Requests recorded, none job-shaped (11 boards)

> `finding the jobs feed: none of the N JSON request(s) this page made returned a list of job postings`

The **deterministic pre-filter** dropped everything before the model was ever asked. No
LLM call was spent (`attempts: 0`).

| Board | URL | JSON requests |
|---|---|---|
| **Google** | `https://careers.google.com/jobs/results/` | 3 |
| **Stripe** | `https://stripe.com/jobs/search` | 3 |
| **Y Combinator (Work at a Startup)** | `https://www.workatastartup.com/jobs` | 3 |
| **NetEase** | `https://hr.163.com/job-list.html` | 5 |
| **JD.com** | `https://campus.jd.com/` | 12 |
| **Epic Games** | `https://www.epicgames.com/site/en-US/careers/vacancies` | 8 |
| **Home Depot** | `https://careers.homedepot.com/job-search-results/` | 2 |
| **Two Sigma** | `https://careers.twosigma.com/careers/Home` | 1 |
| **Shopify** | `https://www.shopify.com/careers` | 1 |
| **EY** | `https://careers.ey.com/ey/search/` | 1 |
| **Bosch** | `https://careers.smartrecruiters.com/BoschGroup` | 1 (redirects to `jobs.bosch.com`) |

### 3. The model looked and said none of them is jobs (18 boards)

> `finding the jobs feed: none of the N JSON request(s) this page made is a list of job postings`

Note the one-word difference from group 2 — **"is"** means a Haiku call ran and returned
`NoJobsFeedError`; **"returned"** means the pre-filter refused first. Same next action
for the user, different amount of money spent.

| Board | URL | JSON requests |
|---|---|---|
| **Binance** | `https://www.binance.com/en/careers/job-openings` | 40 (1 oversize) |
| **IBM** | `https://www.ibm.com/careers/search` | 30 |
| **Dell** | `https://jobs.dell.com/search-jobs` | 24 (resolves to `enterpriseplatform.dell.com`) |
| **Marriott** | `https://careers.marriott.com/` | 19 |
| **Atlassian** | `https://www.atlassian.com/company/careers/all-jobs` | 14 — **the correct careers URL still refuses**, so this is not the root-domain paste problem |
| **Disney** | `https://www.disneycareers.com/en/search-jobs` | 12 |
| **Nintendo** | `https://careers.nintendo.com/job-search/` | 12 (page title is **"404"**) |
| **JPMorgan** | `https://careers.jpmorgan.com/us/en/students/programs` | 11 (resolves to `jpmorganchase.com`) |
| **Oracle** | `https://careers.oracle.com/jobs/` | 9 |
| **Ubisoft** | `https://www.ubisoft.com/en-us/company/careers/search` | 8 — reached and failed the `browser_fetch` tier, see above |
| **Bloomberg** | `https://careers.bloomberg.com/job/search` | 7 — resolver drags it to `bloomberg.com/company/what-we-do/` |
| **Citadel** | `https://www.citadel.com/careers/open-opportunities/` | 5 |
| **GM** | `https://search-careers.gm.com/en/jobs/` | 5 |
| **Siemens** | `https://jobs.siemens.com/careers` | 4 |
| **Zalando** | `https://jobs.zalando.com/en/jobs` | 3 |
| **Shein** | `https://careers.shein.com/` | 2 |
| **Riot Games** | `https://www.riotgames.com/en/work-with-us/jobs` | 2 |
| **Apple** | `https://jobs.apple.com/en-us/search` | 1 |

### 4. The page never opened (2 boards)

**McKinsey** — `https://www.mckinsey.com/careers/search-jobs`

> `opening the careers page: capture subprocess failed (rc=1): host-pin: FAULT on https://www.mckinsey.com/careers/search-jobs: TimeoutError('Route.fetch: Timeout 30000ms exceeded. …`

The host-pin route handler timed out fetching the document itself. Fails closed, as
designed — but the message is the ugliest one in the set, and it names an internal
mechanism rather than anything the user can act on.

**Huawei** — `https://career.huawei.com/reccampportal/portal5/social-recruitment.html`

> `checking the careers URL: blocked by our safety check (dns_resolution_failed): could not resolve 'career.huawei.com': [Errno 8] nodename nor servname provided, or not known`

**Not a board property** — my machine could not resolve the host. Unmeasured, not failed.

### 5. A refusal you will only see if the resolver is bypassed

> `opening the careers page: capture subprocess failed (rc=1): host-pin: aborted redirect <url> -> <other-host>`

The capture browser pins navigation to the **entry URL's own host** and aborts any
cross-host redirect. I hit this on Cisco, Salesforce and ByteDance when I called
`discover()` directly. **The real add flow does not hit it** — `discover_ats` follows and
re-validates every redirect first and hands discovery the *final* URL. Worth knowing
because it makes direct-`discover()` measurements disagree with the UI.

---

## Don't test these — ATS fast path

These resolve to a supported ATS and add instantly with **no discovery, no checklist**.
Testing the capture feature with one of them proves nothing.

| Pasted URL | Resolves to | How |
|---|---|---|
| `https://jobs.intel.com` | `workday` / `intel` | redirect |
| `https://jobs.cisco.com/jobs/SearchJobs/` | `workday` / `cisco` | embedded |
| `https://careers.adobe.com/us/en/search-results` | `workday` / `adobe` | embedded |
| `https://jobs.nike.com/` | `workday` / `nike` | embedded |
| `https://www.samsung.com/us/careers/` | `workday` / `sec` | embedded |
| `https://www.accenture.com/us-en/careers/jobsearch` | `workday` / `accenture` | embedded |
| `https://jobs.target.com/search-jobs` | `workday` / `target` | embedded |
| `https://www.palantir.com/careers/` | `lever` / `palantir` | embedded |
| `https://x.ai/careers` | `greenhouse` / `xai` | embedded |
| `https://www.hudsonrivertrading.com/careers/` | `greenhouse` / `hrttalentcommunity` | embedded |

---

## How this was measured, and what it doesn't cover

**Method.** A throwaway script called `discover_ats()` (the same L0→L1→L2 ladder
`POST /api/users/companies/resolve` runs) and then `discover()` on its `final_url`,
inspecting the returned `DiscoveryOutcome`. **No database was touched** and nothing was
added through the UI.

**Environment.** Repo's own headless Chromium, **Browserbase off**, residential US IP,
2026-08-20. Real `ANTHROPIC_API_KEY` from `.env.local`; one Haiku call per selection
round.

**Honest gaps:**

- **Prod replays from Railway, this measured from a laptop.** IP- or geo-gated boards
  could behave differently there — in either direction.
- **"Probe read" is not the board size.** Acceptance clamps to 2 pages
  (`_ACCEPTANCE_MAX_PAGES`). The nightly harvest reads to the budget column.
- **Nightly budget is a ceiling, not a promise.** The sweep stops on the first short
  page; the `~N` totals are `(max_pages − headroom) × page_size` and are indicative only.
- **Huawei could not be measured** (DNS failure on my machine).
- **Google, Apple and Microsoft are already scraped first-party** by this repo's Python
  scrapers. They are listed as controls, not as things to onboard.
- **Nothing here was harvested end-to-end.** Discovery acceptance was measured; the
  15-minute claim tick, the upsert and the completeness gate were not.
- **Carried-forward rows were re-verified today, not trusted:** Amazon, TikTok, Spotify,
  Jane Street and Meta all reproduced their prior results exactly.
