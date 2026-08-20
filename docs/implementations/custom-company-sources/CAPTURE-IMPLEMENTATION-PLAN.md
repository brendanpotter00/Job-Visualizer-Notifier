# Custom Companies via Deterministic API Capture — Implementation Plan (step 3)

> **Status:** implementation plan, validated by POCs (see `scripts/one_off/http_capture_poc/RESULTS.md`
> and `DETERMINISTIC-CAPTURE-DIRECTION.md`). This is the plan the implementation PR builds against —
> plan and code live in the **same** PR. Written 2026-08-19 after an owner review session.
>
> **Dependency:** this reuses the E7 foundations that currently live in the unmerged stack
> (#243 Phase 1 + #247 Phase 2): the `companies`/`user_companies`/`company_scripts` tables, the
> add-flow + provisional "discovering" row, `url_guard`, the scaffolded `recipe_runner`, and the
> Phase-2 completeness gate (VERIFIED-only closing). We either land #243/#247 first or bring those
> pieces into this PR. Nothing here depends on #248's Stagehand-DOM path — that path is **retired**
> (see Migration).

## Goal & principle

Let a signed-in user paste a careers URL; we read that company's jobs on the existing cadence,
privately to them. The **how** is the pivot: instead of re-running an LLM browser agent every day
(the #248 approach, which is expensive and non-deterministic), we **use a browser once at discovery
to find the board's underlying jobs API, emit a deterministic recipe, and replay that recipe cheaply
every day** — no LLM, no DOM parsing at runtime.

**Deterministic-only principle (owner):** every runtime path either works or it doesn't, decided
**once** at discovery. There is **no** non-deterministic DOM/agent tier that could silently fail and
burn resources daily. A board with no capturable API is **refused** ("not trackable").

## The two tiers (else refuse)

| Tier | Recipe runs as | Where | Daily cost | Example |
|---|---|---|---|---|
| **1a · http_json** | plain HTTP request | our server (`recipe_runner` + `httpx`) | **$0** | Amazon, Spotify |
| **1b · browser_fetch** | the same request via `page.evaluate(fetch())` on the site's origin | **our own headless Chromium** (Railway) | our compute (no LLM, no Browserbase) | TikTok |
| **✗ no clean API** | — | — | — | refuse → "not trackable" (e.g. Meta) |

Tier 1a is tried first; 1b only when 1a's replay fails (origin/cookie/CORS-gated APIs). Both are
**deterministic** and validated at discovery.

## Where things run (own-Chromium first)

- **Daily replay** runs on infra we already have: 1a via `httpx` in the backend; 1b via our own
  headless **Playwright/Chromium in the Railway deployment** — the exact pattern the existing
  TikTok/Apple/Microsoft scrapers use. **No Browserbase browser-hours for daily replay.**
- **Browserbase is a targeted discovery-time tool only**, used when our own Chromium can't:
  (a) **bot-walled sites** that block our datacenter IP (Browserbase stealth/residential IPs), and
  (b) the **hosted live-view embed** for the progress UX. Discovery on normal boards can use our own
  Chromium too.
- Tradeoff to respect: own-Chromium uses Railway RAM (~200–500 MB/session on the 4 GB container), so
  concurrency is bounded and we supervise crashes; Browserbase offloads that at a per-hour cost.

## Discovery flow (once per company)

Runs as an async task (`discover_custom_company`) off the existing non-ATS add path. Steps map 1:1
to the progress UX below.

1. **Establish origin.** Open the pasted careers URL in a browser (own Chromium by default;
   Browserbase when stealth/live-view is needed). Trigger lazy loads with cheap `observe`/scroll if
   required — never an autonomous agent.
2. **Capture network.** Record every XHR/fetch JSON response (URL, method, request headers, POST
   body, response body) via the Playwright response listener / CDP `Network` domain.
3. **Deterministic pre-filter.** Keep only JSON responses containing an array of objects (drops
   analytics/config/tracking noise) → candidate set.
4. **LLM selects + maps — once.** **Claude Haiku 4.5** (via the existing `ANTHROPIC_API_KEY`, same
   client as location normalization), structured-output JSON: given the candidates (URL, method,
   small body sample), return `{chosen_request, records_path, field_map{title,location,url,id,posted_at}}`.
   This is the one-time expensive step; runtime never calls it.
5. **Synthesize the recipe** — `{transport, origin_url, method, endpoint, headers, body_template,
   records_path, field_map, pagination{param,page_size,style}}`.
6. **Acceptance gate — replay from the PRODUCTION environment** (not the capture browser):
   - 1a: `recipe_runner` + `httpx` from our server. 1b: `page.evaluate` in a fresh own-Chromium.
   - **Assert:** HTTP 200 (+ payload `code==0` where applicable) · parses as JSON · job-shaped ·
     non-empty (≥ `expected_min`) · **matches the capture** (same/overlapping ids the browser saw).
   - **Pass →** store the recipe, flip to tracked, **show the user a preview of the found jobs**.
     **Any fail →** try the next candidate; exhausted → **REFUSE** ("not trackable"), store nothing.
   - Trying the acceptance replay from the prod env is what catches IP/geo gating or a missing header
     **before** we promise tracking.
7. **SSRF (must-design-in).** `url_guard.validate_public_url` on **both** the pasted URL and the
   **discovered endpoint** — https-only, reject RFC1918/loopback/link-local/metadata IPs, no
   cross-host redirects, resolved-IP pin. Applies at discovery AND on every daily replay.

## Storage

Reuse `company_scripts` (`company_id`, `script` JSONB, `script_version`, `transport`, `oracle_kind`).
`transport ∈ {http_json, browser_fetch}`. The `script` holds the recipe from step 5. Jobs land under
`source_id = custom:<company_id>` (unchanged isolation).

## Daily replay

Reuse the leaf-task shape. `recipe_runner.run_recipe(recipe)`:
- **http_json:** `httpx` through a `GuardedTransport` (no redirects, `url_guard` every hop).
- **browser_fetch:** own headless Chromium → navigate `origin_url` → `page.evaluate(fetch(endpoint,
  {headers, body, credentials:'same-origin'}))` → parse. Bounded timeouts; supervised.
- Paginate via the recipe's `pagination`. Map rows via `field_map`. Raise (never `[]`) on
  non-2xx/malformed/zero/`< expected_min`.
- Feed the rows to the **existing Phase-2 completeness gate** (VERIFIED-only closing, never
  wrong-close). Daily validation (200 + shape + non-empty) is the gate; on failure → mark stale →
  enqueue re-discovery, **close zero jobs**.

## Discovery-progress UX (frontend)

Because the steps are deterministic and known, render a **4-step checklist** (not a spinner), with
the read-only Browserbase **live-view iframe** (`pointer-events:none`, `&navbar=false`) as the visual
during steps 1–2:

1. Opening the careers page → 2. Finding the jobs feed → 3. Verifying we can read it → 4. Ready to track.

- Each done step shows a **specific** result ("read 90 jobs"). Success terminal = job **preview** +
  "Start tracking". **Refuse fails at a named step** ("Found the feed ✓ · Couldn't confirm the
  results match ✕"), framed as "we couldn't read {Company}'s board" + different next actions (paste
  the direct board URL, request manual, notify-me) — never a bare retry.
- Mobile: checklist primary; live view behind a "Watch live" toggle. Safety nets: on
  `browserbase-disconnected` fall back to steps-only; soft per-step timeouts advance the substatus copy.
- Poll `listMyCompanies` while `health_state='discovering'` (existing pattern); the task streams step
  state.

## Name input (later phase, in this plan — not first)

`resolve_company_name(name) → careers URL`: curated alias map → web search ("<name> careers", filter
to careers/ATS hosts) → Claude rank → **confirm the match with the user** → feed the same pipeline.
Sequenced after the core tiers ship.

## Migration off #248

- **Retire the Stagehand-DOM daily path** (transport `browser_agent`) — remove it, or keep behind a
  default-OFF flag as a debug escape hatch (owner's call).
- **Keep** the Phase-1/2 gate, `company_scripts` storage, `url_guard`, the add-flow, and the
  provisional "discovering" row + poll.
- **Re-discover existing custom companies** (the raindrop demo) under the new model; a board with no
  capturable API becomes refused.

## Files (add / change)

Backend (`src/backend/api/`):
- `services/capture/discover.py` — orchestrates the discovery flow (steps 1–7).
- `services/capture/network_capture.py` — own-Chromium/Browserbase session + CDP/response capture.
- `services/capture/request_selector.py` — pre-filter + the Claude Haiku pick+map call (structured output).
- `services/recipe_runner.py` — extend for `browser_fetch` (own-Chromium `page.evaluate`); keep `http_json`.
- `services/url_guard.py` — reused; assert on entry + discovered endpoint.
- `tasks/discover_custom_company.py` — async discovery task (emits step state).
- `tasks/fetch_custom_company.py` — daily leaf: route `http_json`/`browser_fetch` to `recipe_runner` → gate.
- `routers/user_companies.py` — non-ATS add → discovery; job-preview on success.

Frontend (`src/frontend/`): `MyCompaniesPage`/`MyCompaniesList` discovery-progress checklist + live-view
iframe + job-preview + named-step failure states.

Tests: request-selector (fixture candidates → correct pick/map), acceptance-gate (match/refuse),
recipe_runner http_json + browser_fetch, SSRF rejection table, the never-wrong-close regression, the
import-guard (runtime path imports no LLM/agent).

## Phasing

1. **Core:** capture discovery (own-Chromium) + request-selector + recipe synthesis + acceptance gate
   + `http_json` + `browser_fetch` daily replay + SSRF + wire to the completeness gate + refuse. Retire #248 DOM path.
2. **UX:** discovery-progress checklist + live-view embed + job preview.
3. **Later:** name input; Browserbase-stealth for bot-walled sites; facet-splitting for >10k boards.

## Risks (from the review) & how the plan handles them

1. **SSRF** — `url_guard` on entry + discovered endpoint, every replay hop (core, step 7).
2. **Tier-1b cost** — runs on our own Railway Chromium (~free), not Browserbase; concurrency bounded by container RAM.
3. **Recipe drift** — daily gate marks stale → re-discovery; a staleness window is expected.
4. **>10k caps** — facet-splitting deferred (phase 3); most boards are under the cap.
5. **Migration** — retire the DOM path, re-discover existing companies.
6. **ToS/legal** — flagged for the owner; product decision.
