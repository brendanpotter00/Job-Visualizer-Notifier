# Id-in-href as rung 0 — measured, not guessed

**Measured 2026-08-30.** 25 board URLs loaded in a real browser, 20 scored.

> **Verdict — the scepticism is vindicated, and for a reason nobody predicted.**
> **Rung 0 hit rate 11/20 (55%)** as specified — one id per record, substring match.
> **Rung 1 rescues 4 of the 7 misses (57%)**, and never runs on the 2 boards that need it most.
> **False positives: 2**, and **1 of them survives the two-real-jobs proof** and would ship.
> **The killer: this is already built.** `request_selector.derive_url_templates_from_links`
> is rung 0 with four extra rules, wired into the ladder at `discover.py:2484`. Head-to-head
> on the same 20 captures the naive version finds **zero** correct links the shipped one
> does not already produce, and adds **three** false positives the shipped one refuses.

---

## What was actually run

For each board: one real headless-Chromium page load (24 s observation window, scrolling),
recording **every JSON response** *and* **every `<a href>` in every frame** from the same
load. Then, offline:

* **rung 0 strict** — keys = the one `id` field a stored recipe keeps (`dedupe_key`);
* **rung 0 generous** — keys = *every* scalar leaf in the record (what the shipped code does);
* a template derived by replacing the matched value with `{field.path}`, majority vote;
* **the real proof** — `discover._prove_job_link` imported and called, not reimplemented,
  through `discover._default_probe` (the same SSRF-guarded client the nightly replay uses);
* **rung 1** — find the element whose visible text equals a feed title, click it,
  read `window.location`;
* head-to-head against the shipped `derive_url_templates_from_links`.

Minimum id length for a match: **4 chars**. Deliberately generous — a stricter floor would
have hidden coincidence matches, which is the thing worth seeing.

**Scored: 20 boards.** Excluded and why:

