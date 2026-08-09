# Phase 3 — stored HTTP scripts + one-time browser discovery (implementation plan)

> **Read first:** `OVERVIEW.md` (the discovery→replay split — *discovery needs an agent,
> replay must not*), `BUILD-PLAN.md` **§6 Phase 3** (the closed primitive vocabulary),
> **§3** (the 12-check gate; the `facet_sum`/`header`/`sitemap` seam Phase 2 left as
> `NotImplementedError`), **§9** (per-target: Amazon, Meta, YC, Jane Street),
> `PHASE-2-PLAN.md` (the gate + `HarvestEvidence` contract this plan extends),
> `STACK-ORCHESTRATION.md` (the per-PR review loop). This file is the file/test-level
> *how*. Branch `feat/e7-phase3-discovery`, worktree `.claude/worktrees/2`. Do all work
> here; **do not `cd` to the parent repo; do not commit** (the orchestrator commits).

---

## 0. The framing — what Phase 3 actually ships (and deliberately does not)

Phase 1/2 made **ATS-client** custom companies real and safe (Greenhouse/Ashby/Lever/Gem/
Workday/Eightfold, gated, closing only when VERIFIED). Phase 3 is the first phase where a
company is **not an ATS**: a user pastes `amazon.jobs` or `metacareers.com`, an agent runs
**once** to author a stored script, and every night after that a **deterministic, agent-free
executor** replays that script through the **same gate**. The ATS client was "primitive #1";
Phase 3 makes the leaf task run a **multi-primitive script** for everything else.

**Scope fences (hold these — they keep Phase 3 shippable and un-blocked on Phase 4):**

1. **Replay is HTTP-transport only** — `transport ∈ {http_json, http_html}`. The four
   in-scope targets (Amazon, Meta, YC, Jane Street) all yield their data to plain `httpx`
   (+ `beautifulsoup4` for the YC island). **No browser at replay time.** Page-context
   `page_fetch`/`dom` replay (CBRE behind a WAF, DOM-virtualized boards) is **Phase 4**,
   gated on Brendan's articles — do **not** depend on it, do **not** import Playwright into
   the replay path.
2. **Discovery drives *local* Playwright** at add-time only (Phase 4 later swaps the vendor
   to Browserbase; the observe/author logic is identical). Playwright becomes a backend dep
   but is imported **only** by `services/discovery/`, **never** by `recipe_runner` or `tasks/`.
3. **`click_sequence` is cut from v1** (OVERVIEW "what the review changed"). The validator
   must *reject* it, and "the agent asked for a capability we don't have" is a logged REFUSE
   reason, not a new primitive.
4. **No new tables / columns.** `company_scripts` (`script` JSONB + `script_version` +
   `transport` + `oracle_kind`), `company_harvests`, `company_add_attempts`, and the
   `companies` E7 columns all already exist (Phase 1, `db_models.py:757-851`, `:672-714`).
   Phase 3 only adds new **values** (`transport='http_json'|'http_html'`,
   `oracle_kind ∈ {facet_sum,header,sitemap}`, `health_state='refused'`, new
   `company_add_attempts.outcome` values). That keeps every migration catalog-only.

### 0.1 Non-negotiable invariants (carry from OVERVIEW/BUILD-PLAN, unchanged)

1. **Only a VERIFIED run may close a job.** UNVERIFIED and FAILED never close.
2. **`run_recipe` RAISES, never returns `[]`** — on non-2xx, unparseable payload, a path
   that doesn't resolve, zero rows, or a count `< expected_min_jobs`. An empty list is
   indistinguishable from "this company stopped hiring" → the 2026-03-29 false-close class.
3. **`tolerance > 0` on a run ⇒ that run closes nothing** — now *live* (Amazon's ~43
   facet-invisible jobs score 0.998 vs a 1% tolerance; a percentage never catches a
   *structural* hole, so an approximate oracle may only **add** rows, never close).
4. **First VERIFIED run, and the first run after any `script_version` change, close nothing.**
5. **Replay is agent-free, enforced in code** — `recipe_runner.assert_no_agent_imports()`
   raises if `anthropic`/`openai`/`stagehand`/`browserbase`/`langchain`/`playwright` ever
   lands in `sys.modules` on the replay path. This is a *proof*, not a convention.
6. **Discovery is bounded and loud** — ≤ 2 authoring attempts, then **REFUSE** (record the
   reason on `company_add_attempts`; set `health_state='refused'`). Nothing half-created.

---

## 1. LEAD DECISION — the discovery spend, surfaced up front

Everything else in Phase 3 is testable for **$0**. Discovery is the only thing that costs money.

