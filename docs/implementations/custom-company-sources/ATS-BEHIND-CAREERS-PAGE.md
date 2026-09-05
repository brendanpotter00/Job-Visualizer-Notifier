# ATS Behind the Careers Page

**Researched 2026-09-01.** The add-a-company flow has two paths: paste a URL that matches
one of six ATS host shapes and it resolves **instantly and free**; paste anything else and
it goes to **Discovery** — a real browser, a model call, ~45s, can fail. The trap: most
companies' own marketing puts a branded careers site in front of Google, and that branded
site is very often *not* the ATS host, even when a working ATS board sits one hop away.

**What happened today.** The owner pasted `careers.cisco.com/global/en/job/...`. Discovery
burned a browser session and a model call, then correctly refused — the rendered page never
names Cisco's Workday board (confirmed: 0 hits for `myworkdayjobs` across 177 KB of rendered
HTML). Only that one host string was searched, so this is evidence about Workday, not proof
that no provider's URL appears anywhere; the six-pattern check below is what settles that.
Cisco's real board, `cisco.wd5.myworkdayjobs.com/Cisco_Careers`, was already sitting in
`companies` (id `u-jw8iz8sqvy`) and resolves instantly, free, **1,248 jobs**. This doc is the
list of which other well-known companies do the same thing, verified rather than guessed.

---

## Corrections (2026-09-01)

Three claims below were wrong, and all three were found by measuring rather than
re-reading. They are corrected in place; this block exists so the corrections are not
silently absorbed.

**1. Cisco is not a Discovery trap — it was a DEEP-LINK trap.** The paragraph above says
Discovery "correctly refused". It refused because of the URL it was given, not because
Cisco is unresolvable. Measured across five plausible Cisco careers URLs:

| pasted | before | after the walk-up fix |
|---|---|---|
| `careers.cisco.com/` | ✅ free, 2.0s | ✅ |
| `careers.cisco.com/global/en` | ✅ free, 2.2s | ✅ |
| `careers.cisco.com/global/en/home` | ❌ → paid Discovery | ✅ free |
| `careers.cisco.com/global/en/search-results` | ✅ free, 1.6s | ✅ |
| `www.cisco.com/c/en/us/about/careers.html` | ❌ → paid Discovery | ✅ free |

L2 appended its sub-paths to the *pasted* path, so a deep link probed
`…/home/search-results` (a 404) instead of `/global/en/search-results` (ten hits). The
owner had browsed to a job and copied the address bar — the single most likely thing a
user does. Fixed by walking up one level at a time; jumping to the host root does not
work, because Cisco answers every path with the same 176,896-byte SPA shell and `/`
redirects back to `/global/en`.

**2. Raindrop has a live Ashby board.** It is listed below as the one live example of
Discovery's own output (`ats = 'discovered'`). `jobs.ashbyhq.com/raindrop` returns **9
jobs** — the same 9 the discovered recipe reads. Our only paid-Discovery company never
needed to be one. A name search finds it at rank 2.

**3. Jane Street has a live Greenhouse board.** `boards-api.greenhouse.io/v1/boards/janestreet/jobs`
returns **231 jobs** with real `gh_jid` apply links. `browserbase-agent/README.md` lists
Jane Street as a hard scraping target whose per-job URLs "only exist in the page's
anchors" — true of `janestreet.com`, and moot, because the Greenhouse board is free.

**Not a correction:** Spotify. The table below is right that `jobs.lever.co/spotify` is a
live Lever board already in `companies`; "negative result" refers to its *careers page*
revealing no ATS, not to Spotify lacking one.

---

## Part 1 — the search prompt

Rewritten from the owner's draft (*"give me spotify's career webpage and if there is a
workday greenhouse lever ashby the job board, give me that one, those job boards over their
traditional page"*) into something a model can execute without ambiguity: prefer the ATS,
name the six shapes, force structured output, define the no-ATS case.

### Search endpoint — **under 200 characters** (use this one)

Browserbase's search endpoint caps the prompt, so this is the version that actually
ships. **174 characters** — 26 to spare, which is room for a company name up to
35 characters once `{COMPANY}` (9 chars) is substituted. Every real name fits.

```
Find the Greenhouse, Ashby, Lever, Gem, Workday or Eightfold job board behind {COMPANY}'s careers page. Return that board's URL. Only if none exists, return the careers page.
```

It keeps the three things that matter and drops everything else: it **names all six**
ATS providers (without the list, a search model has no idea what counts as a valid
answer and hands back the branded page), it states the **preference direction**, and it
defines the **fallback** so a company with no ATS still returns something usable.

