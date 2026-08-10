# E7 Pivot — Stagehand browser-agent discovery + runtime

**Status:** proposed (research + one bounded validation run done; NOT implemented).
**Author:** research/plan agent, 2026-08-09.
**Supersedes:** the Phase-3 discovery mechanism (`services/discovery/observer.py` +
`author.py` + the local-Playwright-observe → Sonnet-authors-JSON step) and the
planned separate "Phase 4 — Browserbase runtime" (BUILD-PLAN §6). Stagehand is
**both** the discovery engine and the browser runtime, so the two collapse into one.

---

## 0. Lead answer (read this first)

**Does the validation experiment PROVE Stagehand produces a usable, reusable artifact
on 2–3 pages? YES — with one load-bearing caveat.**

One bounded Browserbase Stagehand session (`scripts/one_off/stagehand_spike/run_spike.py`,
session `b8570ede…`, **63.3 s wall total**, Claude Sonnet via our own `ANTHROPIC_API_KEY`)
did all of the following in a single run:

- **YC raindrop** (`ycombinator.com/companies/raindrop/jobs`) — the exact page the
  Sonnet-authors-JSON path was reported to fail on — Stagehand read **9 jobs off the
  rendered page** (titles + locations), matching the known "raindrop 9/9" ground truth
  (BUILD-PLAN.md:292).
- **amazon.jobs**, bounded to **2 pages**: `observe()` returned a concrete "next page"
  action, `extract()` pulled page-1 results, `act("click next page")` advanced (returned
  `success=True`), and `extract()` on page 2 returned a **different** set of titles —
  proving real pagination AND that the bound held (it stopped at 2 of ~22k, never crawled).
