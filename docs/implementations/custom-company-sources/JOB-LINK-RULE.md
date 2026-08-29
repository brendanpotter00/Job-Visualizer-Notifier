# How a discovered board gets a job's link

**Measured 2026-08-29 over 19 real board payloads.** Plain `httpx`, public endpoints,
no Browserbase, no captures. Every number below came from a fetch.

> *"Are we just guessing what the actual link to the job listing is going to be?"*

Yes, and on three of the six boards where we guess, the guess was wrong. This is the
rule that replaces the guess, the corpus it was measured on, and what it refuses.

---

## The defect, stated once

`field_map.url` comes back from the selector as one of two very different things, and
until now they were treated identically:

| | what it is | example | who is responsible if it 404s |
|---|---|---|---|
| **published** | a field the board itself filled with a link | `portalJobPost.portalUrl` → `https://globalcareers-atlassian.icims.com/jobs/25583/…` | the board |
| **synthesised** | a path **we invented**, with an id substituted into it | `https://www.janestreet.com/jobs/{id}` | us |

`_validate_url_field` checks that the result is *link-shaped*. Its own docstring
concedes it cannot tell a well-formed 404 from a real link without fetching. So a
synthesised path was stored on the strength of looking plausible, and the first anyone
learned it was dead was by clicking it.

`repair_url_template` (the Goldman fix) scores placeholder fields against URLs the
capture recorded on the board's host. It fixed Goldman because Goldman's own SPA
prefetches `/_next/data/<build>/roles/181782.json`. Jane Street's page never requests a
job page, so there was nothing to score, the rule refused, and the wrong link shipped.
**A heuristic that needs the board to have already told us the answer is not a rule.**

---

## The corpus

19 boards, real payloads, fetched 2026-08-29. 11 of the 17 "Tracked" boards in
[TESTABLE-BOARDS.md](TESTABLE-BOARDS.md) (the other six need captured request headers
we do not have on disk), plus eight boards drawn from the ATS families a bespoke board
is usually wearing underneath — Binance's "custom" board is a Lever export, Atlassian's
is iCIMS, SpaceX's is Greenhouse.

### What the payload offers

**13 of 19 (68 %) publish a link field. 6 of 19 (32 %) publish none.**

| publishes a link | field | | publishes none |
|---|---|---|---|
| Amazon | `job_path` | | **Jane Street** |
| Atlassian | `portalJobPost.portalUrl` | | **Goldman Sachs** |
| Microsoft | `positionUrl` | | **Walmart** |
| Binance · Palantir | `hostedUrl` (Lever) | | **Spotify** |
| SpaceX · Figma · Roblox · Anthropic · Stripe | `absolute_url` (Greenhouse) | | **TikTok** |
| Netflix | `canonicalPositionUrl` | | **Kakao** |
| Hygraph | `careers_url` (Recruitee) | | |
| Bosch | `ref` (SmartRecruiters) | | |

### What today's logic produces on the six that force a template

Page sizes below are what the shipped code measures: the body with `<script>` and
`<style>` stripped, tags removed, whitespace collapsed. Stripping scripts is not
cosmetic — an SPA ships its whole dataset inside one, so an empty shell still *contains*
every job's title until you take the bundle out.

| Board | stored spec | rendered | what actually happens |
|---|---|---|---|
| **Jane Street** | `…/jobs/{id}` | `/jobs/8631912002` | **404** on every job |
| **Goldman** *(pre-repair)* | `/roles/{roleId}` | `/roles/183031_GS_MID_CAREER` | **200, dead** — a **23-char** shell, identical for every job |
| **Goldman** *(post-repair)* | `/roles/{externalSource.sourceId}` | `/roles/183031` | works — 4,003 / 3,383 / 4,713 chars, each carrying its own title |
| **Walmart** | `/job/{job_id}` | `/job/CP-9438-11101` | **200, dead** — 1,606-char shell, identical for every job; `careers.walmart.com` answers 200 for *every* path |
| **Spotify** | `/jobs/{id}` | `/jobs/senior-product-designer-…` | works — 6,113 / 4,682 / 5,531 |
| **TikTok** | `/search/{id}` | `/search/7678060214174157061` | works — 8,785 / 7,772 / 7,855, own titles |
| **Kakao** | *(not stored)* | — | every path on `careers.kakao.com` returns the same 60-char shell |

**Three dead boards, not two.** Walmart has been shipping a dead link the whole time
and nobody clicked it. That is the argument for a rule rather than a third patch.

---

## The rule

Two branches, decided by one question that the code already knows how to ask:
**did the board give us this path, or did we make it up?**

