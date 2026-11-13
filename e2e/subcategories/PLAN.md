# E2E gate — SWE subcategories (section 4)

**Status: BUILT AND RUN.** Written and executed 2026-09-16 against `feat/e2e-subcategories`,
cut from `origin/main` @ `6e3e526e` — all six epic PRs merged, the feature fully on main.
Real run results are in `CASES.md`; this file is the reasoning.

## What this gates

Software-engineering jobs now carry up to **2** subcategory slugs from a **17**-slug set, in
`job_listings.enrichment_subcategories` (`text[]`, nullable). The filter reaches SQL as

```sql
job_listings.enrichment_subcategories && %s::text[]
```

That one operator carries six behaviours the owner asked to see proven, and five of them can
break silently — a filter that returns too much looks exactly like a filter that works, until
you count.

---

## 0. TL;DR for anyone reading this next

| | |
|---|---|
| **Run it** | `e2e/run.sh subcategories` (measured 79–96 s) · `--fast` skips the browser tier (measured 10 s) |
| **Cost** | **$0, unconditionally.** No LLM call, no Browserbase session, no network beyond its own stack. There is no `--live` and no opt-in that changes this. |
| **Ports** | backend `8203`, frontend `3203`. `8000`/`8100`/`3000` are the owner's; `8201`/`3201` are add-companies + live-view; `8202` is add-companies' short-lived flagged backends. |
| **Database** | **its own** — `jobscraper_e2e_subcategories`, schema-only, ~17 s and ~110 MB to provision |
| **Nothing starts red** | every case was green on a real run, and two deliberate code mutations were used to prove they bite (§6) |
| **The one surprising decision** | this section does **not** use the 46k-job corpus every other section uses. §2. |

---

## 1. Where it sits in the convention

`add-companies/PLAN.md` §1's three rules, applied:

1. **A directory under `e2e/` named after the skill section.** `e2e/subcategories/` owns its
   `PLAN.md`, `CASES.md`, `fixtures.py`, `seed.py`, `env.subcategories`, `run.sh`,
   `playwright.config.ts`, `api/` and `ui/`.
2. **Anything reusable belongs in `e2e/shared/` — generalise, do not fork.** This section needed
   a second stack, and rather than copying `stack_up.sh` it **parameterised** it. §3.
3. **The skill gains a section file, not a new skill.**
   `.claude/skills/e2e-gate/sections/subcategories.md`.

```
e2e/subcategories/
├── PLAN.md                  # this file
├── CASES.md                 # the case table, with REAL run results
├── fixtures.py              # the eleven-row corpus — ONE source of truth for both tiers
├── seed.py                  # writes it; also the reveal-flag switch
├── env.subcategories        # the only env this section's backend reads
├── run.sh                   # stack up -> seed -> pytest -> playwright -> down
├── playwright.config.ts
├── api/                     # pytest — the SQL/route truth
│   ├── conftest.py
│   ├── test_taxonomy.py             # SC-00
│   ├── test_parent_category.py      # SC-01
│   ├── test_single_subcategory.py   # SC-02
│   ├── test_composition.py          # SC-03
│   ├── test_full_stack_widening.py  # SC-04
│   ├── test_reveal_flag.py          # SC-05
│   └── test_null_vs_empty.py        # SC-06
├── ui/                      # Playwright — only what a person can see
│   ├── corpus.ts            # reads fixtures.py --json; re-declares nothing
│   ├── helpers.ts           # the section's signed-in fixture + the tree-control driver
│   ├── parent-category.spec.ts      # SC-01
│   ├── single-subcategory.spec.ts   # SC-02
│   ├── composition.spec.ts          # SC-03
│   ├── full-stack-widening.spec.ts  # SC-04
│   └── reveal-flag.spec.ts          # SC-05
└── artifacts/               # gitignored
```

---

## 2. The one real departure: this section seeds, it does not clone

Every other section runs on `jobscraper_e2e`, a full `pg_dump | pg_restore` of
`jobscraper_pr243` — 46,145 OPEN jobs, 725 MB of `job_listings`. `add-companies` needs that,
and the reason is specific: AC-06 compares a discovered board's title set against every
published company's, so an empty seed makes it vacuous.