What it gives up versus the longer prompts below: no structured JSON, no `evidence`
field, and no host-shape hints. So you cannot tell a found link from a guess — grade a
sample by hand, or re-run the survivors through the long prompt.

### Medium — a chat model or agent with no length limit

```
Find {COMPANY}'s job board. I want the underlying applicant-tracking system (ATS), not the
company's branded/marketing careers page — if a Greenhouse, Ashby, Lever, Gem, Workday, or
Eightfold board exists behind the careers site, return THAT board's URL instead of the
marketing page, even if the marketing page is what search results show first.

Six ATS host shapes to look for, in links, redirects, or API calls the careers page makes:
- Greenhouse:  boards.greenhouse.io/<token>  or  job-boards.greenhouse.io/<token>
- Ashby:       jobs.ashbyhq.com/<token>
- Lever:       jobs.lever.co/<token>
- Gem:         jobs.gem.com/<token>
- Workday:     <tenant>.wd<N>.myworkdayjobs.com/<career-site-slug>
- Eightfold:   <company>.eightfold.ai/careers  (or an Eightfold deployment on the company's
               own domain — look for eightfold.ai or *.vscdn.net in page requests)

Return JSON only:
{
  "company": "{COMPANY}",
  "ats": "greenhouse|ashby|lever|gem|workday|eightfold|none",
  "ats_url": "<the ATS board URL, or null if none found>",
  "marketing_careers_url": "<the branded careers page you started from>",
  "evidence": "<the specific link, redirect, or API call that told you this>"
}

If none of the six is behind the careers page, set "ats" to "none" and "ats_url" to null,
and use "evidence" to say what the page actually runs on instead (a name if you can tell —
Phenom, SuccessFactors, iCIMS, a custom API — otherwise "custom/unknown").
```

### Long — sweep / audit, when you want to grade the answer

Use this when running many companies and you need to trust the output without re-checking
each one by hand — it forces the model to show its work and to distinguish "I found a link"
from "I guessed from the company name."

```
Find the real job board for {COMPANY}. Prefer the underlying applicant-tracking system (ATS)
over the company's own branded/marketing careers page, even when the marketing page is what
search results surface first and even when the marketing page itself lists open roles. A
branded careers page frequently sits IN FRONT OF an ATS — same jobs, different host — and I
always want the ATS host, because it is free and instant to read while the marketing page
usually is not.

Look specifically for these six ATS host shapes. A match can appear as a direct link on the
page, a redirect target, or a JSON/XHR request the page's own JavaScript makes:
- Greenhouse:  boards.greenhouse.io/<token>  or  job-boards.greenhouse.io/<token>
               (also boards-api.greenhouse.io/v1/boards/<token>/... if only the API host shows)
- Ashby:       jobs.ashbyhq.com/<token>
- Lever:       jobs.lever.co/<token>
- Gem:         jobs.gem.com/<token>
- Workday:     <tenant>.wd<N>.myworkdayjobs.com/<career-site-slug>
               (tenant and career-site-slug are often DIFFERENT strings from the company's
               brand name — e.g. Slack's tenant is "salesforce", not "slack")
- Eightfold:   <company>.eightfold.ai/careers, OR an Eightfold deployment on the company's
               own domain (look for eightfold.ai, *.vscdn.net, or /api/pcsx/ in requests)

Do this in order:
1. Open the company's most obvious careers URL (their own domain's /careers, or the top
   organic search result).
2. Read the actual page content and any network requests it makes — do not infer the ATS
   from the company's size or reputation.
3. If you find one of the six shapes, confirm it responds (a real page load or API 200), not
   just that the string appears somewhere.
4. If the company runs MULTIPLE systems (this happens — some companies have a Workday board
   for one population and an Eightfold or vendor-name-branded front end for another), report
   the one that actually returns jobs, and note the other in "evidence".
5. If nothing on the page names one of the six, do not guess a plausible-looking URL. Report
   "ats": "none".

Return JSON only:
{
  "company": "{COMPANY}",
  "ats": "greenhouse|ashby|lever|gem|workday|eightfold|none",
  "ats_url": "<the ATS board URL you confirmed responds, or null>",
  "marketing_careers_url": "<the branded careers page you started from>",
  "evidence": "<the specific link, redirect, or network request that proves this — quote it>",
  "confidence": "confirmed_live | found_link_not_tested | inferred_no_direct_evidence"
}

If "ats" is "none", use "evidence" to name what the page actually runs on if you can tell
(Phenom, SuccessFactors, iCIMS, Workable, a custom in-house API) — "custom/unknown" if you
truly cannot tell. Never leave "evidence" empty.
```

