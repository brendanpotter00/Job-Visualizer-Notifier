# SWE subcategories — case table

The contract `.claude/skills/e2e-gate/sections/subcategories.md` reads. `PLAN.md` carries the
reasoning behind every case; this is the quick-reference + current status.

**Last real run: 2026-09-16, `e2e/run.sh subcategories` @ `feat/e2e-subcategories` (base
`6e3e526e`). 36 API + 16 UI = 52 collected, 52 PASS, 0 FAIL, 0 BLOCKED, exit 0 —
summary verdict GREEN.** Measured, twice back to back with no manual reset in between:
**79 s and 96 s** for the full gate, **10 s** for `--fast`. The API tier itself is 2–4 s; the
browser tier is ~1.3 min and is the whole of the difference. First provision of the database
adds ~20 s, once.

**Cost: $0, and there is no flag that changes that.** No LLM call, no Browserbase session, no
request to any host but this section's own stack. `e2e_app.py` refuses to boot with
`CAPTURE_USE_BROWSERBASE=true` or a Browserbase key set, and `env.subcategories` blanks both.
This section has no `--live` and no `BLOCKED` state: there is no third party for it to be
blocked by.

**Auth**: the API tier is entirely **anonymous** — `/api/jobs/search`, `/api/jobs/facets` and
`/api/jobs/settings` are all public read paths, so no token is minted on that tier at all. The
UI tier signs in (reusing `shared/auth`) only because a signed-out Recent page caps the list at
12 cards behind an overlay.

**Non-coverage, stated plainly**: the Vercel serverless proxy (`api/jobs.ts`) is **not
exercised** — the frontend runs under plain `vite dev`, same known gap as `add-companies`
(`PLAN.md` §7 lists this and four others).

## Case table

| ID | Proves | Tier | Status | Notes |
|---|---|---|---|---|
| **SC-00** | The 17 slugs agree across all four places that hold them: `fixtures.py`, `enrichment_writer.SUBCATEGORY_SLUGS`, the seeded `job_subcategories` rows, and `GET /api/jobs/facets` | API | 🟢 **GREEN** (3/3) | Not one of the named behaviours — a **pin under them**. Every case below asserts something about specific slugs and goes vacuous if the set moves. Also pins `MAX_SUBCATEGORIES == 2` (the fixture corpus seeds a two-slug row as the ceiling) and the widening table itself |
| **SC-01** | Selecting **Software Engineering** returns jobs across **all** its subcategories — including rows whose array is `NULL` or `'{}'`. The parent must not narrow to labelled rows | API + UI | 🟢 **GREEN** (4 API / 3 UI) | Exact-set equality, not "contains". The control is `J-PM` (a `product_manager` row) — without it a filter that returned *everything* would pass. The mirror is the unfiltered read, which must include `J-PM`, so its absence is the filter working rather than the row missing |
| **SC-02** | Selecting **one subcategory** returns **only** jobs carrying that slug | API + UI | 🟢 **GREEN** (9 API / 4 UI) | The decoy `J-SECURITY` ({security}) must be absent under `?subcategory=mobile`, and the mirror (`?subcategory=security` returns it) proves the absence. `mobile`/`security` chosen because **neither widens** — so SC-02 cannot pass for SC-04's reason. Also pins that `&&` matches a **non-primary** slug (`J-PAIR` is `{infrastructure_platform, backend}` and must be found by both), that repeated keys OR, and that an unknown-but-well-formed slug matches nothing **without** a 422 |
| **SC-03** | Multiple filters compose with **AND** | API + UI | 🟢 **GREEN** (6 API / 2 UI) | Two compositions, because they fail differently: subcategory **+ level** (decoy `J-BACKEND-MID` — right slug, wrong level) and subcategory **+ company** (decoy `J-OTHER-BACK` — right slug, other company). Both decoys have mirrors. Also pins the **redundant-but-consistent** pair the UI actually sends (ticking a child auto-checks its parent) and that a subcategory paired with the *wrong* parent is unsatisfiable |
| **SC-04** | `full_stack` widening is **ONE-WAY**: `frontend`/`backend` also surface `full_stack`; `full_stack` alone stays exact | API + UI | 🟢 **GREEN** (5 API / 4 UI) | The exact half is the load-bearing one — everything else would still pass if the relation were symmetric. **Proven to bite**: making the map symmetric turned it RED on both tiers (`PLAN.md` §6). The expected sets come from `fixtures.expected_for_subcategory()`, which applies the widening from the **fixture table**, so this is not `expand_subcategories` compared against itself |
| **SC-05** | The reveal flag gates the **UI only**. Flag off ⇒ the control is absent and results are the no-subcategory results; the backend does **not** gate `?subcategory=` on it | API + UI | 🟢 **GREEN** (3 API / 3 UI) | The asymmetry is **deliberate and documented** (`features/settings/subcategoryReveal.tsx`): a clobber-on-mount guard would destroy legitimately saved selections. **If this case ever goes red, read that file before changing it.** The UI half asserts the chevron's absence — with `childOptions: []` the tree renders identically to the flat control, so the chevron *is* the subcategory control's whole UI signature. Off is written as an **absent row**, which is what ships (`app_settings` has no seed row by design) |
| **SC-06** | `NULL` vs `'{}'` survives end to end: `subcategories` serializes `null` as `null`, never `[]`; an active filter hides **both** | API only — see below | 🟢 **GREEN** (6/6) | **Proven to bite**: changing `JobListingResponse.subcategories` to `Field(default_factory=list)` turned three of the six RED. Also pins the sharpest difference from `category`/`level`: a **level** filter keeps `J-EMPTY` (it has a level), a **subcategory** filter drops it. That gap is the entire reason the reveal flag exists |

