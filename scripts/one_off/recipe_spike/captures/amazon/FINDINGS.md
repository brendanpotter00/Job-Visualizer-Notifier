# amazon — discovery findings

Entry URL: the user's filtered search (`software engineer`, within 24km of Austin, TX, `sort=recent`).

## Technique that worked: plain HTTP JSON (kind=http_json)

The amazon.jobs search page (Rails app) renders its results from one XHR:

```
GET https://www.amazon.jobs/en/search.json?<same query params as the HTML page>
```

- **Auth/headers/cookies: none.** A bare `httpx` GET with only the replay executor's Chrome
  User-Agent returns HTTP 200 `application/json`. No cookies, no CSRF token, no redirect
  (works with `follow_redirects=False`). Verified with `captures/amazon/probe.py page1`.
- **Payload shape:** top-level keys `content, error, facets, hits, job_posting_search_request, jobs`.
  `hits` = site-claimed total for the filter set; `jobs` = array of records
  (`id` UUID, `id_icims` requisition number, `title`, `job_path`, `posted_date`,
  `normalized_location`, `job_category`, `company_name`, full description text, ...).
  All 76 records had non-null id/id_icims/title/job_path (probe `nullcheck`).
- **The `facets[]` params the real page sends are optional** — dropping them still returns
  identical `jobs`/`hits`.
- **Pagination scheme (server side):** `offset` + `result_limit`, zero-based.
  Verified offset=0 and offset=10 return disjoint pages (0 id overlap), same `hits`.
- **Page-size cap: 100, enforced weirdly.** `result_limit=500` returns **HTTP 200** with
  `{"error": "Result limit cannot be greater than 100", "jobs": null, "hits": 0}`.
  `result_limit=100` returns exactly 100 records (probe `cap` / `cap100`).
  Replay handles the over-cap shape loudly (`records_path 'jobs' did not resolve to a list`).
- **End-of-results signal:** `len(jobs) < result_limit`, or `offset >= hits`.

## Recipe chosen: single-request GET, `result_limit=100`, `pagination.style=none`

All filter params + `result_limit=100` (the server max) are baked into `entrypoint.url`.
One request retrieves the entire filtered set (76 jobs today).

### Why NOT `pagination.style=offset` (important — this is a harness constraint, not a site one)

replay.py passes the pagination cursor as `httpx` `params=`, and **httpx 0.28 REPLACES the
URL's entire query string when `params` is given** (verified offline:
`httpx.Request('GET','https://example.com/x?a=1&b=2', params={'b':9})` gives `https://example.com/x?b=9`).
So on every paginated request, `base_query`, `city`, `latitude`, etc. are silently dropped and
the endpoint degrades to the unfiltered global board — observed live: `hits` jumped 76 -> 10000
with plausible-looking jobs (probe `replaysim`). That is a *silent wrong-data* failure, worse
than a crash. POST with a JSON body (replay's other way to merge a cursor) is rejected:
**HTTP 422**, Rails CSRF (probe `post`). Hence single-request style=none is the only correct
expression of this scrape in the current harness.

## Gotchas that would break a naive implementation

1. **Errors arrive as HTTP 200.** Bad `result_limit` (and likely other param errors) returns
   200 with an `error` string and `jobs: null`. Status-code-only checking is insufficient;
   you must fail when `jobs` isn't a list (replay does).
2. **httpx params-replacement** (above) — a naive "keep the URL, add `params={'offset': n}`"
   paginator silently unfilters the search.
3. **`posted_date` double space:** single-digit days are space-padded (`"August  3, 2026"`,
   `"April  7, 2026"`). A strict `%B %d, %Y` parse fails; normalize whitespace first.
4. **Raw control bytes in `description`:** replay already parses with `json.loads(strict=False)`
   (its comment even names Amazon as the reason).
5. **Relative `job_path`:** http_json mapping applies no `base_url`; the recipe uses a template
   field `"https://www.amazon.jobs{job_path}"`.
6. The browser capture's `networkidle` never settles (Adobe/Google/RUM analytics chatter) —
   capture.py hit its 60s goto timeout yet still recorded everything. Irrelevant to replay
   (no browser), but tune `--wait load` if re-capturing.
7. No bot-wall observed at this request volume (~10 requests over ~10 min). Politeness note:
   the full filtered set costs ONE request.

## Fragility assessment

- **Biggest risk (SILENT):** if this filtered search ever exceeds 100 open jobs, the recipe
  returns exactly the newest 100 (`sort=recent`) with no error — the same class of silent
  under-count as the 3,582-job false-closure incident. Today it returns 76/76 (full coverage,
  headroom 24). The payload's `hits` field is the ready-made tripwire, but the schema cannot
  express "assert count vs a total field" (see SCHEMA GAP).
- **Loud failures (good):** endpoint renamed/moved -> HTTP >=400 raise; params rejected ->
  `jobs: null` -> "did not resolve to a list" raise; payload restructure -> dig raise;
  count collapse below 20 -> expected_min_jobs raise.
- **Silent-ish failures:** Amazon changing filter *semantics* (e.g. ignoring `radius`) would
  change the result set without an error; `expected_min_jobs=20` floor only catches collapse,
  not drift. A future `id_icims: null` record would be silently dropped by the field mapper;
  at discovery all records had it.
- `expected_min_jobs=20` rationale: 76 at discovery; an Austin/AWS-hub SWE search dropping
  below 20 means endpoint/filter breakage or a real hiring shock — human review either way.

## SCHEMA GAP

1. **No replayed-count vs claimed-total assertion.** The payload exposes `hits` (76). A field
   like `total_path: "hits"` + "raise if unique mapped records < min(total, page cap x pages)"
   would convert the only silent failure mode (growth past 100) into a loud one. This is the
   exact guard the false-closure incident needed.
2. **Paginated GET cannot preserve non-cursor query params.** `run_http_json`'s offset/page
   styles are only usable for endpoints whose sole query param is the cursor, because httpx
   `params=` wipes the rest of the query string. Fix options: build the per-page URL by
   merging into the parsed query (e.g. `url.copy_merge_params`), or add a
   `pagination.base_params` object sent with every page. Until then, any filtered
   Rails/REST board caps out at one page per recipe.

## Measurements

| metric | value |
|---|---|
| capture wall-seconds | 66.3 (60 of it: networkidle goto timeout; harmless) |
| replay wall-seconds | 0.8 |
| replayed job count | **76** (unique ids) |
| site-claimed total (`hits`) | **76** — exact match |
| discovery HTTP requests | ~10 total (1 browser page + 9 httpx probes) |
| dollars spent | 0 |

Recipe: `scripts/one_off/recipe_spike/recipes/amazon.json`
Probes (re-runnable evidence): `scripts/one_off/recipe_spike/captures/amazon/probe.py`
