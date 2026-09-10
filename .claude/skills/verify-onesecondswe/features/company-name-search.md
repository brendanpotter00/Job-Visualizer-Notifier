# Company name search — `/add-companies` (`ROUTES.MY_COMPANIES`, flag-gated)

Type a company's **name** into the add box and get that company's job board. The same box
[`add-companies.md`](add-companies.md) covers accepts either a name or a careers URL; that
file owns the URL half, this one owns the name half. It is a separate feature because it
is a separate backend path — `POST /api/companies/search-by-name`, a paid Browserbase
Search behind it — and because it has its own gate with its own rules about what counts
as proof.

Page: `src/frontend/src/pages/MyCompaniesPage/`, box in
`src/frontend/src/components/my-companies/ResolveUrlForm.tsx:155` (labelled *"Company name
or careers page link"*). Flags: `VITE_CUSTOM_COMPANIES_ENABLED` on the frontend, backend
`CUSTOM_COMPANY_SOURCES_ENABLED=true` **and** `COMPANY_NAME_SEARCH_ENABLED=true`.

**A claim that this feature works is not supportable without a run of its suite.** Not
"the picker returns the right URL", not "I tried four companies by hand" — a run, printed,
with the case list it covered. The suite exists because a previous report of *"4 for 4,
live"* was false in four separate ways, each of which is now a mechanism rather than a
convention.

## Sub-features

- **The ATS-board channel** — the search resolves a real ATS token and the real ATS client
  answers with a job count; `candidates[].autoAddable` means we would add it without asking.
- **The already-published channel** — the name matches a company we already publish, said
  at SEARCH time rather than one press later. `matchKind` (`board` vs `name`) decides
  whether *"This isn't the same company"* is offered.
- **The careers-page channel** — no board, but a careers page we will vouch for. Offered
  only if it is job-list-shaped.
- **The honest dead end** — no board, no careers page, no published match. `Facebook` and
  `Poke` are recorded this way: offering *something* here is a worse answer than offering
  nothing, because the somethings on hand were `facebook.it` and a poke-bowl restaurant.
- **The name gate** — a stranger's board that merely contains the typed name must not
  suppress the answer (`IBM` → Harvey's Ashby board) or be handed over as it
  (`Meta` → Anthropic's and Cohere's).

## How to get to it (user POV)

Sidebar "Add Companies" (only when the flag is on), route `/add-companies`. Sign-in
required. Type a name — not a URL — into the box and press enter.

## Driving it with WebMCP

**There is no WebMCP tool for this surface.** None of the 14 tools on `window.__webmcp__`
touches Add Companies — it is a form-driven, search-backed pipeline, not a store or
endpoint the shim wraps — so this is the second drive in this skill (after `@live-view`)
that reaches the DOM directly. That is a limit of the tool surface, recorded rather than
worked around; every other convention is kept (`signedInPage`, `verify.playwright.config.ts`,
evidence into the run's artifacts dir).

Everything below is **$0** except the last row.

```bash
bash "$REPO/.claude/skills/verify-onesecondswe/helpers/name_search.sh"            # $0
bash "$REPO/.claude/skills/verify-onesecondswe/helpers/name_search.sh" --prove-it # $0
bash "$REPO/.claude/skills/verify-onesecondswe/helpers/name_search.sh" --live     # ~$0.27
```

| Entry point | Cost | What it does |
|---|---|---|
| `name_search.sh` | **$0** | `cases.toml` validity → `test_judge.py` dead-endpoint pins → re-judge a **recorded** green run → the `@name-search` drive |
| `name_search.sh --prove-it` | **$0** | re-judges every case against a dead endpoint and requires the run to go **red** |
| `--grep '@name-search'` | **$0** | the drive alone (needs `launch.sh` first) |
| `name_search.sh --live` | **~$0.27** | delegates to `e2e/run.sh company-name-search` — ~38–39 real Browserbase Search calls at $0.007 |

**The `@name-search` drive owns exactly one thing: the typed name reaches the endpoint
byte-identical.** That is the layer the gate structurally cannot see. `intent_test.py`
speaks HTTP straight to the endpoint and imports no service module — the rule that makes
it honest — so it composes the request body itself and can never observe what the *browser*
sends. A `.trim().toLowerCase()` added to the form tomorrow would re-open the original bug
with every case in `cases.toml` still green.

It drives `Databricks` (the already-published channel) and `Facebook` (the nothing-offered
channel), answering the endpoint from the committed recording so nothing is billed, and
asserts `POST /api/users/companies` is **never** issued — both auto-add branches
(`MyCompaniesPage.tsx:278`, `:327`) would otherwise write a real owned company into
`jobscraper_e2e`.

**The judging is not re-implemented here, on purpose.** `judge()` in `intent_test.py` is
the only judge. `--replay` re-runs it over stored response bodies, so all four rules below
are enforced for $0. Restating any of them in TypeScript is how they drift.

### The four rules a green run rests on

| Rule | What it stops |
|---|---|
| **`truth` provenance** — only `owner:<date>` and `measured:<doc>` count; anything else reports `PASS?` and never counts toward the pass line | Inventing the expectation. Oracle was scored correct for returning `oracle.com/careers/`, a marketing page, and had been failing the whole time. |
| **Job-list shape**, applied to the value recorded in `cases.toml` **and** to every value the endpoint returns | A brochure being written down as ground truth, or accepted as an answer for a company nobody has established one for. `oracle.com/careers/` and `careers.airbnb.com/` both fail it; `careers.oracle.com/en/sites/jobsearch/jobs` passes. |
| **The `vacuous` rule** — a case with no positive expectation FAILS when the endpoint answers nothing | Passing because nothing came back. `metabase`, `poke`, `gm` and `hp` once all reported PASS against a completely dead endpoint. |
| **`known_limitation`** — the case still runs, its reasons still print, but it sits on its own `known` line outside the `N/M` count | A gap we decided not to close being read as a regression that arrived today — and, in the other direction, being quietly forgotten. If it starts passing the run says **FIXED**. |

`citadel` currently carries the marker: the name gate accepts a host that merely *extends*
the typed name, so `Citadel` auto-adds `ashby:citadel-ai` (a Japanese AI company, 2 jobs).
It is **expected to fail today**, it stays visible on its own line every run, and it is
outside the `21/21`.

## Gotchas

- **Casing is an input, and nothing normalizes it.** The typed name reaches the search
  verbatim (`company_name_search.py:597`, `models.py:1299`). Measured twice each on
  2026-09-04: `Atlassian careers` ranks the right answer **2nd**; `atlassian careers`
  does not return it **at all**. Every case used to be capitalized, so the suite reported
  4/4 on a query no user ever makes while the owner failed 3/3 by hand. The `lowercase`
  tag now covers the five spellings people actually type. Add **both** spellings for
  anything whose canonical form is not what a person types.
- **`--prove-it` is not decoration.** Against a dead endpoint the suite must land on
  **2/21**, and the only two passing may be `facebook` and `poke` — the cases that
  explicitly expect silence. Any other number means an assertion has stopped asserting.
- **The recorded run is perishable.** `e2e/company-name-search/recorded/` holds one real
  paid run's stored bodies. It is the answer the endpoint gave on **2026-09-05**, not the
  answer it gives today — boards move (Poke's went live → 404 in 24 hours). A green replay
  proves the *judge* and the *plumbing*, never that the feature still works against the
  live web. Only `--live` proves that.
- **Re-record when `cases.toml` gains a case.** A case with no stored body is silently
  skipped by `--replay`, so the pass line would shrink without saying why.
- **Never wire the live run into CI or a commit hook.** It is a before-you-say-ready gate,
  run by a human or an agent on purpose. `--max-searches` is the whole invocation, not one
  run, so `--runs N` wants roughly `40*N`.
- **The drive is read-only and must stay that way.** If `POST /api/users/companies` ever
  fires, the spec fails on its own guard — but a row will already exist in `jobscraper_e2e`
  and `cleanup.sh` will need to sweep it.
- **Ground truth is perishable and the repo's docs disagree with each other.**
  `CAREERS-FALLBACK-POC.md` §Q3 optimises for landing pages *on purpose* and is in direct
  conflict with the owner's expectation; Cisco has three different "correct answers" across
  the docs. `cases.toml` follows the owner. Do not treat
  `docs/implementations/custom-company-sources/*.md` as an oracle.