| Excluded | Why |
|---|---|
| **Roblox** | Would not load in local headless Chromium at all — `net::ERR_HTTP2_PROTOCOL_ERROR`, reproduced with and without HTTP/2. Not a failure of the approach; not measurable here. |
| **Y Combinator/Raindrop, Reddit, Anthropic, Ramp** | `http_html` boards. Their recipe takes the record id **out of the href** (YC's stored recipe is literally `id: ".@href"`). Rung 0 is circular there and proves nothing. Reported separately below. |

---

## Per-board results

`r0` columns: ✅ correct template · ❌ **false positive** · — no match.
"Storable" = the derived template also survives `_prove_job_link`.

| Board | feed ids (sample) | anchors | r0 strict | r0 generous | template rung 0 derived | correct? | proof | storable |
|---|---|---|---|---|---|---|---|---|
| **Jane Street** | `8631912002` | 32 | — | — | none | n/a | n/a | no |
| **Nintendo** | `internal_job_id 4173984009` | 74 | — | ✅ | `careers.nintendo.com/jobs/{id}/` | yes | pass | **yes** |
| **Atlassian** | `25583` | 325 | ✅ | ✅ | `atlassian.com/company/careers/details/{id}` | yes | pass | **yes** |
| **Goldman Sachs** | `roleId 179373_GS_MID_CAREER` | 34 | — | ✅ | `higher.gs.com/roles/{externalSource.sourceId}` | yes | pass | **yes** |
| **JPMorgan (Oracle)** | `Id 210775811` | 251 | ✅ | ✅ | `…/sites/CX_1001/job/{Id}` | yes | **reject** | no |
| **Cisco** | `jobId 2006625` | 60 | ❌ | ❌ | `…/hvhapply?jobSeqNo=CISCISGLOBAL{jobId}EXTERNALENGLOBAL` | **no — apply form** | reject | no |
| **Microsoft** | `1970393556852588` | 24 | ✅ | ✅ | `apply.careers.microsoft.com/careers/job/{id}` | yes | pass | **yes** |
| **Amazon** | `id` = uuid, `id_icims 10515090` | 58 | — | ✅ | `amazon.jobs{job_path}` | yes | pass | **yes** |
| **SpaceX** | `greenhouseId 8324817002` | 2 284 | ✅ | ✅ | `boards.greenhouse.io/spacex/jobs/{greenhouseId}` | yes | **reject** | no |
| **Spotify** | `id` = slug | 32 | — | ❌ | `…/find-your-team/job-categories/{main_category.slug}` | **no — category page** | reject | no |
| **Rockstar** | `7632962003` | 110 | ✅ | ✅/❌ tie | `rockstargames.com/careers/openings/position/{id}` | yes | **reject** | no |
| **Walmart** | `job_id CP-9046-11101` | 33 | — | ❌ | `twitter.com/{brand}World` (3-way tie) | **no — social page** | reject | no |
| **Snap** | `_source.id R0046484` | 205 | ✅ | ✅ | `careers.snap.com/job?id={_source.id}` | yes | pass | **yes** |
| **Notion** | uuid | 138 | ✅ | ✅ | `jobs.ashbyhq.com/notion/{id}` | yes | pass | **yes** |
| **Toss** | `52701` | 290 | ❌ | ❌ | `toss.im/career/article/{id}` (1 of 20 records) | **no — article route** | **pass** | **yes (wrong)** |
| **Rippling** | `jobId` uuid | 122 | ✅ | ✅ | `ats.rippling.com/rippling/jobs/{jobId}` | yes | pass | **yes** |
| **Discord** | `8599937002` | 121 | ✅ | ✅ | `discord.com/jobs/{id}` | yes | pass | **yes** |
| **Robinhood** | `8054481` | 154 | ✅ | ✅/❌ tie | `boards.greenhouse.io/robinhood/jobs/{id}?gh_src=NaN&gh_jid={id}` | yes | **reject** | no |
| **Micron** | `externalPath /job/…_JR101216` | 23 | ✅ | ✅ | `micron.wd1.myworkdayjobs.com/en-US/External{externalPath}` | yes | **reject** | no |
| **Databricks** | `id Greenhouse__Job__8559344002` | 953 | — | ❌ | `…/professional-services-operations/sr-forward-deployed-engineer-fde---communications-media-entertainment--games-{gh_Id}` | **routes, but names another job** | pass | **yes (ugly)** |

### The three numbers

| | strict (one id) | generous (every field) |
|---|---|---|
| found a match | 13 / 20 | 19 / 20 |
| **found the RIGHT template** | **11 / 20 = 55 %** | 12 clean + 2 coin-flip = 14 / 20 |
| **false positives** | **2** (Cisco, Toss) | **4** (Cisco, Spotify, Walmart, Toss) + 1 cosmetic (Databricks) |
| FPs the proof lets through | **1** (Toss) | **2** (Toss, Databricks) |
| correct templates the proof *rejects* | **5** (JPMC, SpaceX, Rockstar, Robinhood, Micron) | same 5 |
| **correct AND storable after the proof** | **6 / 20 = 30 %** | 8 / 20 |

**Read that last row twice.** The proof throws away more correct answers (5) than rung 0
produces wrong ones (2). Rung 0's real ceiling is not its own accuracy — it is that the
existing proof cannot see a client-rendered job page.

### Rung 1 — 4 of 7 rescues

Run on every strict-mode miss (feed title → matching element → click → `window.location`):

| Board | Rung 1 | Result |
|---|---|---|
| **Nintendo** | ✅ rescue | title sits inside `careers.nintendo.com/jobs/4295098009/` |
| **Goldman Sachs** | ✅ rescue | `higher.gs.com/roles/179373` — the id that routes |
| **Spotify** | ✅ rescue | clicked → `lifeatspotify.com/jobs/{id}`; **proof passes**. Rung 1 is the *only* thing that finds Spotify's link |
| **Walmart** | ✅ rescue | clicked → `careers.walmart.com/us/en/jobs/{job_id}` — and this is **right**, where the stored recipe's `careers.walmart.com/job/{job_id}` serves the same 1 606-char page for every job |
| **Jane Street** | ❌ | the pasted URL is a *hub* with two "View open roles" buttons and zero job cards. Its titles are also homoglyph-obfuscated in the feed (`꓆achine ꓡearning ꓣesearcher`), so text matching cannot work by construction |
| **Amazon** | ❌ | the title element is not inside a link; the click fired and `window.location` never changed |
| **Databricks** | ❌ | no element whose visible text equals the feed title (the first records are Japanese-titled) |

**The structural problem with rung 1 is not its hit rate.** It only runs when rung 0 finds
*nothing*. On **Cisco**, rung 1 clicks through to `careers.cisco.com/global/en/job/2006625/ASIC-Core-DFT-Technical-Lead`
— the correct job page, verified in a browser. It will never run, because rung 0
confidently returned the apply form.

### The circular four

Excluded from the rate because the answer is baked in:

| Board | job anchors | Note |
|---|---|---|
| YC / Raindrop | 9 of 68 | stored recipe is `id: ".@href"` — rung 0 matches the href against itself |
| Reddit | 153 of 200 | server-rendered `job-boards.greenhouse.io/reddit/jobs/{id}` |
| Anthropic | 50 of 53 | same shape |
| **Ramp** | **0 of 83** | the Ashby list did not render in local headless Chromium; nothing to match either way |

---

## Every false positive, in detail

### 1. Cisco — the apply form, not the job (strict *and* generous)

```
feed:   jobId "2006625",  jobSeqNo "CISCISGLOBAL2006625EXTERNALENGLOBAL"
anchor: https://careers.cisco.com/global/en/hvhapply?jobSeqNo=CISCISGLOBAL2006625EXTERNALENGLOBAL
r0  ->  https://careers.cisco.com/global/en/hvhapply?jobSeqNo=CISCISGLOBAL{jobId}EXTERNALENGLOBAL
```

10 of 10 records match. **The id really is in the href** — the proposal's premise holds
perfectly and still yields the wrong page. Rendered, that URL is the application form:
*"You are applying for — ASIC Core DFT Technical Lead (2006625)"*. There is no job
description on it.

It is worse than one bad template: generous mode produces **28 distinct templates** and a
**3-way tie for first**, all three of them apply-form variants (`{jobId}`, `{reqId}`,
`{jobSeqNo}`). There is no principled tie-break.

Caught only by luck. The proof rejected it at *493 vs 493 chars* — Cisco serves the apply
route as a JS shell. Cisco server-renders its **listing**; if it server-rendered the apply
page, the two pages would differ and each would carry its own title, and the proof would
have **passed an application form as the job link on every Cisco job**.

### 2. Toss — a 1-vote template that passes the proof and ships

```
feed:   career-article posts, id 52701, "…토스인슈어런스 Server Developer"
r0  ->  https://toss.im/career/article/{id}     agreed on by 1 of 20 records
proof:  PASSES — HTTP 200, 157 chars, each page carries its own title
```

**Nothing in the proposal checks coverage.** One coincidental anchor match out of twenty
records produced a template that was then applied to the whole board, and the two-real-jobs
proof happily confirmed it, because `_link_samples` renders the template over *all* records
and never asks how many of them voted for it.

The underlying board problem is separate and also real: Toss's 258 jobs are server-rendered
as `toss.im/career/job-detail?job_id=7827417003`, while the only JSON feed the capture sees
is the *articles* endpoint (`workspaces/13/posts`). Rung 0 cannot fix a wrong feed — but it
will confidently emit a link for one.

### 3. Walmart — a Twitter page as the per-job link

```
feed:   job_id "CP-9046-11101", brand "Walmart"   (33 anchors, none of them jobs)
r0  ->  3-way tie, 10/10 records each:
          https://twitter.com/{brand}World
          https://www.facebook.com/{brand}World
          https://www.glassdoor.com/Overview/Working-at-{brand}-EI_IE715.11,18.htm
```

`"Walmart" in "https://twitter.com/WalmartWorld"` is true, so a *company-name field*
became the job id. Rejected downstream for two accidental reasons — every record renders
the *same* URL (so `_link_samples` cannot find two distinct ones), and Facebook answers
our probe with a 400. Neither is the check that should have stopped it.

### 4. Spotify — the job **category** page

```
feed:   main_category.slug "design"  (32 anchors, none of them jobs)
r0  ->  https://www.lifeatspotify.com/find-your-team/job-categories/{main_category.slug}
        49 of 77 records
```

Rejected at *3 845 vs 3 917 chars* — the two sampled jobs happened to be in `design` and
`content`, and Spotify's two category pages happen to be within the proof's 2 % length
band. That is luck, not a guard: category pages of very different sizes would have passed.
Spotify's genuine link (`lifeatspotify.com/jobs/{id}`, proof passes) is reachable **only**
via rung 1.

### 5. Databricks — 627 templates, a 14-vote winner, and it works anyway

```
feed:   id "Greenhouse__Job__8559344002"  (Gatsby node id — strict mode misses entirely)
        gh_Id 8559344002
r0  ->  https://www.databricks.com/company/careers/professional-services-operations/
        sr-forward-deployed-engineer-fde---communications-media-entertainment--games-{gh_Id}
        851 of 856 records matched … across 627 DISTINCT templates. Winner: 14 votes.
proof:  PASSES — HTTP 200, 9 521 / 9 913 chars, each page carries its own title
```

Every Databricks job link ends in `{dept-slug}/{title-slug}-{id}`, so each record derives
its **own** template and the "majority" is 1.6 % of the board. The winner hard-codes one
job's department and title and substitutes only the id — and it *works*, because Databricks
routes on the trailing id and ignores the slug. So 856 job links would ship pointing at the
right page under a URL that names a different job.

**This is the most dangerous shape in the set**, because nothing flags it. Had Databricks
validated the slug, a 14-vote majority would have broken 856 links and the proof would
still have had no opinion — it only ever looks at two.

---

## Where rung 0 beats today's ladder, and where it does not

**Genuine wins — measured, both confirmed by fetching two real jobs:**

| Board | what the board publishes | what it serves | id-in-href |
|---|---|---|---|
| **Nintendo** | `absolute_url` (`?gh_jid=`) | **842 vs 842 chars — the listing page for both jobs** | `careers.nintendo.com/jobs/{id}/` ✅ |
| **Atlassian** | `portalJobPost.portalUrl` (iCIMS) | **18 086 vs 18 086 chars — the same page for both jobs** | `atlassian.com/company/careers/details/{id}` ✅ |

**Goldman is the clean demonstration of the two-ids problem:**

```
higher.gs.com/roles/179373_GS_MID_CAREER   -> HTTP 200,    23 chars   (empty shell)
higher.gs.com/roles/179373                 -> HTTP 200, 6 135 chars   (the role)
```

Strict rung 0 misses it — `"179373_GS_MID_CAREER" in href` is false. Only the generous
form, which tries every field, finds `externalSource.sourceId`.

**Where the ladder still wins outright:**

* **Jane Street.** Zero job anchors on the URL the corpus uses — it is a chooser page. The
  list lives at `?type=experienced-candidates` (146 anchors) and `?type=students-and-new-grads`
  (52), and the ids there *are* feed ids. Today's JS-bundle regex reads
  `href="/join-jane-street/position/${t.id}/"` straight out of the board's own code and gets
  the right answer from the hub page. Rung 0 and rung 1 both get nothing.
* **Every board that publishes a usable url field.** Microsoft (`positionUrl`), Amazon
  (`job_path`), Snap (`_source.absolute_url`), Rippling (`url`), Robinhood/Discord/Databricks
  (`absolute_url`), Micron (`externalPath`), Cisco (`applyUrl`). The published-field rung
  already covers 9 of the 20 boards; rung 0 adds nothing there and, on Cisco, actively
  produces something worse.

---

## The finding that decides it: this rung already exists

`request_selector.derive_url_templates_from_links` (called from `discover.py:2484`) is the
proposal, already shipped, with four rules the naive version lacks:

1. tries **every** id-token path, not just the recipe's `id` — Goldman and Nintendo work;
2. matches **whole path segments**, never substrings;
3. requires **`_MIN_TEMPLATE_AGREEMENT = 3` different records** to agree;
4. **drops the query string**, and ranks by agreement then shortest template.

Head-to-head on the same 20 captures:

| | naive rung 0 (generous) | shipped `derive_url_templates_from_links` |
|---|---|---|
| correct templates | 14 | 7 |
| **false positives** | **4 + 1 cosmetic** | **2** |
| refused rather than guessed | 1 | 11 — *9 of which a published url field already covers* |

Every false positive above is refused by a rule that is already there:

| FP | refused by |
|---|---|
| Cisco `CISCISGLOBAL{jobId}EXTERNALENGLOBAL` | whole-segment rule (rule 2) |
| Walmart `twitter.com/{brand}World` | whole-segment rule |
| Databricks `slug-{gh_Id}` | whole-segment rule |
| Robinhood `?gh_src=NaN&gh_jid={id}` carry-over | query-drop (rule 4) |
| Rockstar `careers/offices/{seo_url}` tie | agreement-then-shortest ranking (rule 4) — the correct template ranks first |

Two survive the shipped rules too, and they are the two the proposal cannot help with:
**Spotify's category page** (proof catches it) and **Toss's article route** (proof does
not — `career/article/{key}`, 4 of 20 records, passes).

**And the naive version's extra correct answers?** SpaceX, Robinhood, Rippling, Microsoft.
All four are refused by exactly one rule — `_absolute_board_links` keeps only anchors on
the board's **own host**, and all four link off-host (`boards.greenhouse.io`,
`ats.rippling.com`, `apply.careers.microsoft.com`). Neutralising that one filter and
re-running the shipped function:

