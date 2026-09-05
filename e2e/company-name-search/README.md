# company-name-search — the intent test

**Type a company name into the add box, get that company's job board.** This gate says
whether that works, for a curated list of names, end to end, at the outermost layer.

> **A claim that this feature is done is not supportable without a green run of this
> suite.** Not "the picker returns the right URL", not "I tried four companies by hand" —
> a green run, printed, with the case list it ran.

```bash
e2e/run.sh company-name-search                       # everything (~38 searches, ~$0.27, ~60s)
e2e/run.sh company-name-search --case oracle         # one case (repeatable flag)
e2e/run.sh company-name-search --tag careers         # one slice
e2e/run.sh company-name-search --runs 2 --max-searches 90   # flakiness: 2/2 or it is FLAKY
e2e/run.sh company-name-search --max-searches 10     # hard spend ceiling
```

Free, spends nothing:

```bash
.venv/bin/python e2e/company-name-search/intent_test.py --validate-only
.venv/bin/python e2e/company-name-search/intent_test.py \
    --replay e2e/company-name-search/artifacts/<run>/results.json
.venv/bin/python -m pytest e2e/company-name-search/test_judge.py -q
```

`--replay` re-judges a previous run's **stored response bodies**. Every assertion change
should be checked this way first — it costs $0 instead of another $0.27.

`test_judge.py` judges a **dead endpoint** — `{"candidates": [], "careersUrl": null}` —
against every case in the file, and pins the one invariant that cannot be checked any
other way: *the only cases a dead endpoint may pass are the ones that explicitly expect
silence*. It needs no backend and no key.

## This costs real money

Every case spends at least one **Browserbase Search** call at **$0.007**, and a second one
whenever the careers fallback fires. A full run is ~38 searches ≈ **$0.27**. The runner
prints the count and the dollar figure, and refuses to start a case it cannot pay for
under `--max-searches` (default 60).

**`--max-searches` is the whole invocation, not one run.** `--runs N` multiplies the bill,
so raise it to about `40*N` or the last cases are SKIPPED — and a skipped case is not a
passing case, so the run reports red for a reason that is only about money.

**Never wire this into CI, a pre-commit hook, or anything that runs per push.** It is a
before-you-say-ready gate, run by a human or an agent on purpose.

## Adding a case

One line in [`cases.toml`](cases.toml), never Python:

```toml
zalando = { input = "Zalando", careers_url = "https://jobs.zalando.com/en/jobs", truth = "owner:2026-09-10", tags = ["careers"] }
```

The file's own header documents every key. Four of them are load-bearing:

- **`truth`** — where the expected value came from. Only `owner:<date>` and
  `measured:<doc>` count. Anything else still runs but reports **`PASS?`
  (unverified-truth)** and never counts toward the pass line.
- the URL must be **job-list-shaped**, or the file refuses to load.
- **say what a RIGHT answer is, not only what a wrong one is.** A case asserting only
  `must_not` is judged **`vacuous`** and fails when the endpoint answers nothing at all —
  there is no answer for `must_not` to look at, so it would otherwise pass by default.
  Add `must_answer = true`, or `nothing = true` if silence really is the right answer
  here (`facebook`, `poke`).
- **`known_limitation = "why"`** — this case is expected to fail today. It still runs and
  its reasons still print in full; it moves out of the `N/M passing` line onto its own
  `known` line, so a gap we have decided not to close is not confused with a regression.
  If it starts passing the run says **FIXED** and tells you to delete the marker.

## What "correct" means, and why a marketing page cannot fake it

The endpoint answers on exactly three channels, and each has its own proof:

| Channel | How a case pins it | Why it cannot be faked |
|---|---|---|
| ATS board (`candidates[].autoAddable`) | `board = "workday:ebay"`, `min_jobs = 200` | needs a resolved ATS token **and** a live job count from the real ATS client. A web page has neither. |
| already published (`alreadyPublic`) | `already_public = "databricks"` | a company id from our own table. |
| careers page (`careersUrl`) | `careers_url = "https://…"` (exact) or `careers_host` (weaker, labelled) | exact match against reviewed truth **and** the job-list shape rule below. |

**The job-list shape rule is the anti-Oracle mechanism.** A careers URL must have a path
segment that is a list word — `jobs`, `jobsearch`, `all-jobs`, `openings`, `positions`,
`search` — or sit on a `jobs.*` / `job-boards.*` host. It is applied in **both** directions:

- to the value **recorded in `cases.toml`** — so `oracle.com/careers/` cannot be written
  down as ground truth. The file fails to load.
- to the value the endpoint **actually returns**, globally, on every case — so a brochure
  cannot be accepted as an answer even for a company nobody has established the truth for.

Measured against this corpus it separates cleanly:

| passes | fails |
|---|---|
| `careers.oracle.com/en/sites/jobsearch/jobs` | `www.oracle.com/careers/` |
| `atlassian.com/company/careers/all-jobs` | `www.atlassian.com/company/careers` |
| `github.careers/careers-home/jobs` | `amd.com/en/corporate/careers.html` |
| `careers.amd.com/careers-home/jobs` | `careers.airbnb.com/` |
| `jobs.sap.com/?locale=en_US` | `jpmorganchase.com/careers/explore-opportunities/programs` |

### Why there is no live "does this page have jobs on it" probe

It was tried and measured, and it does not work. Fetched plain:

