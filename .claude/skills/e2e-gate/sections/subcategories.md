# SWE subcategories — e2e gate runbook

Full design/reasoning: `e2e/subcategories/PLAN.md`. Live case status + the fixture corpus:
`e2e/subcategories/CASES.md`. This file is the "sub-skill": what each case proves, how to run
just it, and what to look at first when it goes red.

## Run it

```bash
e2e/run.sh subcategories              # full gate, measured 79-96 s
e2e/run.sh subcategories --fast       # API tier only, measured 10 s - run on every commit
e2e/run.sh subcategories --case SC-04 # one case, for a fix loop
e2e/run.sh subcategories --keep-up    # leave the stack on :8203/:3203 for a fix loop
e2e/run.sh subcategories --refresh-db # re-provision jobscraper_e2e_subcategories from scratch
```

**Cost: $0, unconditionally.** There is no `--live` and no opt-in that changes it. No LLM call,
no Browserbase session, no request to any host but its own stack — every fact it asserts is a
property of one SQL operator over eleven seeded rows.

**Ports `8203`/`3203`, database `jobscraper_e2e_subcategories`.** It shares nothing with
`add-companies`/`live-view` (`:8201`/`:3201`, `jobscraper_e2e`) and takes its own run lock, so
the two gates can run **at the same time**. It will refuse a second copy of itself, because that
would reseed the fixtures out from under the first run.

## When to run this gate

Before claiming "ready to test" on anything touching:

- `services/job_search.py` — especially `build_search_where` and `expand_subcategories`
- `routers/jobs_search.py` — the `?subcategory=` param, its validation, the cursor fingerprint
- `services/enrichment_writer.py` — `SUBCATEGORY_SLUGS`, `SUBCATEGORY_PARENT`,
  `SUBCATEGORY_FILTER_EXPANSION`, `MAX_SUBCATEGORIES`
- `services/app_settings.py` and `routers/jobs.py`'s `/settings` — the reveal flag
- `models.py`'s `JobListingResponse.subcategories` / `FacetsResponse`
- `services/database.py`'s `_LIST_COLUMNS` (it serializes the array on both read paths)
- any migration touching `job_listings.enrichment_subcategories` or `job_subcategories`
- `src/frontend/src/components/shared/filters/FacetTreeMultiSelect.tsx`,
  `components/recent-jobs-page/RecentJobsFilters.tsx`,
  `features/settings/subcategoryReveal.tsx`, `features/jobs/searchJobsArgs.ts`

## Files this suite does NOT own — report bugs there, don't fix them here

`services/job_search.py`, `routers/jobs_search.py`, `services/enrichment_writer.py`,
`services/app_settings.py`, `models.py`, and the Recent-page filter frontend. If a case fails
because of a bug in one of these, the case is doing its job — **report the bug, don't patch the
test to match it.**

## Per-case reference

| ID | Proves | Known-red? | First thing to check on red |
|---|---|---|---|
| **SC-00** | The 17 slugs agree across `fixtures.py`, `enrichment_writer.SUBCATEGORY_SLUGS`, the seeded `job_subcategories` rows and `GET /api/jobs/facets` | No — green | Which of the four disagrees; the message names the diff. A slug added to the enricher **without** a seed migration lands here. If the change is intended, move `fixtures.EXPECTED_SUBCATEGORY_SLUGS` deliberately and re-read every case's expected set — SC-00 red usually means the cases below are now vacuous, not merely failing |
| **SC-01** | Selecting the **parent** category still returns the rows with no subcategory (`NULL` and `'{}'`) | No — green | `build_search_where`'s `categories` branch. A red here means the category predicate started consulting `enrichment_subcategories` — which silently hides the 65% of SWE rows the enricher has not labelled, and on day 0 of a backfill that is *all* of them |
| **SC-02** | One subcategory returns **only** jobs carrying that slug | No — green | The `&&` clause in `build_search_where`. If the decoy (`J-SECURITY`) came back, the predicate is not narrowing at all; if `J-PAIR` went missing, something started reading only the array's **first** element and a job's second specialty is unreachable |
| **SC-03** | Subcategory ANDs with level and with company | No — green | `conditions.append` in `build_search_where` — every dimension goes on the same AND list. An OR here makes the list **grow** when the user narrows, which is the version a person notices. Check `J-BACKEND-MID` (right slug, wrong level) and `J-OTHER-BACK` (right slug, other company) |
| **SC-04** | `full_stack` widening is **one-way** | No — green; **proven to bite** (`PLAN.md` §6) | `SUBCATEGORY_FILTER_EXPANSION` in `enrichment_writer.py` — it must have exactly **two** keys. A third key (`full_stack`) makes the relation symmetric and turns Full Stack into a synonym for the whole category. Also check nobody added a second expansion site: `buildSearchJobsArgs` must send the selection **verbatim**, or the widened pair gets persisted into saved filters and chips |
| **SC-05** | The reveal flag gates the UI **only** | No — green | **Read `features/settings/subcategoryReveal.tsx` before touching this.** The asymmetry is deliberate: the backend does not gate `?subcategory=` on the flag, because a clobber-on-mount guard would destroy legitimately saved selections. If the API half went red, someone "tidied" that into a feature gate and every saved subcategory filter breaks the moment the flag flips. If only the UI half went red, check `RecentJobsFilters.tsx`'s `revealSubcategories ? (facets?.subcategories ?? []) : []` |
| **SC-06** | `NULL` ≠ `'{}'`, end to end | No — green; **proven to bite** (`PLAN.md` §6) | `JobListingResponse.subcategories` must be `list[str] \| None = None` — **never** `default_factory=list`. A default of `[]` erases "never evaluated" at the wire and the backfill queue reads itself as complete. If instead the *filter* half went red, `&&` grew a `COALESCE` or an `IS NULL` escape hatch |

## Reading a red

Same as every section: `e2e/subcategories/artifacts/<run>/summary.md` first, then
`cases/<test>/step.txt`, which names the failing step in words. Several cases also dump the raw
response body beside it (`response.json`, `backend.json`, `serialization.json`) — the fastest
way to tell "wrong rows" from "wrong shape".

UI failures additionally get a screenshot and a Playwright trace under the run's `ui/`.

**Three failure modes that are NOT product regressions**, and what they look like:

| Symptom | Cause | Fix |
|---|---|---|
| Every case fails, `seed wrote N rows, expected 11` | the fixture seed and the database disagree | `--refresh-db` |
| `job_subcategories holds 0 slugs` at boot | the database never got migration `5a7d3e9c1b46` | `--refresh-db` |
| The UI tier fails on set comparison with a message about the **2400px viewport** | the fixture corpus outgrew the mounted-row window | raise the viewport in `ui/helpers.ts`; do **not** loosen the assertion |

## One thing not to do

**Do not scope a new case with `?company=` and then forget the mirror.** Almost every API query
here carries a company scope, which is only legitimate because SC-03 separately proves that
scope is a real AND rather than a no-op
(`test_sc03_dropping_the_company_scope_returns_both_companies`). A case that scopes without a
mirror is asserting against a subset for a reason nobody checked.

## Known non-coverage

- The Vercel serverless proxy (`api/jobs.ts`) — the suite runs the frontend under plain
  `vite dev`, same gap as `add-companies`.
- The enricher's **write** path — nothing here decides whether the right slugs get assigned.
- `user_saved_filters.subcategory` round-tripping through the saved-filters API.
- Cursor paging under an active subcategory filter (eleven rows never make a second page).
