# janestreet — discovery findings

## Verdict

**Recipe kind: `http_json`** — the best possible outcome. The hand-rolled open-roles SPA fetches its
entire job inventory as one flat JSON array over plain GET. No browser, no auth, no cookies, no
pagination needed at replay time.

- Recipe: `scripts/one_off/recipe_spike/recipes/janestreet.json`
- Replay: **OK, 225 jobs in 0.4s** (`results/discover-20260805T051618Z.json`)

## Technique

- Entry URL `https://www.janestreet.com/join-jane-street/open-roles/` does NOT redirect (200). It is a
  landing page with two cards; the visible lists live at `?type=experienced-candidates` and
  `?type=students-and-new-grads`. All of them are fed client-side by the same XHR.
- **Endpoint: `GET https://www.janestreet.com/jobs/main.json`** — 200, `application/json`, 688,974
  bytes, top-level array of 225 records. Verified directly with httpx (same status/bytes as in-browser),
  only a desktop User-Agent header sent (replay.py's default). `records_path: ""`.
- Record shape: `id, position, category, availability, city, duration, overview (HTML), team,
  min_salary, max_salary`. Distinct numeric ids (Greenhouse-style `…002` suffix — this is almost
  certainly a Greenhouse export behind a custom front end).
- **No URL field in the records.** Detail URL pattern discovered and verified by probe
  (`captures/janestreet/probe.py`): `https://www.janestreet.com/join-jane-street/position/{id}/` → 200.
  Slugged variant and `/open-roles/position/{id}/` → 404. Recipe uses the template-field feature for `url`.
- Auxiliary endpoints seen (not used): `/jobs/internships.json` (46 open/closed status rows, no ids),
  `/static/position-directories.json` (bare id list, 293 ids).

## Pagination

**None — confirmed single full listing.** One request returns all records for all four offices
(NYC 94, HKG 62, LDN 55, SGP 14 at discovery). No count field in the payload; the array length is the total.

## Completeness reconciliation (the 3,582-job-incident check)

The site shows no numeric total, so I reconciled against the rendered DOM
(`captures/janestreet/probe_rows.py`):

- The typed listing pages **default to a New York location filter**. Rendered distinct position-link
  ids across both pages: **94** — exactly the **94** `city == "NYC"` records in main.json (0 rendered
  ids outside main.json; every non-rendered main.json id is LDN/HKG/SGP, i.e. hidden by the default
  city filter, not missing).
- So main.json (225) is the strict superset the UI filters from: recipe ≥ site-visible. Not a fraction.

## Gotchas

1. **Lisu homoglyph anti-scrape quirk**: 3 records ("Machine Learning Researcher") spell M/L/R with
   Lisu codepoints U+A4DF/U+A4E1/U+A4E3 ("ꓟachine ꓡearning ꓣesearcher"). Renders identically to Latin,
   but breaks naive title matching/keyword filters. Ids are clean, so id-keyed dedup is unaffected.
2. **No posted/created date anywhere** in the payload — freshness must come from our `first_seen_at`.
3. `city` is a code (NYC/LDN/HKG/SGP), not a full name; `availability` is the employment-type facet
   ("Full-Time: Experienced" 157, "Summer Internship" 37, "Full-Time: New Grad" 23, plus 8 misc).
4. `overview` is raw HTML (full job description ships in the listing payload — nice for detail-free scraping).

## Fragility

- **Loud failures** (replay raises): endpoint path change (HTTP 4xx/5xx), payload wrapped in an object
  (`records_path '' did not resolve to a list`), inventory collapse below 100 (`expected_min_jobs`).
- **Silent failures**: (a) the `url` template — if Jane Street re-routes detail pages, the recipe still
  passes while emitting dead links; worth an occasional sampled HEAD in production. (b) homoglyph titles
  polluting any title-keyed logic downstream.
- No CSS selectors used at all, so markup churn cannot break this recipe.
- `expected_min_jobs=100` justification: total was 225 at discovery and the largest single-city subset
  (NYC = 94) is *below* the floor — a regression to a default-filtered/one-office feed fails loudly
  instead of half-passing.

## Measurements

| metric | value |
| --- | --- |
| capture wall time | 7.9 s |
| replay wall time | 0.4 s |
| replay job count | 225 |
| site-claimed total | none displayed; UI default view = 94 (NYC filter), full inventory = 225 (reconciled 94/94 on NYC) |
| requests used | ~10 total across discovery (1 capture pageload + JSON probes + 2 DOM probes); replay = 1 request |
| dollars | 0 |

## SCHEMA GAP (minor, non-blocking)

- No post-extraction transform hook: can't normalize the Lisu homoglyphs back to Latin (a fixed
  codepoint map, perfectly deterministic) or expand city codes to full names. Both are cosmetic here.
- No way to express "sample one record's `url` and assert 200" as a replay-time health check; the url
  template is the only silently-breakable part of this recipe.

## Evidence files

- `captures/janestreet/report.json`, `raw/000.json` (main.json body), `page.html`
- `captures/janestreet/probe.py` — httpx status/bytes for main.json + detail-URL pattern proof
- `captures/janestreet/probe_rows.py` — DOM-vs-JSON id reconciliation (default NYC filter discovery)
- `captures/janestreet/probe_grouping.py`, `probe_grouping2.py` — city/availability breakdowns
