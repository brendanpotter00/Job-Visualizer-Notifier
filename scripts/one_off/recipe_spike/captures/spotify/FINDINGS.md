# Spotify (lifeatspotify.com) — discovery findings

## Verdict

**Recipe kind: `http_json`** — a single plain-HTTP GET returns every open job. No browser, no pagination, no auth, no special headers.

- Recipe: `scripts/one_off/recipe_spike/recipes/spotify.json`
- Replay: **OK, 90 jobs in 0.3s** vs site-claimed total of **90** (exact match, verified two independent ways below).

## Technique

`https://www.lifeatspotify.com/jobs` is a Next.js SPA over a headless WordPress backend. The page server-renders only chrome + filters; the job list is fetched client-side from:

```
GET https://api.lifeatspotify.com/wp-json/animal/v1/job/search
User-Agent: <any browser-ish UA>   (plain httpx with the replay UA works; 200)
```

Response shape:

```
{ "main_categories": [...14...],
  "result": [ { id, text, main_category{name,slug}, sub_category, locations[{location,slug,num_jobs}], job_type{name,slug} }, ... ],
  "time": <unix epoch> }
```

`records_path = "result"`. `id` is a URL slug; canonical detail page is `https://www.lifeatspotify.com/jobs/{id}` (verified 200).

## Pagination: none (verified, not assumed)

- Endpoint **ignores** `limit`, `per_page`, `page`, `offset` — each tested; all returned the identical full 90-row set with the same first record.
- The site UI paginates client-side only ("Load more jobs" / "Showing N out of 90"); capture shows one job/search fetch (issued twice by React re-render) and no further requests on scroll.
- The endpoint DOES honor filter params (`?c=engineering` → 33 rows). A stray filter param is the main way to accidentally get a subset — the recipe sends none.

## Completeness cross-check (the 3,582-job-incident test)

Two independent oracles agree with the replayed count of 90:

1. UI claim: rendered page says "Showing … out of **90**".
2. `__NEXT_DATA__` → `props.pageProps.allFilters.categories[].positions` sums to exactly **90** (each job has one main category).

Trap: `allFilters.locations[].positions` sums to **120** because 29/90 jobs list multiple locations. Never use the locations sum as the completeness oracle.

## Gotchas that would break a naive implementation

1. **No posted/created date exists anywhere** in the search payload — `first_seen_at` in our DB is the only freshness signal for Spotify.
2. **Multi-location jobs**: `locations` is an array; recipe maps `locations.0.location` only. A per-location fan-out (like Apple's id-suffix scheme) would need the raw array.
3. **`job_type` missing/false on some records** (7/90 at discovery) — maps to None; don't make it required.
4. **`sub_category.slug` can be boolean `false`**, not a string.
5. **`_next/data/<buildId>/jobs.json` is NOT a viable alternative**: the buildId rotates every deploy, and its pageProps hold only meta + filters, not the job list.
6. **Job cards carry no `<a href>`** — JS-clickable divs (`data-info="<slug>"`), so an http_html/selectors approach could never extract URLs anyway.

## Fragility assessment

- **Breaks loudly** (replay raises): endpoint moves, non-JSON response, `result` renamed, HTTP 4xx/5xx, count below expected_min_jobs=30.
- **Breaks silently** (the dangerous kind): the endpoint starting to honor a server-side cap while the catalog grows past it. Today it returns the full set at n=90. Production mitigation: re-run the categories-sum oracle from `__NEXT_DATA__` on the jobs page and alert on mismatch with the API count.
- `wp-json` namespace `animal/v1` is the site's own data source — it cannot rot without the public site rotting too.

## expected_min_jobs = 30, justified

One third of discovery-time total (90). Spotify is a 7,000+ employee public company; fewer than 30 open roles worldwide would be extraordinary and far more likely a truncated/filtered response (a single category, engineering, is 33 alone). Not set to 1; a subset response must fail.

## Measurements

| metric | value |
|---|---|
| capture wall time | 9.7 s |
| replay wall time | 0.3 s |
| replayed job count | 90 (all unique ids) |
| site-claimed total | 90 (UI text + categories-sum, both match) |
| discovery requests | ~10 (1 browser page load + 9 polite httpx probes) |
| dollars | 0 |

## SCHEMA GAP

None for the recipe itself — `http_json` + `pagination: none` expresses this site exactly.

Production-side note (not a blocker): the schema cannot express a *secondary completeness oracle* (e.g. "also fetch the jobs page, check categories-sum equals API count"). For this target that check is the only defense against the silent-cap failure mode; `expected_min_jobs` is the blunt stand-in.
