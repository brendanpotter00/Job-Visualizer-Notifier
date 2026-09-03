# SPIKE: browser-agent discovery → deterministic scrape recipe

**Verdict: GO** — with one caveat named in the first table below.

An agent exploring a careers site **once** can emit a deterministic recipe that
replays forever with no AI and no browser in the loop. Six of seven targets
produced a working recipe. Every one of them replays over **plain HTTP**.
Total spend: **$0.00**.

The headline is Meta. This spike existed largely to find out whether the hard
case forces a real browser into the 30-minute cron forever. It does not:
Meta's entire 801-job catalogue comes back from one forgeable HTTP POST in
0.8 seconds.

| Question the spike had to answer | Answer |
|---|---|
| Can one-time discovery produce a durable recipe? | **Yes** — 6/7 targets, all replay over plain HTTP |
| Must `browser_dom` exist in production? | **No** — not one target needed it. Recommend not building it (see §5) |
| Is a per-run daily-AI fallback tier needed? | **No** — nothing needed AI at replay time |
| What did it cost? | **$0.00** — local Playwright + Claude; no Browserbase, no paid API |
| **Caveat** | Durability is proven over **hours, not the planned 48 h**. Rounds 2–3 are pending (§7) |

Date: 2026-08-05 · Repo: Job-Visualizer-Notifier · Branch:
`feat/custom-company-sources-spike` · Harness: `scripts/one_off/recipe_spike/`
· ClickUp: E7 / 7.2 (`wdwb1cbnc4`)

---

## 1. Measured results

Replay round 1, all recipes, no agent involved:

| target | kind | jobs | source's own total | replay | discovery capture | $ |
|---|---|---:|---|---:|---:|---:|
| meta | `http_json` | 801 | 801 (exact) | 0.8 s | 9.9 s | 0 |
| tiktok | `http_json` | 3799 | 3799 (exact) | 8.4 s | 13.7 s | 0 |
| janestreet | `http_json` | 225 | none published | 0.3 s | 7.9 s | 0 |
| spotify | `http_json` | 90 | 90 (exact) | 0.6 s | 9.7 s | 0 |
| amazon | `http_json` | 76 | 76 (exact) | 1.2 s | 66.3 s¹ | 0 |
| ycombinator | `http_html` | 8 | 8 (exact) | 0.7 s | 7.4 s | 0 |
| tesla | **none** | — | 7,597 located, unreachable | — | 6.6 s | 0 |

¹ 60 s of Amazon's capture was a harmless `networkidle` timeout caused by
analytics chatter, not work.

**Discovery cost per company: ~8–15 seconds of local browser time and one
agent pass.** The plan's GO bar was a median under 10 browser-*minutes*; the
measured median is ~10 browser-*seconds*, roughly 60× under budget. The
recurring cost of a recipe afterwards is one HTTP request set — cents per
month at any realistic scale.

**Observed churn.** TikTok replayed 3799, then 3798 eleven minutes later: one
job genuinely closed. That is 0.03% drift, and it is the only movement seen
across every re-run so far.

## 2. Method, and why the numbers are trustworthy

Discovery and replay are two code paths that never meet
(`scripts/one_off/recipe_spike/README.md`). `replay.py` calls
`assert_no_agent_imports()` before every run and refuses to execute if
`anthropic`, `openai`, `stagehand`, `browserbase`, or `langchain` is in
`sys.modules`. If replay could reach an agent, none of the above would mean
anything.

**Priors were deliberately withheld.** The sibling `job-watcher` repo already
scrapes Amazon and Meta, so each discovery agent was given only a URL and the
harness — never the known answer. Amazon's `search.json` endpoint and Meta's
GraphQL behaviour were re-derived from scratch. This measures discovery, not
recall.

**The invariants are proven, not asserted.** `test_invariants.py` runs offline
and checks all ten, currently 10/10:

```
incomplete harvest raises (got 10 of declared 4000)     vanished completeness oracle raises
zero records raises, never returns []                   count below expected_min_jobs raises
import guard fires if an LLM client leaks in            non-https entrypoint rejected
```

## 3. What each target actually turned out to be

- **meta** — one POST to `metacareers.com/graphql` (persisted query
  `CareersJobSearchResultsV2DataQuery`), whole catalogue in a single response,
  no pagination. The gate is **header plausibility, not authentication**: with
  sparse headers every request 400s, including plain GETs; with a full Chrome
  header block, a **completely made-up `lsd` token and zero cookies** returns
  200 and all 801 jobs. Fragility: `doc_id` rotates with Meta frontend
  releases — and fails *loudly* (400 → raise), never as a silent empty list.
