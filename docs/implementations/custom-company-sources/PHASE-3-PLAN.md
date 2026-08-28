# Phase 3 — stored HTTP scripts + one-time discovery (partly shipped, partly retired)

> ## ⚠️ HALF LIVE, HALF REPLACED — read the split before you trust a section
>
> **Shipped and running (still the design):** **§3** the closed primitive vocabulary / script
> schema (`services/recipe_schema.py`), **§4** the deterministic agent-free replay engine
> (`services/recipe_runner.py`), **§5** the richer oracles (`facet_sum`/`header`/`sitemap` in
> `harvest_verification.py`). Storage columns, gate integration and the `HarvestEvidence`
> contract all landed as written.
>
> **Replaced, describes nothing running:** **§1**'s spend model and **§6**'s discovery
> architecture. §6's `services/discovery/observer.py` (local Playwright observe) +
> `author.py` (Sonnet authors the whole JSON recipe) were **built, then swapped for
> Stagehand, then deleted by the capture pivot** (2026-08-20 — `STACK-ORCHESTRATION.md:69`
> and `:78`). Discovery today is `services/capture/`: one headless-Chromium session records
> the board's own JSON XHRs, a deterministic pre-filter keeps the job-shaped ones, and **one
> Claude Haiku call** picks the request and maps its fields — the model never writes the
> recipe. `services/discovery/` survives as `models.py` + `progress.py` only. §1's Sonnet
> costs are kept **as the historical baseline the pivot was measured against**.
>
> **Read instead for discovery:** `CAPTURE-IMPLEMENTATION-PLAN.md` (what/why),
> `IMPLEMENTATION-PLAN.md` (open work).
> **For context:** `OVERVIEW.md` (the discovery→replay split — *discovery needs an agent,
> replay must not*) and `BUILD-PLAN.md` — **§6 Phase 3** (the closed vocabulary), **§3** (the
> 12-check gate, and the `HarvestEvidence` contract this plan extends), **§9** (per-target:
> Amazon, Meta, YC, Jane Street).

---

## 0. The framing — what Phase 3 shipped (and deliberately did not)

Phase 3 is the first phase where a company is **not an ATS**: a user pastes `amazon.jobs`,
something runs **once** to author a stored script, and every night after that a **deterministic,
agent-free executor** replays it through the **same gate**. The ATS client was "primitive #1";
Phase 3 makes the leaf task run a **multi-primitive script** for everything else. That framing
survived every pivot — only the *authoring* half changed.

**Scope fences (held):**

1. **Replay is HTTP-transport only** — `{http_json, http_html}` at plan time; the capture pivot
   later added `browser_fetch` (the *same captured request* re-issued by `fetch()` inside our own
   Chromium — no LLM, no DOM parsing, no agent). `dom`/`page_fetch` are still rejected.
2. **`click_sequence` is cut.** The validator *rejects* it; "the agent asked for a capability we
   don't have" is a logged REFUSE reason, not a new primitive.
3. **No new tables / columns** — only new **values** (`transport`, `oracle_kind`,
   `health_state='refused'`, new `outcome`s), so every migration is catalog-only.

### 0.1 Non-negotiable invariants (carry from OVERVIEW/BUILD-PLAN, unchanged)

1. **Only a VERIFIED run may close a job.** UNVERIFIED and FAILED never close.
2. **`run_recipe` RAISES, never returns `[]`** — on non-2xx, unparseable payload, a path that
   doesn't resolve, zero rows, or a count `< expected_min_jobs`. An empty list is
   indistinguishable from "this company stopped hiring" → the 2026-03-29 false-close class.
3. **`tolerance > 0` on a run ⇒ that run closes nothing.** A percentage never catches a
   *structural* hole, so an approximate oracle may only **add** rows, never close.
4. **First VERIFIED run, and the first run after any `script_version` change, close nothing.**
5. **Replay is agent-free, enforced in code** (§4.2). This is a *proof*, not a convention.
6. **Discovery is bounded and loud** — ≤ 2 authoring attempts, then **REFUSE** (record the
   reason on `company_add_attempts`; set `health_state='refused'`). Nothing half-created.

