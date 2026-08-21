# Testable Boards — measured, not guessed

**Measured 2026-08-20. Re-measured and corrected 2026-08-21** — the first sweep ran with
a capture bug that lost boards. **Read [the correction](#correction--2026-08-21) before
trusting any refusal.** Every row was produced by calling
`api.services.capture.discover.discover()` for real — real headless Chromium, real Haiku
call, real acceptance replay. Nothing here is a guess. **Live boards drift** — a ✅ can
become a ❌ the week a company redesigns its careers page.

**70 URLs measured. 17 tracked · 43 refused · 10 never reached discovery (ATS fast path).**
The refusal tables below list **41** of those — Google and Bloomberg were each measured at
two different URLs and refused identically both times.

**No board landed `browser_fetch`.** See [The browser_fetch hunt](#the-browser_fetch-hunt).

---

## Correction — 2026-08-21

**The 2026-08-20 numbers were taken with a broken observation window.** Two of our own
limits, not the boards, produced refusals that read as "this board has no jobs feed":

| Ceiling | Was | Now | Board it cost us | Fixed in |
|---|---|---|---|---|
| **Observation window** | 6s + 2 × 1.2s = **8.4s** (and a failed `scrollBy` cut it to 6s) | 6s + 12 × 1.5s = **24s** | **Atlassian** — feed lands ~10.6s | `f97e915` |
| **Per-body cap** | **2 MB** | **4 MB** | **Binance** — feed is 2,775,685 B | this commit |

Both told the user the same lie: *"none of the N JSON request(s) this page made is a list
of job postings"*, about a page that made exactly that request.

**What was re-measured.** All **39** refusals that could still be a false negative — every
"no JSON request we could record" and every "none of them is a list of job postings" row —
plus 3 already-tracked boards as controls. Same method as the original sweep: `discover()`
called directly, `DiscoveryOutcome` inspected, **no database touched**, Browserbase off.

**Result: 2 of 39 previously-refused boards now TRACK.** Atlassian and Binance. The other
37 reproduced their original refusal, most of them to the exact JSON-request count.

**What this means for the rest of the doc.** The ✅ table and the refusal tables below are
the corrected 2026-08-21 numbers. The 15 boards that were already tracked were **not**
re-run in full — 3 were spot-checked and reproduced exactly (see
[the controls](#controls--the-longer-window-did-not-break-what-worked)).

---

## How to test

1. **Both flags must be on.** `CUSTOM_COMPANY_SOURCES_ENABLED=true` **and**
   `CUSTOM_COMPANY_DISCOVERY_ENABLED=true`. With only the parent flag on, a non-ATS URL
   returns the plain 422 "unsupported" — it looks like a bad board, not a dark feature.
2. **Don't test with an ATS link.** Greenhouse, Ashby, Lever, Gem, Workday and Eightfold
   URLs resolve on the free path and **never run discovery** — no checklist, no browser,
   instant add. The resolver also detects *embedded* ATS boards, so `jobs.nike.com` and
   `www.palantir.com/careers/` are ATS too. [Full list below](#dont-test-these--ats-fast-path).
3. **Discovery takes 27–75 s.** The checklist ticks through 4 steps. The floor is now the
   fixed **24 s** observation window, so nothing finishes fast any more; the slow ones are
   slow pages, not slow code. (Measured 2026-08-21: 27.3 s–45.9 s across 43 boards.)
4. **Job counts appear ~15 min later, not immediately.** The harvest is a Procrastinate
   periodic task on `*/15 * * * *`
   (`api/tasks/claim_custom_companies.py`). A freshly-added company shows its
   preview jobs right away and its real count after the next claim tick.

---

## ✅ Tracked — 17 boards

Paste the **URL** column verbatim. "Probe read" is what the acceptance replay actually
returned (capped at 2 pages); "nightly budget" is the stored ceiling the harvest sweeps to.

**🆕 = recovered by the [2026-08-21 correction](#correction--2026-08-21)** — refused before,
tracks now, and the board never changed.

| Board | URL | Transport | Oracle | Probe read | Nightly budget | Surprise |
|---|---|---|---|---|---|---|
| **SpaceX** | `https://www.spacex.com/careers/jobs/` | `http_json` | `none` | **2,188** | 1 request | Whole board in one static CDN file |
| **🆕 Atlassian** | `https://www.atlassian.com/company/careers/all-jobs` | `http_json` | `none` | **250** | 1 request | Feed lands **~10.6 s** in — invisible to the old 8.4 s window |
| **🆕 Binance** | `https://www.binance.com/en/careers/job-openings` | `http_json` | `none` | 81 | 1 request | Feed is **2.78 MB** — invisible to the old 2 MB body cap. **Tracks one department** |
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
→ **SpaceX** (2,188 — the biggest), **Atlassian** (250), **Jane Street** (233),
**Spotify** (87), **Rockstar** (68).

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

**Accepted but narrow — good bug bait.** All three pass every gate and still track a
sliver. Walmart's GraphQL response paginates in a way the selector did not spot; Kakao's
captured XHR carried the page's own `part=TECHNOLOGY&company=KAKAO` filter into the
stored recipe; **Binance's feed is 14 department groups and the selector bound
`records_path: "4.postings"` — Engineering only, 81 of 279 postings.** None is *wrong* —
they read exactly the list the browser saw — but none is the whole board.
→ **Walmart** (10 jobs), **Kakao** (8 jobs), **Binance** (81 of 279).

**Binance is the one to fix next.** It is the only board here whose whole board is
already in the captured body — the selector picked a sub-list of it. That is a selector
problem with the evidence sitting in the fixture, not a board we cannot read.

---

## Controls — the longer window did not break what worked

A longer window records **more** responses, which is the thing that could have pushed a
working board into a ceiling. It did not. Re-run 2026-08-21 against the 24 s window:

| Board | Probe read then | Probe read now | Responses recorded | Verdict |
|---|---|---|---|---|
| **SpaceX** | 2,188 | **2,187** | 5 | unchanged (board drifted by 1 job) |
| **Amazon** | 200 | **200** | 12–14 | unchanged, still `self_consistent`, still 100 × 100 |
| **TikTok** | 200 | **200** | 8 | unchanged, still `declared_probed`, still 43 × 100 |

Atlassian was run **3 times** and captured its feed **3/3**. Under the old window the same
board captured it on **1 run in 11**.

---

## The two ceilings — one was biting, one was not

The window fix pushes both of the child's recording limits closer to the edge, so both were
re-checked with the limits deliberately raised, then A/B'd on a single page load.

### 🔴 Per-body cap (2 MB) — **was biting, now fixed**

**Binance loses its board to it.** Its jobs feed is
`/bapi/career/jobs-lever/v0/postings/binance?group=department&mode=json` — a Lever export,
**2,775,685 bytes**, 39% over the old cap. Over the cap it is recorded with an **empty**
body and `truncated: true`, the pre-filter drops it with the tracking pings, and the user
is told the board has no jobs feed.

One page load, cap the only variable:

```
per-body cap = 2,000,000  → 40 recorded, 1 oversize, biggest kept body   158,881 B
                            REFUSE  "none of the 40 JSON request(s) … is a list of job postings"
per-body cap = 4,000,000  → 40 recorded, 0 oversize, biggest kept body 2,775,685 B
                            TRACK   http_json / oracle none / read 81 job(s)
```

Raised to **4 MB**. The aggregate cap (`_MAX_TOTAL_BODY_BYTES`, 16 MB) is **unchanged**, so
the worst case does not move — that is the number that protects the container and the pipe.
Locked by `test_the_per_body_cap_clears_the_biggest_real_jobs_feed`.

Biggest bodies measured across the sweep: **Binance 2.78 MB · Atlassian 1.85 MB ·
Ubisoft 1.26 MB · Dell 625 KB · SpaceX 489 KB**. Only the first two are jobs feeds.

**A second, smaller lie is still in place.** `discover()` only says "returned more data than
we can record" when the pre-filter is left with *nothing*. Binance had six other candidates,
so the oversize truth was swallowed and the generic "none of them is a list of job postings"
was shown instead. Not fixed here.

### 🟡 40-response cap — **at the ceiling, not biting**

**Binance is the only board that reaches it**, and it reaches it exactly: 40 recorded, 43
available with the limit raised. What the cap actually dropped:

```
40   21 B  /en/mfa-ui/version
41 2437 B  /bapi/fe/message/immed/web/register
42   42 B  /bapi/fe/message/immed/web/device/report
```

All junk, all after the feed. **Binance's jobs feed is response #8** — the analytics chatter
did not crowd it out. Next chattiest: **IBM 31 · Dell 28 · Atlassian 19 · Marriott 19**.

**Left at 40 on purpose.** No board has been measured losing a feed to it, and the
first-come-first-served risk is real but hypothetical. Worth knowing: the child reports
`responses_total = len(captured)`, so a capped capture is only visible as "exactly 40" —
there is **no dropped count**. If this cap ever does bite, that missing number is what will
make it hard to see.

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

**Re-measured 2026-08-21 against the 24 s window and the 4 MB body cap**, except where a
row says otherwise. The "JSON requests" counts are the fresh ones; where the longer window
recorded more than the 2026-08-20 sweep saw, the old number is shown struck through. **A
higher count with the same refusal is the useful signal** — we watched the page three times
longer, saw more of it, and it still has no jobs feed.

### 1. Nothing to capture (12 boards)

> `finding the jobs feed: this page loaded its jobs without any JSON request we could record — it renders them on the server or blocks automated browsers`

Zero JSON XHRs recorded — **still zero after 24 s of watching and scrolling**, on all 9
re-measured. This is the one refusal class the window bug could not have caused, and the
re-measurement confirms it: a page that makes no JSON request in 8.4 s makes none in 24 s
either. Two different underlying causes, both ending here:

| Board | URL | What actually happened |
|---|---|---|
| **Tesla** | `https://www.tesla.com/careers/search/` | Page title came back **"Access Denied"** — bot wall. *Not re-measured* |
| **Salesforce** | `https://careers.salesforce.com/en/jobs/` | Redirects to `www.salesforce.com/…`, title **"Access Denied"** — bot wall. *Not re-measured* |
| **Starbucks** | `https://www.starbucks.com/careers/find-a-job/` | Title **"Server Error"** — bot wall. *Not re-measured* |
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
| **JD.com** | `https://campus.jd.com/` | ~~12~~ **14** |
| **Epic Games** | `https://www.epicgames.com/site/en-US/careers/vacancies` | 8 |
| **Home Depot** | `https://careers.homedepot.com/job-search-results/` | 2 |
| **Two Sigma** | `https://careers.twosigma.com/careers/Home` | 1 |
| **Shopify** | `https://www.shopify.com/careers` | 1 |
| **EY** | `https://careers.ey.com/ey/search/` | 1 |
| **Bosch** | `https://careers.smartrecruiters.com/BoschGroup` | 1 (redirects to `jobs.bosch.com`) |

### 3. The model looked and said none of them is jobs (16 boards)

> `finding the jobs feed: none of the N JSON request(s) this page made is a list of job postings`

Note the one-word difference from group 2 — **"is"** means a Haiku call ran and returned
`NoJobsFeedError`; **"returned"** means the pre-filter refused first. Same next action
for the user, different amount of money spent.

**Two boards left this table on 2026-08-21** — Atlassian (window) and Binance (body cap).
Both are in [the ✅ table](#-tracked--17-boards) now, and neither board changed.

| Board | URL | JSON requests |
|---|---|---|
| **IBM** | `https://www.ibm.com/careers/search` | ~~30~~ **31** |
| **Dell** | `https://jobs.dell.com/search-jobs` | ~~24~~ **28** (resolves to `enterpriseplatform.dell.com`) |
| **Marriott** | `https://careers.marriott.com/` | 19 |
| **Disney** | `https://www.disneycareers.com/en/search-jobs` | 12 |
| **Nintendo** | `https://careers.nintendo.com/job-search/` | 12 (page title is **"404"**) |
| **JPMorgan** | `https://careers.jpmorgan.com/us/en/students/programs` | 11 (resolves to `jpmorganchase.com`) |
| **Oracle** | `https://careers.oracle.com/jobs/` | 9 |
| **Ubisoft** | `https://www.ubisoft.com/en-us/company/careers/search` | 8 — burns **both** selection rounds and still refuses; reached and failed the `browser_fetch` tier, see above |
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
mechanism rather than anything the user can act on. **Reproduced identically on
2026-08-21** — it never reaches the observation window, so neither fix could have helped.

**Huawei** — `https://career.huawei.com/reccampportal/portal5/social-recruitment.html`

> `checking the careers URL: blocked by our safety check (dns_resolution_failed): could not resolve 'career.huawei.com': [Errno 8] nodename nor servname provided, or not known`

**Not a board property** — my machine could not resolve the host. Unmeasured, not failed.
Still unmeasured on 2026-08-21.

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
added through the UI. The 2026-08-21 re-measurement used the same script with an injected
`capture` seam that only *records* the response count and body sizes — the ceiling
telemetry in [The two ceilings](#the-two-ceilings--one-was-biting-one-was-not).

**Environment.** Repo's own headless Chromium, **Browserbase off**, residential US IP,
2026-08-20 and 2026-08-21. Real `ANTHROPIC_API_KEY` from `.env.local`; one Haiku call per
selection round.

**Honest gaps:**

- **The 15 originally-tracked boards were not all re-run.** Three were
  ([the controls](#controls--the-longer-window-did-not-break-what-worked)); the other
  twelve carry their 2026-08-20 numbers. A longer window can only add responses, and none
  of the three controls moved, so the risk is low — but it is not zero and it is not
  measured.
- **The three bot walls were not re-measured** (Tesla, Salesforce, Starbucks). They failed
  on the page *title* — "Access Denied" / "Server Error" — which is upstream of anything
  the window or the body cap does.

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
- **Carried-forward rows were re-verified on 2026-08-20, not trusted:** Amazon, TikTok,
  Spotify, Jane Street and Meta all reproduced their prior results exactly.
- **One refusal string is still not the truth.** A board whose feed is over the body cap is
  only *told* so when nothing else survives the pre-filter; with any other candidate
  present it gets the generic "none of them is a list of job postings". That is how Binance
  hid for a day.