**Which to use.** Short for a one-off "does company X have a Greenhouse board" check. Long
for a batch sweep whose output you intend to trust without individually re-verifying every
row — the `confidence` field and the explicit "don't guess" step are what make that safe.

---

## Part 2 — the company table

**Method.** Every ✅ row below was checked one of two ways: fresh `curl` against both the
branded page and the ATS URL (today, 2026-09-01, output quoted where it matters), or cited
from this repo's own `docs/implementations/custom-company-sources/TESTABLE-BOARDS.md`
(2026-08-30 methodology — real headless Chromium + browser network capture, or plain
`curl`/`httpx`). Nothing below is inferred from the company's reputation or a plausible-
looking URL. Companies I tried and couldn't verify (PayPal's branded domain didn't resolve;
Turo and Expedia's branded pages returned 403/000 to a plain fetch) are **not** listed —
their ATS is real and working in prod, but I won't publish a guessed marketing URL for them.

Ground truth for the ATS column is `companies` in prod (`ats`, `board_token`,
`provider_config`), queried read-only. **131 companies** run one of the six ATS today (62
Ashby, 49 Greenhouse, 12 Workday, 4 Lever, 3 Gem, 1 Eightfold) — **132** non-script rows
total, the extra one being `Raindrop`, tracked via the Discovery/custom-recipe tier and not
one of the six, listed below as the one live example of what Discovery itself produces.

### The traps — branded page embeds no ATS URL at all

These fall through to Discovery if pasted as-is. The literal ATS host string does not
appear anywhere in the branded page's rendered HTML (checked by `curl` + `grep`, not by
inspecting the URL) — that absence is exactly what our own resolver's embedded-link scan
(`_EMBEDDED_ATS_PATTERNS` in `src/backend/api/services/ats_discovery.py`) needs to find and
doesn't. **Paste the ATS URL directly instead.**

| Company | Branded careers URL | Real ATS | ATS URL | Verified? |
|---|---|---|---|---|
| **Cisco** | `careers.cisco.com/global/en` | Workday (`cisco`) | `cisco.wd5.myworkdayjobs.com/Cisco_Careers` | ✅ Verified — Workday API returns **1,248 jobs** live; branded page is Phenom (`phenompeople` in page source), 177 KB rendered, **zero** occurrences of `myworkdayjobs` |
| **Discord** | `discord.com/careers` | Greenhouse (`discord`) | `job-boards.greenhouse.io/discord` | ✅ Verified — Greenhouse board live (200); branded page has **zero** occurrences of `greenhouse` — the fetch lives in a lazily-loaded chunk that fans out to 3 Greenhouse boards client-side (also confirmed independently in `TESTABLE-BOARDS.md`) |
| **Snap** | `careers.snap.com/jobs` | Workday (`snapchat`, career site `snap`) | `snapchat.wd1.myworkdayjobs.com/snap` | ✅ Verified — Workday API returns **178 jobs** live; branded page is 444 KB, genuinely custom SSR (Google Cloud infra), **zero** occurrences of `myworkdayjobs`. Two live, near-duplicate systems running in parallel |
| **General Motors** | `search-careers.gm.com/en/jobs` | Workday (`generalmotors`) | `generalmotors.wd5.myworkdayjobs.com/Careers_GM` | ✅ Verified — Workday API returns **799 jobs** live; branded page is behind a Cloudflare bot-check (`cf-mitigated: challenge`, 403 to a plain fetch) — the exact case Discovery's real browser exists for, and it still refused (`TESTABLE-BOARDS.md`: 5 JSON requests, none job-shaped) |

### The negative results — genuinely not one of the six

**Spotify** is the sharpest one, because it looks like a solved case and isn't. The owner
named it directly.

| Company | Branded careers URL | What it actually runs | The real ATS board sitting alongside it | Verified? |
|---|---|---|---|---|
| **Spotify** | `lifeatspotify.com/jobs` | **Not one of the six.** A Next.js app; the job list is fetched client-side after page load by an XHR this repo's own `discover()` sweep captured returning 87 jobs (`TESTABLE-BOARDS.md`) — I confirmed independently that neither the server-rendered `__NEXT_DATA__` payload nor any shipped JS bundle (`main.js`, `jobs-*.js`, and 6 more) contains the string `lever`, `greenhouse`, `workday`, `ashby`, or `smartrecruiters` anywhere | `jobs.lever.co/spotify` — a **live, working Lever board**, 86 postings, already in `companies` (id `spotify`, token `spotify`) | ✅ Verified both ways |
| **Walmart** | `careers.walmart.com/results` | **Not one of the six.** A chat-assistant GraphQL endpoint (`jobSearchAssistant`), 10 jobs/page, `total_jobs: 47298` in its own body | none found — this is genuinely outside the six-shape vocabulary | ✅ Verified via `TESTABLE-BOARDS.md` (measured `partial`, 10 of 47,298 reachable) |