| what | detail |
|---|---|
| **Model** | **Claude Sonnet** (BUILD-PLAN §6). One structured-output call per authoring attempt (≤ 2 attempts/add), fed a compact evidence report (not raw page bytes). |
| **Cost / add** | **~$0.25–1.00** (~50–200k input tokens of evidence + a small JSON script out). ≤ 2 attempts ⇒ worst case ~$2/add. Discovery runs **once per company, ever** — never nightly. |
| **Key source** | `settings.anthropic_api_key` (`config.py:46-51`), read from `ANTHROPIC_API_KEY` in the **project-root `.env.local`** — the *same* key the app already uses for Tier-2 location normalization (`services/llm_client.py:248`). No new secret, no new provider. In prod it is already set on Railway. |
| **Replay cost** | **$0** — plain `httpx`. Fully testable with committed fixtures. |
| **What actually spends** | ONLY a real discovery run. Unit tests mock the LLM and the browser, so the whole suite is $0. |

**The three things I want the orchestrator to confirm before implementation (see §11):**

1. **Sonnet is approved** as the discovery model (vs. Opus for higher first-try success at
   ~5× the token price, or Haiku to cut cost at a real quality hit).
2. **One paid end-to-end discovery run** (real Playwright + real Sonnet against
   `amazon.jobs`, ~$0.25–1) is authorized as the *single* paid acceptance test — everything
   else stays $0 on fixtures/mocks. Recommendation: **yes** — it is the only way to prove the
   observe→author→validate→replay→gate loop closes against a live site, and it is a
   one-time spend, not per-CI.
3. **Discovery runs async (Procrastinate), not inline in the add request** (§5). It exceeds
   the 25s request budget and spends money, so it must not block or be retried by a request
   thread. Recommendation: **async**.

---

## 2. What we port from the spike (reuse, do not reinvent)

The spike (`scripts/one_off/recipe_spike/`) is the proven starting point. It imports nothing
from `src/backend/` and its replay path has **10/10 green invariant tests**.

| spike file | → production target | port notes |
|---|---|---|
| `recipe_schema.py` (`validate_recipe`, `dig`, `KINDS`, `PAGINATION_STYLES`, `RecipeError`) | `services/recipe_schema.py` | Harden into the closed-vocabulary validator (§3). Keep `dig` verbatim — it is the dotted-path resolver every extractor and oracle uses. |
| `replay.py` (`run_recipe`, `run_http_json`, `run_embedded_json`/`run_http_html`, `check_completeness`, `map_records`, `render_field`, `_request`, `assert_no_agent_imports`, `FORBIDDEN_MODULES`, `RecipeExecutionError`, `_arrays_matching_shape`) | `services/recipe_runner.py` | Port the HTTP paths verbatim; **drop `run_browser_dom`** (Phase 4). Add `playwright` to `FORBIDDEN_MODULES`. Make the runner emit `HarvestEvidence` (§4). Keep the `_request` `copy_merge_params` fix (`replay.py:106-108`) — it is why a filtered board doesn't silently unfilter to the 10k firehose. |
| `test_invariants.py` (10 offline invariants) | `api/tests/test_recipe_runner_invariants.py` | Port all 10; add the new Phase-3 invariants (facet sweep determinism, header/sitemap oracle, playwright-in-guard). |
| `recipes/{amazon,meta,ycombinator,janestreet}.json` | `api/tests/fixtures/recipes/*.json` | Committed fixture scripts. **Note:** the spike `amazon.json` is a *filtered Austin* search (76 jobs) — the Phase-3 Amazon target is the **global board** (`hits` caps at 10,000; facet_sum → 22,191), so it needs a **new** global-board script + capture (§4.1, §7). |
| `captures/{amazon,meta,...}/raw/*.json`, `FINDINGS.md` | `api/tests/fixtures/captures/*` | Committed response fixtures for $0 deterministic replay/oracle tests. |
| `capture.py` (`find_record_arrays`, `score_object`, `JOB_KEY_HINTS`) | `services/discovery/observer.py` | Port the evidence-scoring logic; the discovery observer records network+DOM and builds the same compact report the agent reads (§6). |

---

## 3. Task 1 — the script schema + closed primitive vocabulary

**Files:** `src/backend/api/services/recipe_schema.py` (new, ported), consumed on **write**
(discovery author, §6) **and read** (leaf task load, §5). Validation-on-read is load-bearing:
`company_scripts.script` is **data that drifts**, so `load_custom_company_for_run`
(`custom_companies_service.py:324`) must re-validate before the runner touches it.

### 3.1 The stored `company_scripts.script` shape (multi-primitive)

`transport` and `oracle_kind` are **columns** (`db_models.py:776-777`); the `script` JSONB
carries the ordered primitive pipeline + oracle block + floor:

```jsonc
{
  "script_version": 1,
  "transport": "http_json",              // mirrors the column; validated equal
  "expected_min_jobs": 500,              // the raise-below floor (check 2)
  "steps": [                             // the ordered primitive list (Amazon = 9, YC = 3)
    { "op": "fetch", ... },
    { "op": "paginate_facet", ... },
    { "op": "extract_json_path", ... },
    { "op": "parse_date", ... },
    { "op": "transform", ... },
    { "op": "dedupe_key", ... },
    { "op": "assert_cap_not_hit", ... },
    { "op": "assert_page_advances" },
    { "op": "assert_unique", "field": "id" }
  ],
  "oracle": { "kind": "facet_sum", ... } // the completeness oracle (check 9/11)
}
```