- **`observe()` returns a reusable artifact**: each result is
  `{description, selector: "xpath=…", method: "click", arguments: [], cacheHit: false}` —
  a replayable action with a stored selector and a `cacheHit` flag (Stagehand's
  observe→cache→act deterministic-replay path is real: [Browserbase — caching](https://www.browserbase.com/blog/stagehand-caching)).
- **`extract(schema=…)`** takes a JSON-Schema / Pydantic schema and returns an array of
  objects — exactly the structured-jobs shape we need
  ([docs — extract](https://docs.stagehand.dev/v3/basics/extract)).

**The single biggest risk (surfaced directly by the run):** the schema'd `extract()` did
**NOT** return a stable per-job identifier. The `url` field came back as `"0-650"`,
`"3363"`, … — DOM-position / tracking indices that **repeat across page 1 and page 2**.
Close-detection and the whole verification gate key on a **stable unique id** (dedupe,
`assert_unique`, page-advance/disjoint-id, miss-counting → close). A browser-agent extract
that yields row-indices instead of real requisition ids/hrefs will either (a) collapse
every page to "the same 10 ids" (breaking dedupe) or (b) churn ids every night (closing
and re-opening every job). **Mitigation is mandatory and is the crux of this plan** (§3.4,
§6): the extract must be instructed to capture the real apply-href / req-id, the runner
must assert id shape + cross-page disjointness and **RAISE → FAILED** (never a wrong close)
when it can't, and any board without a proven-stable id stays **UNVERIFIED forever** (shown,
never closes) — which the existing gate already enforces for un-provable completeness.

Everything downstream of "we got rows + a stable id" is **already built and reused
unchanged**: the gate, the oracles, the leaf-task upsert/close tail, the SSRF concept, the
add-flow, the storage, and the frontend.

---

## 1. What STAYS vs what the pivot REPLACES

| Area | File(s) | Verdict |
|---|---|---|
| Stored-script storage | `db_models.py:757` `CompanyScript` (`script` JSONB, `script_version`, `transport`, `oracle_kind`) | **STAYS** — add a `transport='browser_agent'` value + bump `script_version` to 2; no migration (values only). |
| Verification gate + verdict | `services/harvest_verification.py` (`run_gate`, `verify_harvest`, `effective_oracle_kind`) | **STAYS, untouched** — browser-agent path emits the same `HarvestEvidence`. |
| Oracles | `recipe_runner._compute_declared_total` for http; `HarvestEvidence`/gate for `self_consistent` | **STAYS** — discovered browser-agent boards use `self_consistent` (they publish no trustworthy total; PHASE-3 §9 YC). |
| Leaf task shell | `tasks/fetch_custom_company.py` | **STAYS** — add a **third** transport branch (§3.3) alongside the existing `http_json/http_html` (line 330) and ATS (line 340) branches; the gate/verdict/upsert tail is byte-identical. |
| SSRF guard (concept) | `services/guarded_client.py` `GuardedTransport`, `services/url_guard.py` | **STAYS** for http replay; the browser layer needs its **own** analog (CDP host-pin, §5). |
| Add-flow (202 / refuse) | `routers/user_companies.py:124`, `services/custom_companies_service.py` (`add_discovered_company:223`, `record_discovery_refusal:321`) | **STAYS** — same 202/refuse contract; `add_discovered_company` stores `transport='browser_agent'`. |
| Discovery task shell | `tasks/discover_custom_company.py` | **STAYS** — same queue/timeout/persist; its body calls the new Stagehand discovery. |
| Deterministic http replay | `services/recipe_runner.py`, `recipe_schema.py`, `guarded_client.py` | **STAYS as the OPTIMIZATION tier** — a board graduates `browser_agent → http_json/html` when a forgeable API is distilled (§4). Not deleted. |
| Frontend My Companies | `features/userCompanies/userCompaniesApi.ts`, `components/my-companies/*` | **STAYS** — one completion-UX fix (§7). |
| **Local-Playwright observe** | `services/discovery/observer.py`, `_capture_main.py` | **REMOVED** — Stagehand drives its own cloud Chromium. |
| **Sonnet-authors-JSON step** | `services/discovery/author.py` | **REMOVED** — no second blind LLM authoring call; Stagehand's own LLM reasons over the real page. |
| **discover() observe→author loop** | `services/discovery/discover.py` | **REWORKED** — becomes "run one bounded Stagehand session → capture artifact → the first bounded harvest IS the acceptance replay/gate; ≤2 attempts then REFUSE". |

---

## 2. Chosen Stagehand integration

**SDK: Python `stagehand` v3 (installed 3.22.0), the hosted REST client.** The v3 Python
SDK is a thin `httpx` client to `api.stagehand.browserbase.com`; the browser **and the
LLM run remotely** (Browserbase), and `act`/`observe`/`extract`/`execute` are HTTP calls.
This is the important simplifier: **no Node sidecar is required** — Python talks to
Stagehand directly. (The TS SDK is the older/original and runs the LLM in-process; we do
not need it. Sources: [PyPI stagehand-py](https://pypi.org/project/stagehand-py/),
[stagehand-python](https://github.com/browserbase/stagehand-python),
[all-languages](https://www.browserbase.com/blog/browser-automation-all-languages-with-stagehand).)

**Invocation: OUT OF PROCESS, via a subprocess**, mirroring the existing observer pattern
(`observer._subprocess_capture` → `_capture_main.py`, observer.py:238-293). A new
`api/services/browser_agent/_stagehand_main.py` runs the bounded session and prints a JSON
report; a parent `run_stagehand(...)` shells out with `asyncio.create_subprocess_exec`.

**Why a subprocess and not an in-process import:** the replay path's runtime guard
`recipe_runner.assert_no_agent_imports()` (recipe_runner.py:60,72) **raises if
`stagehand`/`browserbase`/`playwright` is resident in the worker process** — that guard is
the load-bearing proof that http replay is agent-free. Importing `stagehand` in the shared
Procrastinate worker would trip it and break the import-guard tests. Keeping Stagehand in a
child process preserves the guard exactly as the observer already does, and lets the SAME
worker host both a `browser_agent` harvest and an `http_json` harvest without contamination.

**Model / key:** `model_api_key = settings.anthropic_api_key` (already loaded, used by
author.py:342), `model_name="anthropic/claude-sonnet-4-5"` (proven in the run).
`browserbase_api_key`/`browserbase_project_id` from settings (new env vars, §6). Tokens are
billed to **our** Anthropic key, not Browserbase's included `$5`.

```python
# _stagehand_main.py (sketch — mirrors _capture_main.py)
with Stagehand(server="remote",
               browserbase_api_key=BB_KEY, browserbase_project_id=BB_PROJECT,
               model_api_key=ANTHROPIC_KEY) as client:
    s = client.sessions.start(model_name="anthropic/claude-sonnet-4-5",
                              browser={"type": "browserbase"},
                              dom_settle_timeout_ms=15000, self_heal=True,
                              system_prompt="You read public job-board pages. Never crawl a whole board.")
    # navigate → observe(pagination) → extract(schema) → [act(next) → extract]×(max_pages-1)
```

---

## 3. Stored-artifact shape, replay model, and how it slots in

### 3.1 The artifact (`company_scripts.script`, `transport='browser_agent'`, `script_version=2`)

```jsonc
{
  "script_version": 2,
  "transport": "browser_agent",
  "entry_url": "https://www.ycombinator.com/companies/raindrop/jobs",
  "extract": {
    "instruction": "extract every job posting: title, location, and the apply/detail URL",
    "schema": { "type":"object", "properties": { "jobs": { "type":"array", "items": {
      "type":"object",
      "properties": { "title":{"type":"string"}, "location":{"type":"string"},
                      "url":{"type":"string"}, "id":{"type":"string"} },
      "required": ["title","url"] } } }, "required": ["jobs"] }
  },
  "pagination": {                          // OPTIONAL; absent = single page
    "next_action": "click the next-page control",
    "max_pages": 3                         // HARD-CAPPED at 3 by the schema validator
  },
  "id_field": "url",                       // the STABLE dedupe key (must be a real href/req-id)
  "expected_min_jobs": 5,
  "oracle": { "kind": "self_consistent" }, // discovered boards publish no trustworthy total
  "observed_actions": [                    // OPTIONAL cache hook for the later optimization (§4)
    { "description": "next page button", "selector": "xpath=…", "method": "click" }
  ],
  "discovered_at": "…", "discovered_by": "stagehand/claude-sonnet-4-5"
}
```

### 3.2 Replay model — RECOMMENDATION: **v1 re-runs a bounded Stagehand session each cadence**

This is the owner's explicit "big-guns-first" posture, and it is the correct v1 because the
experiment showed the durable artifact Stagehand gives you is **brittle absolute xpaths +
cache-with-LLM-fallback** ([caching](https://www.browserbase.com/blog/stagehand-caching):
on DOM drift it treats the cache as a miss and re-infers with the LLM), **not** a
no-LLM-forever recipe. So:

- **v1 (this plan):** every 24h, the leaf task shells out to the bounded Stagehand
  subprocess (navigate → observe → extract, ≤3 pages). An LLM is in the loop each run — that
  is acceptable and bounded. Rows + `HarvestEvidence` flow into the unchanged gate.
- **Optimization (later, opt-in per board):** during discovery, Stagehand can also inspect
  the page's own network JSON; when a **forgeable API** is found, emit an `http_json`
  recipe (the existing `recipe_runner` path, `$0`/deterministic) and store `transport='http_json'`
  instead. The board "graduates" with no schema change — same `company_scripts` row, different
  `transport`. `observed_actions` is the cache seed if we later adopt Stagehand action-cache
  replay. **`recipe_runner`/`recipe_schema`/`guarded_client` are kept precisely for this.**

Do **not** try to make v1 deterministic-replay-only; the run proves that would refuse most
real boards. Do **not** use the autonomous `agent.execute()`/`sessions.execute()` for the
harvest — it is unbounded; use the explicit navigate/observe/extract/act loop with a fixed
page cap (what the run did).

### 3.3 Leaf-task wiring (`fetch_custom_company.py`)

Add one branch next to the existing transport dispatch (currently `http_json/http_html` at
line 330, ATS at 340):

```python
if transport == "browser_agent":
    oracle_kind_effective = str(company.get("oracle_kind") or "self_consistent")
    raw_jobs, evidence = await _run_browser_agent_script(script, company_id, oracle_kind=oracle_kind_effective)
elif transport in ("http_json", "http_html"):
    ...
else:  # ats_client
    ...
```

`_run_browser_agent_script` runs the subprocess (like `_run_discovered_script:227`),
maps the returned rows via `recipe_rows_to_job_listings`, and builds a `HarvestEvidence`
(paginated variant: `terminated_cleanly` iff the last page was short AND `max_pages` was not
hit; `page_advance_ok` from cross-page disjoint id-sets; `declared_total=None` for
`self_consistent`). The rest of `fetch_custom_company` (gate → verdict → upsert →
miss/close) is **unchanged**, so all Phase-2 safety (VERIFIED-only close, 36h floor, fleet
breaker, self-consistent 3-run streak, first-run-closes-nothing) applies for free.

### 3.4 The stable-id requirement (the lead risk, operationalized)

- Discovery must PROVE the `id_field` is stable before storing: run the bounded session,
  and if pagination is used, assert **page-2 ids are disjoint from page-1 ids** and every id
  "looks like" a URL/slug/number of plausible length (not a `"0-650"` row index). If it
  can't, either retry the extract with a sharper instruction ("the href of the job's detail
  link, not its row position") or **REFUSE**.
- Replay (`_run_browser_agent_script`) re-asserts the same invariants each run and **RAISES
  → FAILED** on violation (reusing the `recipe_runner` "raise, never return `[]`" contract,
  recipe_runner.py:16-20). A FAILED run writes nothing destructive and is not a miss.
- Until a board's id is proven stable, it stays `oracle_kind='self_consistent'` and never
  reaches a 3-run VERIFIED streak on shaky evidence — i.e. it is shown but **never closes**,
  the safe default the gate already guarantees.

### 3.5 Discovery rework (`services/discovery/` → `services/browser_agent/`)

`discover(url)` (discover.py:86) keeps its signature, the ≤2-attempts/REFUSE loop
(`_MAX_ATTEMPTS`), and its `DiscoveryOutcome` return, but its body becomes:

1. Run ONE bounded Stagehand session (the same subprocess replay uses) that ALSO snapshots
   `observe()` actions + `expected_min_jobs`.
2. Assemble the artifact (§3.1); validate its shape (new `browser_agent` schema validator).
3. **The first bounded harvest IS the acceptance replay** — feed rows+evidence to `run_gate`
   (as `_replay_and_gate` does today, discover.py:63) with `oracle_kind='self_consistent'`;
   a zero/garbage result REFUSES.
4. On success → `add_discovered_company(..., transport='browser_agent', oracle_kind='self_consistent')`
   (unchanged service, custom_companies_service.py:223). On 2 failures → `record_discovery_refusal`.

`observer.py`, `author.py`, `_capture_main.py` are deleted; `models.py`
(`DiscoveryOutcome`) stays.

---

## 4. The 2–3 page bound (belt, suspenders, and a hard stop)

1. **Artifact schema:** `pagination.max_pages` is **rejected if > 3** at write time and
   re-checked at read/replay time (a new `validate_browser_agent_script`).
2. **Driver loop:** `for page in range(min(max_pages, 3))` — a fixed Python loop, not an
   agent goal. No `sessions.execute()` autonomous crawl.
3. **Subprocess wall-clock cap:** `_STAGEHAND_TIMEOUT_S` (≈120 s, like observer's
   `_SUBPROCESS_TIMEOUT_S:44`); the parent kills + REFUSEs/FAILs on timeout.
4. **Session cap:** Browserbase free tier already hard-caps sessions at **15 min**
   ([pricing](https://www.softwaresuggest.com/browserbase/pricing)); set a shorter
   `browserbase_session_create_params.timeout` too.
5. **System prompt:** "never crawl the whole board; work only on the page you are on"
   (proven effective in the run — Amazon stopped at 2 of 22k).

Discovery and replay use the **same** bound, so an Amazon-sized board can never blow up in
either phase.

---

## 5. SSRF / safety at the browser layer

- **Add-time entry-URL guard stays:** `url_guard.validate_public_url` already runs on the
  entry URL through the add-flow (`user_companies.py`, `discover`), rejecting IP-literals,
  RFC1918/loopback/link-local/metadata, and DNS answers that resolve private.
- **`allowedDomains` is necessary but NOT sufficient:** Browserbase's `allowedDomains`
  restricts **only main-frame navigations**, "does not block iframe/subframe loads or other
  in-page resource requests (images, scripts, XHR)"
  ([create-a-session](https://docs.browserbase.com/reference/api/create-a-session)); it is
  also bypassable via proxy/translate services on an allowed domain
  ([gemini-cli #23224](https://github.com/google-gemini/gemini-cli/issues/23224)). Set it to
  `[host]` as defence-in-depth, but do not rely on it for request-level SSRF.
- **Request-level pin (the real control) = CDP `Fetch.requestPaused`, as BUILD-PLAN §Phase 4
  specified.** The v3 session exposes `session.data.cdp_url`; connect Playwright over CDP in
  the subprocess, enable `Fetch.requestPaused`, and **abort any request whose host isn't the
  pinned target** (re-validated through `url_guard`, closing DNS-rebind). This is the
  browser-layer analog of the existing `GuardedTransport` (guarded_client.py:50). `verify=True` /
  `ignoreCertificateErrors:false`.
- **v1 acceptability:** because the entry URL passes `url_guard` at add time and v1 targets
  are trusted public boards, `allowedDomains=[host]` + entry-guard is a defensible v1; the
  CDP pin is the **must-do-before-untrusted-scale** hardening (flag it, don't skip it
  silently). Note the current http-replay `GuardedTransport` does NOT protect the
  browser-agent path — that path needs the CDP pin, not the httpx transport.

---

## 6. Free-tier feasibility & cost

Measured: **one bounded discovery/harvest ≈ 63 s wall ≈ ~1 browser-minute**, a handful of
observe/extract LLM calls (~tens of K tokens ≈ single-digit cents on our Anthropic key).

| | Browser-minutes | Anthropic tokens |
|---|---|---|
| One discovery (≤3 pages) | ~1 min | ~cents |
| One nightly harvest (≤3 pages, v1 re-run) | ~1 min | ~cents |
| 1 company, 24h cadence, per month | ~30 min | ~$0.30–1 |

- **Free tier** = **1 browser-hour/mo** + `$5` model tokens + 3 concurrent browsers +
  15-min session cap ([pricing](https://www.softwaresuggest.com/browserbase/pricing)). That
  sustains **~2 companies daily** OR **~60 one-time discoveries** — plenty for the E2E and a
  handful of dogfood companies; the account is currently near-untouched.
- **Developer $20/mo = 100 browser-hours** (~6,000 min) → **~200 companies daily**, matching
  OVERVIEW's "cliff at ~200 companies" (OVERVIEW.md:130). Overage ≈ `$0.10–0.12`/browser-hr.
- The scaling limit remains **repair throughput**, not dollars (OVERVIEW.md:132).

---

## 7. Frontend completion-UX fix (the owner's bug)

**Root cause (confirmed):** `MyCompaniesList` polls `getUserCompanies` only while
`rows.some(isStillSettling)`, where `isStillSettling = healthState==='unverified' &&
openJobCount===0` (MyCompaniesList.tsx:30,145). But on a `discovery_pending` 202 **no
`companies` row exists yet** — the add-flow writes only a `company_add_attempts` row
(user_companies.py:204) and defers the task; the `companies` row is created only when
discovery ACCEPTs (`add_discovered_company`) or REFUSEs (`record_discovery_refusal`). So
during discovery there is nothing to poll on, the list stays idle, and the "One-time setup"
Alert in `DiscoveryCTA` (DiscoveryCTA.tsx:37) is terminal — the user must hard-refresh.

**Recommended fix (B — robust, reuses the refusal-row pattern):** on the 202 path, ALSO
insert a provisional `companies` row `health_state='discovering'` (`enabled=false`,
`next_run_at=NULL`, no `company_scripts`) so `getUserCompanies` returns it immediately; the
discovery task flips it to tracked (writes the script + `health_state`) or `refused`. Then:
- extend the poll predicate to include `healthState === 'discovering'`
  (MyCompaniesList.tsx:30);
- add a badge case `'discovering' → { label: 'Setting up…', color: 'info' }`
  (companyHealth.ts:26);
- `DiscoveryCTA` success/pending copy points at the list row.
This survives refresh (single source of truth) and mirrors the existing disabled-row
pattern (`record_discovery_refusal:321`).

**Lighter alternative (A — frontend-only):** lift the 202 `isDiscoveryPending` signal from
`DiscoveryCTA` up to `MyCompaniesPage`, drive `CompaniesPoller active` on it, and render a
client-only "Setting up <host>…" placeholder until a row with that `finalUrl`/`displayName`
appears. No backend change, but the placeholder is lost on refresh and can't show `refused`.
Prefer B.

---

## 8. File- & test-level task breakdown

**Backend — new**
- `api/services/browser_agent/_stagehand_main.py` — subprocess entry: one bounded session,
  navigate→observe→extract→(act→extract)×, prints `{rows, pages_fetched, terminated_cleanly,
  page_id_sets, expected_min_jobs, observed_actions}` JSON. Imports `stagehand` (child only).
- `api/services/browser_agent/runner.py` — `run_browser_agent(script) -> (rows, HarvestEvidence)`:
  `asyncio.create_subprocess_exec` the entry, parse JSON, assert bound + id-stability, build
  evidence, RAISE on any failure. (Analog of `observer._subprocess_capture` + the evidence
  half of `recipe_runner`.)
- `api/services/browser_agent/schema.py` — `validate_browser_agent_script` (transport,
  `max_pages ≤ 3`, required extract schema keys, `id_field`, `oracle.kind`), + a
  `TRANSPORTS_V2 = (...,'browser_agent')` addition.
- `api/services/browser_agent/discover.py` — reworked `discover()` (§3.5).

**Backend — edited**
- `tasks/fetch_custom_company.py` — third transport branch + `_run_browser_agent_script` (§3.3).
- `tasks/discover_custom_company.py` — import `browser_agent.discover` instead of
  `services.discovery.discover`; unchanged otherwise.
- `services/custom_companies_service.py` — `add_discovered_company` default oracle/transport
  → `browser_agent`/`self_consistent`; add the provisional `'discovering'` insert on 202 (§7).
- `routers/user_companies.py` — 202 path writes the provisional row (§7).
- `config.py` — `browserbase_api_key`, `browserbase_project_id`, `browser_agent_enabled` (flag).
- `services/recipe_runner.py` FORBIDDEN set already lists `stagehand`/`browserbase` — keep.
- **Delete** `services/discovery/observer.py`, `author.py`, `_capture_main.py`.

**Backend — tests**
- `test_browser_agent_schema.py` — reject `max_pages>4`, missing `id_field`, non-`self_consistent`
  oracle on a discovered board.
- `test_browser_agent_runner.py` — subprocess **mocked** (inject a fake report): asserts the
  bound, that duplicate cross-page ids RAISE, that a `"0-650"`-style row-index id RAISES,
  that a clean 2-page report yields correct `page_advance_ok`/`terminated_cleanly`.
- `test_fetch_custom_company_browser_agent.py` — the third branch lands UNVERIFIED on a
  `self_consistent` board with streak<3 (never closes); FAILED on a runner raise writes nothing.
- `test_discover_browser_agent.py` — accept path stores `transport='browser_agent'`; 2×fail → REFUSE.
- Import-guard tests (existing) — assert `_stagehand_main`/`runner` are NOT in the leaf-task
  closure and `assert_no_agent_imports` still holds in the worker (the whole reason for the
  subprocess).

**Frontend — edited + tests**
- `userCompaniesApi.ts` — add `'discovering'` to `UserCompanyHealthState`.
- `companyHealth.ts` + `companyHealth.test.ts` — `'discovering'` badge.
- `MyCompaniesList.tsx` + test — extend `isStillSettling`/poll predicate to `'discovering'`.
- `DiscoveryCTA.tsx` + test — copy points at the list row.

**One paid E2E** (authorize like the Phase-3 `~$2` run, log entry 2026-08-09): a real
bounded Browserbase harvest against YC raindrop, behind the flag, never CI.

---

## 9. Branch / PR recommendation

**Rework on the existing Phase-3 branch (`feat/e7-phase3-discovery`, PR #248), do NOT stack
a new Phase 4.** Rationale:
- #248 is **unmerged** (STACK-ORCHESTRATION.md:32) and it OWNS exactly the discovery
  mechanism being replaced — layering a new phase on top of code you're deleting is churn.
- The pivot **collapses old Phase-3 (discovery) and planned Phase-4 (Browserbase runtime)
  into one** browser-agent mechanism — Stagehand is both. The queued
  `feat/e7-phase4-browser-runtime` branch (never created, STACK-ORCHESTRATION.md:33) is
  **subsumed and dropped**.
- Concretely: rebrand #248 to "Stagehand discovery + browser-agent runtime," swap
  observer+author→Stagehand there, keep the stack shape (base = P2/#247), and fold the
  Phase-4 SSRF-pin work into it (§5). Update STACK-ORCHESTRATION.md's stack table + LOG.
- Keep `recipe_runner`/`recipe_schema`/`guarded_client` in-tree (the optimization tier, §4) —
  they are not part of what's deleted.

---

## 10. End-to-end verification plan

1. **Real bounded Browserbase run (done; reproduce via the driver):**
   `scripts/one_off/stagehand_spike/run_spike.py` already proved YC raindrop (9 jobs) +
   amazon 2-page. Port it into `_stagehand_main.py` and re-run once through the subprocess
   path against YC raindrop; assert ≥1 page, ≤3 pages, jobs returned.
2. **Local stack + flags:** backend :8000 `--reload`, `vercel dev`, Node 22.14.0,
   `CUSTOM_COMPANY_SOURCES_ENABLED` + `custom_company_discovery_enabled` +
   `browser_agent_enabled` + `VITE_CUSTOM_COMPANIES_ENABLED` all on.
3. **Happy path:** paste `ycombinator.com/companies/raindrop/jobs` on `/my-companies` → 202
   → the provisional row shows "Setting up…" → poll flips it to "Tracking — building history"
   with ~9 jobs → the private trend page renders. (Verifies §7 + §3.3 end to end.)
4. **Refuse path:** paste a board Stagehand can't read → after ≤2 attempts, the row shows
   "Not trackable" (`refused`) and nothing is scheduled.
5. **Close-safety:** simulate a second harvest that drops a job → assert **nothing closes**
   (`self_consistent`, streak<3, first-run-closes-nothing), `guard_reason='unverified_harvest'`
   or `streak_too_short`, `closed_jobs==0`.
6. **Bound proof:** inspect the subprocess report — `pages_fetched ≤ 3`, and on an
   Amazon-sized board it stops early (never 22k).
7. **Id-stability proof (the risk):** a golden test that a `"0-650"`-style row-index id makes
   the runner RAISE → FAILED, not silently close jobs.
8. **SSRF (when CDP pin lands):** a board whose page attempts an XHR to `169.254.169.254` /
   an internal host is aborted by `Fetch.requestPaused`; the harvest FAILS rather than relays.

---

## Appendix — validation artifact

`scripts/one_off/stagehand_spike/` (throwaway, gitignored venv + result):
`run_spike.py` + `spike_result.json` (session `b8570ede…`, model
`anthropic/claude-sonnet-4-5`, 63.3 s). Raw returns quoted in §0. Delete after review or keep
as the driver seed for `_stagehand_main.py`.

**Web sources:** [Stagehand caching](https://www.browserbase.com/blog/stagehand-caching) ·
[extract docs](https://docs.stagehand.dev/v3/basics/extract) ·
[stagehand-python](https://github.com/browserbase/stagehand-python) ·
[all-languages](https://www.browserbase.com/blog/browser-automation-all-languages-with-stagehand) ·
[Browserbase pricing](https://www.softwaresuggest.com/browserbase/pricing) ·
[create-a-session / allowedDomains](https://docs.browserbase.com/reference/api/create-a-session) ·
[allowedDomains bypass](https://github.com/google-gemini/gemini-cli/issues/23224).