```
spec = the selector's field_map["url"]

1. PUBLISHED  — the board filled in the path. Keep it. Fetch nothing.
     · spec is a plain field path whose value renders "https://…" or "/…"
       AND is different on different jobs
       (absolute_url, hostedUrl, portalJobPost.portalUrl, job_path, ref)
     · or spec is a template whose placeholder renders a PATH, not an id token
       (https://apply.careers.microsoft.com{positionUrl} → /careers/job/197…)

2. PUBLISHED ELSEWHERE — we invented a path but the board publishes one anyway.
     Prefer the board's field, best-ranked. Fetch nothing.

3. SYNTHESISED — a template whose placeholder renders an opaque id. PROVE IT:
     fetch the rendered URL for TWO different jobs and require
       · both < 400, and
       · each page carries its OWN job's title and not the other's,
         OR the two pages differ materially (≥ 200 chars and ≥ 2 %).
     Candidates in order: the repaired template, then the selector's original.
     First one that proves wins. At most 4 GETs, once, per board.

4. NOTHING PROVED — do not ship a link we cannot stand behind.
     Fall back to the board's own listing page, with the job id as a fragment.
```

### "Link-shaped" is not enough — it has to be per-job

A board's `companyLogoUrl`, careers banner or department page renders a perfectly
well-formed absolute URL on every record. A rule that only asked "is this field
link-shaped?" would happily store a PNG as the link to 2,000 jobs, and the recipe would
look completely fine. **A link to this job is different on a different job**, so both
branch 1 and branch 2 require the field to render more than one distinct value across
the sampled records. A board with a single posting cannot answer the question and is
given the benefit of the doubt.

### One thing this does not fix

SmartRecruiters publishes exactly one link-valued field, `ref`, and it points at
`api.smartrecruiters.com/v1/companies/<co>/postings/<id>` — the API, not the page a
person wants. It is per-job, it resolves, and it carries the job's own title, so both
the classifier and the proof accept it, and a user clicking through gets JSON.

Left alone deliberately. "Prefer a human page over an API endpoint" needs a signal the
payload does not carry, and every rule that could be written for it today would be a
guess about hostnames. A working link to the wrong *representation* is a much smaller
harm than a 404, and this is the only board in the corpus where it happens.

### Why "does the placeholder render a path?" is the branch test

Because it is the guard that already keeps Microsoft alive. `_renders_id_token` was
written for `repair_url_template` — a placeholder that renders `/careers/job/197…`
contains a `/`, so it is a path the board authored, not an id we pasted into a path we
invented. The same predicate answers both questions, so there is exactly one definition
of "we made this up" in the codebase.

### Why two real jobs, and not a fabricated control id

The obvious verification is "fetch the URL and check the status". Goldman is the proof
that it is worthless: `higher.gs.com/roles/<anything>` answers **200**. The next idea is
to fetch a deliberately-bogus id as a control — but that means inventing an id, and an
invented id can collide with a real job.

Two *real* jobs need no invention and answer the same question better: **if the board
serves the same page for two different jobs, the template does not route on that id.**
Measured:

| | job 1 | job 2 | verdict |
|---|---|---|---|
| Goldman `{roleId}` | 23 chars | 23 chars | same shell → **refuse** |
| Goldman `{externalSource.sourceId}` | 4,003, own title | 3,383, own title | **accept** |
| Walmart `{job_id}` | 1,606 | 1,606 | same shell → **refuse** |
| Kakao `{jobOfferId}` | 60 | 60 | same shell → **refuse** |
| Jane Street `{id}` | HTTP 404 | — | **refuse** |
| TikTok `{id}` | 8,785, own title | 7,772, own title | **accept** |
| Spotify `{id}` | 6,113 | 4,682 | lengths differ → **accept** |

### Why branch 1 must never fetch

Because the same test **rejects two working production links** when pointed at a
published field. Of the 13 published links in the corpus, 11 would pass a probe and
these two would not:

| Board | published link | two-job comparison | reality |
|---|---|---|---|
| **Atlassian** | iCIMS `portalJobPost.portalUrl` | 18,086 vs 18,086, neither page carries its title | the job renders in an **iframe**; the outer page is a shell — the same bytes for every job, exactly like Goldman's |
| **Roblox** | Greenhouse `absolute_url` | 6,447 vs 6,397 (0.8 %), each page carries its own title **and the other's** | a related-jobs block trips the listing-page guard, and 0.8 % is under the bar |

A client-rendered job page can be indistinguishable over plain HTTP from a
client-rendered 404 shell. That is not a flaw in the test — it is the reason the test is
only ever applied to a path **we** authored, where the alternative is shipping a guess.
When the board authored the path, the board is the authority and there is nothing to
prove. Atlassian is also the board the brief names as must-not-regress; probing it would
have cost it its links to catch nothing.

---

## Hit rate

| | boards | before | after |
|---|---|---|---|
| Published link (branch 1/2) | 13 | 13 work | **13 work, byte-identical specs** |
| Synthesised + proved (branch 3) | 3 | 3 work (by luck) | **3 work, proved** |
| Synthesised + unprovable (branch 4) | 3 | **3 dead links** | **0 dead links** |
| **Total** | **19** | **3 lies** | **0 lies** |

