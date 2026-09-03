# Meta (metacareers.com) — discovery findings

**Verdict: NO runtime browser needed. Pure `http_json` recipe, one request, full catalogue (801/801 jobs).**
This was the pivotal target for the browser-at-runtime decision: the answer is that Meta's GraphQL
is fully forgeable from plain httpx once the request carries a plausible Chrome header set.

## Technique that worked

- Endpoint: `POST https://www.metacareers.com/graphql`
- Operation: `CareersJobSearchResultsV2DataQuery`, `doc_id=27129360303422352` (Relay persisted query — no query text ever sent)
- Body: `application/x-www-form-urlencoded` in the browser; in our recipe the same params ride the **query string** (see Schema fit below)
- Records: `data.job_search_with_featured_jobs_v2.all_jobs` — 801 objects `{id, title, locations[], teams[], sub_teams[]}`
- Companion count query (`CareersJobSearchHideFiltersBarV2Query`, `doc_id=26210170368675892`) returns `job_count: 801`
- **Cookies: none required.** **Session tokens: none required** (details below)
- Pagination: none — `results_per_page: null` returns the entire catalogue in one 172KB response

## The forgeability experiment (the key evidence)

All attempts from fresh `httpx.Client`s (guaranteed cookieless unless stated). Captured browser values came
from `captures/meta/graphql/002_req.txt` (full request headers + body recorded by `discover_graphql.py`).

| # | What was sent | Result |
|---|---------------|--------|
| A | Exact captured `lsd` + full form body, sparse headers (UA/Origin/Referer/x-fb-* only), no cookies | **HTTP 400**, 1543-byte generic Facebook error page |
| B | Made-up `lsd`, same sparse headers | **HTTP 400**, same page |
| C | Minimal body (lsd+doc_id+variables+friendly_name), sparse headers | **HTTP 400** |
| E | Captured `datr` cookie + captured `lsd`, sparse headers | **HTTP 400** — cookies don't help |
| F | Plain httpx `GET /jobs` with sparse headers (bootstrap attempt) | **HTTP 400** — even the HTML page is refused |
| G | `GET /jobs` with **full Chrome header set** (`sec-ch-ua*`, `Sec-Fetch-*`, `Upgrade-Insecure-Requests`, full `Accept`) | **HTTP 200**, 522KB HTML — the block is header-plausibility, not TLS fingerprinting |
| J | POST with captured `lsd` + **full Chrome XHR header set**, no cookies | **HTTP 200, `all_jobs=801`** |
| K | POST with **made-up `lsd`** (`AdSforgedforgedforge`) + full XHR headers, no cookies | **HTTP 200, `all_jobs=801`** — lsd value is NOT validated for logged-out traffic, only its presence |
| L | POST with lsd freshly harvested from an httpx GET (self-contained bootstrap) | **HTTP 200, `all_jobs=801`** |
| M | Through `replay._request` verbatim: POST, all params in the **query string**, body `{}` | **HTTP 200, `all_jobs=801`** |
| N | Through `replay._request`: params as **JSON body** | **HTTP 400** — Meta rejects JSON bodies |

Scripts: `forge_test.py` (A–D), `forge_test2.py` (E–F), `forge_test3.py` (G), `forge_test4.py` (J–L), `forge_test5.py` (M–N), all in this directory.

Conclusion: what Meta actually gates on is a **plausible browser header set** (`sec-ch-ua`, `sec-ch-ua-mobile`,
`sec-ch-ua-platform`, `Sec-Fetch-Site/Mode/Dest`, believable `Accept`/`Accept-Language`, matching User-Agent).
The `lsd`/`x-fb-lsd` anti-CSRF pair must be present but any value passes when logged out. No cookies, no doc_id
handshake, no per-session state. The POST is deterministic and replayable forever with static values.

## Recipe kind chosen: `http_json`

