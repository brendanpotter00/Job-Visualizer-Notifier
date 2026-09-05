# e2e-gate section: company-name-search

The **intent test** for "type a company name into the add box, get that company's job
board". Full detail lives in `e2e/company-name-search/README.md`; this file is the
dispatch card.

## Run it

```bash
e2e/run.sh company-name-search                    # the gate — required before "ready to test"
e2e/run.sh company-name-search --case oracle      # one case, for a fix loop (repeatable)
e2e/run.sh company-name-search --tag careers      # one slice
e2e/run.sh company-name-search --runs 3           # flakiness check: 3/3 or FLAKY
```

Free, spends nothing:

```bash
.venv/bin/python e2e/company-name-search/intent_test.py --validate-only
.venv/bin/python e2e/company-name-search/intent_test.py --replay e2e/company-name-search/artifacts/<run>/results.json
```

## THIS ONE COSTS MONEY

~30 Browserbase Search calls ≈ **$0.21** per full run, at $0.007 each. The run prints the
count and refuses to exceed `--max-searches` (default 40).

**Never put it in CI, a pre-commit hook, or anything per-push.** Before changing an
assertion, `--replay` the last run's stored bodies instead of paying for a new one.

## When to run it

- Before any message containing "ready to test" about company-name search.
- Before opening a PR that touches any of the gated files below.
- **Any time you are about to say this feature works.** A count of companies you tried by
  hand is not a result; a printed `N/M passing` line is.

## Gated files

Changing any of these requires a run:

- `src/backend/api/routers/companies.py` (`search_company_by_name`, `_probe_shown`,
  `_careers_fallback`, `_published_candidate`)
- `src/backend/api/services/company_name_search.py`
- `src/backend/api/services/careers_page_pick.py`
- `src/backend/api/services/company_name_match.py`
- `src/backend/api/services/published_board_match.py`
- `src/backend/api/services/custom_companies_service.py`

## What green means

Only `N/N passing` is green. Every other verdict is not:

| Verdict | Meaning |
|---|---|
| **PASS** | held across every run, on an expectation someone actually established |
| **FAIL** | wrong on every run |
| **FLAKY** | right on some runs, wrong on others. **Not a pass.** Search results vary between calls; a suite that hides that is worse than none |
| **ERROR** | the endpoint 503'd or the request failed. Not a wrong answer, and not a pass either |
| **PASS?** | correct, but the expectation is unverified (`truth` is not `owner:` or `measured:`). Never counted |

Also read the **`weak`** line. It names every passing case that rests only on a host match
or a "must not return X" check — those are real, but they are not the same evidence as an
exact answer, and a suite made mostly of them is not proof the feature works.

## Adding a case

One line in `e2e/company-name-search/cases.toml`. Never in Python. The header of that file
documents every key. Two rules the loader enforces before a cent is spent:

- **`truth` is required** and only `owner:<date>` / `measured:<doc>` counts as verified.
- **a recorded `careers_url` must be job-list-shaped.** You cannot write `oracle.com/careers/`
  down as ground truth — that is exactly how Oracle was once scored as a pass while it was
  failing.

## Not yours to fix

`careers_page_pick.py`, `company_name_search.py` and `routers/companies.py` are product
code. If a case goes red there, **report it — do not weaken the case to make it pass.** In
particular, do not relax the job-list shape rule to accept a marketing page: that rule is
the entire reason this suite catches what the last one missed. Changing it is a deliberate
decision, in a commit of its own, with the corpus in `README.md` re-checked.
