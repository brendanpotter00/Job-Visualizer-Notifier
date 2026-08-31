# Custom company sources — locked decisions and ground truth (E7)

> ## Status: the decisions here still hold; the three-PR build plan does not
>
> This was the original 3-PR implementation plan (2026-08). **PR 1 shipped** —
> `services/url_guard.py`, `services/ats_link_resolver.py`, `services/ats_discovery.py`,
> `POST /api/companies/resolve` and the `vercel.json` rewrite are all in the tree.
> **PR 2 and PR 3 as specified here were never built.** The recipe runtime was
> re-planned as gated scripts + `HarvestEvidence` (`BUILD-PLAN.md`, `PHASE-3-PLAN.md`),
> and the ownership/visibility work shipped in a different shape.
>
> `BUILD-PLAN.md:23` is the reason this file survives: *"the locked owner decisions
> D1–D12 still hold."* What is kept below is the half that cannot be reconstructed —
> those decisions, the environment traps, the rejected alternatives, the live-probe
> measurements, the prod numbers, and the accepted security gap that
> `services/ats_discovery.py` cites by section. The step-by-step build instructions for
> all three PRs have been removed; the shipped code and its tests are the record now.
>
> **Read first:** `OVERVIEW.md` (architecture) and `BUILD-PLAN.md` (the live spec).
> `STACK-ORCHESTRATION.md` is the running log of what actually happened.

A signed-in user pastes a careers-page URL. The company is scraped on the existing
cadence and appears in the existing views **for that user only**, plus an
"Add Companies" page.

ClickUp: epic E7 `wdwb1cbnc2`, subtasks 7.1 `wdwb1cbnc3`, 7.3 `wdwb1cbnc5`,
7.4 `wdwb1cbnc6`. Spike 7.2 `wdwb1cbnc4` → `docs/spikes/2026-08-browser-agent-discovery.md` (**GO**).

---

## 0. Owner decisions that OVERRIDE the tickets

Read this section before the tickets. Where they disagree, this wins.

| # | Locked decision | What the ticket says | Where the ticket text must be ignored |
|---|---|---|---|
| D1 | **No approval flow, anywhere.** An add takes effect immediately, scoped to the adding user. The owner reviews after the fact. | 7.4 "An admin review queue: list pending, approve … or reject"; 7.4 Open decision 1 ("ship v1 with approval on for both"); epic risk section "human approval before anything reaches the cron" | 7.4 Scope item 4; 7.4 AC "Approving an ATS request creates exactly one `companies` row"; 7.3 out-of-scope "approval queue — 7.4" |
| D2 | **Admin observability dashboard instead of a gate.** Every add AND attempted add (failures + unsupported URLs), per-user counts, cost, most-attempted unsupported domains, plus a **Promote to public** row action. | 7.4 models `company_requests` as a *pending queue* with `status`/`decided_at`/`reject_reason` | Table becomes **`company_add_attempts`** — a pure append-only audit log that gates nothing. No `status='pending'`, no `decided_at`, no `reject_reason`. |
| D3 | **Global scrape, private visibility.** One `companies` row per company, scraped once. `companies.visibility ∈ {'public','user'}` + a `user_companies` ownership table. | 7.4 Open decision 2 leaves this open | Resolved: global row + `user_companies`, **not** `user_enabled_companies` (that is a soft *allow-list* where zero rows means "see all" — reusing it would make a private company visible to everyone with no rows). |
| D4 | **My Companies page = list + health badge** (checking / active / needs attention), last-updated, open-job count. No run logs, recipes, or error internals for users. | 7.4 "a submit form and a 'my requests' status list" | Diagnostics stay admin-only. |
| D5 | **v1 input is a URL only.** No company-name search. | — | — |
| D6 | **Feature flag defaulting off**; rollback = flip the flag or `enabled=false`. | agrees | — |
| D7 | **Quotas only, no gate**: max 5 custom companies/user, sliding-window add cooldown keyed on `user_id`, global cap. | 7.4 also wants "N pending requests per user (start at 3)" | No pending state exists ⇒ **no pending quota**. Keep: per-user total (5), cooldown, global cap. |
| D8 | **No `browser_dom`.** `http_json` + `http_html` only. Playwright never enters the scrape hot path. | 7.3 "Playwright only if 7.2 blessed `browser_dom`" | Spike §5 says do not build it. Do not build it. |
| D9 | **Frozen recipe schema is `scripts/one_off/recipe_spike/recipe_schema.py`.** Do not invent one. `recipe_runner` is a port/hardening of `scripts/one_off/recipe_spike/replay.py`. | 7.3 agrees | — |
| D10 | **`total_path` enforcement is required** where a source publishes a total. | 7.3 does not mention it (predates the spike) | Spike §4/§6. |