**Design reconciliation (call it out in review):** the spike is a *declarative* recipe
(`entrypoint`/`pagination`/`records_path`/`fields`); this plan expresses it as an **ordered
`steps` list** to honour the BUILD-PLAN "list of primitives" framing and match
`db_models.py:763` ("Later phases store the closed-vocabulary primitive lists"). **Each
`op`'s executor body is the corresponding hardened `replay.py` function** — the list is a
thin dispatcher over proven code, not a new interpreter. See §11 decision (2) if the
orchestrator prefers keeping the flat declarative recipe verbatim instead.

### 3.2 The closed vocabulary — every allowed `op` + params (exhaustive)

Anything not on this list is a `RecipeError` on validate. Params typed strictly; unknown keys
rejected (a typo must fail loudly, not silently no-op).

**Transport / fetch**
- `fetch` — `{method: GET|POST, url (https:// only), headers?: obj, body?: obj}`. The
  entrypoint request. Ported from `replay._request`; POST merges pagination into the JSON
  body, GET merges into the query via `httpx.URL.copy_merge_params` (never `params=` — that
  wipes filters, `replay.py:104-108`).

**Pagination (exactly one, or none)**
- `paginate_offset` — `{param, page_size, max_pages, window_cap?}`. Zero-based offset loop
  (`replay run_http_json` offset branch). `window_cap` feeds `assert_cap_not_hit`.
- `paginate_page` — `{param, page_size, max_pages, start_page?}`. Page-number loop.
- `paginate_cursor` — `{cursor_path, param, max_pages}`. Token from response body fed to the
  next request. **NEW** — `PAGINATION_STYLES` names "cursor" but `replay.py` never
  implemented it; Phase 3 implements it (terminate on empty/absent cursor or `max_pages`).
- `paginate_facet` — `{facet_param, facet_values: [str] | facet_values_path, page_size,
  max_pages_per_facet, window_cap?}`. **NEW and load-bearing for Amazon.** Partition the
  board by a **single-valued** facet to escape the `hits` ES-window cap: run one
  offset/page sweep per facet value, union, then `dedupe_key`. Each sweep is bounded and
  `assert_cap_not_hit` applies per sweep.

**Extraction (exactly one)**
- `extract_json_path` — `{records_path}`. `dig` to the record array (`http_json`).
- `extract_embedded_island` — `{selector, source: attribute|text, attribute?, records_path}`.
  JSON island in markup (YC `div[data-page]`, `__NEXT_DATA__`, `ld+json`) — the *preferred*
  `http_html` mode, survives CSS churn (`replay run_embedded_json`).
- `extract_css` — `{record_selector, field_selectors: obj}`. CSS DOM extraction — last
  resort for `http_html` (rots fastest; discovery must prefer the island when one exists).

**Field shaping (zero or more)**
- `transform` — `{field, op: template|base_url_join, template?|base_url?}`. Field templating
  (Amazon `"https://www.amazon.jobs{job_path}"`) / relative-URL join (`replay.render_field`
  + `base_url`).
- `parse_date` — `{field, mode: strptime|humanized|iso, format?}`. Normalize `posted_at` to
  ISO; whitespace-tolerant for Amazon's double-space dates; `humanized` for YC's "about 12
  hours". Never synthesize — unparseable → `None` (the leaf task's window-validator drops it).
- `lookup_join` — `{detail_fetch: {url_template}, join_key, fields}`. Join a per-record
  detail endpoint onto the list rows. **NEW; declared for completeness, YAGNI for the four
  Phase-3 targets** — validator accepts it, but no in-scope script uses it. Mark "unexercised
  until a real target needs it" so it isn't gold-plated with untested execution paths.
- `dedupe_key` — `{field}`. Dedupe by a stable key (`replay run_recipe` dedup; keeps first).

**The assert family (check→primitive map, BUILD-PLAN §3)**
- `assert_status` — HTTP status in allowed set (check 1; enforced in `fetch`).
- `assert_no_inband_error` — `{error_keys: [str]}`. Fatal `error`/`errors`/`message` key in a
  200 body (check 3). This fills the `run_gate(error_keys=…)` seam (`harvest_verification.py:141,160`).
  Amazon returns `{"error":"Result limit cannot be greater than 100","jobs":null}` as **HTTP 200**.
- `assert_pinned_operation` — `{doc_id?, url_contains?, response_shape_path?}`. The
  discovery-time operation identity still resolves (check 4). **Meta: pin `doc_id`, not
  `operationName`** — Meta doesn't validate the friendly name, so a rename returns
  byte-identical results; only the `doc_id` rotation is a real failure. Also assert
  `data.job_search_with_featured_jobs_v2.all_jobs` shape.
