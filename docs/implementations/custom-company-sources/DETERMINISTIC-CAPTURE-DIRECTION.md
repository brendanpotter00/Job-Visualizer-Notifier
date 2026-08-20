# Deterministic API-Capture Direction (Tier-1) — the plan we have now

> **Status: DIRECTION, not yet a committed implementation plan.** Written 2026-08-19 to
> persist the thinking from an owner review session. The agreed workflow is:
> **(1) persist this direction [this doc] → (2) validate it with proofs-of-concept →
> (3) write the full-fledged implementation plan** once the POCs prove it works.
> Nothing here is built. It supersedes the daily-Stagehand approach in PR #248 as the
> intended end-state (see `PHASE-STAGEHAND-PLAN.md` for what shipped).

## Why this exists (the gap the owner caught)

The shipped E7 custom-company path (PR #248) discovers a board with a Browserbase
**Stagehand** session that reads the **rendered DOM**, stores a Stagehand *recipe*, and
then **re-runs a Browserbase Stagehand session every 24 hours** to re-read the page.

That daily re-run is the problem:
- It costs **~1 browser-minute per board per day** — this is what exhausted the
  Browserbase free tier (the `402 Free plan browser minutes limit reached` the owner hit).
- Browserbase meters **autonomous agent runs** with hard caps (3 Free / 15 Developer /
  50 Startup per month), so anything agent-per-run is unscalable.
- Calling replay "cheap" was wrong: replay is another paid browser session.

**What the owner wants instead:** use the browser **once** at discovery to find the
board's **underlying network request** (the JSON/GraphQL API behind the page), emit a
**deterministic script**, validate it, and then run *that* cheaply on a daily cadence
with **plain HTTP — no browser, no LLM, $0**. This is the original plan's `http_json`
recipe kind; the "Stagehand everything, dial back later" pivot deferred it and never
built it.

## The three tiers (fall back only when forced)

| Tier | How | Daily cost | Use when |
|---|---|---|---|
| **1 · http_json** | Capture the API once → replay with plain HTTP (`httpx`) | **$0** — no browser, no LLM | Board has a clean, stable, unsigned JSON/GraphQL API (many do) |
| **2 · observe-cache** | Cache Stagehand `observe()` actions → replay with `act()` | browser-hours, **no LLM on cache hit** | No clean API, but stable DOM |
| **3 · agent / extract** | Today's Stagehand DOM read (or full `agent()`) | browser-hours + LLM; `agent()` hits the 15/mo cap | Last resort: dynamic, signed, or bot-walled boards (e.g. Meta) |

Tier 1 is the default we *try*; the validation gate (below) decides whether a board
qualifies or must fall back.

## How it works — Browserbase primitives, in order

### ① One-time discovery (on Browserbase, ~1 browser-minute)
1. **Create a session** — `bb.sessions.create({ projectId })` → `connectUrl` (CDP WS endpoint).
2. **Connect over CDP and `Network.enable`** to record all requests/responses.
3. **Navigate** the careers URL; if jobs load lazily, use cheap Stagehand `observe`/`act`
   to click "Load more"/scroll. **Do NOT use the capped `agent()` primitive.**
4. **Find the request** whose response body is job-shaped JSON; pull it with
   `Network.getResponseBody` (do this **live** during the session — the post-hoc Session
   Logs API does not guarantee response bodies are retained).
5. **Synthesize an `http_json` recipe** — `{method, url, headers, records-path, field-map}`.
   This is **our code** (optionally one Claude call to map fields); **Browserbase does not
   emit an HTTP client** — its primitives are DOM/UI-level and its Director export is a
   *Stagehand* (browser) script, not an API client.
6. **Validate immediately** — replay the recipe with plain `httpx`; confirm HTTP 200 +
   expected JSON shape + non-empty jobs that match what the page showed. Match → store
   `transport='http_json'`. No match → fall back (Tier 2/3), flag `requires-browser`.

### ② Daily replay (off Browserbase, cheap)
1. Load the stored recipe from `company_scripts`.
2. Run it with plain `httpx` through the existing **`recipe_runner.py` + `url_guard`**
   (SSRF-safe). **No Browserbase, no LLM.**
3. Validation gate: HTTP 200 + expected JSON shape + non-empty jobs.
4. Pass → feed the **same completeness gate already built** (VERIFIED-only closes).
5. Fail (tokens rotated / endpoint drift) → mark stale, **re-run one discovery session**
   to re-capture; never wrong-close.

## Where Tier 1 breaks (be honest)

These make a captured request un-replayable by plain HTTP; the discovery-time validation
gate catches them and drops the board to Tier 2/3 / `requires-browser`:
1. **Rotating / short-lived auth tokens** (bearer / CSRF / nonce minted per page-load) —
   the single biggest killer for daily replay.
2. **Request signing / anti-bot tokens** (HMAC params, Akamai / PerimeterX / Cloudflare
   Turnstile / DataDome) — can't regenerate without running the site's JS.
3. **Browser-vs-direct-client divergence** (TLS/JA3 fingerprinting, required full header set).
4. **IP / geo gating** — a request captured through a residential proxy may 403 from a
   datacenter IP.
5. **Endpoint drift / parameterization** — GraphQL persisted-query hashes, cursors, date
   params may need templating, not verbatim replay. (Backend APIs are still generally more
   stable than DOM classes — a point in Tier 1's favor.)

## What we reuse (already in the codebase)

- **`recipe_runner.py` + `http_json` transport** — scaffolded, never wired to discovery.
  Tier 1 finally uses it.
- **`url_guard`** — SSRF guard for the daily HTTP replay.
- **The Phase-2 completeness gate** — VERIFIED-only closing, never-wrong-close. Unchanged.
- **`company_scripts`** — stores the recipe (`transport`, `oracle_kind`, `script` JSONB).
- **The add-flow + provisional "discovering" row + poll** — unchanged UX.

## Answers to the owner's side questions (persisted)

- **Does Amazon work with the current build today?** Not meaningfully — `amazon.jobs`
  isn't a supported ATS, so it hits the bounded ≤3-page Stagehand-DOM discovery (captures
  only the first ~2–3 pages of ~20k jobs, re-runs daily, may bot-refuse), and it's
  402-blocked now. **With Tier 1 it's nearly ideal:** `amazon.jobs/…/search.json?offset=N&result_limit=100…`
  is a clean public offset-paginated JSON API a prior project (`job-watcher`) already hit
  with plain `httpx` → all jobs, $0/day.
- **Name input ("Amazon" instead of a URL)?** Not built (Phase-5). A
  `resolve_company_name(name) → URL` layer: curated alias map → web search
  ("`<name>` careers", filter to careers/ATS hosts) → LLM rank → **confirm with the user**
  → feed the existing pipeline.
- **Could Claude's agent platform do this instead of Browserbase?** Not the browser part.
  Claude's hosted tools (`web_search` / `web_fetch`) read returned HTML but don't execute
  the page's JS or expose network requests, so they can't capture the hidden API. That
  needs a real browser (Browserbase, or self-hosted Playwright). **Split: Browserbase
  drives + captures; Claude/LLM reasons** (maps the captured request → recipe fields).
- **Embed the browser video so the user watches discovery live?** Feasible — Browserbase
  exposes a per-session **live-view URL** (iframe-able) + **downloadable recordings**.
  Could embed the live view on the "Setting up…" screen. Confirm the exact embed API before
  committing.

## Cost model (from Browserbase docs)

- Plans: Free $0 (1 browser-hr) / Developer $20 (100 hr, $0.12/hr overage) / Startup $99
  (500 hr) / Scale custom. **Billing unit = browser-hours** (session wall-clock).
- **Agent runs** metered separately: 3 / 15 / 50 / custom per month — overage **not
  published**. Tier 1 & 2 avoid agent runs entirely.
- **Cost fit:** discovery pays browser-hours **once per company** (~1 min); daily replay is
  plain HTTP **off Browserbase = $0**. A $20 Dev plan ≈ ~6,000 one-minute discoveries/mo.
  Browserbase shrinks to "discovery sessions only."

## Open questions to settle in the POC (step 2)

1. Does a live CDP `Network` capture on `amazon.jobs` yield a replayable `search.json`
   request (method/url/headers/body) that returns the same jobs via plain `httpx`?
2. Do the captured headers include a rotating/nonce'd token that breaks next-day replay?
3. What's the minimal header set needed for the direct client to not get a bot/empty response?
4. Confirm the exact Browserbase live-view embed + recording-download API (for the UX idea).
5. Field-mapping: deterministic vs. one Claude call — which is more robust across boards?

## Reference — Browserbase / Stagehand docs

- Web data retrieval (recommended approach = DOM extraction): https://docs.browserbase.com/use-cases/web-data-retrieval
- CDP explainer (Network domain, `getResponseBody`): https://www.browserbase.com/blog/what-is-cdp
- Session Logs API: https://docs.browserbase.com/reference/api/session-logs
- Session Inspector (live view / recording): https://docs.browserbase.com/features/session-inspector
- Stagehand `observe` (cacheable actions): https://docs.stagehand.dev/v3/basics/observe · caching: https://docs.stagehand.dev/v3/best-practices/caching
- Agents / Director (script export): https://docs.browserbase.com/use-cases/agents · https://www.browserbase.com/director
- Pricing: https://www.browserbase.com/pricing
