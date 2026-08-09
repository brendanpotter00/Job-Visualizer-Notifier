# Custom company sources — implementation plan (E7)

A signed-in user pastes a careers-page URL. The company is scraped on the existing
30-minute cadence and appears in the existing views **for that user only**, plus a
"My Companies" page.

ClickUp: epic E7 `wdwb1cbnc2`, subtasks 7.1 `wdwb1cbnc3`, 7.3 `wdwb1cbnc5`,
7.4 `wdwb1cbnc6`. Spike 7.2 `wdwb1cbnc4` → `docs/spikes/2026-08-browser-agent-discovery.md` (**GO**).

Ships as **3 sequential PRs**, each independently shippable and independently
revertible. Everything is behind a feature flag defaulting **off**.

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
| Feature flag | Backend `settings.custom_company_sources_enabled: bool = False`; frontend `VITE_CUSTOM_COMPANIES`. **Both must be on.** Backend is authoritative. | Copies the enrichment-flag pattern (`config.py:53-79`) and `config/auth.ts:21`. `Settings.model_config` has `extra="ignore"` (`config.py:104`), so a typo'd env var fails silently — pin the name with a test. |

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

---

# PR 1 — Backend foundation (no schema changes)

**Title:** `feat(companies): SSRF url_guard + ATS link resolver + resolve endpoint`
**Risk:** LOW. Additive, read-only, persists nothing. Rollback = delete the route.

## 1.1 Files

### Added
| Path | Purpose |
|---|---|
| `src/backend/api/services/url_guard.py` | Standalone SSRF boundary. Reused by PR 2 and PR 3. |
| `src/backend/api/services/ats_link_resolver.py` | L0 pure resolver + `AtsCandidate`. IO-free. |
| `src/backend/api/services/ats_discovery.py` | L1 `follow_to_ats` + L2 `sniff_embedded_ats` + `probe_candidate`. The only IO in this PR. |
| `src/backend/api/tests/test_url_guard.py` | 9-case rejection table + redirect-hop cases. |
| `src/backend/api/tests/test_ats_link_resolver.py` | Parametrized URL→candidate table + zero-network assertion + import guard. |
| `src/backend/api/tests/test_ats_discovery.py` | `follow_to_ats` / `sniff_embedded_ats` / `probe_candidate` with `httpx.MockTransport`. |
| `src/backend/api/tests/test_companies_resolve_endpoint.py` | Endpoint: 200 / 401 / 422 / writes nothing. |

### Modified
| Path | Change |
|---|---|
| `src/backend/api/routers/companies.py` | Add `POST /resolve` (Bearer required). Existing `GET ""` untouched. |
| `src/backend/api/models.py` | `ResolveUrlRequest`, `AtsCandidateResponse`, `ProbeResultResponse`, `ResolveUrlResponse` — camelCase aliases via the existing `ConfigDict(alias_generator=to_camel, populate_by_name=True)` used at `models.py:210,223`. |
| `src/backend/api/config.py` | `custom_company_sources_enabled: bool = False` (+ comment), placed beside the enrichment flags. |
| `vercel.json` | Add `{"source": "/api/companies/:path(.*)", "destination": "/api/companies?path=:path"}` to `rewrites`, adjacent to the `/api/locations` entry (~line 38). |

**No migration in PR 1.** Alembic head stays `a7c31d9e0b46`.

## 1.2 `services/url_guard.py` — contract

```python
class UrlGuardError(ValueError):
    """A URL was rejected. `.reason` is a stable machine-readable code."""
    reason: str          # one of the _REASON_* codes below

# stable reason codes (surfaced to the client, logged, and stored in PR 3)
REASON_SCHEME          = "scheme_not_https"
REASON_USERINFO        = "userinfo_present"
REASON_PORT            = "non_standard_port"
REASON_HOSTNAME        = "invalid_hostname"
REASON_DNS             = "dns_resolution_failed"
REASON_PRIVATE_ADDRESS = "resolves_to_private_address"
REASON_ATS_HOST        = "not_an_allowed_ats_api_host"
REASON_TOO_MANY_HOPS   = "too_many_redirects"

@dataclass(frozen=True)
class GuardedUrl:
    url: str                    # normalized absolute https URL
    host: str                   # lowercased hostname
    resolved_ips: tuple[str, ...]

def validate_public_url(url: str) -> GuardedUrl:
    """Raise UrlGuardError, or return the guarded URL. Performs DNS only."""

def assert_ats_api_host(ats: str, url: str) -> None:
    """A candidate for `ats` may only ever be fetched from that ATS's fixed API host."""

async def guarded_get(
    url: str, http: httpx.AsyncClient, *,
    max_hops: int = 5, max_bytes: int = 1_048_576,
    allow_cross_host: bool = True,      # discovery=True, scrape=False
) -> tuple[httpx.Response, tuple[str, ...]]:
    """Manual redirect loop. Every hop re-validated BEFORE the request.
    Returns (final response, tuple of hop URLs). Never uses follow_redirects=True."""
```

Rules enforced by `validate_public_url`, in order (fail closed, explicit allow):

1. `urlsplit` parses; scheme is exactly `https` (`http`, `file`, `gopher`, `ftp`,
   `data`, empty ⇒ reject).
2. No userinfo — reject if `"@"` appears in `netloc`.
3. Port is `None` or `443`. `https://boards.greenhouse.io:8080/acme` ⇒ reject.
4. Hostname non-empty, ≤253 chars, is not an IP literal, is not `localhost`,
   does not end in `.localhost`/`.local`/`.internal`. Normalize with IDNA
   (`hostname.encode("idna")`) so a Unicode homoglyph host cannot bypass.
5. `socket.getaddrinfo(host, 443, proto=IPPROTO_TCP)` → **every** returned
   address must pass `ipaddress.ip_address(a)` with all of:
   `not is_private and not is_loopback and not is_link_local and not is_reserved
   and not is_multicast and not is_unspecified`, plus explicit rejection of
   `0.0.0.0/8`, `169.254.0.0/16`, `fc00::/7`, `::1`, `::ffff:0:0/96`
   IPv4-mapped forms of any of the above. **All** answers must pass — a host with
   one public and one private A record is rejected.

`assert_ats_api_host` allowlist (values read from the existing clients, do not retype):

| ats | permitted API host | source |
|---|---|---|
| greenhouse | `boards-api.greenhouse.io` | `greenhouse_client.py:39` |
| ashby | `api.ashbyhq.com` | `ashby_client.py:43` |
| lever | `api.lever.co` | `lever_client.py:45` |
| gem | `api.gem.com` | `gem_client.py:51` |
| eightfold | delegate to `_is_allowed_eightfold_host` — **import it** | `eightfold_client.py:96` |
| workday | `^[a-z0-9][a-z0-9-]*\.wd[0-9]+\.myworkdayjobs\.com$` | derived; see note |

> **Workday note.** `workday_client.py` has **no** host check today (verified: the
> only "host" in the file is prose in the docstring at line 29; `base_url` is used
> verbatim at lines 166 and 394). E0 ticket 0.3 owns that gap — **do not fix it in
> `workday_client.py`.** `url_guard` gets its own Workday host regex and PR 1/PR 3
> call it on user-supplied input only. Leave existing seeded rows alone.

**TOCTOU is accepted and documented.** DNS can change between `validate_public_url`
and the socket connect. Mitigations that are *in* scope: revalidate on every hop,
revalidate at scrape time (PR 2), pin ATS candidates to fixed API hosts. Pinning the
resolved IP into the connection is out of scope for v1 — write that in the module
docstring so a reviewer does not think it was missed.

## 1.3 `services/ats_link_resolver.py` — contract

```python
@dataclass(frozen=True)
class AtsCandidate:
    ats: str                          # 'greenhouse'|'ashby'|'lever'|'gem'|'workday'|'eightfold'
    board_token: str
    provider_config: dict[str, str]   # {} for the token-only ATSs
    source_url: str                   # the URL this was derived from (may be a redirect target)

def resolve_ats_url(url: str) -> AtsCandidate | None: ...
```

`urllib.parse` is the entire dependency list, plus `re`, plus the *imported*
`_is_allowed_eightfold_host`. **No `httpx`, no `socket`, no DB, no `llm_client`.**

Matchers (host lowercased and `www.`-stripped first; trailing slashes and query
strings ignored):

| ats | host(s) | token | provider_config |
|---|---|---|---|
| greenhouse | `boards.greenhouse.io`, `job-boards.greenhouse.io` | first path segment | `{}` |
| ashby | `jobs.ashbyhq.com` | first path segment, **lowercased** | `{}` |
| lever | `jobs.lever.co` | first path segment | `{}` |
| gem | `jobs.gem.com` | first path segment | `{}` — verify the public host form live before trusting it; only `GEM_BASE_URL` at `gem_client.py:51` is authoritative in-repo |
| workday | regex in §1.3 above | `tenant_slug` | `{base_url, tenant_slug, career_site_slug}` — casing per §1.3 |
| eightfold | only if `_is_allowed_eightfold_host(host)` | registrable domain of the host | `{tenant_host: host, domain: <registrable domain>}` matching prod's `{"domain":"netflix.com","tenant_host":"explore.jobs.netflix.net"}` |