### Why SC-06 has no UI half

`null` and `[]` render **identically**: `JobChipsSection` falls back to the category chip for
both. There is no visible difference to assert, and `add-companies/PLAN.md` §3's rule is that a
UI assertion for a non-UI fact is a lie. A UI spec here would pass whatever the wire did — which
is worse than no spec. SC-06 is API-tier only, on purpose, and `run.sh` knows it: `--case SC-06`
prints *"no UI spec matches — it is an API-tier-only case"* rather than failing on Playwright's
zero-match error.

## The fixture corpus

Eleven rows, two companies, seeded by `seed.py` from `fixtures.py` — the one source of truth
both tiers read (`ui/corpus.ts` shells out to `fixtures.py --json` rather than re-declaring
anything). Every row exists because a case would be weaker without it.

| key | subcategories | level | why it is here |
|---|---|---|---|
| `J-BACKEND` | `{backend}` | senior | SC-02 match; SC-03's senior match |
| `J-BACKEND-MID` | `{backend}` | mid | **SC-03's AND decoy** — right slug, wrong level |
| `J-FRONTEND` | `{frontend}` | mid | SC-04 widening source |
| `J-FULLSTACK` | `{full_stack}` | senior | SC-04: must surface under both `frontend` and `backend`, and must come back **alone** under `full_stack` |
| `J-PAIR` | `{infrastructure_platform, backend}` | senior | the two-slug ceiling, **ordered** — `&&` must match on the non-primary slug too, and the order must survive the wire |
| `J-MOBILE` | `{mobile}` | mid | SC-02 subject; a slug with **no** widening |
| `J-SECURITY` | `{security}` | senior | **SC-02's decoy** — a different slug, which must be absent |
| `J-NULL` | **NULL** | mid | SC-01 must include it; SC-06 must hide it and serialize it as `null` |
| `J-EMPTY` | **`'{}'`** | mid | SC-06's other half — `&&` is *false*, not NULL, and the wire must say `[]` |
| `J-PM` | NULL, `category=product_manager` | senior | **SC-01's control** — the parent filter must not reach outside its category |
| `J-OTHER-BACK` | `{backend}`, other company | senior | **SC-03's company decoy** |

## Why this section does not use the shared 46k-job clone

Measured on `jobscraper_pr243` before a line was written: 46,145 OPEN jobs, of which **3** are
`software_engineering` and **0** carry a subcategory array (the column does not exist at that
revision). The corpus contributes nothing here and costs plenty — it makes exact-set comparison
impossible, which turns every case from "only these jobs" into "at least these jobs", and that
is precisely the assertion that cannot catch a filter returning too much.

So this section runs on its own `jobscraper_e2e_subcategories`, provisioned by the new
`ensure_db.sh --schema-only`: schema + six small dimension tables + the same
`alembic upgrade head`. **20 s and ~110 MB** versus minutes and ~760 MB. Full reasoning in
`PLAN.md` §2.

## Two things about this suite that are easy to get wrong

**The UI tier runs in a 2400px-tall viewport, and that is load-bearing.** The Recent list is
window-virtualized, so at the default 720px only a screenful of rows is mounted — and "this
title is absent" would be true of a row that simply had not scrolled into view. Every absence
assertion would pass for the wrong reason. `expectResults` also cross-checks the rendered titles
against `data-client-window`, so a corpus that outgrows the viewport fails loudly instead of
quietly asserting a prefix.

**SC-05 mutates the reveal flag, so it is re-set in three places.** The API tier's autouse
fixture re-seeds before every test; the UI spec has an `afterAll`; and `run.sh` re-seeds between
the two tiers. An order-dependent flag is green alone and the cause of a mystery failure in
whatever runs after it.

## Known non-coverage

- **The Vercel proxy layer** (`api/jobs.ts`) — plain `vite dev`, not `vercel dev`. It
  allow-lists query params and **appends** repeatable ones; comma-joining `subcategory` there
  would send one bogus slug that matches nothing, with a 200. Covered by
  `api/tests/test_proxy_path_allowlists.py`, not here.
- **The write path.** Nothing drives the enricher — whether the right slugs are *assigned* is
  `test_internal_enrichment.py`'s question.
- **Saved filters.** `user_saved_filters.subcategory` round-tripping is not covered. The obvious
  next case if this section grows.
- **Cursor paging under a subcategory filter.** Eleven rows never produce a second page.
  `test_jobs_search_contract.py` pins the fingerprint behaviour.