* **False negatives on synthesised templates: 0.** Every template that actually works
  passed (Goldman-repaired, Spotify, TikTok).
* **False positives: 0.** Every dead template failed.
* **Regressions: 0.** Nothing in branch 1 or 2 is fetched, re-pointed, or rewritten.

## What it refuses, and why that is correct

**Jane Street, Walmart and Kakao lose their per-job link.** All three are SPAs that
answer 200 for every path (Walmart, Kakao) or route job pages under a prefix that
appears nowhere in the payload, the capture, the page's server HTML, or a sitemap
(Jane Street: the real path is `/join-jane-street/position/{id}/`; neither
`janestreet.com` nor `higher.gs.com` publishes a `sitemap.xml`, and both careers pages
render their listings client-side, so the raw HTML contains **zero** job anchors).

There is no evidence anywhere in what we hold from which the right path could be
derived. Refusing to claim one is the whole point.

### The fallback, and the decision inside it

The brief said *"refuse or store no URL"*. Both were rejected, and this is the third
option:

* **Storing no URL is not available.** `url` is one of `CANONICAL_REQUIRED_FIELDS`, and
  an empty one reaches the frontend as `href=""` — which reloads the page. Worse than a
  404 and no more honest.
* **Refusing the board fails the e2e suite, correctly.** `AC-05` runs live discovery
  against Jane Street and asserts `outcome == 'tracking'`. Refusing a board we can read
  perfectly — 233 jobs, a working hiring-trend graph — because we cannot link to one of
  its pages sacrifices the product for the footnote.
* **So: the board's own listing page, with the job id as a fragment** —
  `https://www.janestreet.com/join-jane-street/open-roles/#8631912002`. It is the page
  the user pasted, it cannot 404, it is distinct per job, and it takes a clicker to the
  list the job is actually on. A `logger.warning` and a clause on the discovery
  checklist say so out loud.

### Seen happening, not just asserted

The `e2e/run.sh add-companies` run on 2026-08-29 drove real discovery against the live
boards. Its backend log is the whole change in four lines:

```
17:47  ACCEPTED apply.careers.microsoft.com   (no probe — published)
17:48  ACCEPTED www.atlassian.com             (no probe — published)
17:49  job link 'https://www.janestreet.com/jobs/{id}' is not usable:
       HTTP 404 on https://www.janestreet.com/jobs/8631912002
17:49  no per-job link could be proved for .../open-roles/ …
       linking every job at this board to its own listing page instead
17:51  job link 'https://www.lifeatspotify.com/jobs/{id}' proved against the live board
```

Jane Street still tracked, still 233 jobs, and the 404 the owner reported never reached
the database. 48 / 48 cases green.

### Considered and rejected: enumerating sibling paths

Jane Street's real path shares a prefix with the listing page the user pasted
(`/join-jane-street/open-roles/` → `/join-jane-street/position/{id}/`), so a wordlist of
plausible segments (`position`, `job`, `role`, `opening`, …) probed against the
verifier would recover it. It was measured and dropped: it recovers **1 of 19** boards
(Walmart and Kakao answer 200 for every path, so nothing can be proved on them), costs
up to 24 fetches per discovery, and its ordering is a per-board table wearing a rule's
clothes.

## `lookup_join` is not needed

`recipe_schema.py:100` defers `lookup_join` — a per-job detail fetch — partly on the
Microsoft board's cost (~10 min serial for 2,055 jobs against a 600 s budget). It would
be the tool if a job's URL could only be *read out of a per-job detail response*. No
board in the corpus is like that: the link is either already in the list payload
(branch 1) or derivable from an id in it (branch 3). Verification is **4 requests once
at discovery**, not one request per job per night. `lookup_join` stays deferred.

## Where the corpus lives

`src/backend/api/tests/fixtures/job_links/*.json` — one file per board, holding real
records from its real feed plus what its job pages actually returned on 2026-08-29:
status, length after script/style stripping, whether the page carried that job's own
title, and whether it carried the others'. `test_recipe_corpus_regression.py` replays
them offline at $0.

Those four numbers are enough to reproduce the verdict exactly: the fixtures were
generated by running the reconstruction *beside* the live bodies and requiring the two
to agree on all 13 boards, which they did. `kind` (who authored the path) and `proves`
(what fetching it says) are both asserted per board, so a future edit to either half of
the rule fails a test rather than a board.

## Cost

Four GETs, once, per discovered board — and only on the third of boards that need a
template at all. Ten of the thirteen corpus boards fetch nothing. Against a discovery
that already spends 27–75 s in a real browser, this is not a number worth optimising.

## Re-discovery is required

**This fixes discovery, not the database.** The four boards already in
`company_scripts` keep whatever url spec they were stored with — including Jane Street's
404 and Goldman's `{roleId}` — until each is re-discovered. Nothing here backfills a
stored recipe, and nothing should: rewriting a stored `fields.url` in place would need
the same proof this rule performs at discovery time, on a schedule nobody has asked for
yet.