- **tiktok** — `POST api.lifeattiktok.com/.../job/posts`. Exactly one header is
  load-bearing, established by removing them one at a time: `website-path:
  tiktok`. Without it, HTTP 400; with it alone and nothing else, a full 200.
- **janestreet** — a hand-rolled site that nonetheless serves
  `janestreet.com/jobs/main.json`, a flat array, no auth. Notable: the site's
  own UI silently defaults to a New York filter showing 94 roles; the recipe
  returns the full 225 across four offices — a superset of what a human sees.
- **spotify** — headless WordPress at
  `api.lifeatspotify.com/wp-json/animal/v1/job/search`. No pagination exists at
  all; `limit`/`page`/`offset` are ignored and the full set always returns.
- **amazon** — `search.json` with real `offset` paging (server caps
  `result_limit` at 100 and reports the violation as **HTTP 200 with a body
  error**, an errors-as-200 trap).
- **ycombinator** — no API; the jobs are a JSON island in an Inertia
  `data-page` attribute. The wrapper element's id is a per-render UUID, so the
  recipe selects on the attribute. This is strictly more durable than CSS
  selectors over Tailwind classes.
- **tesla** — see §6.

## 4. Frozen recipe schema v1

Implemented and validated by `scripts/one_off/recipe_spike/recipe_schema.py`,
which is the authoritative definition. 7.3 implements this contract.

```jsonc
{
  "recipe_version": 1,
  "kind": "http_json | http_html | browser_dom",   // ranked, see §5
  "entrypoint": { "method": "GET|POST", "url": "https://…", "headers": {}, "body": null },
  "pagination": { "style": "none|offset|page|cursor",
                  "param": "offset", "page_size": 100, "max_pages": 50 },
  "records_path": "data.job_post_list",            // dotted path to the array
  "total_path": "data.count",                      // OPTIONAL, see below
  "completeness_tolerance": 0.05,
  "fields": { "id": "…", "title": "…", "url": "…", "location": "…", "posted_at": "…" },
  "expected_min_jobs": 2000,
  "discovered_at": "…", "discovered_by": "…", "notes": ["…"]
}
```

Two extraction modes beyond a plain JSON endpoint:

```jsonc
// http_html — prefer a JSON island over CSS selectors wherever one exists
"embedded_json": { "selector": "div[data-page]", "source": "attribute",
                   "attribute": "data-page", "records_path": "props.jobPostings" }

// browser_dom — locate records by SHAPE, not by name
"capture": { "mode": "network_json", "url_contains": "/graphql",
             "records_shape_keys": ["title", "location"] }
```

Field values are dotted paths, or templates with `{dotted.path}` placeholders
(`"url": "https://www.amazon.jobs{job_path}"`).

**`total_path` is the most important thing this spike added.** Three targets
independently surfaced the same gap: `expected_min_jobs` catches a *collapse*
to near-zero, but nothing catches a scrape that quietly returns 100 of 4,000
jobs — the exact shape of the 2026-03-29 incident. `total_path` compares the
harvest against the source's own declared total and raises on a shortfall.
Where a source publishes a total, a recipe should be required to use it.

### Known gaps, deliberately deferred

Recorded so 7.3 inherits them as decisions rather than surprises:

- **No UI-scraped completeness oracle.** `total_path` only reads a total the
  *payload* publishes. Tesla's near-miss (§6) was a payload that published a
  perfectly consistent total for the *wrong board*. An assertion against a
  number scraped from the site's own page would catch that class; nothing
  currently does, except a human noticing.
- **No lookup-table joins.** `fields` resolves dotted paths within one record.
  Tesla ships compact rows (`"l":"401022"`) plus sidecar `lookup.*`
  dictionaries; a recipe can emit `location_id` but not `location`. Common
  enough to deserve a `lookups` block if the schema is revised.
- **No post-extraction transforms.** Jane Street's titles contain Lisu
  homoglyphs (`ꓟ` for `M`) as an anti-scrape measure; city codes need
  expanding. Id-keyed dedup is unaffected, but title-keyed matching is not.
- **`http_json` POSTs send JSON bodies only.** Meta needs form params, which
  worked by putting them in the query string. A `body_format: "form"` option
  would remove that workaround.