---

## 1. RETIRED — the Sonnet-era discovery spend model

**Historical.** What discovery cost when Sonnet authored the whole JSON recipe (§6) — the
baseline the capture pivot (one Haiku call over a pre-filtered candidate list) was measured
against. Keep the numbers for that comparison, not as today's spend.

| what | detail |
|---|---|
| **Model** | **Claude Sonnet** (BUILD-PLAN §6). One structured-output call per authoring attempt (≤ 2 attempts/add), fed a compact evidence report (not raw page bytes). |
| **Cost / add** | **~$0.25–1.00** (~50–200k input tokens of evidence + a small JSON script out). ≤ 2 attempts ⇒ worst case ~$2/add. Discovery runs **once per company, ever** — never nightly. |
| **Key source** | `settings.anthropic_api_key` (`config.py:46-51` then, `config.py:72` today) — the *same* key the app already uses for Tier-2 location normalization. No new secret, no new provider; already set on Railway. |
| **Replay cost** | **$0** — plain `httpx`. Fully testable with committed fixtures. |
| **What actually spends** | ONLY a real discovery run. **Unit tests are $0** — they mock the LLM and the browser. |

---

## 2. What was ported from the spike (`scripts/one_off/recipe_spike/`)

| spike file | → production | the part that still matters |
|---|---|---|
| `recipe_schema.py` | `services/recipe_schema.py` | `dig` (the dotted-path resolver every extractor and oracle uses) kept verbatim. |
| `replay.py` | `services/recipe_runner.py` | HTTP paths ported verbatim; `run_browser_dom` dropped. **Keep the `_request` `copy_merge_params` fix** (`replay.py:104-108`) — GET pagination merges into the existing query; `params=` **wipes the board's filters**, which is how a filtered board silently unfilters into the 10k firehose. |
| `test_invariants.py` | `api/tests/test_recipe_runner_invariants.py` | All 10 offline invariants. |
| `recipes/*.json`, `captures/*` | `api/tests/fixtures/` | **Measured fixture gap:** the spike `amazon.json` is a *filtered Austin* search of **76 jobs**. It **cannot prove 22,191** — the global board needs its own fixture (§5.1). |

---

## 3. The script schema + closed primitive vocabulary — **SHIPPED**

**Authority is now the code: `src/backend/api/services/recipe_schema.py`** — the per-op param
spec that used to live here is that file. Validation runs on **write** (discovery) *and* on
**read** (`load_custom_company_for_run`): `company_scripts.script` is data that drifts, so the
runner never touches an unvalidated script. `transport` + `oracle_kind` are columns; the `script`
JSONB carries `{script_version, transport, expected_min_jobs, steps: [...], oracle: {...}}` — an
ordered primitive list, each `op` dispatching to a hardened `replay.py` function. Anything not in
the table below is a `RecipeError`, and so is an unknown key inside a step (a typo must fail
loudly, not silently no-op).