| URL | text after stripping scripts |
|---|---|
| `careers.oracle.com/en/sites/jobsearch/jobs` — **the correct answer** | **6 chars** (empty SPA shell) |
| `www.oracle.com/careers/` — the marketing page | 403 |
| `atlassian.com/company/careers` — **the wrong answer** | **27,737 chars** |
| `atlassian.com/company/careers/all-jobs` — the right one | 5,175 chars |

A content probe would have inverted several cases. The structural rule separates the same
corpus, costs nothing, and cannot be wrong about network weather.

## Non-determinism

Browserbase Search results vary between calls. `--runs N` repeats every case; anything
short of N/N reports **FLAKY**, never PASS. Use it before believing a green run —
Atlassian passed 3/3 in one sitting while the owner watched it fail.

### Casing is an input, and it changes the results

That Atlassian split was not flakiness. The typed name reaches the search **verbatim** —
nothing normalizes it, frontend included — and the two spellings return different result
sets. Measured 2026-09-04, twice each:

| second-search query | `atlassian.com/company/careers/all-jobs` |
|---|---|
| `Atlassian careers` — what this suite used to send | **rank 2**, 2/2 |
| `atlassian careers` — what the UI sends | **absent from all 25 results**, 2/2 |

Every case here was capitalized and nobody types that way, so the suite reported 4/4 on a
query no user ever makes. The `lowercase` tag now covers the five spellings people
actually type. **Add both spellings for anything whose canonical form is not what a
person types** — an acronym (`IBM`), an intercapital (`eBay`), a brand people lowercase.

## Four mistakes this is built to prevent

1. **Testing the wrong thing.** A previous check called `pick_careers_url` directly. The UI
   calls `POST /api/companies/search-by-name`, which runs a probe phase, a 20s budget, a
   published-company check and `_careers_fallback` before the picker is reached. This
   harness only ever speaks **HTTP to the real endpoint**; it imports no service module and
   never may.
2. **Inventing the ground truth.** Oracle was scored correct for returning
   `oracle.com/careers/`. It had been failing the whole time. Hence `truth`, hence the
   shape rule, hence the `weak` line in the summary that names every case resting on a
   host-only or negative-only check.
3. **Printing a failure that looks like a pass.** Oracle later failed on a query string
   — the returned URL and the expected one were identical for 57 characters, so both
   columns showed the same clipped prefix and the row read as correct with the word
   FAIL beside it. The ACTUAL column is now clipped **against the expectation**
   (`_clip_diff`), so the window moves to where the two part, and every non-passing
   case is repeated in full under a **`WHY:`** block below the table.
4. **Passing because nothing came back.** `must_not` is checked against what the user is
   *offered*, so a case that asserts only `must_not` was satisfied by an endpoint that
   offered nothing: `metabase`, `poke`, `gm` and `hp` all reported PASS against
   `{"candidates": [], "careersUrl": null}` — a dead endpoint would have printed **4 of
   21 passing**. `judge()` now fails any case with no positive expectation against an
   answer of nothing, and `test_judge.py` pins the invariant for every case in the file,
   including ones added later.

## Ground truth is perishable, and the docs disagree with each other

Do not treat `docs/implementations/custom-company-sources/*.md` as an oracle:

- **`CAREERS-FALLBACK-POC.md` §Q3 optimises for landing pages on purpose** — it scores "top
  hit is a single job posting" as a *defect* and rejects a query wording *because* it
  returned real job-listing pages. That is the design decision that produces
  `oracle.com/careers/`, and it is in direct conflict with the owner's expectation. The
  conflict is real and lives in the picker, not in this harness.
- **Cisco has three different "correct answers"** across the docs:
  `cisco.wd5.myworkdayjobs.com/Cisco_Careers`, `careers.cisco.com/global/en`, and
  `jobs.cisco.com`. `cases.toml` follows the owner.
- **Poke's board went from live to HTTP 404 in 24 hours.** A stale expectation looks
  exactly like a regression. That is what the dated `truth` field is for.

## Stack

`run.sh` boots the **real** `api.main:app` on `:8202` against `jobscraper_e2e` (154 seeded
public companies — the published-match cases need them) via `stack_app.py`, which patches
exactly one seam: `api.auth.jwt._get_jwks_client`, so a token minted by
`e2e/shared/auth/mint.py` validates. `jwt.decode` still enforces algorithm, audience,
issuer, expiry and the email claim for real.

Its guards, which differ from the add-companies gate's on purpose:

| Guard | Add-companies gate | Here |
|---|---|---|
| `BROWSERBASE_API_KEY` | must be **blank** | must be **present** — it is the feature |
| `CAPTURE_USE_BROWSERBASE` | must be false | must be false — **searches yes, browser hours never** |
| database | `jobscraper_e2e` | `jobscraper_e2e` (read-only; this endpoint writes nothing) |

The key is read from the repo-root `.env.local` at launch and exported to the child process
only. It is never printed and never written to an artifact.

To point the harness at some other backend instead (e.g. the owner's `:8000` with a real
token):

```bash
NAME_SEARCH_TOKEN=<jwt> .venv/bin/python e2e/company-name-search/intent_test.py \
    --base-url http://127.0.0.1:8000
```

## Artifacts

`artifacts/<run-id>/` holds `summary.txt` (what was printed), `results.json` (every
response body, replayable) and `backend.log`. Gitignored.