Returns `None` (never a guess) for `https://www.tesla.com/careers`,
`https://www.amazon.jobs`, `https://www.metacareers.com/jobs`,
`https://jobs.intel.com`, `https://jobs.cisco.com`, a bare
`https://boards.greenhouse.io/`, and any eightfold-shaped URL on a non-allowlisted host.

## 1.4 `services/ats_discovery.py` — contract

```python
@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    job_count: int
    error: str | None       # the underlying message, NOT collapsed to a bool

@dataclass(frozen=True)
class DiscoveryResult:
    candidate: AtsCandidate | None
    via: str                # 'direct' | 'redirect' | 'embedded' | 'unsupported'
    hops: tuple[str, ...]
    final_url: str
    reason: str | None      # a url_guard REASON_* or 'no_ats_detected'

_PROBE_TIMEOUT_S: float = 12.0          # well below the clients' DEFAULT_TIMEOUT_SECONDS = 30.0

async def follow_to_ats(url: str, http: httpx.AsyncClient) -> DiscoveryResult: ...
async def sniff_embedded_ats(url: str, http: httpx.AsyncClient) -> DiscoveryResult: ...
async def discover_ats(url: str, http: httpx.AsyncClient) -> DiscoveryResult:
    """L0 → L1 → L2, first hit wins. The single entry point PR 3 calls."""
async def probe_candidate(c: AtsCandidate, http: httpx.AsyncClient) -> ProbeResult: ...
```

`follow_to_ats` (L1): run L0 on the input; if miss, `guarded_get(..., allow_cross_host=True,
max_hops=5)` with `method="HEAD"` falling back to `GET` on 405, running L0 against
**each hop URL including the final one**. First hit wins. This is what makes Intel
work.

`sniff_embedded_ats` (L2): fetch, through `guarded_get`, at most **4** URLs — the
final URL from L1, then `<final_path>/search-results`, `/careers`, `/jobs` (same
host, path-only variations, each individually guard-validated). Cap each body at
512 KB. Regex-scan the decoded body for known ATS URL forms:

```
https://[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com/[A-Za-z0-9_-]+     # Cisco hits here
https://(?:job-)?boards\.greenhouse\.io/[A-Za-z0-9_-]+
https://jobs\.ashbyhq\.com/[A-Za-z0-9_-]+
https://jobs\.lever\.co/[A-Za-z0-9_-]+
https://jobs\.gem\.com/[A-Za-z0-9_-]+
```

Feed each match back through L0. If more than one distinct candidate appears, pick
the **most frequent** and record the runners-up in `DiscoveryResult` for the admin
log — do not silently pick the first. HTML is scanned as text with `re`; **no
BeautifulSoup in PR 1** (bs4 arrives in PR 2).

`probe_candidate` delegates to the existing per-ATS `fetch_jobs`:
`greenhouse_client.fetch_jobs(board_token, http)`,
`ashby_client.fetch_jobs(...)`, `lever_client.fetch_jobs(...)`,
`gem_client.fetch_jobs(...)`,
`workday_client.fetch_jobs(provider_config, http)`,
`eightfold_client.fetch_jobs(tenant_host, domain, http)`.
It calls `assert_ats_api_host(ats, ...)` first and wraps in
`asyncio.wait_for(..., _PROBE_TIMEOUT_S)`.

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

## 1.5 `POST /api/companies/resolve`

```
POST /api/companies/resolve        Depends(get_current_user)   # 401 without a Bearer token
body  {"url": "https://jobs.intel.com"}                        # max_length 2048, extra="forbid"
200   {"candidate": {"ats","boardToken","providerConfig","sourceUrl"},
       "probe": {"ok","jobCount","error"},
       "via": "redirect", "hops": [...], "finalUrl": "..."}
422   {"reason": "no_ats_detected" | <url_guard REASON_*>, "finalUrl": "...", "hops": [...]}
503   when settings.custom_company_sources_enabled is False
```

Writes **nothing**. Add it to `routers/companies.py`, which currently has one route
(`GET ""` at line 25) and no auth dependency — import `get_current_user` from
`..auth.dependencies` (`dependencies.py:79`). Keep the existing `except psycopg2.Error:
conn.rollback()` idiom if the handler touches the DB; it should not need to.

## 1.6 Tests

`test_url_guard.py` — the 9-case rejection table, each asserting **zero outbound requests**
(pass an `httpx.MockTransport` whose handler raises):

| # | Input | Expected reason |
|---|---|---|
| 1 | `http://169.254.169.254/latest/meta-data/` | `scheme_not_https` |
| 2 | `http://localhost:8000/api/admin/users` | `scheme_not_https` (and `invalid_hostname`) |
| 3 | `https://127.0.0.1/` | `invalid_hostname` (IP literal) |
| 4 | `https://[::1]/` | `invalid_hostname` |
| 5 | `http://10.0.0.5/` | `scheme_not_https` |
| 6 | `https://user:pass@evil.tld/` | `userinfo_present` |
| 7 | `https://boards.greenhouse.io:8080/acme` | `non_standard_port` |
| 8 | `file:///etc/passwd` | `scheme_not_https` |
| 9 | a monkeypatched `getaddrinfo` returning `10.0.0.5` for `evil.example` | `resolves_to_private_address` |

Plus:
- **Redirect-hop rejection:** a `MockTransport` that 302s `https://ok.example` →
  `http://169.254.169.254/` is rejected **at the hop**, and the handler is invoked
  exactly once (assert the call counter).
- **Mixed DNS answers:** one public + one private A record ⇒ rejected.
- **`assert_ats_api_host`:** a greenhouse candidate pointed at
  `https://evil.tld/v1/boards/acme` raises; `https://boards-api.greenhouse.io/...` passes.
- **IPv4-mapped IPv6** `::ffff:10.0.0.5` rejected.

`test_ats_link_resolver.py`:
- Parametrized URL→candidate table: one correct URL per ATS (trailing slash, query
  string, `www.`, uppercase host variants) and one wrong URL per ATS.
- **Prod-parity:** `provider_config` equals the live row byte-for-byte for
  `blueorigin`, `capitalone`, `adobe`, `disney`, `gm`, `slack`, `netflix`; and
  `board_token` equals the live row for the non-Workday ATSs only (see §1.3's
  contradiction note).
- `/BlueOrigin` ⇒ `career_site_slug == "BlueOrigin"`; `/Capital_One` ⇒ `"Capital_One"`;
  `/external_experienced` ⇒ `"external_experienced"`.
- **`/External/page/6042070b79e01001f04fa9b468070000` ⇒ `career_site_slug == "External"`,
  `tenant_slug == "intel"`, `base_url == "https://intel.wd1.myworkdayjobs.com"`.**
- `/en-US/BlueOrigin` ⇒ same as `/BlueOrigin` (locale prefix stripped).
- Bare `https://intel.wd1.myworkdayjobs.com/` ⇒ `None`.
- Eightfold on a non-allowlisted host ⇒ `None`.
- `None` for tesla/amazon/metacareers/`jobs.intel.com`/`jobs.cisco.com`.
- **Zero-network assertion:** call every resolver case with a module-level
  `httpx.MockTransport` that raises, and additionally assert
  `"socket" not in <module source>` is not enough — instead monkeypatch
  `socket.getaddrinfo` to raise and confirm the whole table still passes.
- **Import guard:** after importing `ats_link_resolver` in a subprocess
  (`sys.executable -c`), assert none of
  `{"anthropic","openai","stagehand","browserbase","langchain","playwright"}`
  is in `sys.modules`. Subprocess, not in-process — the test session will already
  have `anthropic` loaded via `services/llm_client.py`. Mirror
  `replay.py:43-46`'s `FORBIDDEN_MODULES` list.

`test_ats_discovery.py` (all `httpx.MockTransport`, no live network in CI):
- **Intel regression, mocked:** transport replays the real chain
  `jobs.intel.com` →301→ `corpredirect.intel.com/...?404;https://jobs.intel.com/`
  →301→ `intel.wd1.myworkdayjobs.com/External/page/6042…` and asserts
  `via == "redirect"`, `candidate.ats == "workday"`, `career_site_slug == "External"`.
- **Cisco regression, mocked:** `jobs.cisco.com` →302→ `careers.cisco.com` →303→
  `/global/en` (body contains no ATS URL), then `/global/en/search-results` body
  containing `https://cisco.wd5.myworkdayjobs.com/Cisco_Careers`; asserts
  `via == "embedded"`, `career_site_slug == "Cisco_Careers"`, `tenant_slug == "cisco"`.
  *(Cisco only has to work end-to-end by PR 3; the resolver half is proven here.)*