### D11 — the two acceptance targets the owner named (new, not in any ticket)

| Target | Pasted URL | Must work by | Verified shape |
|---|---|---|---|
| **Intel** | `https://jobs.intel.com` | **end of PR 1** | 301 → `corpredirect.intel.com/Redirector/404Redirector.aspx?404;https://jobs.intel.com/` → 301 → `https://intel.wd1.myworkdayjobs.com/External/page/6042070b79e01001f04fa9b468070000` (200). Workday, **cross-host redirect chain**, path form `/<slug>/page/<hex>`. |
| **Cisco** | `https://jobs.cisco.com` | **end of PR 3** | 302 → `https://careers.cisco.com` → 303 → `/global/en` (200). Phenom People front end, but the **ATS of record is Workday** — see §1.4. |

### D12 — a runtime browser is not runtime AI

The single most-misread point in this epic. They are independent:

- **An agent/LLM** works out *how* a site serves its jobs. Runs **once**, at
  add-time. Never on the cadence. Non-negotiable — it is what makes the
  economics work (~10 s once, versus ~36 browser-hours per company per month).
- **A browser** is just a runtime tool for JS-heavy sites. It would be
  acceptable and free if a target needed one — `scripts/{google,apple,microsoft}_jobs_scraper/`
  already drive deterministic Playwright hourly at zero marginal cost.

D8 says don't build `browser_dom` because **no target needed it** (spike §5),
not because a browser would be philosophically wrong. If a future target
genuinely requires one, that is a cost question, not a violation of the design.

---

## 0.5 Local environment traps

These cost an afternoon each if you meet them cold.

**The dev-database collision.** The backend suite can produce ~125 failures, or
1,300+ errors, that have nothing to do with your changes. Two causes:

1. *Alembic revision not found.* The shared `jobscraper` dev DB may be stamped
   with a migration that exists only on another local branch (as of 2026-08,
   `a3c32c2aa4d3` from the unmerged `fix/job-freshness-sidecar-unit23`). Alembic
   then cannot locate the DB's own revision and every DB-fixture test errors.
2. *Procrastinate's tables live in `public`* and are shared across the per-test
   schemas, so deferred-job counts leak between tests (`assert 10 == 5`).

Workaround — give the branch its own database:

```bash
docker exec jobscraper-postgres psql -U postgres -c "CREATE DATABASE jobscraper_wt2;"
cd src/backend
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/jobscraper_wt2" PYTHONPATH=.:../.. \
  ../../.venv/bin/python -c "
import asyncio
from api.tasks.procrastinate_app import procrastinate_app, ensure_schema_async
async def main():
    async with procrastinate_app.open_async():
        await ensure_schema_async(procrastinate_app)
asyncio.run(main())"
```

Then run tests with `TEST_DATABASE_URL=…/jobscraper_wt2`. Do **not** drop the
procrastinate tables piecemeal — `DROP TABLE CASCADE` leaves the enum types
behind and the schema install is not idempotent; drop the whole database.

**Establish your baseline before blaming your own code.** As of 2026-08-08 it is
**125 failed / 1379 passed**. If your failure count matches, you broke nothing.
To prove it, move your new files aside and re-run — that is exactly how PR 1 was
cleared.

**Other traps.** `alembic` must run from the **repo root** (`alembic.ini` lives
there, not `src/backend`). The system `python3` is 3.8 — always use the repo
`.venv` (3.13). The frontend's vitest hangs silently on Node < 22.12.0; use nvm
22.14.0.

---