| op | purpose | status |
|---|---|---|
| `fetch` | the entrypoint request (https only); `assert_status` covers check 1 here | live |
| `paginate_offset` / `paginate_page` | offset / page-number loop | live |
| `paginate_facet` | partition the board by a **single-valued** facet to escape the ES window cap, one sweep per value, then dedupe — load-bearing for Amazon | live |
| `paginate_cursor` | token-from-body pagination | **rejected** — named in `PAGINATION_STYLES` but never implemented in `replay.py`; shipped code rejects it at validate (a next-URL-from-body is also an SSRF surface) |
| `extract_json_path` | `dig` to the record array (`http_json`) | live |
| `extract_embedded_island` | JSON island in markup (`__NEXT_DATA__`, `ld+json`) — preferred `http_html` mode, survives CSS churn | live |
| `extract_css` | CSS DOM extraction — last resort, rots fastest | live |
| `transform` / `parse_date` / `dedupe_key` | field templating, date normalization (never synthesize — unparseable → `None`), stable-key dedupe | live |
| `lookup_join` | per-record detail fetch | **rejected.** Marked YAGNI here ("validator accepts it, no in-scope script uses it") — and that became a **real silent-data-loss bug**: it validated on write but appeared nowhere in the runner's `if/elif` dispatch, so the step was **silently discarded at compile** — a working scrape with missing data and no error anywhere (`IMPLEMENTATION-PLAN.md:157`). Now raises. |
| `assert_no_inband_error` | fatal `error`/`errors`/`message` key **in a 200 body** (check 3). Amazon returns `{"error":"Result limit cannot be greater than 100","jobs":null}` as **HTTP 200** | live |
| `assert_pinned_operation` | the discovery-time operation identity still resolves (check 4). **Meta: pin `doc_id`, not `operationName`** — Meta doesn't validate the friendly name, so a rename returns byte-identical results; only a `doc_id` rotation is a real failure | live |
| `assert_cap_not_hit` / `assert_page_advances` | `offset + page_size <= window_cap` (check 5); page N's id-set disjoint from prior pages, catching offset-wrap (check 6) | live |
| `assert_unique_ids_vs_total` / `assert_unique` / `assert_delta_vs_last_run` | checks 7/10, 8, 12 | live |
| oracle: `facet_sum` / `header` / `sitemap` / `declared_probed` / `self_consistent` | exactly one; mirrors the `oracle_kind` column. A Phase-3 script may legitimately be `self_consistent` (Jane Street, YC publish no total) | live |

**Rejected with a test:** `click_sequence`, and any transport/op in
`{page_fetch, page_request, dom, browser_dom}`. The rejection message names the missing
capability, so the REFUSE reason *is* the next-primitive roadmap.

---

## 4. The deterministic REPLAY engine (`services/recipe_runner.py`) — **SHIPPED**

### 4.1 It emits the gate's existing `HarvestEvidence`
`run_recipe(script, http) -> (rows, HarvestEvidence)` — the leaf task supplies the client, so
timeouts and SSRF pinning are injected in one place. The evidence is the **same**
`HarvestEvidence` the Phase-2 gate already consumes, so `verify_harvest` needed **no rewrite**,
only the oracle dispatch wired (§5): the oracle total rides `declared_total`, `harvest_meta.py`
gained no new fields, and `cap_hit`/`page_advance_ok`/`terminated_cleanly`/`pages_fetched`/
`transport_ok` come off the asserts.

### 4.2 The agent-free proof (the load-bearing invariant)
- **Runtime:** `assert_no_agent_imports()` runs first on every call and raises if a forbidden
  module is resident in `sys.modules`.
- **Static AST walk** over `recipe_runner.py` **and every module under `tasks/` reachable from
  `fetch_custom_company`** — assert no `import`/`from` of a forbidden package. **This catches
  what a runtime probe misses:** a transitive import on a branch the test never exercises is
  invisible at runtime but obvious in the tree.
- **Why that matters more now:** the shipped runtime guard deliberately checks only
  `playwright`/`stagehand`/`browserbase`/`langchain`, **not** the LLM SDKs — the replay leaf runs
  in a worker co-hosting location normalization, which imports `anthropic` at module load, so
  `anthropic`'s residence proves nothing. The **AST walk is the only enforcement for
  `anthropic`/`openai`** (`recipe_runner.py:63-74`).

---

## 5. The richer oracles — **SHIPPED** (Phase-2's `NotImplementedError` seam is filled)

All three are **exact-match, tolerance-0**: `n == total` → VERIFIED; `n < total` →
`count_mismatch`; `n > total` → `over_harvest`. `cap_hit` and `page_advance_ok is False`
short-circuit to UNVERIFIED *before* the oracle.

### 5.1 `facet_sum` (Amazon → 22,191) — the single-valuedness proof
- **A facet that *covers* is not a facet that *partitions*.** A multi-location job is counted
  once per state, so `normalized_state_name_facet` **over-sums**.
  `normalized_country_code_facet` / `is_intern` / `employee_class_facet` are **single-valued**
  (each job in exactly one bucket).
- **Discovery must PROVE single-valuedness** on a slice known to be *under* the 10k cap, by
  asserting **`Σ facet == hits`** there. In the committed capture the country facet sums to
  **76 == `hits`**; the state facet sums **> 76** → rejected. The proven facet is pinned into
  the script; the runner does **not** re-derive it nightly.
