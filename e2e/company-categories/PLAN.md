# company-categories — e2e gate plan

Feature plan: `docs/implementations/company-categories/PLAN.md`. Cases: `CASES.md`.
Runbook: `.claude/skills/e2e-gate/sections/company-categories.md`.

## What it gates

The Company type filter end to end: the backend seeds `company_categories` and
`company_category_members` from `src/backend/api/data/company_categories.json` on boot, serves
them as facets, and filters `GET /api/jobs/search?company_category=` by membership; the SPA
shows a checkbox dropdown, the landing cards link to it, and Saved Filters stores a default.

The failure that matters is silent: a dropped param (proxy, router, a truthiness check on an
empty membership) comes back as an ordinary unfiltered 200. So every case asserts an exact set
and has a decoy.

## Shape

| | |
|---|---|
| Stack | own: backend `:8208`, frontend `:3208`, database `jobscraper_e2e_company_categories` (schema-only clone) |
| Ports | `:8208/:3208`, not `:8206/:3206`: `:8206` is the enricher's kill-switch backend |
| Cost | $0, unconditionally: no LLM, no Browserbase, PostHog blanked, the browser fenced to `127.0.0.1` |
| Auth | the SPA's auth switch is pinned in `env.company_categories` (a worktree has no `src/frontend/.env.local`); one reader identity, `e2e|company-categories-reader` |
| Fixtures | `fixtures.py`, nine rows at REAL member ids (Google, Apple, Stripe, ...) plus one decoy company in no type. The oracle (`COMPANY_TYPES`) is restated, and CC-00 checks it against the JSON |
| Seed | `seed.py`: rows + `companies` rows (`script` ats for real ids: never scraped) + clears the reader's saved filters. The membership tables are NOT seeded here; the backend owns them |

## Tiers

- API (`api/`, pytest, anonymous): CC-00 to CC-05. `--fast` runs only these.
- UI (`ui/`, Playwright): CC-U1 to CC-U5.

## Non-coverage

- The Vercel proxy (`api/jobs.ts`'s `company_category` entry): the stack runs plain `vite dev`,
  the same gap as every section. Covered by `jobs.serverless.test.ts`.
- The onboarding question lives in the `onboarding` section (OB-10, OB-U1, OB-U18).