**This section needs the opposite, and the numbers say so.** Measured on the source database
before writing a line:

| | |
|---|---|
| OPEN jobs | 46,145 |
| ...with `enrichment_category = 'software_engineering'` | **3** |
| ...carrying a subcategory array | **0** — the column does not exist at that revision |

The corpus contributes nothing to any question this section asks. It is not neutral either: a
46k-row table means every assertion has to be scoped to something, exact-set comparison becomes
impossible, and "only the jobs carrying that slug" degrades into "at least the jobs carrying
that slug" — which is the assertion that cannot catch a filter returning too much.

So: `ensure_db.sh --schema-only`, a new mode that clones the SCHEMA plus six small dimension
tables (`alembic_version`, `job_categories`, `job_levels`, `locations` and the two alias
tables), then runs the same `alembic upgrade head` and the same `_scrub.py` the full mode
does. `job_subcategories` is deliberately *not* copied — migration `5a7d3e9c1b46` seeds all 17
rows itself, and copying them would create a second, staler source for the same data.

**Measured: 20 s and ~110 MB, versus minutes and ~760 MB.** Both modes end at the same
migration head with the same seeded taxonomy.

On top of that, `seed.py` writes **eleven** rows across two companies. Every one exists because
a case would be weaker without it — the table in `fixtures.py` gives the reason per row.

### Why raw SQL rather than the product's own write path

`add-companies` §8 forbids hand-written DML: a test there must mutate through the endpoints,
because those endpoints are what it tests. The write path for this column is the **enricher**,
reaching it over `POST /api/internal/enrichment/results` behind an internal key. Driving that
would make every case here depend on the enricher's contract in order to assert something about
the **reader's** SQL. The column, not the writer, is this section's subject.

So the seeding is raw SQL, fenced two ways: `assertions.connect()` refuses any database but
this section's, and every statement is scoped to `source_id = 'e2e_subcategories'` or to the
two fixture company ids. Nothing here can touch a row it did not write.

---

## 3. The stack — and what had to be generalised to get one

Ports `8203`/`3203`, database `jobscraper_e2e_subcategories`, env `env.subcategories`, pidfiles
under `e2e/subcategories/.pids/`. It reuses `e2e/shared/stack/e2e_app.py` **unchanged** — same
one patched seam (`api.auth.jwt._get_jwks_client`), same boot guards.

Rule 2 says generalise rather than fork, and five shared files were written with `8201`/`3201`/
`jobscraper_e2e` baked in. Each gained a parameter **whose default is the value that shipped**,
so `add-companies` and `live-view` are byte-for-byte unaffected:

| File | What became a parameter | Default |
|---|---|---|
| `shared/stack/stack_up.sh` | ports, env file, pidfile dir, target DB, schema-only, vite config | 8201/3201, `env.e2e`, `.pids`, `jobscraper_e2e`, off |
| `shared/stack/stack_down.sh` | pidfile dir (`E2E_PID_DIR`) | `.pids` |
| `shared/stack/vite.e2e.config.ts` | listen port + proxy target | 3201 → 8201 |
| `shared/stack/e2e_app.py` | expected database (`E2E_EXPECTED_DB`) | `jobscraper_e2e` |
| `shared/db/ensure_db.sh` | `--target-db`, `--schema-only` | `jobscraper_e2e`, full clone |
| `shared/db/assertions.py` | expected database | `jobscraper_e2e` |
| `shared/playwright/playwright.config.ts` | `FRONTEND_BASE_URL` | `:3201` |
| `shared/playwright/fixtures.ts` | backend base URL | `:8201` |
| `e2e/write_summary.py` | `--section`, for the heading | `add-companies` |

**Env vars, not flags**, and that is deliberate: the same five values have to reach four
processes `run.sh` does not invoke directly — vite's config, Playwright's config, pytest's
conftest, and the backend. An env var crosses all four boundaries; a flag would need re-plumbing
at each.

**Two new guards came with the parameterisation**, because a knob is also a way to point a gate
somewhere it must never go:

* `stack_up.sh` refuses to start on `8000`, `8100` or `3000` — the owner's stack. Without this,
  a fat-fingered port would not just collide: `stack_down.sh` would then kill his dev server by
  pidfile on the way out.
* `ensure_db.sh` and `e2e_app.py` both refuse any database name that is not `jobscraper_e2e` or
  `jobscraper_e2e_<something>`. `ensure_db.sh` DROPs its target on `--refresh`, so the target is
  exactly the name that has to be fenced.

### Its own run lock, keyed on the section

`live-view` takes *the same* lock as `add-companies`, correctly — it shares that stack. This
section shares nothing, so a shared lock would only mean the two gates could never run at once
for no reason. Its lock is keyed on repo path **and** section name: it can run alongside
`add-companies`, never alongside a second copy of itself (which would reseed the fixtures out
from under the first run's assertions). Like the others, it lives under `$TMPDIR` — `vercel dev`
watches the repo root and a lock directory churning under it has taken the owner's dev server
down before.

---

## 4. Tiers — and one case that deliberately has no UI half

The rule from `add-companies/PLAN.md` §3 stands: **if the UI does not render a fact, the UI test
must not claim it.**

| Fact | Visible? | Tier |
|---|---|---|
| "Selecting Software Engineering still lists the unlabelled jobs" | **yes** — they are rows | API + UI |
| "Only jobs carrying that slug came back" | **yes** | API + UI |
| "Subcategory ANDs with level" | **yes** — the list shrinks | API + UI |
| "`full_stack` widening is one-way" | **yes** | API + UI |
| "The control is absent with the flag off" | **only** visible | UI (API asserts the endpoint + the ungated filter) |
| "`null` serializes as `null`, not `[]`" | **no** — the card renders both identically | **API only** |

SC-06 is the last row. `JobChipsSection` falls back to the category chip for a NULL array and
for an empty one alike, so there is no rendered difference to assert. It gets an API-tier case
and `CASES.md` says why, rather than a UI case that would pass whatever the wire did.

### What the UI tier had to work around

The Recent Jobs page has **no `data-testid` anywhere** — not on the filters, not on the list,
not on a job card. Checked, not assumed. So every handle is an ARIA role/name or one of the two
attributes the list publishes on purpose (`data-client-window`, `data-index`). Three mechanics
are load-bearing and live in `ui/helpers.ts` rather than inline:

1. **A parent row's accessible name is polluted by its chevron.** The expand `IconButton`'s
   `aria-label` sits inside the `MenuItem`, so the option's computed name is
   `"Software Engineering Expand Software Engineering"` and an exact-name match misses it.
   Hence the anchored regex.
2. **Collapsed children are not in the DOM.** The parent must be expanded first, and the
   *chevron* expands it — clicking the row toggles the checkbox instead.
3. **Filter edits are debounced 300 ms.** A DOM-only wait races a request that has not been
   sent, and reads the previous filter's rows as this one's. Every helper waits on the
   `/api/jobs/search` **response**.

And two facts about the list that decide how results can be asserted at all:

* **Signed in, always.** A signed-out Recent page caps the list at `SIGNED_OUT_JOB_LIMIT: 12`
  behind an overlay and turns paging off. Eleven rows fit under that today — which is exactly
  the kind of coincidence that silently becomes a truncated assertion when a twelfth row is
  added. The section uses its own signed-in fixture (not `shared/playwright/fixtures.ts`'s,
  whose company-sweeping is an add-companies concern).
* **A 2400px-tall viewport.** The list is window-virtualized, so only a screenful of rows is
  mounted. At the default 720px, "this title is absent" would be true of a row that merely had
  not scrolled into view — the assertion would pass for the wrong reason. 2400px mounts all
  eleven, which is what makes **exact title-set** comparison possible. `expectResults` also
  cross-checks the rendered titles against `data-client-window`, so a corpus that outgrows the
  viewport fails loudly instead of quietly checking a prefix.

---

## 5. Why every assertion is a set, not a count or a "contains"

The defect this feature invites is a filter that returns **too much** — an `OR` where an `AND`
belongs, a widening that became symmetric, a predicate that got dropped. All three produce a
superset, and all three pass "did my jobs come back?".

So: eleven rows, and every case compares an exact set against an expectation derived from
`fixtures.py` — including `expected_for_subcategory()`, which applies the widening **from the
fixture table** rather than by calling `expand_subcategories`. SC-04 is checking an
independently computed answer, not the code against itself.

Each case also carries a **decoy** seeded for it, and a **mirror** proving the decoy is
reachable under its own filter — so "absent" always means "the filter excluded it", never "the
row was never there".

| Case | Decoy | Mirror |
|---|---|---|
| SC-02 | `J-SECURITY` ({security}) absent under `mobile` | `?subcategory=security` returns it |
| SC-03 | `J-BACKEND-MID` (right slug, wrong level) absent under `+senior` | `?level=mid` returns it |
| SC-03 | `J-OTHER-BACK` (right slug, other company) absent under the primary scope | its own company returns it |
| SC-04 | `J-FRONTEND`/`J-BACKEND` absent under `full_stack` | each returns under its own slug |
| SC-06 | `J-NULL`/`J-EMPTY` absent under any active filter | present with no subcategory filter |

---

## 6. The cases were proven to bite

A gate that has only ever been green has not been tested. Two deliberate mutations were applied
to the code under test, the gate re-run, and the mutation reverted:

| Mutation | Result |
|---|---|
| `SUBCATEGORY_FILTER_EXPANSION` made symmetric (`full_stack → frontend, backend`) | **SC-04 RED on both tiers** — `test_sc04_full_stack_alone_stays_exact` and the UI's "Full Stack alone stays exact". The two `frontend`/`backend` cases stayed green, which is correct: the mutation does not affect them. |
| `JobListingResponse.subcategories` changed to `Field(default_factory=list)` | **SC-06 RED** — three of its six cases. (The endpoint 500s rather than returning `[]`, because pydantic rejects `None` for `list[str]`. The failure message names the request, which is what matters.) |

Both mutations were reverted and `git status` confirmed `src/backend/` clean before committing.

---

## 7. What this section does NOT cover

Stated plainly rather than implied:

* **The Vercel serverless proxy layer.** Same non-coverage as `add-companies` and for the same
  reason (`add-companies/PLAN.md` §2 "Trap 1"): the frontend runs under plain `vite dev` with a
  whole-`/api`-prefix proxy, not `vercel dev`. `api/jobs.ts` allow-lists query params and
  **appends** repeatable ones — comma-joining `subcategory` there would send one bogus slug that
  matches nothing, with a 200. That hop is not exercised here. It is covered by
  `api/tests/test_proxy_path_allowlists.py`.
* **The write path.** Nothing here drives the enricher. Whether the right slugs get *assigned*
  is `test_internal_enrichment.py`'s question; this section only asks what the reader does with
  them.
* **Saved filters.** `user_saved_filters.subcategory` (migration `c48b0f2e7d19`) round-tripping
  through the saved-filters API is not covered. It is the obvious next case if this section
  grows.
* **Cursor paging under a subcategory filter.** The fingerprint includes `subcategory` only when
  the filter is active (so existing cursors did not churn at deploy). Eleven rows never produce
  a second page, so the gate cannot observe it. `test_jobs_search_contract.py` pins it.
* **Coverage/rollout arithmetic.** The 90% number the reveal flag is flipped on is the admin
  page's business, not this gate's.

---

## 8. Re-runnability

* `ensure_db.sh` is idempotent — the database is provisioned once, then skipped. `--refresh-db`
  forces a re-clone.
* `seed.py` drops and rewrites its own eleven rows every time, and the API tier calls it
  **autouse before every test**. One case cannot leave state that changes another's answer.
* SC-05 turns the reveal flag off in the database. The API tier's autouse fixture puts it back;
  the UI spec has an `afterAll` that puts it back; and `run.sh` re-seeds between the two tiers.
  Three layers, because an order-dependent flag is green alone and the cause of a mystery
  failure in whatever runs after it.
* The stack tears down on failure and on Ctrl-C (`trap cleanup EXIT`), and an interrupted run is
  labelled **ABORTED**, not RED — see `SKILL.md`'s four verdicts.