- **Why not `hits`:** `hits` caps at **10,000** (the ES window) and its boundary probe **passes
  cleanly**, so it is *not* a cap detector. The facet sum is the only path to the true 22,191.
- **Fixture gap (measured):** the committed `captures/amazon/raw/000.json` is the *filtered*
  board — facets sum to 76. **The existing capture cannot prove 22,191**; a global-board fixture
  is required.

### 5.2 / 5.3 `header` and `sitemap`
- `header`: `declared_total = int(headers[oracle.header_name])` (e.g. `X-WP-Total`). A missing or
  non-int header **raises** — the oracle "moved" is a FAILED run, never a silent pass.
- `sitemap`: a separate url-guarded GET of `oracle.sitemap_url`, counting `<loc>` entries matching
  `oracle.url_pattern`. Empty or unparseable → raise.

---

## 6. RETIRED — the `services/discovery/` observer + author architecture

**Deleted.** The design was `observer.py` (local Playwright records network + DOM, ranks
job-like JSON arrays into an evidence report) → `author.py` (**Sonnet writes the whole recipe**)
→ validate → replay → gate, ≤2 attempts then REFUSE. It shipped, proved too fragile (Sonnet
*guessed* a JSON API on YC raindrop and 404'd instead of reading the embedded island), was
replaced by Stagehand, then deleted with the Stagehand tier by the capture pivot. Today it is
`services/capture/` (`CAPTURE-IMPLEMENTATION-PLAN.md`). Only the ≤2-attempts-then-REFUSE bound
(§0.1 invariant 6) survived from this section.

---

## 7. Add-flow integration (non-ATS URL → discovery → nightly replay)

**Discovery is async** — it exceeds the 25s request budget and spends money, so it must not run
in the request thread. `add_company`'s non-ATS branch (previously a flat 422 `unsupported`) defers
a discovery task and returns immediately; with the flag off it keeps returning 422, so the
spending path ships dark.

- **On REFUSE: `health_state='refused'`, attempt `outcome='refused'`, and NO COMPANY ROW.**
  *Shipped code deliberately diverges, and says so at the divergence:* `health_state` is a
  `companies` column, so showing "we can't reliably track this site" as a badge needs a row — the
  terminal state is a **disabled, script-less** row (`enabled=FALSE`, `next_run_at=NULL`, no
  `company_scripts`), honoring §0.1 invariant 6 without ever harvesting (RECONCILIATION NOTE in
  `custom_companies_service.record_discovery_refusal`). The add path also inserts a **provisional
  `discovering` row** before deferring, so accept and refuse both *promote* an existing row —
  creating one here resurrected boards the user had already removed.
- **`canonical_source_key` for a discovered company = `f"discovered:{normalized_final_url}"`**
  (there is no `ats:token`) — that is what keeps `UNIQUE(user_id, canonical_source_key)`
  idempotent, so a re-add resolves to the existing discovered company instead of duplicating it.
- **Nightly replay** is the **existing** `fetch_custom_company` leaf with a transport branch:
  `ats_client` → today's ATS dispatch with `effective_oracle_kind(provider)`; otherwise
  `run_recipe` → `recipe_rows_to_job_listings`, oracle read from the **stored**
  `company_scripts.oracle_kind` — **not** `effective_oracle_kind`, which is ATS-provider-derived
  and a discovered company has no provider. The gate/upsert/miss/close tail is identical, and
  scheduling is unchanged — `cadence_hours` + `next_run_at` + the `*/15` claim task already handle
  every custom company regardless of transport.

---

## 10. Ops + config

- **The Playwright chromium binary must be in the backend Docker image** for discovery to run in
  prod. The `scripts/` scrapers install it; the API image is a separate build and does not
  inherit that. Discovery fails at the browser step without it — check before flag-enabling.
- `custom_company_discovery_enabled` (default `False`) is the money flag. It is now the **only**
  discovery gate — the second flag (`browser_agent_enabled`) died with the Stagehand tier.