- **No sampled health check.** Nothing verifies that emitted job URLs still
  resolve; Jane Street's templated URLs would keep passing while emitting dead
  links if the site re-routed detail pages.

## 5. Recommendation: do not build `browser_dom`

Not one of the six working targets needed a browser at replay time, including
the two the whole design feared. The runner supports `browser_dom` because the
spike had to be able to reach that verdict honestly, but **7.3 should ship
without it** and add it only when a real target proves it necessary.

This is a direct, evidence-backed contradiction of the sibling repo:
`job-watcher` drives Playwright and intercepts Meta's GraphQL responses because
it never tried forging the request. Forging works. Carrying that assumption
into JVN would have imported a browser into the hot path for no reason.

If `browser_dom` is ever added: prefer `capture.mode=network_json` (load the
page, intercept its own JSON) over DOM scraping, and locate records by shape
rather than by operation name — a name-keyed match is what silently zeroed
job-watcher's Meta adapter for 41 days.

## 6. Tesla — the one that did not work, and why it strengthens §5

**NO RECIPE.** Tesla sits behind **Akamai Bot Manager**, positively identified
(`errors.edgesuite.net` reference URLs, `_abck`/`bm_*` cookies, an obfuscated
sensor POST). Full evidence: `captures/tesla/FINDINGS.md`, 16 probes.

The critical result is *which* clients get through, all from one machine and IP:

| Client | Result |
|---|---|
| httpx (any headers), curl, httpx + transplanted valid cookies | 403 |
| **Playwright bundled Chromium — headless *and* headed** | 403 |
| Real Google Chrome, headless | 403 |
| Real Google Chrome, headed, no input simulation | 403 |
| **Real Google Chrome, headed, + randomized mouse movement** | **200 — 7,597 jobs** |

Three consequences, and they matter more than the target itself:

1. **This is not a "a browser would fix it" case, so it does not argue for
   `browser_dom`.** The kind we already support — bundled headless Chromium —
   is on the *wrong side* of the line. A `browser_dom` recipe for Tesla would
   fail every single run. Supporting it would require a real Chrome binary
   **and** headed operation **and** synthetic input: an arms race with a
   behavioral sensor, not a deterministic replay. §5's recommendation stands
   and is strengthened.
2. ~~**A cloud browser would not have helped either.**~~ **RETRACTED
   2026-08-08 — this was wrong, and it was the one claim here made without
   running the experiment.** The reasoning was that since success and failure
   alternated on the same IP, the IP was never the discriminator, therefore a
   cloud browser changes nothing. The inference does not hold: Browserbase
   differs from local Playwright in browser build and fingerprint, not only in
   egress IP. Measured directly once credentials existed:

   | client, same machine and day | `tesla.com/careers/search/` |
   |---|---|
   | httpx, bare or with a Chrome UA | 403, 390 B |
   | local headless Chromium (Playwright) | "Access Denied", 1 request |
   | **Browserbase (Chrome 151, us-west-2)** | **200 — 87 requests, 7,639 listings** |

   Akamai's sensor POST returned **201**, so the sensor was accepted rather
   than merely tolerated, and `GET /cua-api/apps/careers/state` came back at
   1,462,763 bytes.

   **This does not change the recommendation, for a different reason than the
   one originally given.** The payload is not replayable: the same request
   403s from *inside the live session* via `page.request.get`, and 403s through
   httpx even carrying that session's full `_abck` / `bm_*` cookie jar and exact
   headers. Only the page's own JS-issued XHR succeeds. So a Tesla recipe can
   never be a stored request — it is "drive a cloud browser and intercept,"
   every run: roughly **8 browser-hours per company per month** at the 30-minute
   cadence. Point 3 below is what actually kills the cheap design, and it stands
   on measured evidence rather than inference.
3. **Cookie transplant fails.** Valid `_abck` cookies harvested from a trusted
   Chrome session still 403 through httpx — Akamai binds the session to the TLS
   fingerprint that earned it. Every "warm it once, then replay cheaply
   forever" design is dead for this class of site.

**The near-miss is the most valuable thing here.**
`www.tesla.cn/cua-api/apps/careers/state` answers plain httpx with a clean 200
and the same JSON shape. It holds **28 China-only jobs with zero overlap** with
the real 7,597-job board. A recipe built on it would have replayed green
forever — `OK 28 jobs` — while missing 99.6% of the company. That is the
2026-03-29 failure mode reproduced exactly, and it was caught only because the
agent cross-checked against Tesla's own published count (4,830 US, matched to
the unit). This is the strongest possible argument for §4's `total_path`
requirement, and for extending it (see below).

