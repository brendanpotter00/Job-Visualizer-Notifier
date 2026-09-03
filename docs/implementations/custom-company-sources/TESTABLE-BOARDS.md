# Testable Boards — measured, not guessed

**Measured 2026-08-20. Re-measured and corrected 2026-08-21 and 2026-08-22.** The
2026-08-21 sweep ran with a capture bug that lost boards
([correction](#correction--2026-08-21)); the 2026-08-22 pass fixed the three boards that
were *accepted while reading a sliver*
([correction](#correction--2026-08-22--the-sliver-reads)). **Read both before trusting a
row.** Every row was produced by calling
`api.services.capture.discover.discover()` for real — real headless Chromium, real Haiku
call, real acceptance replay. Nothing here is a guess. **Live boards drift** — a ✅ can
become a ❌ the week a company redesigns its careers page.

**70 URLs measured. 17 tracked · 43 refused · 10 never reached discovery (ATS fast path).**
The refusal tables below list **41** of those — Google and Bloomberg were each measured at
two different URLs and refused identically both times.

**No board landed `browser_fetch`.** See [The browser_fetch hunt](#the-browser_fetch-hunt).

---

## Correction — 2026-08-22 — the sliver reads

**Three boards were stored as "Successfully tracking" while reading a sliver.** All three
passed every gate — the recipe replayed, the ids matched the capture, the completeness
oracle was honest, and none of them can ever close a job. What was wrong was only what we
*said* about them: the same green chip and the same "read N jobs" tick as a board we had
read completely.

| Board | Was | Now | Root cause |
|---|---|---|---|
| **Binance** | 81 of 276 | **250**, `records_path: '*.postings'` | The response is 14 department groups and every concrete path into it is ONE department. The whole board was in bytes we had already downloaded |
| **Kakao** | 8, green | **8, amber "Tracking part of this board"** | The page fires its own `part=TECHNOLOGY` default tab. The board is 31 and says so in the same response (`jobTypeCountDtoList` sums to 31 beside `totalJobCount: 8`) |
| **Walmart** | 10, green | **10, amber "Tracking part of this board"** | The captured feed is a chat-assistant GraphQL endpoint (`jobSearchAssistant`) that serves 10 jobs a page and publishes `total_jobs: 47298` in the same body |

**How a page-imposed narrowing is told apart from a user-chosen one.** By reading the
CAPTURED BYTES, never by inspecting the URL. A board narrowed by a filter the user asked
for publishes counts that agree with what came back; a board narrowed by its own page
publishes counts that contradict it. So the rule *"a stored recipe inherits the capture's
filter scope"* is unchanged — nothing drops a query parameter, nothing rewrites a URL —
and the new check only compares **what the stored recipe can reach at its full nightly
budget** against **what the response proves is there**. Three signals, all from the
capture: a grouped payload's union, the board's own total in the object holding the
records, and a `{label, count}` facet block's sum.

### What a partial read looks like now

* the discovery outcome is `partial`, not `tracking`;
* the row's chip is amber **"Tracking part of this board"**, not green "Successfully
  tracking";
* the checklist stays on the row **for good** (every other tracked board drops it after
  the first harvest) and carries the board's own numbers — *"read 8 job(s), but this
  board's own category counts add up to 31 — we can only track part of this board"*.

**Nothing about harvesting changed.** The oracle, `run_gate` and `verify_harvest` are
untouched: Kakao is still `declared_probed` (8 of 8 is still exact for the scope it
reads), Walmart and Binance still `oracle: none` → UNVERIFIED forever → they show every
job they can see and close none. Coverage is an honesty signal, not a safety one.

### `records_path` may now carry one `*`

`*.postings` is the union of every group's array (`recipe_schema.dig_records`). At most
one wildcard, never trailing — rejected by the validator on write **and** on every
nightly read, like every other unrunnable recipe. `discover` also widens a single-group
path to the union **deterministically**, after the model answers, and only when the union
maps to strictly more usable job rows through the same field map: the prompt now names
the `*` path, but a prompt is a request and this is the guarantee.

### Amazon is now labelled partial, and that is correct

`10,000` reachable (its Elasticsearch window) against the `22,492` its own facets agree
on. Its recipe, budget, oracle and probe read are **byte-identical** to before — only the
label moved, from a green chip that claimed the whole board to an amber one that does
not.

### Measured, before and after, on the same captures

Real `discover()`, real Haiku, real acceptance replays; captures taken 2026-08-22 with
**Browserbase off** (local Chromium, $0) and replayed from disk so before/after saw the
same bytes. No database touched.

| Board | Probe read before | Probe read after | Outcome before → after |
|---|---|---|---|
| **Binance** | 81 | **250** | `tracking` → `tracking` (whole board) |
| **Kakao** | 8 | 8 | `tracking` → **`partial`** |
| **Walmart** | 10 | 10 | `tracking` → **`partial`** |
| SpaceX | 2,198 | 2,198 | unchanged |
| Amazon | 200 (100 × 100, cap 10,000) | 200 (100 × 100, cap 10,000) | `tracking` → **`partial`** |
| TikTok | 200 (43 × 100) | 200 (43 × 100) | unchanged |
| Jane Street | 233 | 233 | unchanged |
| Spotify | 88 | 88 | unchanged |

### Still not fixed, and now visible

* **Binance loses 26 of its 276 postings to a bad field map.** The model answered
  `title: 'opening'` — Lever's *description* blob — where the title is `text`. 26 postings
  have an empty `opening`, so `map_records` drops them, and the 250 that survive carry a
  page of HTML as their job title. A field-map quality bug, not a scope one, and the
  widening is what made it big enough to see.
* **Walmart cannot be read completely and probably never will be.** 47,298 jobs at 10 a
  page is 4,730 requests against a 100-page ceiling, its page parameter is buried four
  levels down a POST body the recipe vocabulary cannot address, and the endpoint is a
  chat thread with a per-page-load `thread_id`. The honest answer is the amber chip.
* **Kakao's whole board needs an invented parameter value.** Dropping `part=TECHNOLOGY`
  and `company=KAKAO` changes nothing (the API defaults to TECHNOLOGY server-side); only
  `company=ALL` returns all 31, across 3 pages. Guessing a value we never observed is the
  scope change this feature deliberately does not attempt.

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
| **🆕 Binance** | `https://www.binance.com/en/careers/job-openings` | `http_json` | `none` | **250** | 1 request | Feed is **2.78 MB** — invisible to the old 2 MB body cap. 14 department groups read as one via `records_path: '*.postings'` ([2026-08-22](#correction--2026-08-22--the-sliver-reads)) |
| **Jane Street** | `https://www.janestreet.com/join-jane-street/open-roles/` | `http_json` | `none` | 233 | 1 request | — |
| **Spotify** | `https://www.lifeatspotify.com/jobs` | `http_json` | `none` | 87 | 1 request | — |
| **Rockstar Games** | `https://www.rockstargames.com/careers/openings` | `http_json` | `none` | 68 | 1 request | Persisted GraphQL query replays fine |
| **Amazon** | `https://www.amazon.jobs/en/search` | `http_json` | `self_consistent` | 200 | 100 × 100, **window cap 10,000** | Its own `hits: 10000` is distrusted — facets say 22k. **⚠️ partial** (10,000 of 22,492) |
| **TikTok** | `https://lifeattiktok.com/search` | `http_json` | `declared_probed` | 200 | 43 × 100 (~4,300) | — |
| **Shopee** | `https://careers.shopee.com/jobs` | `http_json` | `declared_probed` | 200 | 29 × 100 (~2,900) | Redirects to `careers.shopee.sg`; feed is `ats.workatsea.com` |
| **Tencent** | `https://careers.tencent.com/en-us/search.html` | `http_json` | `declared_probed` | 200 | 25 × 100 (~2,500) | — |
| **ByteDance** | `https://jobs.bytedance.com/en/position` | `http_json` | `declared_probed` | 200 | 16 × 100 (~1,600) | Resolver rewrites to `joinbytedance.com/search` first |
| **Goldman Sachs** | `https://higher.gs.com/roles` | `http_json` | `declared_probed` | 20 | 58 × 20 (~1,160) | GraphQL POST |
| **Didi** | `https://talent.didiglobal.com/social` | `http_json` | `declared_probed` | 32 | 68 × 16 (~1,088) | Chinese-language titles |
| **Microsoft** | `https://jobs.careers.microsoft.com/global/en/search` | `http_json` | `declared_probed` | 20 | 100 × 10 → **hard-capped at 1,000** | Resolves to a different host, `apply.careers.microsoft.com` |
| **Meituan** | `https://zhaopin.meituan.com/web/position` | `http_json` | `declared_probed` | 10 | 100 × 10 → **hard-capped at 1,000** | Chinese-language titles |
| **Kakao** | `https://careers.kakao.com/jobs` | `http_json` | `declared_probed` | 8 | 1 page only | Captured request is **pre-filtered** to `part=TECHNOLOGY`. **⚠️ partial** (8 of 31) |
| **Walmart** | `https://careers.walmart.com/results` | `http_json` | `none` | 10 | 1 page only | Chat-assistant GraphQL, 10 a page. **⚠️ partial** (10 of 47,298) |

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

**Accepted but narrow — ⚠️ `partial`.** These read a real slice of the company's jobs and
nothing more, and since [2026-08-22](#correction--2026-08-22--the-sliver-reads) they say
so: amber chip, and a checklist that stays on the row carrying the board's own numbers.
Binance left this group — its whole board was already in the captured body and
`records_path: '*.postings'` now reads all of it.
→ **Walmart** (10 of 47,298), **Kakao** (8 of 31), **Amazon** (10,000 of 22,492).

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

---

## Candidate boards — proposed, not yet run through `discover()`

**Added 2026-08-30.** Everything below this line is a *candidate list*, not a measurement.
Nothing here was run through `discover()` — no Chromium, no Haiku call, no acceptance
replay. What was done instead, for every URL: fetched it with `curl`/`httpx` (or, where the
page is a client-rendered SPA, loaded it in a real browser and read the actual network
requests) and confirmed it returns 200 and is a real job listing, not a marketing page or a
redirect to one; grepped the page and its script bundles for `boards.greenhouse.io`,
`myworkdayjobs`, `ashbyhq`, `icims`, `smartrecruiters`, `jobvite`, `lever`, `phenom`,
`eightfold`, `workable`, `successfactors` and a few more; and checked `/robots.txt` and
`/sitemap.xml` for a job-specific sitemap. **A board not verified this way is not listed.**
Companies already excluded per the brief (already published, already listed above, or
already an ATS-fast-path control in this doc): Amazon, Apple, Google, Microsoft, TikTok,
Netflix, Spotify, Cisco, Atlassian, Jane Street, Goldman Sachs, Walmart, Y Combinator,
Raindrop, Palantir, Hudson River Trading.

**17 boards, grouped by technical shape, not by company fame.** The interesting axis is how
each board serves its jobs.

### Shape 1 — Custom board, no vendor ATS

| Company | URL | Jobs | Sitemap | Why it's interesting |
|---|---|---|---|---|
| **Roblox** | `https://careers.roblox.com/jobs` | 234 | **Yes** — 235 individual `/jobs/{id}` URLs in `sitemap.xml`, matching the JSON almost 1:1 | A second SpaceX: the whole board is one static file, `https://d32kbl9jppd7az.cloudfront.net/careers/jobs.json`, no vendor markers anywhere. But the fetch **failed** (`net::ERR_FAILED`) inside a real browser tab while plain `curl` succeeded — a CORS/referrer quirk our own headless Chromium capture could plausibly hit too |
| **Grab** | `https://www.grab.careers/jobs/` | 400 (declared inline: *"Displaying 1 to 20 of 400 matching jobs"*) | **Yes** — 402 `/en/jobs/{id}/...` URLs in `sitemap.xml` | Fully server-rendered (zero XHRs fire — confirmed job titles are present in plain `curl` output with no JS), so this is YC's shape on a fresh company, but it *also* declares its own total inline and *also* has a job sitemap — three signals at once on one board |
| **Toss** | `https://toss.im/career/jobs` | 352 (`count` field) | **Yes**, but disagrees — `https://toss.im/career/sitemap.xml` lists **439** `job_id=` URLs, 87 more than the API's own declared count | Custom REST API (`api-public.toss.im/api-public/v3/ipd-thor/api/v1/workspaces/13/posts?page=1`) with `next`/`previous` cursor links and an internal codename leaking through the URL path. `robots.txt` separately disallows a `gh_jid=...` URL, implying a legacy/parallel Greenhouse board exists too. The sitemap-vs-API mismatch is a live version of the exact completeness problem the [2026-08-22 correction](#correction--2026-08-22--the-sliver-reads) is about, on a board we haven't touched |

### Shape 2 — Custom front end over vendor ATS

| Company | URL | Behind it | Jobs | Sitemap | Why it's interesting |
|---|---|---|---|---|---|
| **Robinhood** | `https://careers.robinhood.com/` | Greenhouse, called directly: `api.greenhouse.io/v1/boards/{robinhood,sherwoodmedia}/jobs` | 51 | No | Client JS calls Greenhouse's raw API (not the embed widget) for **two** boards and merges them on one page. The URL itself isn't a Greenhouse domain, so this tests whether the resolver's embedded-ATS detection still catches it |
| **Discord** | `https://discord.com/careers` | Greenhouse, three boards: `discord` (51), `discordinternational` (1), `internationaleor` | 52+ | No (general sitemap only) | **Zero** ATS markers in the served HTML — the fetch call lives in a separately-loaded chunk (`/webflow-scripts/careersNew2025.js`) that fans out to three Greenhouse boards and merges them client-side. Nothing in the initial document hints Greenhouse exists |
| **SAP** | `https://jobs.sap.com/` | SAP SuccessFactors (`performancemanager5.successfactors.eu`) — a vendor not in our supported list at all | 253+ | **Yes, and it IS the feed** — `sitemap.xml` is a Google-Jobs RSS feed with full job descriptions inline, 4.2 MB | A brand-new ATS vendor, plus the purest version of "sitemap.xml doubles as the complete job feed" we found |
| **NVIDIA** | `https://jobs.nvidia.com/careers` | Eightfold (`static.vscdn.net`, `eightfold.ai`) on NVIDIA's own subdomain, not an eightfold.com domain | not stated (paginates 10 at a time via `/api/pcsx/search?query=&location=&start=0`, no total in the response) | No | Eightfold is already a supported fast-path vendor — this tests whether the resolver's embedded-ATS detection catches an Eightfold deployment on a fully custom domain the way it catches Cisco's Workday |
| **Ramp** | `https://ramp.com/careers` | Ashby (`jobs.ashbyhq.com/ramp`) | 139 | No (general sitemap only, no job URLs) | The entire job list, including full HTML descriptions, is server-rendered directly into the page — confirmed present in plain `curl` output — not fetched via XHR. Same "nothing to capture" shape as Snap/YC, but the source underneath is a supported ATS |
| **Klarna** | `https://www.klarna.com/careers/` | Deel, used as a full ATS product (not payroll/EOR): `jobs.deel.com/klarna` | 81 (declared inline: *"we have 81 open roles"*) | **Yes, exact match** — `jobs.deel.com/klarna/sitemap.xml` lists 82 URLs (1 index + 81 jobs) | Deel-as-ATS is a vendor we don't support at all, and it ships **no plain JSON API** — job data arrives inside Next.js React Server Component payloads (`?_rsc=...` requests, `content-type: text/html`). A clean test of what our pre-filter does when the real data isn't JSON |

### Shape 3 — Standard vendor ATS, pasted directly (controls)

| Company | URL | Jobs |
|---|---|---|
| **Anthropic** | `https://job-boards.greenhouse.io/anthropic` | 571 |
| **Notion** | `https://jobs.ashbyhq.com/notion` | 133 |
| **Micron** | `https://micron.wd1.myworkdayjobs.com/External` | 2,783 (via the board's own `wday/cxs` search API) — comfortably past the 2,000-job cap (`WORKDAY_MAX_PAGES × WORKDAY_PAGE_SIZE`) in `src/backend/api/services/workday_client.py`, useful if that cap ever needs a bigger board to reproduce against |
| **WHOOP** | `https://jobs.lever.co/whoop` | **0 right now** — confirmed live (Lever-hosted, loads normally) but genuinely empty: *"No job postings currently open."* Every other Lever slug tried (Netlify, 1Password, Customer.io, Vanta, Carta, Render, Postman, Chainalysis, Attentive, Webflow, Lattice, Digital Ocean, Patreon, Gusto, Amplitude, Medium) 404'd — Lever's tech-company footprint has shrunk. Useful only as an ATS-fast-path resolution control, not as a board with real jobs to page through |

### Shape 4 — Server-rendered HTML

| Company | URL | Behind it | Jobs | Sitemap | Why it's interesting |
|---|---|---|---|---|---|
| **Reddit** | `https://redditinc.com/careers` | Greenhouse — but only as outbound links | 153 | No (general sitemap only) | The page bakes `<a href="https://job-boards.greenhouse.io/reddit/jobs/{id}">` for all 153 jobs directly into the markup — confirmed with plain `curl`, no JS needed. "No XHR to capture" (like YC) **and** "the source is Greenhouse" (like Cisco) on the same board |
| **Snap** | `https://careers.snap.com/jobs` | None — genuinely custom | ~170 (170 rows tagged `Regular` employment type in the static HTML) | No (general sitemap, no job URLs) | True SSR: `curl` with no JS returns the full Role/Team/Type/Location table. A background `POST` to Contentful's GraphQL API loads page copy only — tempting to mistake for the jobs source, but it isn't |

### Shape 5 — GraphQL or nested POST bodies

| Company | URL | Behind it | Jobs | Sitemap | Why it's interesting |
|---|---|---|---|---|---|
| **Rippling** | `https://www.rippling.com/careers/open-roles` | Algolia (`6fnax3tbef-dsn.algolia.net`), not an ATS | 752 (`nbHits` in the response) | No (general sitemap only) | Not GraphQL, but the closest thing to it here: one batched `POST /1/indexes/*/queries` whose body is `{"requests":[{"indexName":"careers_en-US_production","params":"query=...&hitsPerPage=..."}]}` — the actual query parameters live inside a **URL-encoded string nested inside a JSON array**, two levels deep. The public search key is exposed in the page JS with no origin check and replays cleanly from plain `curl` outside any browser |

*No genuine GraphQL jobs API turned up among the candidates checked (Anduril, Applied Intuition, GitLab, Deel, Faire, Adyen, Instacart, Twitch, Brex, Scale AI, Retool all either ATS-backed or had nothing capturable at the landing URL). Goldman Sachs, already in the [✅ Tracked table](#-tracked--17-boards), remains this doc's only confirmed GraphQL-POST example.*

### Shape 6 — Structurally odd

| Company | URL | Behind it | Jobs | Sitemap | Why it's interesting |
|---|---|---|---|---|---|
| **Databricks** | `https://www.databricks.com/company/careers/open-positions` | Greenhouse — but only at build time | 851 unique `gh_jid`s | **Yes** — a dedicated careers sitemap lists 908 job URLs | Gatsby static site. The entire feed — every job, full descriptions, department taxonomy, Greenhouse ids — is baked at **build time** into one static `page-data.json` (7.9 MB) shipped with the page. There is no runtime call to Greenhouse at all. The JSON XHR our capture wants to find *is* there (the client does fetch `page-data.json`), but it's Gatsby's internal page-cache format, not a jobs API by any normal definition — a stress test of the pre-filter's job-shaped-response heuristic on a payload that's real but alien |

### What to test first

**Toss, Klarna, Databricks** — in that order. Toss because the sitemap-vs-API mismatch is
the exact failure class the [2026-08-22 correction](#correction--2026-08-22--the-sliver-reads)
exists to catch, on a board that has never been measured. Klarna because RSC payloads are a
transport our JSON-XHR pre-filter has plausibly never seen, and the outcome — clean
`tracking`, honest `partial`, or a refusal — says something new about how the pre-filter
degrades. Databricks because it inverts the usual assumption that a big JSON response is
good news: 7.9 MB of real job data, zero of it reachable by any request our recipe format
can express.