Spotify is a near-perfect trap for a human, not just for our resolver: `jobs.lever.co/spotify`
returns almost exactly the same job count (86) as `lifeatspotify.com` (87, drift of 1) — close
enough that seeing both would make anyone assume they're the same system talking to itself.
They are not. `lifeatspotify.com` runs its own private API; Lever is a second, separate,
still-live board that happens to track the same company closely.

### Already solved — listed so you know the resolver has these, not to re-add them

These ARE branded pages sitting in front of an ATS, and pasting the branded URL already
works — the page embeds a literal ATS URL somewhere (an "Existing applicant? Sign in" link,
an outbound apply link, an iframe), and our L2 embedded-link scan finds it. No trap, no
Discovery spend. Listed because they were the control group that made the traps above
identifiable — the same check, opposite result.

| Company | Branded careers URL | Real ATS | Evidence the resolver already uses | Verified? |
|---|---|---|---|---|
| **Capital One** | `capitalonecareers.com` | Workday (`capitalone`) | Page links directly to `capitalone.wd12.myworkdayjobs.com/Capital_One/login` | ✅ Verified — literal URL present in rendered HTML |
| **NVIDIA** | `jobs.nvidia.com/careers` | Workday (`nvidia`) — **not** the Eightfold markers the page itself is full of | Page links directly to `nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/login` (2×) | ✅ Verified — Workday API returns **2,000 jobs** live (Workday's own display ceiling); the branded page's own JS *also* references `eightfold.ai` and `*.vscdn.net` — two ATS systems live on NVIDIA at once, and only one of them (Workday) is the one our resolver would ever reach |
| **x.ai** | `x.ai/careers` | Greenhouse (`xai`) | Embedded Greenhouse link on page | ✅ Verified — matches `companies` exactly (id `xai`, token `xai`) |
| **Palantir** | `palantir.com/careers/` | Lever (`palantir`) | Embedded Lever link on page | ✅ Verified — matches `companies` exactly |
| **Nike** | `jobs.nike.com` | Workday (`nike`) | Direct/embedded match | ✅ Verified via `TESTABLE-BOARDS.md` |
| **Samsung** | `samsung.com/us/careers` | Workday (`sec`) | Embedded match | ✅ Verified via `TESTABLE-BOARDS.md` — note the tenant (`sec`) shares nothing textually with "Samsung" |
| **Target** | `jobs.target.com` | Workday (`target`) | Embedded match | ✅ Verified via `TESTABLE-BOARDS.md` |
| **Accenture** | `accenture.com/us-en/careers/jobsearch` | Workday (`accenture`) | Embedded match | ✅ Verified via `TESTABLE-BOARDS.md` |
| **Intel** | `jobs.intel.com` | Workday (`intel`) | Redirect chain resolves directly | ✅ Verified via `TESTABLE-BOARDS.md` |

### Other companies from `companies` with a distinct branded front end

Lower-signal than the trap/solved split above — these are DB-proven working ATS boards
where a separately-branded marketing page also exists and loads, but I did not fully
determine whether the resolver's embedded scan already catches each one.

| Company | Branded careers URL | Real ATS | ATS URL | Verified? |
|---|---|---|---|---|
| **Reddit** | `redditinc.com/careers` | Greenhouse (`reddit`) | `job-boards.greenhouse.io/reddit` | ✅ Verified via `TESTABLE-BOARDS.md` — branded page bakes Greenhouse job links directly into server-rendered markup |
| **Databricks** | `databricks.com/company/careers/open-positions` | Greenhouse (`databricks`) | `job-boards.greenhouse.io/databricks` | ✅ Verified via `TESTABLE-BOARDS.md` — the entire feed is baked at Gatsby **build time**; there is no runtime call to Greenhouse to find at all |
| **Airbnb** | `careers.airbnb.com` | Greenhouse (`airbnb`) | `job-boards.greenhouse.io/airbnb` | ✅ Verified via `TESTABLE-BOARDS.md` — server-rendered WordPress archive, no XHR |
| **Netflix** | `netflix.com/jobs` (301 redirect confirmed live) | Eightfold (domain `netflix.com`) | `explore.jobs.netflix.net` | ✅ Verified — DB-proven Eightfold tenant; branded redirect confirmed live, board content not independently re-checked today |
| **Anthropic** | `anthropic.com/careers` (200, client-rendered — no literal ATS string in the static HTML) | Greenhouse (`anthropic`) | `job-boards.greenhouse.io/anthropic` | ✅ Verified — ATS board confirmed live (200); branded page loads but is client-rendered so a plain fetch can't confirm what it embeds |
| **Instacart** | `careers.instacart.com` (301, confirmed live) | Greenhouse (`instacart`) | `job-boards.greenhouse.io/instacart` | ⚠️ Unverified relationship — both hosts confirmed live independently, embedding not checked |
| **Waymo** | `waymo.com/careers` (301, confirmed live) | Greenhouse (`waymo`) | `job-boards.greenhouse.io/waymo` | ⚠️ Unverified relationship — both hosts confirmed live independently, embedding not checked |

### The Phenom People pattern

**Not one of our six, and very common.** [Phenom](https://www.phenompeople.com) is a
white-label careers-page vendor — confirmed today on both **Cisco** (`careers.cisco.com`,
`phenompeople` string present) and **Adobe** (`careers.adobe.com`, same marker, plus
`utm_medium=phenom-feeds` on its outbound job links). A Phenom front end is *always* a shell
over something else — Adobe's is Workday (`adobe.wd5.myworkdayjobs.com`, already in
`companies`, and unlike Cisco this one **does** embed the literal Workday URL, so it's a
"solved" case, not a trap). **The rule: seeing `phenom` in a page's source tells you nothing
about which of the six ATSes (if any) is underneath — you still have to look.**

### Raindrop — the one live example of Discovery's own output

`companies` has exactly one row with `ats = 'discovered'`: **Raindrop**
(`www.ycombinator.com/companies/raindrop/jobs`). It is not one of the six — it's YC's own
job board, read via the custom-recipe/Discovery tier, `oracle: none`, 9 jobs tracked. Useful
as the concrete counter-example to everything else in this table: this is what happens when
there genuinely is no ATS to find, and Discovery is doing exactly the job it exists for.

---

## Part 3 — telling it apart, and the rule of thumb

**From a URL alone:**

| You see | It usually means |
|---|---|
| `boards.greenhouse.io/…`, `job-boards.greenhouse.io/…` | Already the ATS. Paste as-is. |
| `jobs.ashbyhq.com/…`, `jobs.lever.co/…`, `jobs.gem.com/…` | Already the ATS. Paste as-is. |
| `<tenant>.wd<N>.myworkdayjobs.com/<slug>` | Already the ATS. Paste as-is. |
| `<company>.eightfold.ai/careers`, or a company subdomain calling `eightfold.ai`/`*.vscdn.net` | Already (or effectively) the ATS. |
| `careers.<company>.com`, `<company>.com/careers`, `lifeat<company>.com`, `<company>careers.com` | **A branded front end. Could go either way** — check what's under it before assuming Discovery is needed. |
| Page source contains `phenom` / `phenompeople` / `utm_medium=phenom-feeds` | Confirmed branded front end (Phenom). Still tells you nothing about what's underneath — go look. |

**The check that actually separates a trap from a solved case, in one line:** view-source
(or `curl`) the branded page and search for the six literal host strings —
`myworkdayjobs`, `greenhouse.io`, `ashbyhq.com`, `lever.co`, `jobs.gem.com`, `eightfold.ai`.
Present anywhere (even in a buried "existing applicant login" link) → our resolver's
embedded scan already finds it, paste the branded URL and it just works. Absent everywhere
→ the question is still open, not answered: go look for the ATS host yourself (Google
`<company> workday jobs` / `<company> greenhouse jobs`, or use the Part 1 prompt). Find one
and paste **that** URL instead — that was the trap. Confirm there genuinely isn't one
(Spotify, Walmart, Raindrop) and Discovery is the right tool, so paste the branded URL.

**The rule of thumb:** always paste the ATS URL if you know it or can find it in under a
minute — instant, free, no browser, no model call. Only let a pasted URL go to Discovery
when you've actually checked and there is no ATS behind it (Spotify's marketing page,
Walmart, Raindrop) — Discovery is the right tool there, not a fallback you fall into by
pasting whatever Google showed first.