The product consequence is the honest one: **some sites will not be addable,
and the UX must say so at add time** rather than accept a URL that silently
never produces jobs. See §8.

## 7. Limitations — what this spike does NOT prove

1. **Durability is measured in hours, not 48 h.** Round 1 is recorded and every
   re-run so far agrees (max drift 0.03%). Rounds 2 and 3 were never run, and the
   `replay_round.sh` / `drift.py` harness that would have run them was deleted with
   the rest of the spike scratch (see `scripts/one_off/recipe_spike/README.md` —
   recover from git history at `a2fcd3c` if it is ever wanted). Replaying a round by
   hand is `replay.py --all`; the drift verdict was "flag anything over 5% against
   round 1". **This limitation was overtaken rather than closed:** the production
   port replays these recipes nightly behind the completeness gate, which is a
   stronger durability signal than three spike rounds would have been.
2. ~~**The Browserbase cloud-vs-local comparison never ran.**~~ **CLOSED
   2026-08-08 — it ran. The prediction recorded here was wrong** (see the
   retraction in §6): this section reasoned that a cloud browser "would have
   been refused for the same fingerprint and behavioral reasons," and Tesla
   returned **200** through Browserbase where local headless Chromium got
   "Access Denied." Recording the miss rather than quietly editing it, because
   the error was structural — a prediction stated with the confidence of a
   result, in the one arm that had not been executed.

   The measured verdict, on 14 real careers URLs (1.0 of ~60 free-tier minutes
   spent, $0):

   - **Network-level visibility is real.** Raw CDP `Network.*` events (167 on
     Tesla, 691 on Rippling) and response bodies read over the wire (up to
     2.3 MB). The "agent watching the dev-tools network tab" capability exists
     as advertised.
   - **But it identified no job board that plain HTTP could not.** Across six
     local Playwright captures the browser surfaced exactly one ATS reference
     that plain HTTP missed (Rippling — whose own ATS none of the six clients
     can scrape), and Browserbase added nothing over local Playwright on the
     non-blocked control. Sites proxy their ATS server-side, so the network tab
     shows first-party endpoints only.
   - **Where a browser earns its keep is recipe discovery, exactly as §5 said** —
     Rippling's data endpoint turned out to be Algolia and *is* forgeable over
     plain HTTP with the public search key from the page JS (702 hits, and
     `nbHits` is a ready-made `total_path`). One-time browser, zero browser at
     replay.
   - **Tesla remains a NO, for a better-evidenced reason than before**: the
     payload is not replayable at all (§6), so it is a browser every run.

   **Recommendation, revised but unchanged in outcome: do not adopt Browserbase
   for this feature.** The return is in deterministic coverage, not browsers —
   of 14 URLs, 7 already resolve, 5 more are matcher/heuristic gaps, 1 truly
   needs JS, 1 needs bot-bypass. Keep the account parked; the free tier is
   effectively untouched and preserves the option. The narrow Railway
   datacenter-IP question is still open and still answered more cheaply by
   running `replay.py` once from Railway.
3. **Seven targets is a small sample**, chosen to be hard rather than
   representative. It says nothing about the long tail of small ATS-less boards.
4. **No target published a reliable posted-at date** except Amazon and YC (YC's
   is a humanized string like "about 12 hours"). Meta, TikTok, Spotify and Jane
   Street publish none at all, so freshness for recipe-backed companies must
   come from our own `first_seen_at`, not the source.

## 8. What this changes for 7.3 and 7.4

- **7.3 (runtime)**: implement `http_json` + `http_html` only. Require
  `total_path` where a source publishes a total. Keep the raise-never-empty
  contract and the quarantine-before-close ordering exactly as specified — the
  spike's own transient network blip proved the runner raises correctly rather
  than reporting zero.
- **7.3 (where it runs)**: for HTTP-only recipes the Railway worker is fine;
  Playwright never enters the hot path. Revisit only if limitation §7.2 shows
  datacenter IPs being blocked.
- **7.4 (UX)**: "we can't track this site" is a real, expected outcome (Tesla),
  not an edge case. The add flow must be able to fail honestly at add time
  rather than accepting a URL that will never produce jobs.
- **Cost model**: discovery is ~10 s of local browser per company and one agent
  pass. At $0 measured, the economics that motivated this whole epic hold with
  enormous margin — there is no need for the daily-AI fallback tier that was
  left as a contingency.