- Sniffer stops after 4 fetches; body truncated at 512 KB.
- Multiple distinct candidates ⇒ most frequent wins, runners-up recorded.
- `probe_candidate` propagates the upstream error text; times out at 12 s.

`test_companies_resolve_endpoint.py`: 200 for a mocked known-good board (asserts
`jobCount`), 401 without a token, 422 + `reason` for an unrecognized URL, 503 with the
flag off, and **`SELECT count(*) FROM companies` unchanged in every case**.

**Live smoke (manual, in the PR description, not CI):**
```bash
curl -s -X POST localhost:8000/api/companies/resolve -H 'Authorization: Bearer <t>' \
  -H 'Content-Type: application/json' -d '{"url":"https://jobs.intel.com"}' | jq
# expect: ats=workday, careerSiteSlug=External, tenantSlug=intel, probe.jobCount ≈ 681
```

## 1.7 Acceptance criteria

- [ ] All nine SSRF cases rejected 4xx with **zero** outbound requests; the
      redirect-hop case rejected at the hop with exactly one transport call.
- [ ] `resolve_ats_url` matches prod `provider_config` byte-for-byte for
      blueorigin / capitalone / adobe / disney / gm / slack / netflix.
- [ ] `resolve_ats_url` returns `None` for tesla, amazon.jobs, metacareers,
      `jobs.intel.com`, `jobs.cisco.com`.
- [ ] `resolve_ats_url` performs zero network calls (`getaddrinfo` monkeypatched to raise).
- [ ] Import-guard subprocess test fails if any LLM/agent/browser package is reachable.
- [ ] **`POST /api/companies/resolve` with `{"url":"https://jobs.intel.com"}` returns a
      Workday candidate `{base_url: "https://intel.wd1.myworkdayjobs.com",
      tenant_slug: "intel", career_site_slug: "External"}` and a probe job count > 500.**
      (Mocked in CI; live-verified in the PR description.)
- [ ] 401 without a token; 422 + machine-readable `reason` when unrecognized;
      503 with the flag off; **no `companies` row written in any case**.
- [ ] `alembic heads` still returns exactly `a7c31d9e0b46`.
- [ ] `pytest src/backend/api/tests -q`, `mypy`, `npm run type-check` all clean.

## 1.8 Rollback

Delete the `POST /resolve` route (or leave `custom_company_sources_enabled=False`,
which 503s it). `url_guard` / `ats_link_resolver` / `ats_discovery` have no callers
and no side effects. The `vercel.json` rewrite is inert without the route.

## 1.9 Ordered task list

1. `config.py`: add `custom_company_sources_enabled: bool = False` next to the
   enrichment flags (~line 79), with a comment naming what it gates.
2. Write `services/url_guard.py`. Import `_is_allowed_eightfold_host` from
   `eightfold_client`. Do not modify `eightfold_client.py`.
3. Write `tests/test_url_guard.py` (9-case table first — TDD the guard).
4. Write `services/ats_link_resolver.py`. Confirm each matcher against the prod
   query in §5 before trusting it. Verify the gem public host live.
5. Write `tests/test_ats_link_resolver.py` including the Intel Workday case and
   the subprocess import guard.
6. Write `services/ats_discovery.py` (`follow_to_ats`, `sniff_embedded_ats`,
   `discover_ats`, `probe_candidate`).
7. Write `tests/test_ats_discovery.py` with the mocked Intel and Cisco chains.
8. Add the four Pydantic models to `api/models.py` using the existing camelCase
   `ConfigDict`.
9. Add `POST /resolve` to `routers/companies.py`.
10. Write `tests/test_companies_resolve_endpoint.py`.
11. Add the `/api/companies/:path(.*)` rewrite to `vercel.json`.
12. Run `pytest api/tests -q && mypy && alembic heads`. Live-smoke Intel; paste the
    output into the PR description.

---

# PR 2 — Recipe runtime (inert until rows exist)

**Title:** `feat(scrapers): deterministic recipe runtime with health + quarantine`
**Risk:** HIGH — touches the shared scrape cron. Mitigated by total inertness with
zero recipe rows.
**Depends on:** PR 1 (`url_guard`).

## 2.1 Files

### Added
| Path | Purpose |
|---|---|
| `src/backend/api/services/recipe_schema.py` | **Verbatim port** of `scripts/one_off/recipe_spike/recipe_schema.py` minus `browser_dom` (D8). Keeps `RecipeError`, `validate_recipe`, `dig`, `RECIPE_VERSION = 1`. |
| `src/backend/api/services/recipe_runner.py` | Port/hardening of `replay.py`. `SOURCE_ID`, `run_recipe`, `transform_to_job_listings`. |
| `src/backend/api/services/recipe_store.py` | CRUD + health for `company_scrape_recipes`. |
| `src/backend/api/tasks/enqueue_recipe_fan_out.py` | Mirrors `enqueue_eightfold_fan_out.py` (the provider_config variant). |
| `src/backend/api/tasks/fetch_recipe_company.py` | Mirrors `fetch_greenhouse_company.py` exactly, plus the health/quarantine block. |
| `src/backend/alembic/versions/<ts>_<rev>_add_company_scrape_recipes.py` | `--autogenerate`d. `down_revision = 'a7c31d9e0b46'`. |
| `src/backend/api/tests/test_recipe_runner.py` | The ten spike invariants, ported. |
| `src/backend/api/tests/test_fetch_recipe_company.py` | **The 2026-03-29 regression test.** |
| `src/backend/api/tests/test_enqueue_recipe_fan_out.py` | Mirrors `test_enqueue_greenhouse_fan_out.py`. |
| `src/backend/api/tests/test_alembic_single_head.py` | **Net-new** (see §1.6.1). Computes revisions − down_revisions and asserts len == 1. |

