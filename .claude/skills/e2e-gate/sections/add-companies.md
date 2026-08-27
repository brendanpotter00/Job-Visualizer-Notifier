# Add Companies — e2e gate runbook

Full design/reasoning: `e2e/add-companies/PLAN.md`. Live case status + known drift:
`e2e/add-companies/CASES.md`. This file is the "sub-skill": what each case proves, how to
run just it, and what to look at first when it goes red.

## Run it

```bash
e2e/run.sh add-companies              # full gate, ~8-14 min, a few live LLM calls
e2e/run.sh add-companies --fast       # ~1-2 min, $0 — run on every commit
e2e/run.sh add-companies --case AC-06 # one case, for a fix loop
```

## When to run this gate

Before claiming "ready to test" on anything touching: `routers/user_companies.py`,
`routers/companies.py` (resolve), `services/custom_companies_service.py`,
`services/ats_link_resolver.py`, `services/ats_discovery.py`, `services/capture/**`,
`services/careers_host_match.py`, `services/published_board_match.py`,
`services/harvest_verification.py`, `tasks/discover_custom_company.py`,
`tasks/fetch_custom_company.py`, `tasks/claim_custom_companies.py`, or
`src/frontend/src/{pages/MyCompaniesPage,components/my-companies}/**`.

## Files this suite does NOT own — report bugs there, don't fix them here

`src/backend/api/main.py`, the worker/queue config, `tasks/discover_custom_company.py`,
`services/capture/**`, `routers/user_companies.py`, `services/custom_companies_service.py`,
`services/ats_link_resolver.py`, `tasks/fetch_custom_company.py`,
`services/published_board_match.py`, and the add-flow frontend. If a case fails because of a
bug in one of these, the case is doing its job — report the bug, don't patch the test to
match it.

## Per-case reference

| ID | Proves | Known-red? | First thing to check on red |
|---|---|---|---|
| AC-01 / AC-02 | A board we already publish (Microsoft/Amazon, `ats='script'`) resolves to `already_public` and creates nothing | No — green | `company_add_attempts.resolved_ats` for the latest row; a regression here usually means `careers_host_match.py`'s table or its wiring in `user_companies.py` moved |
| AC-03 | Cisco resolves as embedded Workday, requires an explicit confirm, harvests on the RESERVED interactive queue | No | `procrastinate_jobs` for `queue_name='custom_ats_first_fetch'` vs `'custom_ats_fetch'` — a regression here means the first-harvest enqueue seam moved queues |
| AC-04 / AC-05 | One-time discovery + first harvest for boards with no posted-date field (Atlassian, Jane Street) | No | `discovery.steps` in the row's JSON — which of the 5 rungs is not `done`/`failed` |
| AC-06 | The title-overlap suggestion after Spotify's discovery, and the no-merge guarantee | **Shipped red at plan time** (§11.2: the trigger required a VERIFIED harvest, which a whole-board-in-one-request capture can never reach) — **the fix landed mid-build**; verify current status in `CASES.md` before assuming either way | `provider_config->'public_match'` on the discovered row; if absent, check whether `tasks/fetch_custom_company.py`'s trigger regressed back to `graduated_this_run`/VERIFIED-only |
| AC-06a | Same matcher, hermetic — proves the matcher itself even on a day AC-06 is red | No | Only the matcher's threshold constants (`OVERLAP_THRESHOLD`/`MIN_TITLE_SET`/`MIN_SHARED_TITLES`) or its `shared/max` denominator could break this |
| AC-07 | Delete purges everything (company, script, jobs, harvests) and leaves state clean for an immediate re-add | No | `job_listings WHERE source_id='custom:<id>'` count after delete; `ownerlessCount` DELTA, never the absolute value (baseline is not 0) |
| AC-08 | The full human journey in a real browser | No | Playwright trace for the run; the polling trap (a settled list stops auto-refreshing) is handled, so a hang here is a real regression, not a test bug |
| AC-09 | Both flags gate what they claim to gate, cleanly | No | Which of the two short-lived flagged backends (:8202) failed to boot — check its inline log in the test failure |
| AC-10 | User B cannot see, read, or delete user A's company | No | 403 vs 404 — a 404 on the jobs read (instead of 403) or a 200 on delete would be the leak |
| AC-11 | Re-adding an already-discovered board is free (no second row, no second LLM call) | No | `procrastinate_jobs` count for `queue_name='custom_discovery'` before/after the re-add |
| AC-12 | `trackAnyway` survives the dedupe and creates a real private copy via discovery | No (green once AC-01 landed) | Same checklist as AC-04/05 — this IS a discovery run, not a static clone |

## Known non-coverage

- The Vercel serverless proxy layer (`api/users.ts`, `api/companies.ts`, `api/jobs.ts`) is
  not exercised — the suite runs the frontend under plain `vite dev`, not `vercel dev`
  (`e2e/add-companies/PLAN.md` §2 "Trap 1").
- Hermetic replay of discovery does not exist — AC-03/04/05/06 are genuinely live every run.