Top of the preference order, and it works. `browser_dom` is NOT needed for Meta. The schema quirk:
`run_http_json` sends POST bodies as JSON (`client.post(url, json=...)`) which Meta rejects (row N), but Meta's
www stack reads request params from the query string on POST (row M, proven through `replay._request` itself).
So the recipe carries every form param — including `variables` and `doc_id` — in `entrypoint.url`, and the `{}`
JSON body replay sends is ignored by the server. Not a schema gap, just a documented transport detail.

## Completeness

- Site-claimed total: `job_count = 801` (Meta's own count query, same capture session)
- Recipe returns: **801 unique ids** (verified unique: 801/801)
- `all_jobs` length == `job_count` exactly; single request, no pagination to under-fetch.
- Guard: `expected_min_jobs=500`. If Meta ever introduces server-side pagination, the truncated response would
  be a page-sized fraction (25/50/100) and the replay RAISES. 500 still tolerates ~35% genuine catalogue shrink.

## Fragility

1. **`doc_id` rotation (the real one).** `27129360303422352` is a Relay persisted-query id; it survives sessions
   but rotates with Meta frontend releases on an unknown cadence. When it dies the endpoint returns an error, not
   an empty list -> `RecipeExecutionError` -> **loud** failure. Re-discovery is mechanical: load `/jobs` in any
   browser, copy the new `doc_id` off the `CareersJobSearchResultsV2DataQuery` POST.
2. **Header-plausibility checks tightening.** If Meta starts validating `sec-ch-ua` against TLS fingerprint or
   requires cookies, the response flips to HTTP 400 -> **loud**. (Today the pinned Chrome/120 header set with a
   HeadlessChrome-free UA passes from httpx's TLS stack.)
3. **Operation rename** (the historical 41-day silent-zero killer): here it fails loudly, because the request
   itself names the operation — a renamed operation means our pinned `doc_id` dies (case 1), not a silently
   empty parse. `records_path` drift on a still-valid response would also raise ("did not resolve to a list").
4. **Silent modes:** the only silent-ish failure is catalogue truncation while keeping the same shape (e.g.
   pagination introduced with >500 rows on page 1). Mitigation beyond the floor: production should replay the
   companion count query (`doc_id=26210170368675892`, same transport) and compare `job_count` to rows fetched.
   The spike schema has no cross-check slot — see SCHEMA GAP.
5. `locations`/`teams` arrays can be empty; `fields` uses `locations.0` which maps to `None` then, harmless.
   Payload has **no posted-at timestamp**; freshness must be tracked on our side (first_seen).

## SCHEMA GAP (minor, non-blocking)

- No way to express a **completeness cross-check**: "also run this second request and require
  `count_path >= len(records)*0.9`". Meta ships an exact count query on the same transport; wiring it in would
  convert the one silent failure mode (shape-preserving truncation) into a loud one. `expected_min_jobs` is the
  blunt stand-in today.
- Cosmetic: `http_json` POST always sends a JSON body; a `body_format: "form"` option would let this recipe put
  params in the body like the real browser instead of the query string. Not needed — query-string transport is
  proven — but worth knowing if Meta ever stops reading query params on POST.

## Measurements

- Capture wall-seconds: 9.9 (capture.py) + ~12 (discover_graphql.py targeted capture)
- Replay wall-seconds: **0.8** (run 1), 1.3 (run 2) — both OK, 801 jobs
- Job count: **801** (== site-claimed 801)
- Dollars: **0**
- Politeness: ~12 total requests across the whole discovery (2 page loads, a handful of single POST/GET probes,
  2 replays); no crawling.

## Artifacts

- Recipe: `scripts/one_off/recipe_spike/recipes/meta.json`
- Raw captured GraphQL pairs: `captures/meta/graphql/00{0..3}_{req,resp}.txt` (002 = the job search, 001 = the count)
- Experiments: `captures/meta/forge_test*.py`, `analyze.py`, `verify_url.py`, `emit_url.py`, `discover_graphql.py`
- Replay proofs: `results/discover-20260805T051711Z.json`, `results/replay-verify-20260805T051724Z.json`
