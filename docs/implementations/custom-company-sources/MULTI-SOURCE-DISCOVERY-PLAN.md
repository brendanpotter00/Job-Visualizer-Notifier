# Multi-source discovery: collect six sources, fan out, referee on measurements

**The one-line problem.** Discovery has exactly one source of evidence — network responses
with a JSON content-type — and everything it can ever know is whatever happened to be in
that list. Walmart's answer is not in it. Jane Street's was not in it either, and `f7733b7`
fixed that one case by adding a *second* source (the board's own JS bundle) for a *single*
purpose (link templates). This plan generalises that move: **more places to look, one
question per place, and a referee that decides on measurements instead of on rank.**

**What is out of scope, permanently.** An agentic tool-use loop. It was tried — a
Browserbase agent with a browser, a full tool loop and 75 steps was run against Walmart
live. It never fetched the sitemap and converged on the same chatbot endpoint the
deterministic pipeline did. No hook for one is left anywhere in this design.

---

## 0. What was re-measured before this plan was written

Every claim in the brief was checked against the code and against the live boards on
2026-08-29/30. **Four did not survive.** They are listed first because two of them change
what this work is for.

| claim | measured | verdict |
|---|---|---|
| Walmart's chatbot recipe is what discovery stores today | The stored row was written **2026-08-29 21:24:26 UTC**; `f7733b7` (which calls `page_shape_refusal` at synthesis) landed **2026-08-30 02:37 UTC**. Re-running `page_shape_refusal` on the stored fetch step returns **`page_param_unpaginated`** — `job_page` normalises to `jobpage`, which ends with the `page` suffix at `harvest_verification.py:252`. | **stale.** On HEAD that capture is REFUSED at synthesis. The row is a pre-fix artifact. |
| The sitemap oracle is only schema-admitted | `ORACLE_KINDS` at `recipe_schema.py:146`; shape validated at `recipe_schema.py:587-589`; **computed** at `recipe_runner.py:1058` (`_oracle_sitemap`); routed at `recipe_runner.py:1100-1105`; supplied an HTTP client on the browser tier at `browser_fetch/runner.py:398-403`; **verified** via `_PHASE_3_ORACLES` (`harvest_verification.py:191`) → `_verify_oracle_total` (`:572`). Unit-tested at `tests/test_oracles.py:197-249`. | **false — it is implemented end to end.** See §4 for the half that *is* missing. |
| Discovery cannot see that Walmart has 48,800 jobs | It already does. `_coverage` (`discover.py:805`) read `48,800` off the captured payload via `_totals_beside_records` (`:645`) and rendered it to the user: *"read 10 job(s), but this board's own response counts 48,800 job(s)"*. | **false.** The number is measured, displayed, and then **drives nothing**. |
| The DOM needs a little more work to be a record source | `browser_fetch` is hard-required to use `extract_json_path` (`recipe_schema.py:741-743`) because the subprocess returns raw JSON bodies, and every DOM transport (`page_fetch`/`page_request`/`dom`/`browser_dom`) is rejected as Phase 4 at `recipe_schema.py:86`. There is **no transport that can replay a rendered DOM**. | **false as stated.** Making the DOM a record source means a new browser transport. See §1.3 — it stays a *link* and *counting* source. |

Two further measurements that decided the design:

* **`careers.walmart.com/sitemap.xml`** — one plain GET, `HTTP 200`, **2,019,397 bytes**,
  **294 ms**, **16,210** `<loc>`, of which **15,660** match `/us/en/jobs/` (ids are
  `R-1075582`-shaped, not numeric). `robots.txt` is 197 bytes and names that sitemap
  explicitly. Not a `<sitemapindex>`.
* **Sitemap hit rate is roughly 1 in 4, and indexes are real.** `www.janestreet.com/sitemap.xml`
  → 404. `www.amazon.jobs/sitemap.xml` → 404. `higher.gs.com/sitemap.xml` → 404.
  `www.atlassian.com/sitemap.xml` → **200, but a `<sitemapindex>`** naming eight child
  sitemaps (products/solutions/resources/templates/customers/company/locales/other) —
  **none of which is jobs**. `_oracle_sitemap` does **not** follow a sitemapindex
  (`recipe_runner.py:1063-1072` counts any tag ending `}loc` at any depth), so on Atlassian
  it would count the eight child-sitemap URLs as eight "locs".

**So the problem restated correctly.** Walmart is no longer a wrong-store; it is a
**refusal**. The chatbot candidate dies at synthesis, and there is nothing else in the JSON
network list, so the board is refused entirely. The job of this work is to turn that
refusal into a correct store — and to make sure the referee has an oracle strong enough
that if a chatbot-shaped candidate ever *does* get past the shape checks, its 10-vs-15,660
disagreement kills it on evidence rather than on a hardcoded rule.

---

## 1. The source type, the six collectors, and their cost ceilings

### 1.0 The type

A **source** is a bag of bytes with a provenance and, crucially, a statement about *what
kind of contribution it can make*. That last part is the whole reason the type exists: it
is what lets the fan-out skip a model call, and what stops a sitemap from being proposed
as a jobs feed.

```python
# api/services/capture/sources.py  (new module)

Contribution = Literal["records", "oracle", "link_template", "id_set"]

@dataclass(frozen=True)
class EvidenceSource:
    kind: str                     # one of the six below
    origin: str                   # the URL these bytes came from — SSRF provenance + logs
    media: str                    # "json" | "html" | "xml" | "js" | "text"
    body: str                     # raw bytes as text (may be "")
    request: CapturedRequest|None # the replayable request, when one exists
    replay_transport: str|None    # "http_json" | "http_html" | "browser_fetch" | None
    contributions: frozenset[Contribution]
    note: str = ""                # why it was collected / why it is capped
```

`Candidate` (`request_selector.py:137`) is unchanged and stays the currency of the rest of
the pipeline. A source with `"records"` in `contributions` produces zero or more
`Candidate`s through a per-kind adapter; everything downstream — `select_candidates`,
`synthesize_recipe`, `_try_acceptance`, `_resolve_job_link` — keeps speaking `Candidate`
and needs no change to accept a candidate that came from HTML instead of from an XHR.

Two fields carry the load:

* **`replay_transport`** is what makes a source honest. A source with no transport can
  never produce a stored recipe, whatever the model says about it. This is the invariant
  that keeps the DOM out of the record path without needing a rule about the DOM.
* **`contributions`** is the fan-out's short-circuit. No `"records"` → no model call, ever.

### 1.1 Source 1 — XHR/fetch JSON responses  *(exists)*

`_capture_main._record` (`:236`), carried as `CapturedResponse` and pre-filtered by
`prefilter_candidates` (`request_selector.py:258`). Unchanged.

* Contributions: `records`, `oracle` (`declared_probed`, `facet_sum`), `id_set`
* Transport: `http_json`, falling back to `browser_fetch`
* Ceiling (existing): ≤ 40 responses, ≤ 4 MB each, ≤ 16 MB total, 24 s observation window
* Added cost: **none**

### 1.2 Source 2 — JSON islands embedded in the document  *(NEW)*

`__NEXT_DATA__`, `__remixContext`, `<script type="application/json">`,
`<script type="application/ld+json">`, and the `self.__next_f.push([...])` flight chunks.

**The split that matters, and it is not optional.** An island is a *record source* only if
it is in the **served** document, because `extract_embedded_island`
(`recipe_runner.py:781`) replays by issuing one plain GET and running a CSS selector over
the server's bytes. An island that only exists after hydration is not replayable by any
transport we admit, so it contributes `id_set` and nothing else.

* **Served-document islands** — extracted by the child from the body it *already has*.
  `_install_host_pin` calls `route.fetch(max_redirects=0)` (`_capture_main.py:169`) and
  throws the response away. Keep it.
  Contributions: `records`, `oracle`, `id_set`. Transport: `http_html` +
  `extract_embedded_island`.
* **Rendered-DOM islands** — extracted from `page.content()`, which the child already
  calls. Contributions: `id_set` only. Transport: `None`.

**The child stays dumb.** This is the same class of mechanical extraction as the existing
`_HREF_RE` / `_SCRIPT_SRC_RE` regexes (`_capture_main.py:135-139`): find `<script>` blocks
with a JSON-ish type or a known id, keep the blob and the CSS selector that would re-find
it, rank nothing. The child does not parse, does not score, does not choose.

* Ceiling: ≤ **8** islands per document, ≤ **2 MB** each, ≤ **6 MB** total across both
  documents, folded into the existing `_MAX_TOTAL_BODY_BYTES` accounting so raising this
  cannot raise the worst case
* Added cost: **0 network requests, 0 added wall clock.** Both documents are already in the
  child's memory. The cost is pipe bytes.

### 1.3 Source 3 — the rendered DOM  *(exists as links; extended to counting)*

Already carried as `board_links` / `board_scripts` (`network_capture.py:200-202`),
capped at 600 links / 20 scripts.

**What is needed for the DOM to be a RECORD source: a new browser transport, and that is
out of scope.** `browser_fetch` cannot carry markup (`recipe_schema.py:741`), every
DOM transport is a rejected Phase-4 capability (`recipe_schema.py:86`), and inventing one
would put a Chromium render on the nightly path for every such board — the exact cost the
capture pivot exists to avoid. Say no, and say why, rather than half-building it.

**What the DOM becomes instead: a counting source.** A rendered page carrying 233 hrefs
that match a per-job shape is a published lower bound on the board's size, and it is
already in `board_links`. It joins `_coverage`'s claim list (§3.4) as a **floor only**,
and only when the link count is strictly under `_MAX_BOARD_LINKS` — at the cap the number
is ours, not the board's.

* Contributions: `link_template` (today), `id_set` (new)
* Transport: `None`
* Added cost: **none**

### 1.4 Source 4 — same-origin JS bundles  *(exists)*

`board_scripts` + `_JobLinkContext.code_templates` (`discover.py:1748`). Unchanged.
≤ `_MAX_SCRIPT_FETCHES` (5) same-host script bodies, once per discovery, inside the shared
`_LINK_RESOLUTION_BUDGET_S` (75 s), through the SSRF-guarded `ProbeFn`.

* Contributions: `link_template`
* Added cost: **none**

### 1.5 Source 5 — well-known paths, fetched by convention  *(NEW — the Walmart source)*

The one source no amount of watching network traffic can produce, because the page never
requests it. A **fixed** list, composed from the entry origin, fetched through
`guarded_sync_client` exactly the way `_default_probe` does (`discover.py:1525`).

| order | path | cap | why |
|---|---|---|---|
| 1 | `/robots.txt` | 256 KB | measured 197 B on Walmart. Read **only** for its `Sitemap:` lines. |
| 2 | each `Sitemap:` URL robots names, then `/sitemap.xml` if it named none | ≤ 4 documents, 4 MB each | measured 2.0 MB / 294 ms on Walmart |
| 3 | one level of `<sitemapindex>` expansion, children whose URL contains `job`/`career`/`position`/`opening` first | counts against the same ≤ 4 | Atlassian proves indexes are real; without this the oracle counts child-sitemap URLs as jobs |
| 4 | `/jobs.json`, `/feed`, `/api/jobs` | 4 MB each | speculative — see the honesty note |

**Honesty note on row 4.** Rows 1-3 have measured evidence behind them. Rows 4 do not: I
found no board in this repo's corpus where any of the three exists. They cost three GETs
that 404 in well under a second, so they are cheap enough to keep, but nobody should be
told this plan is about `/jobs.json`. **The sitemap pair is the source that earns this
whole section.**

**`robots.txt` is read, never obeyed as a gate.** Walmart's `Disallow: /api` covers the
exact GraphQL endpoint its own careers page uses; treating a disallow as a refusal would
kill boards we can read. Record it as evidence and move on.

* Contributions: `oracle` (`sitemap`), `id_set`. **NOT `records`** — see §1.7.
* Transport: `None` for records; the stored `sitemap` oracle re-fetches at harvest time
* Ceiling: ≤ **7 requests**, ≤ **12 MB total**, **15 s wall clock**, every URL through
  `guarded_sync_client`
* Added cost: **0 added wall clock.** These need only the entry URL and httpx, both
  available before the browser subprocess is spawned, so the collector runs
  `asyncio.gather`-concurrently with `do_capture`, which takes 30-120 s. The 15 s ceiling
  is inside the browser's shadow.

### 1.6 Source 6 — server-rendered HTML  *(NEW)*

The served document body, which the child **already fetches and discards** at
`_capture_main.py:169`. Carried back as `server_html`.

This is the mirror of the `BIRTH-DEFECTS-PLAN.md §0` finding, and the mirror is the point:
that plan established the served body is the *wrong* bytes for link derivation, because
client-rendered boards put their anchors in the DOM. It is the *right* bytes here, because
`http_html` replay will fetch exactly these bytes every night. **The replay transport
decides which bytes are the right evidence.**

* Contributions: `records`, `oracle` (`header`), `id_set`
* Transport: `http_html` + `extract_css` (`recipe_runner.py:818`) — **implemented, and
  discovery has never emitted it**
* Ceiling: ≤ **2 MB** of markup through the pipe (a careers page is routinely 1-2 MB)
* Added cost: **0 network requests, 0 added wall clock.** Pipe bytes only.
* **Known limit, stated up front:** `validate_recipe` forbids any pagination step on
  `http_html` (`recipe_schema.py:727-738`), because `_run_http_html` reports a one-request
  read as a clean complete sweep. So a server-HTML candidate wins only on a board whose
  whole list is on one server-rendered page. That is a small set. It is also exactly the
  set where `http_html` is safe, and widening it means fixing `_run_http_html`, which is a
  different piece of work.

### 1.7 What each source can and cannot do — the table the fan-out reads

| # | source | records? | oracle | link tmpl | id set | replay transport | new network |
|---|---|---|---|---|---|---|---|
| 1 | XHR/fetch JSON | **yes** | `declared_probed`, `facet_sum` | — | yes | `http_json` / `browser_fetch` | 0 |
| 2a | island in **served** doc | **yes** | `declared_probed` | — | yes | `http_html` + `extract_embedded_island` | 0 |
| 2b | island in **rendered** DOM | no | — | — | yes | none | 0 |
| 3 | rendered DOM | **no** | — | yes | yes (floor) | none | 0 |
| 4 | same-origin JS bundles | no | — | yes | — | none | ≤5 (existing) |
| 5 | well-known paths | **no** | **`sitemap`** | — | **yes** | none | ≤7 |
| 6 | server-rendered HTML | **yes** | `header` | — | yes | `http_html` + `extract_css` | 0 |

**Why the sitemap is not a record source, said plainly.** `CANONICAL_REQUIRED_FIELDS` is
`(id, title, url)` (`recipe_schema.py:123`) and `map_records` drops any row missing an id
or a title. A `<loc>` gives an id and a URL and **no title**. Walmart's sitemap has no
`<news:title>` and no JobPosting extension. So the sitemap can enumerate the board
perfectly and still never *be* the board. Anyone hoping this plan makes Walmart trackable
by reading the sitemap should stop here: it makes Walmart's *wrong answers detectable*,
and it supplies an oracle. Whether Walmart has a real paginated jobs API among its three
captured GraphQL POSTs is **unverified** — see §8, Risk R1.

**Total added cost of collecting all six: ≤ 7 network requests, ≤ 12 MB, 0 s added wall
clock, $0 of model spend.** All of it deterministic code.

---

## 2. Fan-out — one model call per record-bearing candidate

### 2.1 Today

One `select_request` call per round (`request_selector.py:1582`), ≤ 2 rounds
(`_MAX_SELECTION_ROUNDS`). It sees up to `_MAX_CANDIDATES` = 6 candidates rendered by
`_describe` (`:529`): a URL line, records_path + count, ≤ 40 record keys, ≤ 30 query
params, and ≤ 2 sample records at 700 chars each. The model's job is **ranking plus
mapping in one answer** — pick the index, then map the fields.

Measured prompt size: system ≈ 4.9 KB, listing ≈ 6 × 1.7 KB ≈ 10 KB → **≈ 4k input tokens,
≤ 1,024 output** per call.

### 2.2 The change

**One call per record-bearing CANDIDATE, not per source kind.** This is the important
detail and the brief's phrasing under-specifies it: today's crowding-out happens *within*
source 1 — a chatbot response and a real jobs response are both XHR JSON. Fanning out per
source *kind* would put them back in the same prompt and change nothing.

Each call sees exactly one array and answers a strictly simpler question:

> Here is one array of records from `<method> <url>` (or from `<selector>` in the page's
> HTML). **Is this a list of job postings — yes or no?** If yes, map it to
> `{id, title, url, location, posted_at, description}` using dotted paths that appear in
> these records, and name a paging parameter only if you can see one.

Gone from the prompt: `chosen_request_index`, the whole "choose the ONE response" ranking
paragraph, and the `*`-vs-concrete grouped-path instruction (which becomes a deterministic
post-step — `_widen_to_union` at `discover.py:1382` already does it).

New schema field: `is_jobs_feed: bool` plus `confidence: "high"|"low"`. `false` short-
circuits with no field map, which is today's `NoJobsFeedError` restated per-candidate
instead of per-list — and it becomes *cheap* to say no, because saying no about one array
does not forfeit the board.

**Per-call context: ≈ 1 candidate description (1.7 KB) + a ~3 KB system prompt ≈ 1.3k input
tokens, ≤ 400 output.**

### 2.3 Short-circuit — sources that never get a call

No model call is made when:

1. `"records" not in source.contributions` — sources 2b, 3, 4, 5 never cost a token. This
   is the type doing the work.
2. `prefilter_candidates` scored the array below `_MIN_JOB_SCORE` — the existing
   deterministic filter, unchanged.
3. The array is a **known non-feed shape** by structure: fewer than 2 records *and* the
   containing request carries a conversational session key (see §3.5).
4. The candidate is byte-identical to one already asked about this run (islands frequently
   duplicate an XHR payload — dedupe on `sha256(records_json)`).

### 2.4 Concurrency, budget, and total spend

* `asyncio.gather` over the calls with a semaphore of **6** concurrent, existing
  `LLM_TIMEOUT_SECONDS = 30.0` per call.
* Hard cap **`_MAX_FANOUT_CALLS = 10`** per round, candidates offered in
  `prefilter_candidates` rank order so the cap truncates the least job-shaped tail.
* A call that raises or times out **kills that candidate only**, never the discovery. This
  is a strict robustness gain over today, where one bad answer burns a whole round.
* Rounds: `_MAX_SELECTION_ROUNDS` stays 2. Round two is now genuinely different — it
  re-asks only the candidates that *failed acceptance*, with the measured feedback
  attached (the mechanism `f7733b7` built).

| | today (worst case) | fan-out (worst case, N=10) |
|---|---|---|
| calls | 2 | 20 |
| input tokens | ~8k | ~26k |
| output tokens | ~2k | ~8k |
| **Haiku 4.5 cost** ($1/$5 per MTok) | **≈ $0.018** | **≈ $0.066** |
| wall clock (model) | ~2 × 3 s | ~2 × 4 s (parallel) |

**Delta the user pays per add: about +5 cents, worst case; typically +2 cents.** Wall
clock is roughly flat because the calls are parallel and the slow parts of discovery
(browser capture, acceptance replays) do not move.

**Acceptance cost does NOT multiply by N.** The referee ranks first and the acceptance
ladder still runs in rank order and **stops at the first acceptance** — exactly today's
loop at `discover.py:2419-2477`. N candidates produce N *mappings*, not N replays.

### 2.5 When several candidates come back "yes"

That is the referee's job, and it is the next section. The short version: they are ranked
on measurements, not on the model's confidence, and the model's `confidence` field is used
only as the final tie-break after every measurement has tied.

---

## 3. The referee — code MEASURES, the model INTERPRETS

### 3.1 The rule

**A check becomes model-interpreted if and only if one observation has two opposite
meanings and code cannot tell which without guessing.** Everything else stays code.
Symmetry is not a reason. `_prove_job_link` has exactly one interpretation and worked
unchanged on Goldman, Jane Street, Walmart and Kakao — it must not be touched.

**The interpreter may only ever make a verdict STRICTER or leave it unchanged.** It can
refuse, it can downgrade an accept to partial, it can never turn a code refusal into an
accept. This is the same discipline `page_shape_refusal` states about itself
(`harvest_verification.py:310-311`), and it is what keeps never-wrong-close intact when
the model is wrong or unavailable: an interpreter that fails is a refusal, and a refusal
stores nothing.

### 3.2 The table — every check, named

| # | check | where | measured by code | interpreted by model? | why |
|---|---|---|---|---|---|
| C1 | SSRF on entry + every discovered endpoint | `url_guard`, `_public_candidates` | pass/fail | **no** | a security boundary is never a judgement call |
| C2 | pre-filter job-shape score | `prefilter_candidates:258` | int score | **no** | it only ever *proposes*; the model already re-decides |
| C3 | records_path resolves; required fields render scalars | `_validate_field_map:636` | resolves / does not | **no** | one meaning |
| C4 | optional-field null-rate | `_prune_unusable_optionals:1236` | `useful`-count over 20 records | **no** | "renders nothing on 20/20" has one meaning |
| C5 | optional-field distinctness (`description`) | same | distinct-count over 20 | **no** | one meaning, and the constant's docstring already argues why the list has one member |
| C6 | `_prove_job_link` — two real jobs, compare pages | `discover.py:1612` | status, two page-text lengths, title containment | **no — do not touch** | one interpretation; worked unchanged on 4 boards; the failure mode is a *degrade*, not a close |
| C7 | acceptance id-overlap vs capture | `_assert_matches_capture:1916` | overlap ratio | **no** | one meaning |
| C8 | page size honoured | `_assert_page_size_honoured:1943` | `pages_fetched`, `terminated_cleanly` | **no** | one meaning, and it is already a `_PageSizeRefusal` that only costs an attempt |
| C9 | request-shape page tell (13a/13b) | `page_shape_refusal:305` | param names + values | **no** | pure, stricter-only, already correct |
| C10 | in-band error keys | `_inband_error_keys:511` | key presence | **no** | one meaning |
| C11 | declared-total trust (`hits` vs facet consensus) | `_facet_consensus_total:562` | two ints | **no** | the *rule* (largest wins, consensus vetoes) is already right |
| **C12** | **pagination outcome — "page 2 returned 0 new ids"** | new, in acceptance | page-2 status; new-id count; response-byte diff; whether the request actually changed; declared total if any | **YES** | one observation, two opposite meanings — see §3.3 |
| **C13** | **oracle-vs-candidate disagreement, in the ambiguous band** | new, §3.4 | candidate reachable count; every published claim | **YES, band only** | a 1,566× gap has one meaning and code refuses it; 233 vs 240 does not |
| C14 | coverage floor (hard) | `_coverage:805`, promoted | reachable / largest claim | **no** | below the floor there is nothing to interpret |
| C15 | session-bound request token | new, §3.5 | key-name match in the body | **no** — a *ranking penalty*, not a verdict | code cannot prove a session key is fatal, so it must not decide; it demotes and feeds C13 |

**Two checks become model-interpreted. Thirteen stay code.** That ratio is the design.

### 3.3 C12 — the pagination ambiguity, stated accurately

The brief's worked example is right in principle and **does not currently arise**, and it
is worth being precise about why, because it changes when this work is needed.

Discovery only adds a paginate step when `selection.pagination is not None`
(`discover.py:1163`) — i.e. when the model saw an actual paging parameter. Jane Street has
none, so no step is added, the oracle is `none`, and the board is UNVERIFIED forever: it
shows its 233 jobs every night and closes nothing. **Today's code does not guess. It
declines to page, and the decline is safe.**

The ambiguity becomes real the moment sources multiply, in exactly one shape:

> a candidate whose request carries a page parameter, the board publishes **no** total,
> and page 2 comes back with 0 new ids.

Then: either the parameter is decorative and the board is one page (store, oracle `none`),
or the parameter is real and page 2 is empty because the recipe asks wrong (a sweep that
terminates "cleanly" on a short page → `self_consistent` → **VERIFIED → closes the rest**).
That second branch is an invariant-#2 wrong-close, and code has no way to pick.

**The split.** Code measures, in one extra acceptance replay it already does:

```
page2_status, page2_new_ids, page2_bytes_vs_page1, request_actually_changed,
declared_total (or None), page1_count, sitemap_count (or None), dom_link_floor (or None)
```

The model is handed **only those numbers** — never a payload, never bytes — and returns
one of `{healthy_multipage, single_page_board, pagination_broken, unknown}` plus a reason.
Mapping:

* `healthy_multipage` → keep the paginate step (code re-checks C8 anyway)
* `single_page_board` → **drop the paginate step and force `oracle: "none"`.** Strictly
  safer than today: `none` can never close.
* `pagination_broken` or `unknown` → **refuse this candidate**, try the next
* interpreter unavailable / raised / timed out → treated as `unknown` → refuse

Note every branch is a refusal or a *weaker* claim. The model cannot license a close.

### 3.4 C13/C14 — the oracle disagreement, and why Walmart falls out

`_coverage` already collects every count the board publishes about itself
(`discover.py:805-828`): `_totals_beside_records`, `_facet_consensus_total`,
`_labelled_facet_total`. **Two changes.**

**(a) Add the cross-source claims.** The sitemap's matching-`<loc>` count and the DOM's
per-job-href floor join that list. This is the mechanism by which a source contributes an
oracle to a candidate derived from a *different* source: `claims` is a list of published
lower bounds about *the board*, and nothing about it cares which source produced a bound.

**(b) Promote `is_partial` from a banner to a gate.** Today `coverage.is_partial` writes a
log line and a UI sentence (`discover.py:2493-2545`) and the recipe is stored anyway. Add a
hard floor:

```python
_COVERAGE_REFUSAL_RATIO = 0.10   # reach <10% of the largest published claim -> REFUSE
```

Between the floor and `_MIN_CAPTURE_COVERAGE` (0.9) is the **ambiguous band**, and that is
the only place C13's model call fires: *"the candidate reaches 233; the board's own facets
say 240; the sitemap says 236 — is this the board, a slice of it, or is the oracle counting
something else?"* Above 0.9 it is accepted; below 0.10 it is refused; code decides both
ends.

**Walmart, worked through.** Reachable 10, claims `{48,800 (payload), 15,660 (sitemap)}` →
ratio 0.0002 → **refused by code, no model call.** And it is refused for a reason the user
can act on ("this board publishes 15,660 jobs and the feed we found returns 10") rather
than for a request-shape technicality. The disagreement is what makes the wrong answer
detectably wrong, and the disagreement is *arithmetic*.

### 3.5 C15 — the session-bound request penalty

Walmart's stored fetch body carries `thread_id: "S-1788038636412-<uuid>"`. The embedded
epoch-ms decodes to **2026-08-29 21:23:56 UTC — six seconds after the company row was
created**. It was minted inside that one discovery browser session, and it is the defining
property of a chat reply masquerading as a jobs API.

Detector (code, deterministic): any body leaf whose normalised key is in
`{threadid, sessionid, conversationid, chatid, correlationid, requestid, traceid}`.
`iter_body_params` already walks bodies for `page_shape_refusal`, so this is one predicate,
not a new walker.

**It is a ranking demotion and a C13 input, never a refusal.** Code cannot prove a session
key is fatal — plenty of boards send a correlation id that the server ignores — and a
recipe carrying one *passes acceptance by construction*, because acceptance runs minutes
later while the token is still alive. This is textbook birth-defect shape, and the honest
handling is: demote it below every candidate without one, and tell C13 about it.

### 3.6 The referee's order of operations

```
for each candidate (rank order):
  1. hard code gates          C1 C3 C9 C15-demote            -> dead or ranked
  2. rank on measurements     coverage ratio  >  oracle strength  >  transport
                              (http_json > browser_fetch > http_html)  >  job_score
  3. acceptance ladder        unchanged: transports x page sizes, first win stops
  4. code gates on the reply  C7 C8 C10  + C4 C5 prune + C6 link proof (degrade only)
  5. C14 coverage floor       below 0.10 -> refuse this candidate, next
  6. C13 band interpreter     only when 0.10 <= ratio < 0.90
  7. C12 pagination interpreter  only when (page param) and (no declared total)
  -> store, or next candidate
```

Steps 6 and 7 are **at most two model calls for the whole discovery**, not per candidate:
they run once, on the candidate that has already won acceptance. Add ≈ 800 input / 200
output tokens each — under half a cent.

---

## 4. The sitemap oracle: implemented, unreachable, and only half-usable

### 4.1 The finding

**Implemented end to end at replay time. Never emitted by discovery.**

| layer | status | evidence |
|---|---|---|
| admitted by schema | yes | `recipe_schema.py:146` (`ORACLE_KINDS`) |
| shape validated | yes | `recipe_schema.py:587-589` — `sitemap_url` must be https, `url_pattern` a non-empty string |
| computed at replay (http) | yes | `recipe_runner.py:1058` `_oracle_sitemap`; routed at `:1100-1105` |
| computed at replay (browser tier) | yes | `browser_fetch/runner.py:398-403` — passes an http client only when the oracle needs one |
| verified into a verdict | yes | `harvest_verification.py:191` `_PHASE_3_ORACLES` → `:572` `_verify_oracle_total` |
| unit-tested | yes | `tests/test_oracles.py:197-249`; `tests/test_harvest_gate.py:227-236` |
| **emitted by discovery** | **NO** | `discover.py:1235-1241` — the oracle decision can only ever produce `declared_probed`, `self_consistent` or `none` |
| storable without a migration | yes | `company_scripts.oracle_kind` is plain `Text NOT NULL`, no CHECK (`db_models.py:783`, migration `fb8467065dfc`) |

So the answer to "implemented or only schema-admitted" is: **implemented, and orphaned at
the one place that could produce one.** The gap is three lines in `synthesize_recipe`, not
a subsystem.

### 4.2 The gap that is not three lines

`_verify_oracle_total` is **tolerance 0** (`harvest_verification.py:572-604`). A sitemap
oracle VERIFIES only when tonight's post-dedup count *exactly equals* the `<loc>` count. On
a 15,660-entry sitemap that is essentially never true — sitemaps lag, and a five-job drift
gives `count_mismatch` → UNVERIFIED → never closes.

That is **safe** (UNVERIFIED shows every job and closes none) but it is **worse than
useless on a big board**: it replaces a `self_consistent` oracle that *can* verify with one
that structurally cannot. So the attachment rule has to be conservative:

```
attach oracle {kind: "sitemap", sitemap_url, url_pattern} IFF
  (a) id overlap: >= _MIN_ID_OVERLAP_RATIO of the candidate's captured ids appear in the
      sitemap's extracted id set          -> proves it is the same board
  (b) exact agreement: the acceptance replay's reachable count == the <loc> count
                                          -> proves the oracle is usable at tolerance 0
otherwise: keep the oracle discovery would have chosen, and record the sitemap count as a
           coverage claim + as evidence on the row.
```

**Both conditions are required and they answer different questions.** Overlap alone does
not kill Walmart's chatbot — it returns *real* Walmart job ids, so 10 of 10 would be found
in the sitemap. **The count is what kills it.** Overlap proves same-board; count proves
whole-board.

### 4.3 One bug to fix while we are here

`_oracle_sitemap` (`recipe_runner.py:1063-1072`) iterates every element whose tag ends
`}loc` at any depth. In a `<sitemapindex>` those are child *sitemap* URLs, not pages.
Measured on Atlassian: eight of them. A `url_pattern` loose enough to match a child sitemap
name would be counted as eight jobs; a tight one raises `0 <loc> matching` and FAILS the
run. Neither is right. Fix: detect `<sitemapindex>` and either follow one level (bounded,
guarded) or raise a named error. This is a replay-path change and needs its own test.

---

## 5. Migration needs

**None.**

* `company_scripts.transport` and `.oracle_kind` are plain `Text NOT NULL` with no CHECK
  constraint and no enum (`db_models.py:781-783`, migration `fb8467065dfc`). `sitemap` and
  `http_html` are already legal values on disk; `TRANSPORTS` and `ORACLE_KINDS` already
  admit both.
* Collected-source provenance and referee measurements go into the existing
  `companies.provider_config -> discovery` JSONB blob, which already carries the progress
  ledger.
* `RECIPE_VERSION` does **not** move: no stored recipe shape changes. A recipe emitted by
  this work uses ops that `validate_recipe` and `recipe_runner` already implement.

The single-Alembic-head invariant is untouched because nothing is added.

---

## 6. Test plan

### 6.1 Unit — new

| file | covers |
|---|---|
| `test_capture_sources.py` (new) | the `EvidenceSource` type; each collector at its ceiling; a source with no `records` contribution never reaches the fan-out; the served-vs-rendered island split; the DOM link count is a floor only under `_MAX_BOARD_LINKS` |
| `test_wellknown_collector.py` (new) | robots parsed for `Sitemap:` only, never as a gate; sitemapindex followed exactly one level; caps enforced (7 requests / 12 MB / 15 s); **every composed URL goes through `guarded_sync_client`** (assert on an injected client, the same seam `_default_probe` uses); a 404 on all seven is not an error |
| `test_capture_fanout.py` (new) | N calls for N record-bearing candidates and zero for the rest; identical-payload dedupe; one call raising kills one candidate not the run; the semaphore bounds concurrency; `_MAX_FANOUT_CALLS` truncates in rank order |
| `test_referee.py` (new) | the rank order of §3.6; the C14 floor refuses at ratio < 0.10 with **no** model call; the band calls the interpreter exactly once; **the interpreter can only make a verdict stricter** (a fixture returning "this is fine" over a code refusal must still refuse); interpreter timeout ⇒ refuse |
| `test_sitemap_oracle_attach.py` (new) | attach only on overlap **and** exact count; non-exact ⇒ oracle unchanged + claim recorded; `<sitemapindex>` handling in `_oracle_sitemap` |

### 6.2 Unit — existing files that gain cases

* `test_capture_discover.py` — a Walmart-shaped fixture (10 records, 48,800 payload total,
  15,660 sitemap) **refuses at the coverage floor**; an `http_html` candidate synthesises
  and validates; C12's three branches; C15 demotes but never refuses.
* `test_request_selector.py` — the new per-candidate prompt and `is_jobs_feed: false`
  short-circuit; `build_message_params` remains the single source of truth for the request
  shape.
* `test_recipe_schema.py` — `http_html` + `extract_css` / `extract_embedded_island` emitted
  by discovery round-trips; `http_html` + any paginate step still refuses.
* `test_oracles.py` — sitemapindex.
* `test_network_capture.py` — `server_html` and island fields degrade to empty on a report
  from an older child (the same tolerance `board_links`/`board_scripts` already have,
  `network_capture.py:603`).

### 6.3 Mutation targets

The checks whose *inversion must fail a test*, because each one silently wrong-closes:

1. flip `_COVERAGE_REFUSAL_RATIO` comparison → the Walmart fixture must stop refusing
2. make the C13/C12 interpreter able to **upgrade** a verdict → `test_referee.py` fails
3. drop condition (b) from the sitemap attach → a big-board fixture stores a
   permanently-mismatching oracle
4. remove `guarded_sync_client` from the well-known collector → SSRF test fails
5. let a source without `"records"` reach the fan-out → the sitemap gets a model call
6. allow `http_html` + pagination → the existing `recipe_schema` landmine test fails
7. drop the served-vs-rendered island split → an unreplayable island becomes a recipe

### 6.4 e2e — which cases change, and how

Cases that run discovery are **AC-04 (Atlassian)** and **AC-05 (Jane Street)**, both through
`_run_discovery_case` in `e2e/add-companies/api/test_discovery.py`, so every line below
fires twice. AC-06/11/12 also run discovery and inherit the latency risk.

| location | today | after | action |
|---|---|---|---|
| `test_discovery.py:149-154` | `script["transport"] == "http_json"` | may be `http_html` | widen to a set, assert per-board |
| `:185-188` | `(extract,) = [st for st in steps if st["op"] == "extract_json_path"]` | **raises ValueError** on a non-JSON extraction | select on `_EXTRACTION_OPS` |
| `:191` | `extract["fields"]["url"]` | `extract_css` uses `field_selectors` | branch on the op |
| `:101-105` | `oracle_kind == "none"` | a sitemap or island total can change it | assert per-board, not globally |
| `:106-123` | `VERIFIED/history_delta_ok`, `declared_total is None`, `healthState healthy` | follows the oracle above | same |
| `:170-177` | `with_posted_on == 0` for every row | **most likely to fire** — an island or `lastmod` gives these two dateless boards a date | relax to "≥0" with a per-board expected value |
| `:24, 138-142` | `step_keys == EXPECTED_STEP_KEYS` — **exact set equality** | any new checklist rung breaks it | **do not add a rung.** Source collection runs inside `open_page`; the fan-out inside `find_feed`. Keep five steps. |
| `:75-77`, `test_public_match.py:98-101`, `test_lifecycle.py:250`, `test_already_public.py:30,135`, `run.sh:209`, `checklist.spec.ts:36-38` | 240 s / 280 s budgets | +0-5 s expected | leave alone; **treat any increase as a regression**, since sources 5/6 are concurrent and the fan-out is parallel |
| `CASES.md:265-291` | "14-17 `POST /v1/messages` per run, ≤ ~$0.17/run" | roughly 3-4× the calls | update the prose table with the measured new numbers |

**One new e2e case is worth adding: AC-16, Walmart, live, expected REFUSE** with reason
naming the coverage gap. It costs one capture and proves the whole chain — because a
refusal we can *explain* is the correct outcome for that board until §8/R1 is answered.

---

## 7. Staged sequence — each stage ships alone, tests green

> The order is deliberate: **the first three stages fix Walmart's detectability with no
> model change, no new transport, and no storage change.** Everything after that is
> capability, not safety.

**S1 — Promote coverage from a banner to a gate.** `_COVERAGE_REFUSAL_RATIO`; refuse below
it with a user-legible reason. No new source, no model call, no schema change.
*Ships when:* `test_capture_discover.py` has a Walmart-shaped refusal case and AC-04/05 are
untouched. ~1 day.

**S2 — Source 5, feeding `_coverage.claims`.** The well-known collector, concurrent with
capture, through `guarded_sync_client`. Sitemap count becomes a published claim. **Walmart
now refuses on the sitemap's evidence, not only on the payload's.**
*Ships when:* `test_wellknown_collector.py` green, e2e wall clock unmoved. ~2 days.

**S3 — The sitemap as a stored oracle.** The attach rule (§4.2), plus the `<sitemapindex>`
fix in `_oracle_sitemap`. First stage that touches the replay path — it gets its own
review. ~1-2 days.

**S4 — Sources 2 and 6, as candidates.** The child carries the served document and the
island blobs; the parent builds `http_html` candidates and emits `extract_embedded_island`
/ `extract_css`. Two implemented-but-dead replay paths come alive.
*Ships when:* the e2e assertions in §6.4 are widened first, in their own commit. ~3 days.

**S5 — Fan-out.** One call per record-bearing candidate; new per-candidate prompt;
`asyncio.gather` + semaphore; the referee's rank order (§3.6) with **no interpreter yet** —
ambiguity resolves conservatively (refuse) until S6.
*Ships when:* `test_capture_fanout.py` + `test_referee.py` green and the e2e call-count
prose is updated. ~3 days.

**S6 — The two interpreted checks.** C12 and C13's band, stricter-only, measurements-only
prompts. The last stage because it is the only one whose failure mode is a *judgement*, and
by S5 everything it could get wrong already defaults to a refusal. ~2 days.

---

## 8. Risks, and what I would cut first

**R1 — Walmart may still be untrackable, and this plan does not promise otherwise.**
The sitemap has no titles, so it cannot be the record source. Whether a real paginated jobs
API exists among the three captured `careers.walmart.com/api/graphql` POSTs is **unverified
by me** — the capture is not in the DB and confirming it needs a browser run. *Mitigation:*
S1-S3 make the refusal correct and explained either way; run one live capture against
Walmart before S4 and record the answer in this doc. **Do not let S4 be justified by
Walmart until that is done.**

**R2 — Tolerance-0 makes the sitemap oracle a near-no-op on big boards.** §4.2. Mitigated
by the conservative attach rule; the real fix (a small tolerance for sitemap oracles) is a
`harvest_verification` change with close-safety implications and is deliberately **not** in
this plan.

**R3 — `http_html` cannot paginate.** A server-HTML or island candidate is single-page-only
by schema (`recipe_schema.py:727`). S4's win is narrower than it looks. Accepted, not fixed.

**R4 — Fan-out multiplies rate-limit exposure.** 10 concurrent Haiku calls per round.
Mitigated by the semaphore (6) and per-call failure isolation, which is a net robustness
*gain* over today's all-or-nothing single call.

**R5 — Pipe pressure from sources 2 and 6.** Up to 8 MB more across the subprocess pipe.
Folded into the existing `_MAX_TOTAL_BODY_BYTES` accounting so the worst case does not move.

**R6 — e2e drift.** Ten assertions in `test_discovery.py` encode "one JSON network source".
Widening them is a separate commit that ships *before* S4, or S4 lands red.

**R7 — The interpreter is a new way to be wrong.** Bounded by stricter-only + refuse-on-
failure. Worst case is a refused board, never a wrong-close.

### What I would cut first, in order

1. **S6** — the two interpreted checks. Without them ambiguity refuses, which is the safe
   answer and costs only boards we would have half-read anyway. **Cut this first; it is the
   most interesting part of the plan and the least load-bearing.**
2. **The `/jobs.json`, `/feed`, `/api/jobs` probes** — zero measured evidence (§1.5).
3. **S4** — sources 2 and 6. Real capability, narrow reach (R3), and the most e2e churn.
4. **S5** — the fan-out. It is the elegant fix for crowding-out, but S1's coverage floor
   already kills the specific crowding-out case we can actually name.

**What I would not cut, at any pressure: S1 and S2.** Together they are about three days,
they need no model, no migration and no new transport, and they turn "we tracked 10 jobs of
Walmart" into "we can prove this feed is 0.02% of this board". That is the entire safety
value of this document.