### Modified
| Path | Change |
|---|---|
| `scripts/shared/constants.py` | `RECIPE: Final[str] = "recipe_api"` after line 24. |
| `src/backend/api/db_models.py` | New `CompanyScrapeRecipe` model. Legacy `Column(...)` style, `server_default=text(...)`, explicit `Index("idx_…")` names — match the file's conventions, **do not** use `Mapped[...]`. |
| `src/backend/api/tasks/__init__.py` | Two side-effect imports (`fetch_recipe_company`, `enqueue_recipe_fan_out`) after line 17. |
| `src/backend/api/main.py` | Add `"recipe_fetch"` to `_WORKER_QUEUES` (lines 60-69). |
| `src/backend/api/requirements.txt` | `beautifulsoup4>=4.12` (the backend's first HTML-parsing dependency; `http_html` needs it — `replay.py:211,258`). |
| `src/backend/pyproject.toml` | Add `bs4.*` to the stub-less mypy override list (lines 34-43). |
| `src/backend/api/tests/test_db_models.py` | Add `company_scrape_recipes` to the pinned table-name list (~line 35). |
| `src/backend/api/routers/admin.py` | `GET /admin/recipes/health` — the admin read surface 7.3 requires. |

## 2.2 Migration

```
companies_scrape_recipes  →  company_scrape_recipes
  id                    Text  PK
  company_id            Text  NOT NULL   (soft link, matching user_enabled_companies' precedent — no FK; E4 4.2 owns FKs)
  recipe                JSONB NOT NULL
  recipe_version        Integer NOT NULL server_default text('1')
  enabled               Boolean NOT NULL server_default text('true')
  consecutive_failures  Integer NOT NULL server_default text('0')
  last_ok_at            TIMESTAMP(timezone=True)  NULL
  last_error            Text NULL
  last_error_at         TIMESTAMP(timezone=True)  NULL
  quarantined_at        TIMESTAMP(timezone=True)  NULL
  quarantine_reason     Text NULL
  discovered_at         TIMESTAMP(timezone=True) NOT NULL server_default func.now()
  discovered_by         Text NULL
  created_at            TIMESTAMP(timezone=True) NOT NULL server_default func.now()
  UniqueConstraint("company_id", name="company_scrape_recipes_company_id_key")   # one live recipe per company
  Index("idx_company_scrape_recipes_enabled", "enabled", postgresql_where=text("enabled"))
```

Single-head procedure (`docs/incidents/2026-04-18-migration-filled-postgres-volume/`):

```bash
cd src/backend
alembic heads                      # must print exactly a7c31d9e0b46 BEFORE you start
# edit db_models.py
alembic revision --autogenerate -m "add company_scrape_recipes"
# review: one op_create_table, no unrelated diffs, down_revision == 'a7c31d9e0b46'
alembic heads                      # must print exactly one head, the new one
```
Never hand-write the revision. New timestamp columns are real `timestamptz`, never
`Text` (`db_models.py:275-279`).

## 2.3 `services/recipe_runner.py` — contract

```python
SOURCE_ID: Final[str] = SourceId.RECIPE          # "recipe_api"
FORBIDDEN_MODULES = ("anthropic","openai","stagehand","browserbase","langchain","playwright")
_TIMEOUT_S: Final[float] = 25.0
_MAX_BODY_BYTES: Final[int] = 8 * 1024 * 1024

class RecipeExecutionError(RuntimeError):
    """A recipe run failed. Callers must treat this as 'we learned nothing'."""

def assert_no_agent_imports() -> None: ...
async def run_recipe(recipe: dict, http: httpx.AsyncClient) -> list[dict]:
    """Execute a validated recipe. RAISES on any failure — NEVER returns []."""
def transform_to_job_listings(company_id: str, rows: list[dict]) -> list[JobListing]: ...
```

Port from `replay.py` with these **required** deltas:

| Delta | Why |
|---|---|
| Drop `run_browser_dom`, `_arrays_matching_shape`, and `"browser_dom"` from `KINDS`/`RUNNERS` | D8 / spike §5. `validate_recipe` must now **reject** `kind == "browser_dom"`. |
| `httpx.Client` → `httpx.AsyncClient`, injected by the caller | Matches every existing client (`greenhouse_client.py` etc.) and the task's `async with httpx.AsyncClient() as http:`. |
| `await url_guard.validate_public_url(entrypoint.url)` **before the first byte**, on **every** request including each pagination page | 7.3 AC. The stored recipe is data and drifts. |
| `follow_redirects=False` (already the case at `replay.py:162,214,269`) — assert it in a test | §1.2 scrape-phase policy. |
| Keep `copy_merge_params` **exactly** (`replay.py:106-109`) | The 76→10,000-job filter-drop trap. Add a test with a filtered entrypoint URL asserting the filter survives pagination. |
| Keep `check_completeness` **exactly** (`replay.py:126-151`) and make it **required** when the payload publishes a total | D10. Enforce in `validate_recipe`: if `records_path`'s sibling dict contains a plausible total key and `total_path` is absent, that is a *lint warning* at write time, not a runtime failure — but a `total_path` that fails to resolve at runtime **raises** (already does). |
| Cap the response body at `_MAX_BODY_BYTES` and the total pages at `pagination.max_pages` | A user-influenced fetch must be bounded. |
| Keep `map_records`, `render_field`, `dig`, the raise-on-empty and `expected_min_jobs` checks verbatim | These are the ten proven invariants. |

`transform_to_job_listings` builds `scripts/shared/models.JobListing` with:
- `id = f"{company_id}:{row['id']}"` (§1.5) — the composite-PK namespace.
- `company = company_id`, `source_id = SOURCE_ID`.
- `posted_on`: only if the recipe emitted one. Spike §7.4 — most recipe sources
  publish no date, so freshness comes from our own `first_seen_at`. **Do not
  synthesize a `posted_on`.**

## 2.4 `services/recipe_store.py` — contract

```python
def get_enabled_recipes(conn) -> list[dict]:                    # id, company_id, recipe (validated on READ)
def get_recipe_for_company(conn, company_id: str) -> dict | None
def record_success(conn, recipe_id: str, *, at: datetime) -> None      # consecutive_failures=0, last_ok_at=at
def record_failure(conn, recipe_id: str, *, error: str, at: datetime) -> int
    """Increment consecutive_failures, stamp last_error/_at. Returns the NEW count."""
def quarantine(conn, recipe_id: str, company_id: str, *, reason: str, at: datetime) -> None
    """Sets quarantined_at/reason, recipes.enabled=false AND companies.enabled=false.
       Closes ZERO jobs. Never touches job_listings."""
```

`get_enabled_recipes` runs `validate_recipe` on every row and **skips + ERROR-logs**
an invalid one rather than aborting the tick — the `_validate_row_provider_config`
pattern at `enqueue_eightfold_fan_out.py:41`.

## 2.5 `tasks/enqueue_recipe_fan_out.py`

Copy `enqueue_eightfold_fan_out.py` structurally. Exact invariants to keep:

```python
@procrastinate_app.periodic(cron="*/30 * * * *", periodic_id="recipe_fan_out")
@procrastinate_app.task(queue="recipe_fetch", name="enqueue_recipe_fan_out",
                        retry=RetryStrategy(max_attempts=3, exponential_wait=2))
async def enqueue_recipe_fan_out(timestamp: int) -> int:
    if not settings.custom_company_sources_enabled:
        return 0                                     # flag gates the BODY, not the registration
    ...
    await fetch_recipe_company.configure(
        queueing_lock=f"recipe:{company_id}"
    ).defer_async(company_id=company_id, recipe_id=recipe_id)
```

Catch only `(procrastinate_exceptions.ConnectorException, psycopg2.Error)` per row
and `procrastinate_exceptions.AlreadyEnqueued` for the dedupe path. Let programmer
errors propagate. Track `skipped_bad_recipe` in the summary log.

## 2.6 `tasks/fetch_recipe_company.py` — the safety-critical file

Copy `fetch_greenhouse_company.py` **line for line** and change only what must change.
Non-negotiable, verbatim-preserved elements:

- `RetryStrategy(max_attempts=5, exponential_wait=2)`, `queue="recipe_fetch"`
  (`fetch_greenhouse_company.py:65-69`).
- `_TASK_TIMEOUT_S: float = 120.0` and the `asyncio.wait_for(_work(), ...)` wrapper
  (lines 58-62, 200).
- `db.get_connection(..., application_name="task_fetch_recipe", statement_timeout_ms=60_000)`.
- The **safety guard** at lines 112-125 verbatim: `if active_count > 0 and jobs_seen <
  SAFETY_GUARD_RATIO * active_count:` → `logger.error(...)`, `error_count = 1`, `return`.
  `SAFETY_GUARD_RATIO` and `MISSED_RUN_THRESHOLD` **imported** from
  `scripts.shared.incremental`, never redefined.
- The ordered sequence and the load-bearing comment at lines 134-167:
  `upsert_jobs_batch` → `update_last_seen` → `increment_consecutive_misses` →
  `get_jobs_exceeding_miss_threshold` → `mark_jobs_closed`. **Do not reorder.**
  Copy the comment across with a line pointing back at the original.
- The `finally:` that always writes a `ScrapeRun` row, including the fresh
  fallback connection (`application_name="task_fetch_recipe_fallback"`) at lines 259-308.
- The catch tuple `except (httpx.HTTPError, ValueError, psycopg2.Error)` at lines
  246-258, **widened to include `RecipeExecutionError`** (which subclasses
  `RuntimeError`, not `ValueError` — it will not be caught otherwise, and an
  uncaught one burns all 5 retries). This is the single most likely bug in the port.
- The `normalize_location` fan-out after `wait_for` (lines 202-237).

Health/quarantine block, in exactly this order:

```
try:
    rows = await run_recipe(recipe, http)          # raises on ANY failure
except (RecipeExecutionError, httpx.HTTPError, UrlGuardError) as e:
    n = recipe_store.record_failure(conn, recipe_id, error=str(e)[:500], at=now)
    error_count = 1
    if n >= _QUARANTINE_THRESHOLD:                 # 3
        recipe_store.quarantine(conn, recipe_id, company_id,
                                reason=f"{n} consecutive failures: {e}"[:500], at=now)
        logger.error("QUARANTINED recipe for %s after %d consecutive failures: %s",
                     company_id, n, e)             # ERROR ⇒ stderr ⇒ Railway @level:error
    return                                          # ← BEFORE update_last_seen / misses / close
recipe_store.record_success(conn, recipe_id, at=now)
# ... then the copied greenhouse sequence
```

The `return` placement is the whole point. Quarantining closes **zero** jobs; existing
OPEN rows stay OPEN and go stale. Stale-and-visible beats silently-deleted.

## 2.7 `GET /api/admin/recipes/health`

`Depends(require_admin)` (`auth/dependencies.py:88`). Response model
`AdminRecipeHealthResponse` in `api/models.py`, following the `enrichment/health`
template (`routers/admin.py:655`). Rows: `companyId, enabled, consecutiveFailures,
lastOkAt, lastErrorAt, lastError, quarantinedAt, quarantineReason, recipeKind`.
Apply a `_RECIPE_LIST_CAP = 200` constant per the no-unbounded-reads rule
(`routers/admin.py:90,96`).

## 2.8 Tests

`test_recipe_runner.py` — port all ten `test_invariants.py` checks into pytest:
1. incomplete harvest raises (got 10 of declared 4000) — `"incomplete harvest"` in message
2. complete harvest passes (76 of 76)
3. within tolerance passes (98 of 100 at 5%)
4. vanished completeness oracle raises — `"did not resolve"`
5. zero records raises, never returns `[]` — `"zero records"`
6. count below `expected_min_jobs` raises
7. `assert_no_agent_imports()` passes clean; fires when `sys.modules["anthropic"]` is faked
8. recipe missing `fields.id` rejected
9. non-https entrypoint rejected
10. **`kind == "browser_dom"` rejected** (new — enforces D8)

Plus:
- **Query-preservation regression:** an entrypoint URL with an existing query
  (`?loc=US&team=eng`) paginated with `{"offset": 100}` must still carry `loc` and
  `team`. This encodes the spike's 76→10,000 trap.
- `follow_redirects` is `False` on every client the runner constructs.
- `url_guard` is invoked before the first byte and on **every** pagination page
  (assert call count == page count).
- Body over `_MAX_BODY_BYTES` raises.
- `transform_to_job_listings` namespaces ids: two companies with upstream id `"42"`
  yield `"acme:42"` and `"globex:42"`.
- `http_html` + `embedded_json` path (YC-shaped fixture) works with bs4.

`test_fetch_recipe_company.py` — the safety file:
- **🔴 THE 2026-03-29 REGRESSION TEST.** Seed a company with 500 OPEN
  `job_listings` rows. Patch `run_recipe` to raise. Run the task. Assert:
  `SELECT count(*) FROM job_listings WHERE status='CLOSED'` is **0**;
  `SELECT max(consecutive_misses) FROM job_listings` is **unchanged**;
  a `scrape_runs` row exists with `error_count = 1`;
  `consecutive_failures` on the recipe row is 1.
- Same, three times ⇒ `quarantined_at` set, `company_scrape_recipes.enabled = false`,
  `companies.enabled = false`, an ERROR logged (`caplog`), and **still zero CLOSED
  and zero miss increments.**
- Success after two failures resets `consecutive_failures` to 0 and stamps `last_ok_at`.
- Safety guard: a recipe returning 10 rows against 500 active ⇒ `error_count = 1`,
  zero closes, zero miss increments.
- A `RecipeExecutionError` is caught by the task (does not escape and burn retries).
- Composite-PK isolation: two recipe companies with colliding upstream ids do not
  overwrite each other.
- `SAFETY_GUARD_RATIO`/`MISSED_RUN_THRESHOLD` are the imported objects
  (`assert task_mod.SAFETY_GUARD_RATIO is incremental.SAFETY_GUARD_RATIO`).
- Import guard: a subprocess importing `api.tasks` has none of `FORBIDDEN_MODULES`
  in `sys.modules`.

`test_enqueue_recipe_fan_out.py` — mirror `test_enqueue_greenhouse_fan_out.py`
including the `procrastinate_open` fixture that sets `PGOPTIONS` before
`open_async()`. Assert: flag off ⇒ returns 0 and defers nothing; zero recipe rows ⇒
returns 0; queueing lock is `recipe:{company_id}`; an invalid recipe row is skipped
with an ERROR, not an abort.

`test_alembic_single_head.py` (net-new): parse `alembic/versions/*.py`, compute
`revisions − down_revisions`, assert exactly one head, and assert the head is
reachable from base with no cycles.

**Inertness proof:** with zero rows in `company_scrape_recipes`, run the existing
greenhouse/ashby/lever/gem/eightfold/workday test suites unchanged and green.

## 2.9 Acceptance criteria

- [ ] `run_recipe` raises — never returns `[]` — on non-2xx, malformed payload, zero
      records, count below `expected_min_jobs`, and a shortfall against `total_path`.
- [ ] **Regression: a raising recipe closes ZERO jobs and increments
      `consecutive_misses` for no row.**
- [ ] After 3 consecutive failures: quarantined, `companies.enabled = false`,
      ERROR logged, **still zero jobs closed**.
- [ ] A success resets `consecutive_failures` to 0 and stamps `last_ok_at`.
- [ ] `SAFETY_GUARD_RATIO` / `MISSED_RUN_THRESHOLD` imported, not redefined.
- [ ] A recipe whose entrypoint is non-https / private-resolving / off-allowlist is
      rejected before any outbound byte, on every page.
- [ ] `kind: "browser_dom"` is rejected by `validate_recipe`.
- [ ] Pagination preserves the entrypoint's existing query string.
- [ ] Two recipe companies with colliding upstream ids keep separate rows.
- [ ] No LLM/agent/browser package importable under `src/backend/api/tasks/` or
      `recipe_runner.py` (subprocess test).
- [ ] `alembic heads` returns exactly one head; the revision is `--autogenerate`d.
- [ ] **Off by default:** zero recipe rows ⇒ the fan-out returns 0 and every existing
      ATS test passes unchanged.

## 2.10 Rollback

`UPDATE company_scrape_recipes SET enabled = false;` or
`custom_company_sources_enabled=false` (the fan-out body returns 0 immediately).
No deploy needed. The `company_scrape_recipes` table is additive and orphaned if the
code is reverted.

## 2.11 Ordered task list

1. `alembic heads` — confirm `a7c31d9e0b46`.
2. Port `recipe_schema.py` into `services/`, dropping `browser_dom`. Add the
   rejection case to `validate_recipe`.
3. Port `replay.py` → `services/recipe_runner.py` with the deltas in §2.3.
4. Write `tests/test_recipe_runner.py` — all ten invariants plus the query-preservation
   and url_guard-per-page cases. Get green before touching any task.
5. `scripts/shared/constants.py`: add `RECIPE`.
6. `db_models.py`: add `CompanyScrapeRecipe`. Then `alembic revision --autogenerate`.
   Review the diff; confirm one head.
7. Write `tests/test_alembic_single_head.py`.
8. Write `services/recipe_store.py`.
9. Write `tasks/fetch_recipe_company.py` by **copying** `fetch_greenhouse_company.py`
   and diffing the result — the reviewer should be able to read the diff, not the file.
   Remember to add `RecipeExecutionError` to the catch tuple.
10. Write `tasks/enqueue_recipe_fan_out.py` from `enqueue_eightfold_fan_out.py`.
11. `tasks/__init__.py` + `main.py:_WORKER_QUEUES` + `requirements.txt` +
    `pyproject.toml` mypy override + `test_db_models.py` table list.
12. Write `tests/test_fetch_recipe_company.py` — **the 2026-03-29 test first.**
13. Write `tests/test_enqueue_recipe_fan_out.py`.
14. Add `GET /api/admin/recipes/health` + response model.
15. `pytest api/tests -q && mypy && alembic heads`. Run the full existing ATS suites
    to prove inertness.

---

# PR 3 — Ownership, self-serve UX, admin dashboard

**Title:** `feat(companies): user-scoped custom companies, My Companies page, admin dashboard`
**Risk:** HIGH — first user-controlled outbound fetch surface reaching persistence,
plus a visibility model on the shared `companies` table.
**Depends on:** PR 1 (guard + resolver), PR 2 (runtime, for the `ats='recipe'` value —
though PR 3 only creates `ats ∈ {greenhouse,ashby,lever,gem,workday,eightfold}` rows).

## 3.1 Migration (one revision, combined ALTER)

```
ALTER TABLE companies
  ADD COLUMN visibility Text NOT NULL server_default text("'public'")   -- 'public' | 'user'
CREATE TABLE user_companies
  user_id      Text NOT NULL   FK users.id ON DELETE CASCADE
  company_id   Text NOT NULL                                    -- soft link (E4 4.2 owns FKs)
  created_at   TIMESTAMP(tz) NOT NULL server_default func.now()
  PrimaryKeyConstraint("user_id", "company_id")
  Index("idx_user_companies_company_id", "company_id")
CREATE TABLE company_add_attempts                               -- D2: audit log, gates NOTHING
  id                        Text PK
  user_id                   Text NOT NULL
  submitted_url             Text NOT NULL
  final_url                 Text NULL
  outcome                   Text NOT NULL    -- 'created'|'attached_existing'|'unsupported'|'rejected_ssrf'|'quota'|'probe_failed'
  reason                    Text NULL        -- url_guard REASON_* or 'no_ats_detected'
  via                       Text NULL        -- 'direct'|'redirect'|'embedded'
  resolved_ats              Text NULL
  resolved_board_token      Text NULL
  resolved_provider_config  JSONB NULL
  company_id                Text NULL
  registrable_domain        Text NULL        -- powers the "most-attempted unsupported domains" panel
  discovery_cost_cents      Integer NOT NULL server_default text('0')
  discovery_browser_seconds Integer NOT NULL server_default text('0')
  created_at                TIMESTAMP(tz) NOT NULL server_default func.now()
  Index("idx_company_add_attempts_user_id", "user_id")
  Index("idx_company_add_attempts_domain", "registrable_domain")
```

> **The `visibility` default must be `'public'`.** All 133 existing rows become
> public with no backfill statement — a metadata-only `ADD COLUMN ... DEFAULT` on
> Postgres 11+. This is what keeps the migration off the volume-incident path
> (`docs/incidents/2026-04-18-migration-filled-postgres-volume/`). Review the
> autogenerated diff to confirm there is no `UPDATE` and that the three DDLs are in
> one revision.

> **`services/companies_seed.py` re-applies `data/company_profiles.json` on every
> boot** (`main.py` lifespan). Verify it does a targeted `UPDATE ... SET blurb=…,
> accomplishment=…` and cannot clobber `visibility` or delete user rows. If it does
> a full upsert, restrict it to `WHERE visibility = 'public'`.

## 3.2 Backend — files

### Added
| Path | Purpose |
|---|---|
| `src/backend/api/services/custom_companies_service.py` | The add/list/delete write path, quotas, id generation, attempt logging. |
| `src/backend/api/services/company_add_audit.py` | `record_attempt(...)` + the admin aggregations. |
| `src/backend/api/routers/user_companies.py` | `/api/users/companies` router. |
| `src/backend/api/tests/test_custom_companies_service.py` | quotas, id generation, dedupe-to-existing. |
| `src/backend/api/tests/test_user_companies_router.py` | endpoint contract + auth. |
| `src/backend/api/tests/test_jobs_owner_scoping.py` | the visibility leak tests. |
| `src/backend/api/tests/test_admin_custom_companies.py` | dashboard + promote. |

### Modified
| Path | Change |
|---|---|
| `src/backend/api/db_models.py` | `Company.visibility`; `UserCompany`; `CompanyAddAttempt`. |
| `src/backend/api/services/companies_service.py` | `WHERE enabled = TRUE` → `WHERE enabled = TRUE AND visibility = 'public'` (line 29). This is the one-line fix that keeps user companies out of the public directory. |
| `src/backend/api/services/user_preferences_service.py` | Auto-enroll branch (SQL lines 34-49): add `AND c.visibility = 'public'`. |
| `src/backend/api/services/database.py` | `_build_where` (line 132) + `get_jobs` (line 234): new `viewer_user_id: str \| None` param and a visibility predicate. |
| `src/backend/api/routers/jobs.py` | `list_jobs` (line 32): add `user = Depends(get_optional_user)`, thread `viewer_user_id`. |
| `src/backend/api/routers/admin.py` | `GET /custom-companies`, `GET /custom-companies/attempts`, `POST /custom-companies/{id}/promote`. |
| `src/backend/api/config.py` | `custom_companies_max_per_user: int = Field(default=5, gt=0)`, `custom_companies_global_cap: int = Field(default=500, gt=0)`, `custom_company_add_rate_limit_max: int = Field(default=3, gt=0)`, `custom_company_add_rate_limit_window_seconds: int = Field(default=3600, gt=0)` — beside lines 89-90. |
| `src/backend/api/services/rate_limit.py` | `custom_company_add_rate_limiter = SlidingWindowRateLimiter(...)` singleton + `enforce_custom_company_add_rate_limit(user)` dependency, keyed on **`user_id`**, mirroring lines 96-99 / 125. |
| `src/backend/api/main.py` | Include `user_companies.router` at prefix `/api/users/companies`. |
| `api/jobs.ts` | **Forward `Authorization`** (see §1.6.3). Add after `getInternalKeyHeader()` at line 33. |
| `vercel.json` | SPA rewrite `{"source": "/my-companies", "destination": "/index.html"}`. (`/admin/*` is already covered by the wildcard at line 105.) |

## 3.3 The visibility predicate on `/api/jobs` — get this exactly right

`_HIDDEN_COMPANY_PREDICATE` (`services/database.py:125-129`) is an **anti-join**:
a company with **no** `companies` row stays visible. That polarity is deliberate and
load-bearing (the comment at lines 96-103 explains it, and the test conftest
truncates `companies`). **Writing the visibility rule the same way would leak every
private company.** Write it as a positive membership test with an explicit
disjunction:

```python
_PRIVATE_COMPANY_PREDICATE = sql.SQL(
    "NOT EXISTS ("
    " SELECT 1 FROM companies c"
    " WHERE c.id = job_listings.company AND c.visibility = 'user'"
    "   AND NOT EXISTS ("
    "     SELECT 1 FROM user_companies uc"
    "     WHERE uc.company_id = c.id AND uc.user_id = %s))"
)
```

Reads as: "hide a job only if its company is explicitly `visibility='user'` **and**
the viewer does not own it." A company with no row, or `visibility='public'`, stays
visible — preserving today's semantics and every existing fixture. When
`viewer_user_id is None` (anonymous), pass a value that can never match
(`''`), which reduces to "hide all `visibility='user'` companies".

Index support: `idx_user_companies_company_id` plus the PK on
`(user_id, company_id)`. `companies` is ~133 rows; `ix_companies_ats_enabled` does
not cover `visibility`, so add `Index("ix_companies_visibility", "visibility",
postgresql_where=text("visibility <> 'public'"))` — a partial index over the handful
of private rows, mirroring how the existing anti-join is satisfied.

**Also apply it to** `get_job_by_id` (`services/database.py:270`, predicate at 294) —
otherwise `/api/jobs/{source_id}/{job_id}` is a direct read-around.

**Do NOT apply it to** `get_scrape_runs()` or `get_stats()` — same exemption
rationale as the hidden-company guard (admin diagnostics).

## 3.4 `/api/users/companies` — endpoint contract

All `Depends(get_current_user)`; the existing `api/users.ts` proxy already forwards
`Authorization` (lines 30-31) and handles `?path=` — **no new Vercel API proxy is
needed**, only the SPA rewrite.

```
GET    /api/users/companies
       → {companies: [{id, displayName, ats, status, openJobCount, lastScrapedAt, addedAt, sourceUrl}]}
         status ∈ 'checking' | 'active' | 'needs_attention'          # D4 — three values, no internals
POST   /api/users/companies/resolve      {url}     → same shape as PR 1's /api/companies/resolve
POST   /api/users/companies              {url}     → 201 {company, probe} | 4xx
DELETE /api/users/companies/{company_id} → 204
```

**Status derivation** (D4 — no run logs, recipes, or error text leaves the backend):

| status | condition |
|---|---|
| `checking` | no `scrape_runs` row for the company yet, or the only rows are within the first 35 min after `added_at` |
| `active` | most recent `scrape_runs` row has `error_count = 0` **and** `completed_at` within the last 90 min |
| `needs_attention` | otherwise — including `companies.enabled = false` (quarantine) |

`POST /api/users/companies` algorithm:

1. `enforce_custom_company_add_rate_limit(user)` → 429 + `Retry-After`.
2. `count(user_companies WHERE user_id) >= custom_companies_max_per_user` → 429 with
   a message naming the limit. Record attempt `outcome='quota'`.
3. `count(companies WHERE visibility='user') >= custom_companies_global_cap` → 503.
   Record attempt.
4. `discover_ats(url, http)` (PR 1 §1.4). On `UrlGuardError` → 400 with the reason;
   record attempt `outcome='rejected_ssrf'`. On no candidate → **200** with
   `{"supported": false, "reason": "no_ats_detected", "finalUrl": ...}`; record
   attempt `outcome='unsupported'` **with `registrable_domain`** (this is the
   dataset that answers §1.1). Not an error — the user gets an honest "we can't
   track this site yet."
5. `probe_candidate` → on failure, 422 with the propagated error; record attempt
   `outcome='probe_failed'`. **Nothing is persisted for a board that returns nothing.**
6. **Dedupe:** if a `companies` row already exists with the same
   `(ats, board_token, provider_config)`, do **not** create a second one. Insert only
   the `user_companies` link. Record `outcome='attached_existing'`. This is what makes
   D3's "global scrape, private visibility" real — and it means a user who adds Intel
   after the owner has publicly added Intel just gets the public row (skip the
   `user_companies` link entirely in that case; the company is already visible).
7. Otherwise insert `companies` with `visibility='user'`, `enabled=true`, a generated
   `id`, and `display_name` derived from the registrable domain (title-cased) — the
   user can not set it in v1. Insert the `user_companies` link. Record
   `outcome='created'`.
8. **Enqueue an immediate first scrape** so the user is not staring at `checking`
   for 30 minutes: `fetch_<ats>_company.configure(queueing_lock=f"{ats}:{id}").defer_async(...)`.
   This is the only place PR 3 touches the task layer.

**Company-id generation:** `slugify(registrable_domain)` truncated to 40 chars,
matching `ENABLED_COMPANY_ID_PATTERN` (`models.py:31`); on collision append `-2`,
`-3`, … Must never collide with a `COMPANY_IDS` value, because the frontend's static
array is keyed by the same id space — check against a seeded list.

`DELETE`: removes the `user_companies` row. If no `user_companies` rows remain **and**
`visibility='user'`, also set `companies.enabled = false` (do **not** delete the row
or its `job_listings` — the anti-join hides it, and the history stays for the admin
dashboard). Recording a delete in `company_add_attempts` is not required.

## 3.5 Admin dashboard

```
GET  /api/admin/custom-companies
     → rows: {companyId, displayName, ats, visibility, ownerCount, ownerEmails[],
              enabled, openJobCount, lastScrapedAt, lastErrorAt, createdAt}
GET  /api/admin/custom-companies/attempts?limit=&offset=
     → {attempts: [...], perUser: [{userId, email, attempts, created, unsupported, costCents}],
        topUnsupportedDomains: [{registrableDomain, attempts, distinctUsers}],
        totals: {costCents, browserSeconds, created, unsupported}}
POST /api/admin/custom-companies/{company_id}/promote
     → 204. Sets visibility='public'. Idempotent. Leaves user_companies rows intact
       (harmless once public). Logs at INFO with the admin's email.
```

All `Depends(require_admin)` (`auth/dependencies.py:88`), explicit `Admin*Response`
models in `api/models.py`, `_CUSTOM_COMPANY_LIST_CAP = 200`. Follow the
`enrichment/*` cluster's shape (`routers/admin.py:655-743`).

**Promote is the only "approval" verb in this design and it is post-hoc** — it
promotes something already live and already working. It is not a gate. (D1/D2.)

## 3.6 Frontend — the merge seam

### The identity-stability property (the key regression guard)

New file `src/frontend/src/features/customCompanies/selectEffectiveCompanies.ts`:

```ts
export const selectEffectiveCompanies = createSelector(
  [selectCustomCompanyRows],                       // CustomCompany[] | undefined
  (custom): readonly Company[] =>
    !custom || custom.length === 0
      ? COMPANIES                                  // ← the SAME ARRAY REFERENCE
      : [...COMPANIES, ...custom.map(toCompany)]
);
```

Test, with `toBe` not `toEqual`:
```ts
expect(selectEffectiveCompanies(stateWithNoCustomCompanies)).toBe(COMPANIES);
expect(selectEffectiveCompanies(anonymousState)).toBe(COMPANIES);
```
This is what proves anonymous and flag-off renders are byte-identical to today.
`toCompany` builds a full `Company` via an **exported** `createBackendScraperCompany`
(currently module-private at `config/companies.ts:14` — export it, do not duplicate it).

### The registry (avoids editing 17 call sites)

`getCompanyById` (`config/companies.ts:915`) is the single root gate; 17 non-test
files reach it directly or indirectly. Threading a selector through all of them is a
large, risky diff. Instead use the **repo's own precedent** — the `getTokenOrNull`
module-level registry (`features/features/getTokenOrNull.ts`, registered via a
`useLayoutEffect` bridge at `features/features/useFeaturesAuthBridge.ts:19`, mounted
at `app/App.tsx:48`):

`src/frontend/src/config/customCompanyRegistry.ts`
```ts
let registered: readonly Company[] = [];
export function registerCustomCompanies(list: readonly Company[]): void
export function resetCustomCompanies(): void
export function lookupCustomCompany(id: string): Company | undefined
export function getRegisteredCustomCompanies(): readonly Company[]
```

`config/companies.ts:915` becomes:
```ts
export const getCompanyById = (id: string): Company | undefined =>
  COMPANIES.find((c) => c.id === id) ?? lookupCustomCompany(id);
```
The static fast path is unchanged and hit first. Every existing call site — including
`lib/url.ts:26`, `lib/company.ts:21/63`, `CompanySelector.tsx:17`,
`FetchProgressBar`, `JobListingCard`, `CompanyCard` — starts working with custom ids
for free.

**Mandatory hygiene, or this leaks across users:**
- `resetCustomCompanies()` must be called in the sign-out purge block at
  `features/savedFilters/useHydrateSavedFilters.ts:86` (the repo's *only*
  `resetApiState()` site), alongside `customCompaniesApi.util.resetApiState()`.
- `resetCustomCompanies()` in a global test `afterEach` (add to the Vitest setup file)
  so the module-level state cannot make tests order-dependent.
- A test that asserts user A's custom companies are gone after sign-out.

### The seven hard gates

| # | Gate | Change |
|---|---|---|
| 1 | `jobsApi.ts:49-51` 404 on `getCompanyById` miss | **None** — the registry fixes it. Add a test proving a registered custom id no longer 404s. |
| 2 | `jobsApi.ts:96-100` progress seeding, `:173-174` fan-out partition | Replace `COMPANIES` with `getEffectiveCompaniesForFanOut()` (static ∪ registered). Custom companies are all `ats:'backend-scraper'`, so they join the existing batched `/api/jobs?companies=` call — respecting the 150 cap (`routers/jobs.py:28`) and the client's chunking (`backendScraperClient.ts:153`). |
| 3 | `lib/url.ts:26-27` + `:45-47` silent `spacex` fallback | `getCompanyFromURL` consults the registry. Because the registry populates asynchronously, `useCompanyLoader.ts:42` must **hold** on an unknown id until the custom-companies query settles, then fall back. Add a `customCompaniesLoaded` flag; do not default to `spacex` while loading. |
| 4 | `CompanySelector.tsx:31` static enumeration | `useSelector(selectEffectiveCompanies)` instead of `COMPANIES`. |
| 5 | `EnabledCompaniesSection.tsx:49-52` (`useMemo` with `[]` deps) and `:81` `handleSelectAll` | Both take the effective list. The empty dep array is a live bug for this feature — "Select All" currently *deselects* custom companies. |
| 6 | Name-resolution helpers (`lib/company.ts:21,42,63`) | **None** — registry-backed. |
| 7 | Sign-out cache purge (`useHydrateSavedFilters.ts:86`) | Add `customCompaniesApi.util.resetApiState()` **and** `resetCustomCompanies()`. |

### Delta-sync thunk (don't refetch 133 companies mid-session)

`src/frontend/src/features/customCompanies/syncCustomCompanies.ts`:
```ts
export const syncCustomCompaniesIntoAllJobs =
  (added: string[], removed: string[]) => async (dispatch, getState) => { ... }
```
For each `added` id: fetch just that company via `backendScraperClient`, then patch the
`getAllJobs` cache with `jobsApi.util.updateQueryData('getAllJobs', undefined, draft => …)`
following the exact shape of `applyCompanySuccess` (`jobsApi.ts:112-134`), including the
`upsertQueryData('getJobsForCompany', {companyId}, …)` cross-seed at lines 118-124. For each
`removed` id: delete its rows and its progress entry. **Never** `invalidateTags(['Jobs'])` —
`getAllJobs` has a single `void`-arg cache entry, so invalidating refetches all 133.

### New/changed frontend files

| Path | Change |
|---|---|
| `src/frontend/src/features/customCompanies/customCompaniesApi.ts` | New RTK Query slice. `baseUrl: '/api/users/companies'`, `prepareHeaders` with `getTokenOrNull` — copy `features/features/featuresApi.ts:21-37`. Best CRUD template: `features/savedFilters/savedFiltersApi.ts:123-205` (incl. `transformResponse` runtime validators). |
| `.../customCompanies/selectEffectiveCompanies.ts` | above |
| `.../customCompanies/syncCustomCompanies.ts` | above |
| `.../customCompanies/useCustomCompaniesBridge.ts` | `useLayoutEffect` registering the list into the registry — mirrors `useFeaturesAuthBridge.ts`. Mount in `app/App.tsx` beside line 48. |
| `src/frontend/src/config/customCompanyRegistry.ts` | above |
| `src/frontend/src/config/companies.ts` | export `createBackendScraperCompany` (line 14); `getCompanyById` consults the registry (line 915). **Do not touch `COMPANY_IDS`** — it is a `const enum`, compile-time only, with no runtime consumer. |
| `src/frontend/src/pages/MyCompaniesPage/` | New page: add-URL form, result card (supported / unsupported / probe-failed), list with health badge, last-updated, open-job count, delete. |
| `src/frontend/src/pages/AdminCustomCompaniesPage/` | New admin page. Copy `pages/AdminUsersPage/` + `components/UserRosterTable.tsx` (filter :76, sort :88, slice :121, `TableSortLabel` :230-256, `TablePagination` :358) — cleaner than QAPage. Three panels + a Promote row action with a confirm dialog. |
| `src/frontend/src/config/routes.ts` | `ROUTES.MY_COMPANIES = '/my-companies'`, `ROUTES.ADMIN_CUSTOM_COMPANIES = '/admin/custom-companies'`; add to `USER_NAV_ITEMS` (:73) and `ADMIN_NAV_ITEMS` (:75-106). |
| `src/frontend/src/app/App.tsx` | Two `<Route>`s (admin one wrapped in `<AdminRoute>`, per :74-81); mount the bridge. |
| `src/frontend/src/app/store.ts` | Register `customCompaniesApi` — reducer (:25-31) + middleware (:37-43). Mirror in `src/frontend/src/test/testUtils.tsx:20,47`. |
| `src/frontend/src/api/clients/backendScraperClient.ts` | Attach the bearer token to `/api/jobs` requests when available (owner-scoped reads). |
| `src/frontend/src/config/features.ts` (new) | `export const CUSTOM_COMPANIES_ENABLED = import.meta.env.VITE_CUSTOM_COMPANIES === 'true';` — copy `config/auth.ts:21`. Add `VITE_CUSTOM_COMPANIES` to `vite-env.d.ts:3-13`. |

**Logo handling: no change needed.** `getCompanyLogoUrl` (`companies.ts:928`) and
`getCompanyWordmarkUrl` (:939) are pure string builders; the components already fall
back to an initials tile on 404. `__tests__/config/companyLogoAssets.test.ts` iterates
`COMPANIES` only, which stays correct — custom-company logos cannot be committed at
build time. Leave the test alone.

## 3.7 Tests

Backend:
- `test_jobs_owner_scoping.py` — **the leak tests.** A `visibility='user'` company is:
  invisible to an anonymous `/api/jobs`; invisible to a *different* signed-in user;
  visible to its owner; invisible via `/api/jobs/{source_id}/{job_id}` to a non-owner.
  And the polarity guard: a job whose company has **no** `companies` row is still
  visible to everyone (this is what the wrong predicate would break).
- `companies_service` — a `visibility='user'` row never appears in `GET /api/companies`.
- `user_preferences_service` — auto-enroll never picks up a `visibility='user'` row.
- Quotas: the 6th add is rejected naming the limit; rapid adds are throttled by the
  sliding window; the global cap 503s. Limits read from `config.py`, not hardcoded
  (assert by monkeypatching `settings`).
- SSRF: the 9-case table again, now through `POST /api/users/companies`, each asserting
  zero outbound requests **and** zero rows in `companies`/`user_companies`, and one row
  in `company_add_attempts` with `outcome='rejected_ssrf'`.
- Dedupe: two users adding the same board produce **one** `companies` row and two
  `user_companies` rows.
- Unsupported: `https://www.tesla.com/careers` returns 200 `{supported:false}`, writes
  no company, and writes one attempt with `registrable_domain='tesla.com'`.
- 401 without a Bearer token on every `/api/users/companies` route.
- Promote flips `visibility` to `'public'` and makes the company appear in
  `GET /api/companies`; it is idempotent.
- **🟢 Cisco acceptance test (mocked chain, mirroring PR 1's fixture):**
  `POST /api/users/companies {"url":"https://jobs.cisco.com"}` → 201, one `companies`
  row with `ats='workday'`, `provider_config = {base_url:"https://cisco.wd5.myworkdayjobs.com",
  tenant_slug:"cisco", career_site_slug:"Cisco_Careers"}`, `visibility='user'`, one
  `user_companies` row, `via='embedded'`, and a probe count > 900.
- **🟢 Intel acceptance test:** same, `via='redirect'`, `career_site_slug='External'`.

Frontend:
- **`selectEffectiveCompanies` identity** — `toBe(COMPANIES)` with no custom companies
  and when anonymous. The single most important regression guard.
- `getCompanyById` finds a registered custom id; still finds every static id; returns
  `undefined` after `resetCustomCompanies()`.
- `getJobsForCompany` no longer 404s for a registered custom id
  (extend `__tests__/features/jobs/jobsApi.batched.test.ts`, which already `vi.mock`s
  `config/companies` — the template for a dynamic array).
- `getAllJobs` progress `total` includes custom companies; the fan-out includes them
  in the batched call; chunking still respects 150.
- `getCompanyFromURL` with an unknown id **holds** rather than falling back to
  `spacex` while the custom list is loading.
- `EnabledCompaniesSection` "Select All" includes custom companies; a saved custom id
  is not dropped from the selected panel.
- Sign-out clears the registry and the API cache (user A's companies gone for user B).
- MyCompaniesPage renders all three badge states; AdminCustomCompaniesPage sorts,
  paginates, and fires Promote.
- **Flag-off render equality:** with `VITE_CUSTOM_COMPANIES` unset, the nav has no
  My Companies entry and `selectEffectiveCompanies` is `COMPANIES` by identity.

## 3.8 Acceptance criteria

- [ ] All nine SSRF cases rejected 4xx at `POST /api/users/companies` with zero
      outbound requests and zero persisted companies; each logged as an attempt.
- [ ] A redirect to `169.254.169.254` is rejected at the hop.
- [ ] An ATS candidate is only ever fetched from that ATS's fixed API host.
- [ ] 401 without a Bearer token on every `/api/users/companies` route.
- [ ] 6th add rejected naming the limit; rapid adds throttled; global cap enforced;
      all limits in `config.py`.
- [ ] A `visibility='user'` company is invisible to anonymous users, to other users,
      in `GET /api/companies`, and to auto-enroll — and **visible to its owner** in
      `/api/jobs` and `/api/jobs/{source_id}/{job_id}`.
- [ ] A job whose company has no `companies` row is still visible to everyone.
- [ ] A non-ATS URL returns 200 `{supported:false}` with a reason, persists no company,
      and records `registrable_domain`.
- [ ] Every attempt records `user_id`, outcome, and path taken; the admin endpoint
      returns per-user counts, summed cost, and top unsupported domains.
- [ ] Promote flips `visibility` to `'public'` and the company appears in the curated
      directory.
- [ ] **`https://jobs.intel.com` pasted into My Companies produces a working Workday
      company (`career_site_slug='External'`) that scrapes on the next tick.**
- [ ] **`https://jobs.cisco.com` pasted into My Companies produces a working Workday
      company (`tenant_slug='cisco'`, `career_site_slug='Cisco_Careers'`) that
      scrapes on the next tick.**
- [ ] `selectEffectiveCompanies(stateWithNoCustom) === COMPANIES` (identity).
- [ ] With `VITE_CUSTOM_COMPANIES` unset the app renders identically to today.
- [ ] `alembic heads` returns exactly one head; the migration is `--autogenerate`d,
      combined, and contains no `UPDATE`.
- [ ] `npm run type-check`, `npm test`, `pytest api/tests -q`, `mypy` all clean.

## 3.9 Rollback

1. `custom_company_sources_enabled=false` — writes 503, reads unaffected.
2. `VITE_CUSTOM_COMPANIES` unset — UI gone.
3. `UPDATE companies SET enabled=false WHERE visibility='user';` — scraping stops,
   the anti-join hides the jobs.
No code revert and no migration down-grade needed for any of the three.

## 3.10 Ordered task list

1. `db_models.py`: `Company.visibility`, `UserCompany`, `CompanyAddAttempt`. Then
   `alembic revision --autogenerate`. Review: three DDLs, one revision, no `UPDATE`,
   `down_revision` = PR 2's head. `alembic heads` == 1.
2. Audit `services/companies_seed.py` for `visibility` clobbering; fix if needed.
3. `companies_service.py:29` + `user_preferences_service.py:34-49` — add the
   `visibility='public'` filters. Test them **before** anything can create a private row.
4. `services/database.py` `_build_where`/`get_jobs`/`get_job_by_id` + `routers/jobs.py`
   owner scoping. Write `test_jobs_owner_scoping.py` including the polarity guard.
5. `api/jobs.ts`: forward `Authorization`. `backendScraperClient.ts`: attach the token.
6. `config.py` quota settings + `rate_limit.py` limiter and dependency.
7. `services/company_add_audit.py` then `services/custom_companies_service.py`
   (quotas → discover → probe → dedupe → insert → enqueue-first-scrape → record attempt).
8. `routers/user_companies.py` + models; mount in `main.py`.
9. Backend tests: service, router, SSRF table, quotas, dedupe, **Intel and Cisco
   acceptance tests**.
10. Admin endpoints + models + `test_admin_custom_companies.py`.
11. Frontend: `customCompanyRegistry.ts`, export `createBackendScraperCompany`,
    registry-aware `getCompanyById`. Write the identity test **first**.
12. `customCompaniesApi.ts` + store registration + `testUtils.tsx` mirror.
13. `selectEffectiveCompanies.ts` + `useCustomCompaniesBridge.ts` + mount in `App.tsx`.
14. The seven gates in order (§3.6). Gate 3 (`lib/url.ts` hold-don't-default) is the
    subtlest — do it deliberately.
15. `syncCustomCompanies.ts` delta thunk.
16. Sign-out purge: `useHydrateSavedFilters.ts:86` + the global test `afterEach`.
17. `MyCompaniesPage`, `AdminCustomCompaniesPage`, routes, nav, `vercel.json` SPA rewrite.
18. `config/features.ts` + `vite-env.d.ts`.
19. Full suite: `npm run type-check && npm test && pytest api/tests -q && mypy && alembic heads`.
20. Live-verify Intel and Cisco end-to-end against a local stack; paste evidence into
    the PR description.

---

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

---

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

## 6. Definition of Done (every PR)

- [ ] `npm run type-check` clean
- [ ] `npm test` and `pytest` green
- [ ] New/changed behavior has tests
- [ ] Alembic: `--autogenerate` only, single head, metadata-only / combined ALTER
- [ ] CLAUDE.md / docs updated if behavior changed
- [ ] The §4 divergence checklist pasted into the PR description
- [ ] PR opened against `main` with a conventional-commit title