```
spacex     -> https://boards.greenhouse.io/spacex/jobs/{greenhouseId}
robinhood  -> https://boards.greenhouse.io/robinhood/jobs/{id}
rippling   -> https://ats.rippling.com/rippling/jobs/{jobId}
microsoft  -> https://apply.careers.microsoft.com/careers/job/{id}
cisco / walmart / databricks / micron / amazon / snap -> still refused
```

**Four recovered, zero new false positives.**

---

## Recommendation

**Do not build this as rung 0. It is already rung 0, and the naive version is strictly worse.**

Measured, the proposal as written would replace a derivation that refuses 11 boards with one
that guesses on 19 — buying **zero** correct links the ladder does not already produce and
adding **three** confidently-wrong templates (Cisco's apply form, Walmart's Twitter page,
Databricks' mislabelled slug), one of which the proof cannot catch.

**Do this instead, in priority order:**

1. **Relax the same-host filter in `_absolute_board_links` to a same-host-*or*-known-ATS-host
   allowlist.** Four boards (SpaceX, Robinhood, Rippling, Microsoft) recover their correct
   template, no new false positives. This is the whole measured value of the proposal, and it
   is a filter change inside a function that already exists.
2. **Teach `_prove_job_link` to read a rendered page, not a served one.** It rejects **5
   correct templates** here — JPMC, SpaceX (a 301 to `job-boards.greenhouse.io` our SSRF-guarded
   probe answers `0` for), Rockstar, Robinhood, Micron — against **2** wrong ones it catches.
   All five are verified correct in a real browser. This is the binding constraint on job-link
   quality today, not the derivation.
3. **Require coverage before storing a derived template.** Toss ships a wrong link off **1
   vote in 20** and Databricks off **14 in 856**, and nothing anywhere looks at that ratio.
   `derive_url_templates_from_links` counts agreement; `_prove_job_link` never sees it.
4. **Rung 1 (click by title) is worth building — but only as a fallback for boards with no job
   anchors at all**, which is where it earned its 4 rescues. It is the *only* mechanism that
   finds Spotify's and Walmart's real links. Do not gate it on "rung 0 found nothing": on Cisco
   rung 0 finds something wrong and rung 1 would have found the right answer.

---

## Honest gaps

* **Local headless Chromium, residential US IP.** Roblox never loaded; Ramp's job list never
  rendered; Jane Street's hub page renders no cards here. Browserbase could differ.
* **Feed choice was made by hand**, mimicking the pre-filter + model, not by running
  `discover()`. Toss is the case where that choice is visibly wrong (articles, not jobs) —
  and it is exactly the case where rung 0 emitted a passing link anyway.
* **Ties were broken arbitrarily** by the harness. Cisco (3-way), Walmart (3-way), Rockstar
  and Robinhood (2-way, right answer tied against a wrong one) have no principled winner in
  the proposal as specified. The shipped ranking resolves Rockstar correctly.
* **One page load per board**, so pagination and infinite scroll are only partly exercised.
  SpaceX (2 255 records / 2 284 anchors) and Databricks (856 / 953) both had the whole board
  in the DOM; JPMorgan had 25 feed records against 225 anchors and Cisco 10 against 60, so on
  a paginated board rung 0 only ever sees the first page's ids either way.
* **Nothing was written to any database**, and no source file was changed.