- `assert_cap_not_hit` — `{window_cap}`. `offset + page_size <= window_cap` (check 5).
- `assert_page_advances` — page N id-set disjoint from the union of prior (check 6);
  catches offset-wrap.
- `assert_unique_ids_vs_total` — post-dedup unique count vs the oracle total (check 7/10).
- `assert_unique` — `{field}`. The key field is unique post-dedup (check 8).
- `assert_delta_vs_last_run` — trailing-14-run median band (check 12; `self_consistent` only).

**Oracle block (exactly one, `oracle.kind` mirrors the `oracle_kind` column)**
- `facet_sum` — `{facet_path, single_valued: true}` (§4.1).
- `header` — `{header_name}` (§4.2).
- `sitemap` — `{sitemap_url, url_pattern}` (§4.3).
- `declared_probed` / `self_consistent` — inherited from Phase 2 (a Phase-3 script *may*
  legitimately be `self_consistent`: Jane Street, YC — no total published).

**EXCLUDED (validator must reject, with a test):** `click_sequence`, and any `op` /
`transport ∈ {page_fetch, page_request, dom, browser_dom}` (Phase 4). A rejected op's message
names the missing capability so the REFUSE reason *is* the next-primitive roadmap.

### 3.3 Tests (all $0)
`api/tests/test_recipe_schema.py`:
- every valid `op` round-trips; each required param missing → `RecipeError` naming the field
  (port `test_invariants.py:99-103` shape);
- `click_sequence` → `RecipeError`; `transport='dom'` / `op='page_fetch'` → `RecipeError`;
- non-`https://` `fetch.url` → `RecipeError` (port `test_invariants.py:99-103`);
- `transport` field ≠ `transport` column value → `RecipeError`;
- more than one pagination / extraction / oracle op → `RecipeError`;
- unknown key inside a step → `RecipeError` (no silent no-op);
- **validate-on-read:** a stored script mutated to an invalid shape is rejected by
  `load_custom_company_for_run` before the runner sees it.

---

## 4. Task 2 — the deterministic REPLAY engine (`services/recipe_runner.py`)

**Port of `replay.py`.** Public entry: `run_recipe(script: dict, http: httpx.Client) ->
tuple[list[dict], HarvestEvidence]`. (The leaf task supplies the client so timeouts/SSRF
pinning are injected in one place.)

### 4.0 Contract (unchanged from the spike, enforced)
- `assert_no_agent_imports()` runs **first**, every call. `FORBIDDEN_MODULES =
  ("anthropic","openai","stagehand","browserbase","langchain","playwright")` — **playwright
  added** (HTTP-only replay). Raises `RuntimeError` if any is in `sys.modules`
  (`replay.py:43-46`).
- `validate_recipe(script)` second (validate-on-read).
- RAISES `RecipeExecutionError` — never returns `[]` — on non-2xx, in-band error, unparseable
  JSON, a path that doesn't resolve, zero rows, or post-dedup count `< expected_min_jobs`
  (`replay.py:423-438`). The leaf task maps this to a **FAILED** run (writes nothing
  destructive, not a miss).
- Deterministic: same fixture script + same fixture responses ⇒ byte-identical rows twice.

### 4.1 The runner emits `HarvestEvidence` (the clean gate integration)
The runner returns the **same `HarvestEvidence`** the gate already consumes
(`harvest_meta.py:20-68`), so **`verify_harvest` needs no rewrite** — only the oracle
dispatch wired (Task 3). The runner populates:
- `declared_total` = the oracle's total (`facet_sum` sum / `header` int / `sitemap` count /
  `None` for `self_consistent`);
- `cap_hit` from any `assert_cap_not_hit` tripping (per facet sweep for `paginate_facet`);
- `page_advance_ok` from `assert_page_advances` across the whole harvest (all sweeps);
- `terminated_cleanly` = loop ended on short/empty page or reached-total, not a cap;
- `pages_fetched`, `transport_ok`.

`harvest_meta.py` gains **no new fields** — the oracle total rides `declared_total`, exactly
as Phase 2's `declared_probed` does (`_verify_declared_probed`, `harvest_verification.py:253`).
*Optional* extension only if header/sitemap provenance must be distinguished on the harvest
row: add `oracle_source: str | None` to `HarvestEvidence` (nullable, defaulted) — otherwise
skip it.

### 4.2 Import-guard test (the load-bearing proof)
`api/tests/test_recipe_runner_import_guard.py`:
- import `recipe_runner` in a **subprocess** (`sys.executable -c "import ...services.recipe_runner"`),
  assert none of `FORBIDDEN_MODULES` is in that process's `sys.modules`;
