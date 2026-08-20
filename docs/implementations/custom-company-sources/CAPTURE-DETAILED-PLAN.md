# Deterministic API-Capture — Detailed Implementation Plan (file/function level)

> Companion to `CAPTURE-IMPLEMENTATION-PLAN.md` (the what/why). This is the **how**: the exact
> integration surface, the one load-bearing architectural decision, the per-file change list, the
> test plan, and the **PR stack**. Integration surface was mapped against `feat/e7-phase3-discovery`
> (the E7 stack). References below are `file :: symbol`.

## The one architectural decision (drives everything)

`services/recipe_runner.py::run_recipe` calls `assert_no_agent_imports()` on **every** call and forbids
`playwright | stagehand | browserbase | langchain` on the replay path — the agent-free boundary. A
`browser_fetch` recipe drives a headless Chromium, so **it cannot execute inside `run_recipe`.**

**Decision:** `browser_fetch` runs **out-of-band**, exactly mirroring the existing
`fetch_custom_company::_run_browser_agent_script` subprocess split. A new
`_run_browser_fetch_script(...)` (its own module / subprocess that imports Playwright) drives a local
`chromium.launch()`, runs the captured request via `page.evaluate(fetch(...))` on the site origin, and
returns the **same `(rows, HarvestEvidence)`** the http path returns. `run_recipe` and its
agent-free guard are untouched. The transport-agnostic machinery below is reused verbatim.

## Reuse VERBATIM (no change)

- **Gate/verdict** — `harvest_verification.py::run_gate`, `verify_harvest`, `effective_oracle_kind`;
  `harvest_meta.py::HarvestEvidence`. `browser_fetch` emits the same `(rows, evidence)` → gate needs
  nothing new.
- **Row mapping** — `recipe_rows.py::recipe_rows_to_job_listings(company_id, rows)` (scopes to `custom:<id>`).
- **SSRF** — `url_guard.py::validate_public_url` (+ stable reason codes) and `guarded_client.py::
  guarded_sync_client`/`GuardedTransport` (host+IP pin) for the http_json tier.
- **Storage** — `db_models.py::CompanyScript` (`company_id, script JSONB, script_version, transport,
  oracle_kind`); `custom_companies_service.py::add_discovered_company / _promote_to_tracked /
  load_custom_company_for_run / add_discovering_placeholder / record_discovery_refusal`. `transport`
  is free-text → **no migration** to add `browser_fetch`.
- **Leaf-task shared tail** — `fetch_custom_company.py`: after the transport branch, `_remap_for_custom
  → run_gate → compute_baseline → verify_harvest → resolve_safety_guard → upsert/last_seen → VERIFIED-only
  miss/close`, `finally` writes `company_harvests`+`scrape_runs`. Reused by the new branch untouched.
- **Add-flow UX** — `routers/user_companies.py` non-ATS 202 `discovery_pending` + the provisional
  `discovering` row + the 15s poll (`MyCompaniesList.tsx::isStillSettling`/`CompaniesPoller`).

## EXTEND

1. `services/recipe_schema.py` — add `"browser_fetch"` to `TRANSPORTS` (remove from the rejected
   `_BROWSER_TRANSPORTS`); add a per-op validator for the captured shape
   `{origin_url, method, endpoint, headers, body?, records_path, field_map, pagination?}`. This is the
   **write-time gate** for a captured recipe (validate-on-write + validate-on-read, column-equality).
2. `tasks/fetch_custom_company.py` — add a `transport == "browser_fetch"` branch (next to the
   `http_json/http_html` branch, ~L370-421) calling `_run_browser_fetch_script(script, oracle_kind)`;
   use the **stored** `oracle_kind`. Raise `RecipeExecutionError` on any failure to slot into the
   existing narrow `except`.

## ADD (new modules)

- `services/capture/network_capture.py` — open the careers URL in a **local headless Chromium**
  (Playwright `chromium.launch()`; Browserbase `connect_over_cdp` only when stealth/live-view is
  needed), capture every JSON XHR/fetch response (url, method, req headers, POST body, response body)
  via the Playwright response listener. Runs out-of-band (imports Playwright).
- `services/capture/request_selector.py` — deterministic pre-filter (keep JSON responses with an array
  of objects) → **Claude Haiku 4.5** call (via the existing `llm_client` / `ANTHROPIC_API_KEY`, same as
  location normalization), **structured output** → `{chosen_request, records_path, field_map}`.
- `services/capture/discover.py` — orchestrate: capture → select → synthesize recipe → **acceptance
  replay from the production environment** (http_json via `guarded_sync_client`+`run_recipe`;
  browser_fetch via `_run_browser_fetch_script` in a fresh local Chromium) → assert 200/`code==0` +
  job-shaped + non-empty + **matches the capture** → return a `discovery.models.DiscoveryOutcome`
  (reuse verbatim) with `transport ∈ {http_json, browser_fetch}` and the chosen `oracle_kind`, else
  `ok=False` refuse. SSRF: `validate_public_url` on the pasted URL **and** the discovered endpoint.