## 1. Cross-cutting decisions (decide once, cite everywhere)

### 1.1 SCOPE QUESTION — productionise discovery now, or ship ATS-only?

**Recommendation: ship ATS-only. Park non-ATS URLs as `unsupported`. Do NOT
productionise the spike's agent + Playwright discovery in PR 3.**

Reasoning, strongest first:

1. **The owner's own two acceptance targets are both Workday.** Intel resolves to
   Workday after a redirect. Cisco *renders* on Phenom but every `applyUrl` in its
   payload points at `https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/...`, and
   `POST https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs`
   returns `total: 1060` — **the exact number Cisco's own Phenom UI reports**
   (`refineSearch.totalHits = 1060`). Neither target needs an agent. Both need
   redirect-following plus link-sniffing: ~200 lines of deterministic code.
2. **The spike deliberately chose unrepresentative targets** (its own §7.3:
   "Seven targets is a small sample, chosen to be hard rather than
   representative"). Intel and Cisco are what users actually paste — a vanity
   careers domain in front of a mainstream enterprise ATS. If that is the dominant
   shape, deterministic resolution covers most of the demand and discovery covers
   a long tail we cannot yet size.
3. **Discovery is a whole PR of its own.** Productionising it needs: Playwright in
   the Railway image (see `docs/incidents/2026-04-09-oom-memory-fragmentation.md`
   and `docs/incidents/2026-05-05-scraper-pthread-exhaustion.md`) or a laptop-side
   worker; an Anthropic agent loop with a real spend line; per-user cost
   accounting; and an add-time latency budget of 8–70 s (Amazon's capture was
   66.3 s) *while the user watches a spinner*. Bolting that onto PR 3 makes PR 3
   unshippable and unrevertable.
4. **Nothing is wasted.** PR 2 ships the runtime; the runtime is what makes *any*
   recipe runnable regardless of who authored it. Until a discovery PR lands, the
   owner can hand-author a recipe and insert it admin-side. The runtime's
   inertness property (zero recipe rows ⇒ byte-identical behaviour) holds either
   way.
5. **`unsupported` is an honest answer the spike itself demands** (§8: "'we can't
   track this site' is a real, expected outcome (Tesla), not an edge case").

**What makes this a measured decision rather than a guess:** PR 3's
`company_add_attempts` records *every* attempt including unsupported ones, with the
normalized registrable domain. The admin dashboard's **"most-attempted unsupported
domains"** panel is exactly the dataset that says whether the next investment is
agent discovery (E7.5) or a Phenom client (§1.4). Ship the instrument before the
engine.

**Explicit non-goal for PR 3:** no `anthropic`, `playwright`, `stagehand`, or
`browserbase` import anywhere under `src/backend/`. Enforced by the import-guard
test from PR 1 (§2.6), extended in PR 2 and PR 3.

### 1.2 Three-layer resolution ladder (this is the shape of PR 1 + PR 3)

```
L0  resolve_ats_url(url)            pure, IO-free, urllib.parse only.  Intel? no.  Cisco? no.
L1  follow_to_ats(url)              IO. Follows redirects manually, url_guard-checks EVERY hop,
                                    feeds each hop's URL back into L0.   Intel? YES.  Cisco? no.
L2  sniff_embedded_ats(url)         IO. Fetches the final landing page (+ a small fixed candidate
                                    sub-path list) through url_guard, regex-scans the body for
                                    known ATS URLs, feeds hits back into L0.  Cisco? YES.
```

L0 stays pure so its parametrized table and the zero-network assertion survive
intact. L1 and L2 are **composition, not contamination** — they are separate
functions in a separate module that *call* L0.

**L1 and L2 belong in PR 1, not PR 3.** The 7.1 ticket defers embedded-board
sniffing to 7.4 "which owns the SSRF allowlist" — but PR 1 *builds* `url_guard`, so
the stated reason for deferring evaporates. Keeping the whole ladder in one PR also
keeps one coherent test surface for "what does this URL resolve to", and makes
Intel pass at the end of PR 1 as required by D11.

**Redirect policy differs by phase — this distinction is load-bearing:**

| Phase | Cross-host redirects | Why |
|---|---|---|
| **Discovery** (`follow_to_ats`, `sniff_embedded_ats`, add-time only) | **Allowed**, max 5 hops, every hop re-validated by `url_guard` before the request | Intel is `jobs.intel.com` → `corpredirect.intel.com` → `intel.wd1.myworkdayjobs.com`. Forbidding cross-host here blocks the single most common real-world case. |
| **Scrape** (`recipe_runner`, all six ATS clients) | **Not followed at all** (`follow_redirects=False`) | Matches `replay.py:162,214,269`. A recipe's entrypoint is pinned; a redirect at scrape time is a change we must see, not absorb. |

The 7.4 ticket's flat "redirects are not followed across hosts" applies to the
scrape phase only. Say so in the PR description.

### 1.3 Workday matcher — verified rule (supersedes the 7.1 ticket's form)

The ticket's form is `<tenant>.wd<N>.myworkdayjobs.com/<lang?>/<career_site_slug>`.
Intel's real URL is `/External/page/6042070b79e01001f04fa9b468070000` — the slug is
the **first** segment and there are trailing segments the ticket does not mention.

```
host must match  ^(?P<tenant>[a-z0-9][a-z0-9-]*)\.wd(?P<n>[0-9]+)\.myworkdayjobs\.com$   (host lowercased first)
segments = [s for s in urlsplit(url).path.split('/') if s]
if segments and re.fullmatch(r'[a-z]{2}(-[A-Za-z]{2})?', segments[0]):
    segments = segments[1:]                       # strip an optional locale prefix
if not segments: return None                      # bare host ⇒ no guess
career_site_slug = segments[0]                    # VERBATIM. never .lower(), never .title()
# every remaining segment is ignored: /job/..., /details/..., /page/<hex>, /apply, /login
base_url        = f"https://{host}"               # host lowercased
tenant_slug     = tenant                          # from the HOST, not the path
```

Verified against prod (`mcp__postgres-prod__query`, 2026-08-05) and live:

| id | URL form | `career_site_slug` | `tenant_slug` |
|---|---|---|---|
| blueorigin | `blueorigin.wd5.myworkdayjobs.com/BlueOrigin` | `BlueOrigin` ✅ | `blueorigin` |
| capitalone | `capitalone.wd12.myworkdayjobs.com/Capital_One` | `Capital_One` ✅ | `capitalone` |
| adobe | `adobe.wd5.myworkdayjobs.com/external_experienced` | `external_experienced` ✅ | `adobe` |
| disney | `disney.wd5.myworkdayjobs.com/disneycareer` | `disneycareer` ✅ | `disney` |
| **gm** | `generalmotors.wd5.myworkdayjobs.com/Careers_GM` | `Careers_GM` ✅ | **`generalmotors`** |
| **slack** | `salesforce.wd12.myworkdayjobs.com/Slack` | `Slack` ✅ | **`salesforce`** |
| **intel** (live) | `intel.wd1.myworkdayjobs.com/External/page/6042…` | **`External`** ✅ | `intel` |
| **cisco** (live) | `cisco.wd5.myworkdayjobs.com/Cisco_Careers` | **`Cisco_Careers`** ✅ | `cisco` |

Live probes confirming the derived config actually works:
`POST https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs` → `total: 681`.
`POST https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs` → `total: 1060`.

> ⚠️ **Contradiction with 7.1's acceptance criterion.** 7.1 requires the resolver
> output to match the prod row "byte-for-byte on `board_token` **and**
> `provider_config`". For Workday that is **impossible**: prod's `board_token` for a
> Workday row is the internal company id (`gm`, `slack`), not anything derivable
> from the URL (`generalmotors`, `salesforce`). `workday_client.fetch_jobs` never
> reads `board_token` (`workday_client.py:133-136` takes `provider_config` only).
> **Restrict the byte-for-byte assertion to `provider_config` for Workday**, and
> assert `board_token` for greenhouse / ashby / lever / gem / eightfold only. For a
> Workday candidate the resolver returns `board_token = tenant_slug`; the PR-3 add
> path may overwrite it with the generated company id to match the hand-seeded
> convention (cosmetic either way).

### 1.4 Cisco / Phenom — recommendation

**Cisco needs no new ATS client. It resolves to Workday via L2 sniffing.** Verified:
`https://careers.cisco.com/global/en/search-results` serves HTML containing **10
occurrences** of `https://cisco.wd5.myworkdayjobs.com/Cisco_Careers` (inside
`applyUrl` values in the `phApp.ddo` JSON island). The bare landing page
`/global/en` contains **zero** — so the sniffer must try a small candidate
sub-path list, not just the landing URL (§2.4).

**Should Phenom become a 7th first-class ATS client? Yes — but as a follow-up
(E7.5), not inside these three PRs.** Evidence gathered live:

```
POST https://careers.cisco.com/widgets            # value of phApp.widgetApiEndpoint
Content-Type: application/json
{"lang":"en_global","deviceType":"desktop","country":"global","pageName":"search-results",
 "ddoKey":"refineSearch","from":0,"size":100,"jobs":true,"counts":true,
 "pageId":"page4","siteType":"external","keywords":"","global":true,
 "selected_fields":{},"locationData":{}}
→ 200, refineSearch.totalHits = 1060,  refineSearch.data.jobs = [...100]
   from=1000 → hits 60 (correct tail).  size=100 honoured.
   job fields: jobId, title, applyUrl, cityStateCountry, city/state/country,
               postedDate, dateCreated, reqId, category, type, jobSeqNo
```

- It is a **platform, not a site**: `phApp.widgetApiEndpoint`, `ddoKey`, `from`,
  `size`, `pageId`, `siteType` are Phenom-generic. One client keyed on
  `{careers_host, locale, country, page_id}` in `provider_config` would unlock many
  tenants at once — the same economics as the Eightfold client.
- It ships a first-class completeness oracle (`refineSearch.totalHits`), so it
  satisfies D10 naturally.
- `GET /api/apply/v2/jobs?domain=…` exists on the host but returns
  `{"status":"failure","errorMsg":"Tenant not identified"}` for every domain value
  tried (`cisco.com`, `careers.cisco.com`, `CISCISGLOBAL`, `www.cisco.com`). Use
  the `widgets` POST, not that endpoint.
- **Not on the critical path**, because Cisco works via Workday. Let the
  `company_add_attempts` unsupported-domain panel decide when Phenom earns its
  own client.

> 📌 **Concrete gap in frozen recipe schema v1, found while probing Cisco.**
> `phApp.ddo` lives inside a large inline `<script>` alongside other JS assignments
> (551 chars of other code before it; the script is 86 KB). The schema's
> `embedded_json` only supports `source: "attribute" | "text"`
> (`recipe_schema.py:135-144`) — `"text"` would capture the whole script body,
> which is not valid JSON. A Phenom-style page therefore cannot be expressed as an
> `http_html` recipe today. **Do not silently patch the frozen schema.** Record it
> as a known gap alongside the five in spike §4 ("Known gaps, deliberately
> deferred"); a future `source: "js_var"` mode (anchor on an assignment prefix,
> brace-match to close) would close it. Cisco does not need it — the `widgets`
> POST is a plain `http_json` target and the Workday route is better still.

### 1.5 Other cross-cutting decisions

| Question (ticket 7.3 "Open decisions") | Decision | Justification |
|---|---|---|
| Recipe storage | **New `company_scrape_recipes` table** | `companies.provider_config`'s docstring (`db_models.py:525-532`) calls the shape a *frozen contract*, per-ATS. Recipes are machine-generated, versioned, replaceable, and carry health columns (`consecutive_failures`, `last_ok_at`, `quarantined_at`, `quarantine_reason`) that have no business widening `companies`. |
| `source_id` strategy | **One `SourceId.RECIPE = "recipe_api"`**, job ids namespaced `f"{company_id}:{upstream_id}"` | `job_listings` PK is composite `(source_id, id)` (`db_models.py:95`), so namespacing the *id* side gives cross-company uniqueness. Per-company `source_id` values would multiply distinct values through every `scripts/shared/database.py` helper (they all take `source_id` as the leading scoping arg), through `job_freshness`, through enrichment, and through the public route `/api/jobs/{source_id}/{job_id}` (`routers/jobs.py:121`). `constants.py:12` is a fixed `class SourceId` of `Final[str]`, not a dynamic registry. Separator `:` is unambiguous: company ids match `^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$` (`models.py:31`) and never contain `:`. |
| Where execution runs | **Railway worker, in-process with FastAPI** (unchanged) | Spike §8: HTTP-only recipes need no browser. `src/backend/api/requirements.txt` already has `httpx`; only `beautifulsoup4` is added (PR 2). |
| Quarantine threshold | **3 consecutive failures** | At `*/30` that is 90 min of continuous failure. It is *not* racing the close sweep: a failing recipe raises, so `increment_consecutive_misses` never runs and `MISSED_RUN_THRESHOLD=2` is never approached. 3 is purely transient-blip tolerance (the spike hit one real blip). |
| One queue or one per recipe | **One `recipe_fetch` queue** | Worker concurrency is 5 and the six existing ATS queues already share it (`main.py:60-69`). `_TASK_TIMEOUT_S = 120.0` bounds any single recipe. Per-recipe queues would grow `_WORKER_QUEUES` unboundedly, and a test pins its membership. |
| Are attempts public? | **No.** `company_add_attempts` is admin-only. | D2 makes it an audit log. A public "requested companies" board exposes what users are job-hunting for, and D1 removed the dedupe/queue motive for it. |
| Feature flag | Backend `settings.custom_company_sources_enabled: bool = False`; frontend `VITE_CUSTOM_COMPANIES_ENABLED`. **Both must be on.** Backend is authoritative. | Copies the enrichment-flag pattern (`config.py:53-79`) and `config/auth.ts:21`. `Settings.model_config` has `extra="ignore"` (`config.py:104`), so a typo'd env var fails silently — pin the name with a test. |

### 1.6 Verified ground-truth corrections to the briefing

Flag these to the owner; the exploration was thorough but four items are wrong or stale.

1. **`src/backend/api/tests/test_alembic_single_head.py` does not exist in this
   worktree.** `git status --short` here is clean; the file is untracked in the
   *parent* checkout only. PR 2 must **create** it (it is listed as a deliverable
   below), not assume it.
2. **`docs/custom-company-sources-question.md` does not exist.** All four tickets
   cite it as the primary source. `docs/` contains no such file. Do not send an
   implementer looking for it.
3. **`api/jobs.ts` does NOT forward `Authorization`.** `api/users.ts:30-31` and
   `api/companies.ts:34-36` do; `api/jobs.ts` builds its header dict from
   `getInternalKeyHeader()` only (`api/jobs.ts:33`) and allowlists query params.
   Owner-scoped `/api/jobs` (PR 3) requires editing that file.
4. **There is no `/api/companies` rewrite in `vercel.json`.** The bare path works
   via Vercel implicit file routing; `POST /api/companies/resolve` will 404 in
   production without a new rewrite. `api/companies.ts:13-16,43-45` *already*
   handles `?path=` and POST bodies — only the rewrite is missing. PR 1 deliverable.
5. Minor: the frontend auth registry lives at
   `src/frontend/src/features/features/getTokenOrNull.ts` (nested `features/features/`),
   not `src/frontend/src/features/featuresApi.ts`.
6. Minor: current Alembic head is **`a7c31d9e0b46`**
   (`20260730_120000_a7c31d9e0b46_repoint_ashby_boards_and_deactivate_unity.py`),
   49 revisions, exactly one head.

### 1.7 Known gaps deferred out of these three PRs

**First-run posting dates — ClickUp 7.6 (`wdwb1cbp8n`).** Not E7.5: that identifier is
already used above (§1.1, §1.4) for agent discovery / a Phenom client, which is a
different thing.

On the first scrape of a `(company, source_id)` pair, every row's `first_seen_at` is the
scrape timestamp, so the company's entire back catalogue renders as posted on its add
date and the hiring-trend graph shows a spike that never happened. Measured in prod
2026-08-09: **25,892 rows (37.3% of `job_listings`) across all 133 companies** are
first-run rows; median `first_seen_at − posted_on` skew is **31.4 d** (p90 207.9 d)
versus **0.0 d** in steady state — so this is specifically a first-run defect, not a
general one.

**Why it lands on this epic:** every user-added company is by definition a first run, so
PR 3's self-serve flow hits it on day one for every company it creates. **PR 2's
recipe-backed companies inherit it in the worst form** — the 7.2 spike found Meta,
TikTok, Spotify, Tesla and Jane Street publish **no** posted date at all
(`docs/spikes/2026-08-browser-agent-discovery.md` §7.4, and the per-target
`FINDINGS.md`), Amazon does, and YC's is a humanized relative string with the same
lossiness class as Workday's synthetic dates. `recipe_schema.py` has no date field today.
If one is added later it must arrive with a trust policy already decided, or it re-imports
the Workday problem into a new surface.

**Do not attempt a fix inside PR 1–3.** Two findings make it non-trivial and they are
carried in the ticket: the graph reads `first_seen_at` exclusively (no COALESCE anywhere —
`services/database.py:221-231`, `timeBucketing.ts:93`), so it is a presentation-layer
choice, not a storage one; and Workday's `posted_on` is synthesized from relative strings
(`workday_client.py:480-548`) with 2,675 rows sharing a single sliding value, so "prefer
the provider date" is actively wrong there. Note also that a **board switch is the same
shape** — PR #236 / `e2835a568ade` re-created it for 403 rows across 5 companies.

---

# Accepted gaps carried out of PR 1

The rest of the PR-1 / PR-2 / PR-3 specifications are gone — they were executed, or
replaced. These two paragraphs are kept verbatim because they record a decision rather
than an instruction, and `services/ats_discovery.py` cites the second one by section.

## 1.4 services/ats_discovery.py — contract

**Probe runs synchronously inside the request** (7.1 Open decision 1). Justification:
the user needs a real "we found 681 open jobs" confirmation before the row is
written, D1 removed the human review that would otherwise catch a dud, and 12 s is
well inside the Vercel proxy budget. Deferring the probe would mean writing a row we
have not confirmed — exactly the 2026-03-29 shape.

> 📌 **Known gap, accepted in PR 1: the probe byte cap reaches 2 of the 6 ATSs.**
> `ats_discovery._bounded_json` bounds the response body (raw *and* decoded) and
> refuses a non-`identity` `Content-Encoding`, but only Workday and Eightfold —
> the two `_COUNT_ONLY_ATS` paths — go through it. Greenhouse, Ashby, Lever and
> Gem are probed by calling their existing `fetch_jobs` clients, each of which
> does a plain `response.json()` with no ceiling and httpx's default
> `Accept-Encoding: gzip, deflate`. A hostile response there is the same
> unbounded-decode exposure that was measured at 67 MB per chunk on the sniffer.
> **Those six clients are deliberately out of scope for PR 1** — they are shared
> with the scrape path and the six Procrastinate fan-out/fetch tasks, and
> changing their read path is a change to production scraping, not to discovery.
> What bounds the gap today is `assert_ats_api_host`: those four probes can only
> ever reach `boards-api.greenhouse.io`, `api.ashbyhq.com`, `api.lever.co` and
> `api.gem.com`, so exploiting it means compromising the ATS vendor rather than
> getting a URL past the resolver. **PR 2 inherits this as a decision, not a
> surprise**: the natural fix is one shared bounded-JSON read used by all six
> clients, sized per-ATS, landed together with the recipe runtime's own fetch
> path. Recorded here and in the `_bounded_json` docstring.


## 4. Ticket-vs-decision divergence checklist

Print this in every PR description so the approval queue cannot be reintroduced by
an implementer reading the tickets literally.

- [ ] **No `company_requests` table.** It is `company_add_attempts`, append-only, gates nothing. (D2)
- [ ] **No `status='pending'`, no `decided_at`, no `reject_reason`, no approve/reject endpoints.** (D1)
- [ ] **No "N pending requests per user" quota** — there is no pending state. (D7)
- [ ] **No "human approval before anything reaches the cron"** — adds are immediate. (D1)
- [ ] **Promote to public is post-hoc, not a gate.** (D2)
- [ ] **`browser_dom` is not implemented** and is *rejected* by `validate_recipe`. (D8)
- [ ] **`total_path` enforcement is required** — not in any ticket, comes from the spike. (D10)
- [ ] **Cross-host redirects are allowed at discovery time** (contradicts 7.4's flat
      "not followed across hosts", which applies to the scrape phase). Intel needs it. (§1.2)
- [ ] **Embedded-board sniffing lands in PR 1**, not 7.4 — PR 1 owns the SSRF guard. (§1.2)
- [ ] **7.1's "byte-for-byte on `board_token`" is not achievable for Workday.**
      Assert `provider_config` only for Workday. (§1.3)
- [ ] **`user_enabled_companies` is NOT the ownership table** — zero rows there means
      "see all". Use `user_companies`. (D3)
- [ ] **The `/api/jobs` visibility predicate is a positive membership test**, not a copy
      of the anti-join's "no row ⇒ visible" polarity. (§3.3)
- [ ] **Agent discovery is out of scope for all three PRs.** No `anthropic`,
      `playwright`, `stagehand`, or `browserbase` under `src/backend/`. (§1.1)
- [ ] **Phenom is not built here.** Cisco resolves to Workday. (§1.4)
- [ ] `docs/custom-company-sources-question.md` **does not exist** — do not go looking. (§1.6.2)


## 5. Verification commands

Grounding before starting (from the worktree root):

```bash
sed -n '74,114p'  src/backend/api/services/eightfold_client.py     # allowlist to IMPORT
sed -n '100,130p' src/backend/api/services/workday_client.py       # keys only, no host check (E0 0.3)
sed -n '85,175p'  src/backend/api/services/database.py             # the anti-join + _build_where
sed -n '112,125p;134,167p' src/backend/api/tasks/fetch_greenhouse_company.py
sed -n '26,34p'   scripts/shared/incremental.py                    # constants to reuse
grep -n "BASE_URL" src/backend/api/services/{greenhouse,ashby,lever,gem}_client.py
sed -n '60,69p'   src/backend/api/main.py                          # _WORKER_QUEUES
cd src/backend && pytest api/tests -q && mypy && alembic heads
```

Prod cross-check (read-only, `mcp__postgres-prod__query`):

```sql
SELECT id, ats, board_token, provider_config FROM companies
 WHERE id IN ('blueorigin','capitalone','adobe','disney','gm','slack','netflix');
SELECT ats, count(*) FROM companies WHERE enabled GROUP BY ats ORDER BY 2 DESC;
SELECT source_id, count(*) FILTER (WHERE status='OPEN') AS open FROM job_listings GROUP BY 1;
```

Live target checks (re-run before claiming an acceptance criterion):

```bash
curl -sS -I -L 'https://jobs.intel.com' | grep -iE '^(HTTP/|location:)'
curl -sS -X POST 'https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs' \
  -H 'Content-Type: application/json' -d '{"appliedFacets":{},"limit":1,"offset":0,"searchText":""}' | head -c 120
# → {"total":681,...

curl -sS -I -L 'https://jobs.cisco.com' | grep -iE '^(HTTP/|location:)'
curl -sS 'https://careers.cisco.com/global/en/search-results' \
  | grep -oE 'https://[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com/[A-Za-z0-9_-]+' | sort -u
# → https://cisco.wd5.myworkdayjobs.com/Cisco_Careers
curl -sS -X POST 'https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs' \
  -H 'Content-Type: application/json' -d '{"appliedFacets":{},"limit":1,"offset":0,"searchText":""}' | head -c 120
# → {"total":1060,...
```

Spike re-grounding:

```bash
sed -n '1,30p'   docs/incidents/2026-03-29-mass-job-closure.md
python3 scripts/one_off/recipe_spike/test_invariants.py        # 10/10 must hold before porting
sed -n '126,151p' scripts/one_off/recipe_spike/replay.py       # check_completeness — copy exactly
sed -n '100,115p' scripts/one_off/recipe_spike/replay.py       # copy_merge_params — the 76→10,000 trap
```