- **AST walk** of `recipe_runner.py` **and every module under `tasks/` reachable from
  `fetch_custom_company`** — assert no `import`/`from` of a forbidden package (catches a
  transitive import a runtime probe would miss if a branch isn't exercised);
- port `test_invariants.py:79-91`: monkeypatch `sys.modules["anthropic"]=object()` →
  `assert_no_agent_imports()` raises "never import an agent".

### 4.3 How it plugs into the gate (evidence + oracle, no gate surgery)
```
rows, evidence = recipe_runner.run_recipe(script, http)   # http_json/http_html only
jobs           = recipe_rows_to_job_listings(company_id, rows)   # §5.2
gate           = run_gate(jobs, evidence, oracle_kind=stored_oracle_kind)   # checks 2,7,8
verdict        = verify_harvest(stored_oracle_kind, gate, evidence, baseline) # checks 5,6,9,10,11,12
```
The leaf task's upsert / miss / close tail (`fetch_custom_company.py:389-484`) is **untouched**.

---

## 5. Task 3 — the richer oracles (fill the Phase-2 `NotImplementedError` seam)

Phase 2 left `verify_harvest` raising for `facet_sum`/`header`/`sitemap`
(`harvest_verification.py:79,213-217`). Phase 3 replaces that raise with a real dispatch.
**All three are exact-match, tolerance-0** oracles (same contract as `_verify_declared_probed`):
`n == oracle_total` → `VERIFIED`; `n < total` → `count_mismatch`; `n > total` → `over_harvest`.

**Wiring:** in `verify_harvest`, replace the `_PHASE_3_ORACLES` `NotImplementedError` with
`return _verify_oracle_total(n, evidence)` (a generalization of `_verify_declared_probed`
reading `evidence.declared_total`). `cap_hit` and `page_advance_ok is False` short-circuit to
UNVERIFIED *before* the oracle, exactly as today (`harvest_verification.py:231-246`).

### 5.1 `facet_sum` (Amazon → 22,191)
- **Evidence produced by the runner:** sum the counts of a **single-valued** facet from the
  response `facets` block. In the capture, `facets` is `{facet_name: [{label: count}, ...]}`
  (`captures/amazon/raw/000.json`). `declared_total = Σ counts` for `oracle.facet_path`.
- **The single-valued check (the GM 1,042-vs-835 lesson):** a facet that *covers* is not a
  facet that *partitions*. A multi-location job is counted once per state, so
  `normalized_state_name_facet` over-sums; `normalized_country_code_facet` / `is_intern` /
  `employee_class_facet` are single-valued (each job in exactly one bucket). **Discovery must
  prove single-valuedness** on a slice known to be *under* the 10k cap by asserting
  `Σ facet == hits` there (in the capture: country facet sums to 76 == `hits`; state facet
  sums > 76 → rejected). The chosen facet is pinned in the script; the runner does **not**
  re-derive it nightly.
- **Why not `hits`:** `hits` caps at 10,000 (ES window) and its boundary probe passes
  cleanly, so it is *not* a cap detector — the facet sum is the only path to the true 22,191.
- **Fixture:** the committed `captures/amazon/raw/000.json` is the *filtered* board (facets
  sum to 76). The 22,191 test needs a **global-board** fixture — capture one unfiltered
  `search.json` via a single $0 `httpx` GET at implementation time and commit it
  (`fixtures/captures/amazon_global.json`), or synthesize one by scaling the real facet
  structure. Flag: **the existing capture cannot prove 22,191** — a new fixture is required.

### 5.2 `header` (e.g. `X-WP-Total`)
- **Evidence:** the runner captures response headers (the spike discards them — extend
  `_request` to return `(payload, headers)`), `declared_total = int(headers[oracle.header_name])`.
  A missing/non-int header → `RecipeExecutionError` (the oracle "moved" → FAILED, never a
  silent pass — mirrors `check_completeness`'s vanished-oracle raise, `replay.py:137-142`).
- WordPress job boards (`wp-json`) commonly emit `X-WP-Total`; Spotify's `animal/v1` is the
  nearest in-repo shape (`recipes/spotify.json`).

### 5.3 `sitemap` (count)
- **Evidence:** a **separate** `httpx` GET of `oracle.sitemap_url` (url_guarded like any
  fetch), count `<loc>` entries matching `oracle.url_pattern`, `declared_total = that count`.
  Empty/unparseable sitemap → `RecipeExecutionError`.

### 5.4 Tests (all $0, fixture-driven)
`api/tests/test_oracles.py`:
- **Amazon `facet_sum` → 22,191** from the global-board fixture; a *multi-valued* facet
  path is **rejected** by the single-valued assertion (state facet from the real capture);
- `facet_sum` where post-dedup `n == 22,191` → `VERIFIED`; `n < 22,191` → `count_mismatch`
  UNVERIFIED (Amazon's ~43-job structural hole lands here — proves tolerance-0 refuses to
  close); `n > total` → `over_harvest`;
- `header` → `VERIFIED` on `X-WP-Total` match; missing/non-int header → `RecipeExecutionError`;
- `sitemap` → count from a fixture `sitemap.xml`; empty → raise;
- **regression:** `verify_harvest('facet_sum', …)` no longer raises `NotImplementedError`.

---

## 6. Task 4 — the DISCOVERY agent (`services/discovery/`, one-time at add-time)

New package. **The only place that touches the LLM or the browser.** It observes, authors a
script, then hands the script to the **agent-free** gate/replay to validate — so acceptance
is proven by the same deterministic path that runs nightly.

**Files:**
- `services/discovery/observer.py` — port of `capture.py`. Drives **local** Playwright
  (`playwright.async_api`), records every network response + the rendered DOM, and builds a
  **compact evidence report** (in-memory dict; ranks JSON arrays by job-likeness via
  `score_object`/`JOB_KEY_HINTS`/`find_record_arrays`, lists XHRs with method/url/headers,
  sketches embedded JSON islands and repeated DOM classes). Never imported by the runner.
- `services/discovery/author.py` — the Sonnet call. Mirrors `llm_client.py` patterns:
  `AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0, timeout=…)`,
  `SONNET_MODEL = "claude-sonnet-…"`, **structured outputs** (`output_config.format.json_schema`)
  whose schema **is the recipe schema** (§3), so the model can only emit a shape the validator
  accepts. Raises `MissingAnthropicKeyError` (reuse the `llm_client.py:42` class or mirror it)
  **before** building the client when the key is unset — so a keyless env REFUSES cleanly
  instead of erroring mid-flow.
- `services/discovery/discover.py` — the orchestrator:
  1. `observer.observe(url)` → evidence report (local Playwright).
  2. `author.author_script(report)` → candidate `script` (attempt 1).
  3. `recipe_schema.validate_recipe(script)` — invalid shape ⇒ feed the error back to the
     model for attempt 2.
  4. `recipe_runner.run_recipe(script, http)` **agent-free** → rows + evidence; then
     `run_gate` + `verify_harvest`. Accept iff it produces rows and does **not** FAIL
     (VERIFIED or UNVERIFIED-with-rows both mean "the script works"; UNVERIFIED just means it
     can't yet *close*, which is fine day-one).
  5. On failure, retry once (attempt 2) with the failure reason in the prompt. After **2**
     attempts → **REFUSE loudly**: `company_add_attempts.outcome='refused'`,
     `error_detail=<why>` (validation error / gate FAILED / capability-not-in-vocabulary),
     nothing else created.
- `services/discovery/models.py` — `DiscoveryOutcome` dataclass
  (`ok`, `script?`, `transport?`, `oracle_kind?`, `refuse_reason?`, `attempts`, `cost_note?`).

**Cost controls in code:** hard cap at 2 attempts; cap evidence-report size before sending
(truncate raw bodies, keep top-N ranked arrays) so a giant page can't balloon token spend;
one Playwright session per add with a wall-clock timeout.

**Testing discovery within a $0/near-$0 budget:**
- **$0 unit tests** (`api/tests/test_discovery.py`): monkeypatch `author.author_script` to
  return a committed fixture script (from a saved `report.json`), and monkeypatch
  `observer.observe` to return a committed evidence-report fixture. Assert: (a) a good report
  → a valid script that replays green on the fixture responses; (b) a first-attempt invalid
  script → retry → success; (c) two bad attempts → REFUSE with the reason recorded; (d)
  keyless env → `MissingAnthropicKeyError` → REFUSE, no attempt burned.
- **$0 author-contract test:** assert the JSON-schema handed to Sonnet is exactly the recipe
  schema (so the model can't emit an out-of-vocabulary op) — mirrors the location eval's
  "prompt/schema single source of truth" (`llm_client.py:190`).
- **The one paid test** (`api/tests/test_discovery_e2e.py`, marked
  `@pytest.mark.paid`/`skip unless E7_DISCOVERY_E2E=1`): a single real
  observe→author→validate→replay→gate run against `amazon.jobs`. **~$0.25–1, run once,
  behind an env flag, never in CI.** This is decision (2) in §1/§11.

---

## 7. Task 5 — add-flow integration (non-ATS URL → discovery → nightly replay)

**Entry point:** `routers/user_companies.py` `add_company` currently returns
**422 `unsupported`** when `discover_ats` finds no ATS candidate (`user_companies.py:148-158`).
Phase 3 re-routes that branch to discovery — **but discovery is async** (§1 decision 3): it
exceeds the 25s request budget and spends money, so it must not run in the request thread.

**Flow:**
1. `add_company`, non-ATS branch, `custom_company_sources_enabled` **and** the new
   `custom_company_discovery_enabled` sub-flag both on:
   - write a `company_add_attempts` row `outcome='discovery_pending'`;
   - enqueue a **`discover_custom_company`** Procrastinate task (new leaf, its own queue);
   - return **202 Accepted** with `{status:'discovery_pending', detail:'One-time setup…'}`.
   With the sub-flag **off**, keep today's 422 `unsupported` (discovery ships dark and rolls
   back by flag — spend can't happen until it's flipped).
2. **`tasks/discover_custom_company.py`** (new): runs `discovery.discover(url)`. On success,
   create the company via a Phase-3-aware **`add_discovered_company`** in
   `custom_companies_service.py` — the same 4-row transaction as `add_custom_company`
   (`custom_companies_service.py:95`) but storing the **multi-primitive** script with
   `transport ∈ {http_json,http_html}` and the real `oracle_kind` (not `'ats_client'`/`'none'`).
   `canonical_source_key` for a discovered company = `f"discovered:{normalized_final_url}"`
   (there's no `ats:token`) — keeps `UNIQUE(user_id, canonical_source_key)` idempotent. On
   REFUSE: `health_state='refused'`, attempt `outcome='refused'`, no company row.
3. **Nightly replay:** the **existing** `fetch_custom_company` leaf task
   (`tasks/fetch_custom_company.py:220`) gains a transport branch in `_fetch_and_transform`
   (`:129`):
   - `transport == 'ats_client'` → today's ATS dispatch (unchanged), oracle via
     `effective_oracle_kind(provider)` (`:288`);
   - `transport ∈ {http_json,http_html}` → `recipe_runner.run_recipe(script, http)` →
     `recipe_rows_to_job_listings(company_id, rows)`; oracle from the **stored**
     `company_scripts.oracle_kind` (**not** `effective_oracle_kind`, which is ATS-provider-
     derived — a discovered company has no ATS provider). This is the one real branch in the
     leaf task; the gate/upsert/miss/close tail (`:305-484`) is identical.
4. `recipe_rows_to_job_listings(company_id, rows)` — new helper: maps runner dicts
   (`{id,title,url,location,posted_at,department,…}`) → `JobListing` scoped to
   `source_id=custom:<id>`, `company=<id>`, `details` capped 8 KB (`fetch_custom_company.py:85`),
   `posted_on` window-validated (`:108`). Mirrors the ATS `transform_to_job_listings` contract
   so `_remap_for_custom` (`:191`) is reused unchanged.

**Scheduling:** unchanged — `cadence_hours` + `next_run_at` + the `*/15` claim task already
handle every custom company regardless of transport.

**Tests:**
- `api/tests/test_user_companies_router.py` (extend): non-ATS URL + sub-flag on → 202 +
  `discovery_pending` attempt row + task enqueued (assert via the Procrastinate test
  connector); sub-flag off → today's 422 `unsupported` (regression).
- `api/tests/test_discover_custom_company_task.py` (new, discovery mocked): success →
  4 rows created with `transport='http_json'`, real `oracle_kind`; REFUSE → `health_state=
  'refused'`, no company; idempotent re-add resolves to the existing discovered company.
- `api/tests/test_fetch_custom_company.py` (extend): a stored `http_json` script replays
  through the gate; `oracle_kind` comes from the **stored** column, not the provider; a
  facet_sum company reaches VERIFIED on a fixture; first-VERIFIED-run and
  `script_version`-change runs close nothing (reuse the Phase-2 close tests).

---

## 8. Task 6 — frontend (minimal delta)

The resolve/add UI already exists (`pages/MyCompaniesPage/`, `components/my-companies/`,
`features/userCompanies/userCompaniesApi.ts`). Phase 3 adds two states.

- **`userCompaniesApi.ts`:** `addUserCompany` (`userCompaniesApi.ts:180`) currently expects
  201/200 `UserCompany` or 422 `AddUserCompanyFailure`. Add the **202 `discovery_pending`**
  shape (`{status, detail}`) as a distinct success-ish result. `UserCompanyHealthState`
  already includes `'refused'` (`userCompaniesApi.ts:73-77`) — no type change for REFUSE.
- **A "discovery in progress" state** (`components/my-companies/`): on 202, show *"One-time
  setup — we're teaching ourselves to read this site. Jobs appear after the first scan
  (within ~24h)."* The company then surfaces in `MyCompaniesList` (`getUserCompanies` polls/
  invalidates on the `MyCompanies` tag) with its `health_state` badge — reuse
  `companyHealth.ts`.
- **A REFUSE state:** a company/attempt in `refused` renders *"We can't reliably track this
  site."* (the OVERVIEW "this is a success of the design" framing) — surfaced from the
  attempt outcome (a small `GET` on the pending attempt, or folded into the list once the
  task writes `health_state='refused'`).
- The resolve preview's `no_ats_detected` result gains a **"Try one-time discovery"** CTA
  (behind `VITE_CUSTOM_COMPANIES_ENABLED`) that POSTs the same `add` endpoint.

**Tests (Vitest, Node 22.14.0):** `MyCompaniesPage`/`MyCompaniesList` render the pending and
refused states; `userCompaniesApi` maps a 202 body correctly. All existing tests stay green.

---

## 9. Task 7 — test matrix ($0 vs the one paid run)

| test file | proves | cost |
|---|---|---|
| `test_recipe_schema.py` | vocabulary closed; `click_sequence`/browser transport rejected; validate-on-read | **$0** |
| `test_recipe_runner_invariants.py` | 10 ported invariants + raise-never-empty + `< expected_min_jobs` raises | **$0** |
| `test_recipe_runner_determinism.py` | fixture script + fixture responses → **identical rows twice** | **$0** |
| `test_recipe_runner_import_guard.py` | subprocess `sys.modules` clean + AST walk of runner & `tasks/` + `anthropic`-leak raises | **$0** |
| `test_oracles.py` | Amazon `facet_sum` → **22,191**; multi-valued facet rejected; `n<total`→UNVERIFIED (tolerance-0); `header`; `sitemap`; no more `NotImplementedError` | **$0** |
| `test_discovery.py` | LLM+browser **mocked**: good report→valid script; retry-then-succeed; 2-fail→REFUSE; keyless→REFUSE | **$0** |
| `test_discover_custom_company_task.py` | discovery-mocked: 4 rows w/ multi-primitive script; REFUSE path; idempotency | **$0** |
| `test_fetch_custom_company.py` (extend) | stored `http_json` script replays through the gate; stored oracle_kind; VERIFIED via facet_sum; first-run closes nothing | **$0** |
| `test_user_companies_router.py` (extend) | non-ATS → 202 + enqueue (sub-flag on); 422 (off) | **$0** |
| frontend `MyCompanies*.test.tsx` (extend) | pending + refused states; 202 mapping | **$0** |
| **`test_discovery_e2e.py`** (`@pytest.mark.paid`, `E7_DISCOVERY_E2E=1`, never CI) | **one real** observe→author→validate→replay→gate on `amazon.jobs` → VERIFIED @ 22,191 | **~$0.25–1, once** |

**Fixtures to commit ($0 to produce):** the four recipe scripts (Amazon global, Meta, YC,
Jane Street), their captured responses (incl. a **new** Amazon global-board `search.json`
with facets summing to 22,191 and capped `hits`), a `report.json` evidence fixture for the
discovery mock, an `X-WP-Total` header fixture, and a `sitemap.xml` fixture.

---

## 10. Backend dependency + config deltas

- `src/backend/api/requirements.txt`: **add `playwright`** (discovery only) and
  `beautifulsoup4` (the YC island — spike uses `bs4`). `anthropic>=0.107.0` already present
  (`requirements.txt:13`). **Do not** add `browserbase`/`stagehand` (Phase 4). Note the
  Playwright browser binary (`playwright install chromium`) must be in the backend Docker
  image for discovery to run in prod — flag for the Railway verifier (§11).
- `config.py`: add `custom_company_discovery_enabled: bool = False` (the money sub-flag,
  distinct from `custom_company_sources_enabled` at `config.py:88`). No other config change —
  `anthropic_api_key` already exists (`config.py:51`).

---

## 11. Decisions for the orchestrator to confirm (lead with spend)

1. **[SPEND — lead] Sonnet + one paid E2E.** Confirm Claude **Sonnet** as the discovery
   model (~$0.25–1/add, ≤2 attempts, key already on Railway), and authorize the **single
   paid `test_discovery_e2e.py` run** against `amazon.jobs` as the only paid step — everything
   else is $0 on fixtures/mocks. *Recommendation: yes to both;* replay and the whole gate are
   provably testable for free, so the paid run is a one-time closure-of-loop, not a recurring
   cost.
2. **Script IR shape.** `steps` primitive-list (this plan, honours "list of primitives",
   each op = a ported `replay.py` fn) **vs.** keep the spike's flat declarative recipe
   verbatim (less code, identical behaviour, weaker match to the BUILD-PLAN wording).
   *Recommendation: `steps` list — same executor, better future-proofing for Phase 5 repair.*
3. **Async discovery.** Confirm discovery runs as a Procrastinate task with a **202** add
   response (not inline). *Recommendation: async — it exceeds the request budget and spends
   money.*
4. **New sub-flag `custom_company_discovery_enabled`.** Confirm a *second* flag so the
   spending path ships dark independently of the (free) ATS add path. *Recommendation: yes.*
5. **Amazon global-board fixture.** Confirm capturing one unfiltered `search.json` ($0 httpx
   GET) as the 22,191 fixture — the committed spike capture is the *filtered* board and
   cannot prove the number.
6. **Playwright in the prod image.** Discovery needs Chromium in the backend Docker image
   (the scrapers already install it in `scripts/`, but the API image may not). Flag for the
   `railway-prod-verifier` before the discovery path is flag-enabled in prod.

## 12. What Phase 3 explicitly does NOT do (hand-offs)
- **Browser-transport replay** (`page_fetch`/`dom`, CBRE WAF) — **Phase 4** (Browserbase +
  execution-time CDP SSRF pinning), gated on Brendan's articles.
- **Repair loop / admin dashboard / name-input resolver** — **Phase 5**. (`script_version`
  change already closes-nothing on the next run, so the Phase-5 hot-swap slots in safely.)
- **Per-company baseline calibration** — still needs 2–3 weeks of prod data (§4.5); Phase 3
  runs `self_consistent` discovered companies at the 0.5 floor, same as Phase 2.