- `services/capture/browser_fetch_runner.py` (+ `_browser_fetch_main.py` subprocess, the only new
  Playwright importer on the replay side) — `_run_browser_fetch_script` used by both discovery
  acceptance and daily replay.
- `tasks/discover_custom_company.py` — **replace** its `discover()` call with `capture.discover.discover(...)`;
  keep the accept→`add_discovered_company` / refuse→`record_discovery_refusal` wiring. (Or a new sibling
  task; the `_defer_discovery` hook in `user_companies.py` is unchanged.)

## RETIRE (Stagehand-DOM path)

Remove: `services/browser_agent/{__init__,discover,runner,schema,_stagehand_main}.py`;
`fetch_custom_company.py::_run_browser_agent_script` + the `transport=="browser_agent"` branch + the
lazy `from ..services.browser_agent import runner`; the `stagehand>=3.22` dep in `requirements.txt`;
and the `browser_agent_enabled` flag's discovery role (fold into a single `custom_company_discovery_enabled`).
**Keep** `discovery/models.py::DiscoveryOutcome` (transport-agnostic). Re-discover the existing raindrop
custom company under the new model (may refuse if no capturable API).

## Infra — nothing new needed

`requirements.txt` already pins `playwright>=1.40.0`; `Dockerfile` already runs
`playwright install --with-deps chromium` and uses `tini` to reap browser grandchildren (for the
Google/Apple/Microsoft/TikTok scrapers). The local-Chromium `browser_fetch` executor reuses this as-is.
Remove only the now-unused `stagehand` dep.

## PR stack

**Base decision (DECIDED — do not merge to main):** the capture feature builds on the **#248-level
surface** (the recipe engine `recipe_runner`/`recipe_schema`/`recipe_rows`/`guarded_client` are new on
#248; the gate, storage, `url_guard`, add-flow are on #247). We keep the existing 3-PR stack unmerged
and **consolidate the capture work onto its top**:

- **Final PR set = `#243 ← #247 ← #248`** (a stack; test the top). The docs-only PR #258 (off `main`)
  is **closed/folded** — its plan docs move onto **#248**, which becomes *the capture feature PR*
  (recipe engine + plan + POCs; the Stagehand-DOM path is retired by the implementation commits).
- All capture implementation lands on **#248's branch** (`feat/e7-phase3-discovery`), so plan and
  implementation live together. Nothing merges to `main`.

**The implementation lands as ordered commits on #248 (each a reviewable unit):**

1. **PR 1 — `browser_fetch` replay tier.** `recipe_schema` (+browser_fetch), `browser_fetch_runner` +
   `_browser_fetch_main` (local Chromium `page.evaluate`), the `fetch_custom_company` branch → gate.
   *Given a stored browser_fetch recipe, run it daily.* No discovery, no UI.
   Tests: `test_recipe_schema.py` (browser_fetch validate), `test_browser_fetch_runner.py`,
   `test_fetch_custom_company.py` (browser_fetch branch → gate).
2. **PR 2 — capture discovery (swap the discovery engine).** `capture/{network_capture,request_selector,
   discover}.py`; the acceptance-replay gate; rewire `discover_custom_company` to `capture.discover`;
   store `http_json`/`browser_fetch` or refuse; **retire the Stagehand-DOM path** (they swap). SSRF on
   entry + endpoint. Tests: `test_request_selector.py` (fixture candidates → pick/map),
   `test_capture_discover.py` (accept/refuse, match-the-capture), SSRF cases; delete
   `test_discover_browser_agent.py`/`test_browser_agent_raindrop_e2e.py`/`test_fetch_custom_company_browser_agent.py`.
3. **PR 3 — frontend discovery-progress UX.** Backend exposes richer discovery sub-state (the 4 steps +
   a live-view URL) on the company row / a discovery-status endpoint; frontend renders the **4-step
   checklist + read-only live-view iframe + job preview + named-step failure** by extending
   `MyCompaniesList.tsx` (poll), `DiscoveryCTA.tsx`, `companyHealth.ts`. Tests: the existing
   `__tests__/components/my-companies/*` + a checklist-states test.
4. **PR 4 — name input (later phase).** `resolve_company_name(name)→URL` (curated map → web search →
   Haiku rank → **confirm**) in front of the same pipeline.

PR 1 + PR 2 are the backend core (could ship as one larger PR or two stacked — I lean two stacked so
"run a recipe" is reviewable before "discover a recipe"). PR 3 and PR 4 are independent.

## Risks (already reviewed) — addressed in

SSRF → PR2 (validate entry + endpoint) & PR1 (GuardedTransport for http_json). Tier-1b cost → own
Chromium (PR1), no Browserbase hours. Drift → daily gate marks stale → re-discovery. #248 migration →
PR2 retire + re-discover. >10k caps & ToS → deferred / owner decision.
