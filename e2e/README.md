# e2e — regression gates

Runs **before** any agent says "ready to test" (see root `CLAUDE.md` and
`.claude/skills/e2e-gate/SKILL.md`). Each subdirectory under `e2e/` is a **section** — one
feature area's end-to-end gate. `e2e/shared/` is feature-agnostic infrastructure every
section reuses: the stack (backend/frontend/DB), auth (mint a real token against a patched
JWKS seam), DB helpers, and the Playwright base config.

```
e2e/run.sh <section> [--fast] [--case AC-06] [--refresh-db]
```

## Sections

| Section | What it gates | Runtime (full / `--fast`) | Cost |
|---|---|---|---|
| `add-companies` | Add Companies (E7): careers-URL resolve, ATS add, one-time discovery, delete/purge, flags, ownership isolation, idempotency, the published-board-match suggestion | ~8 min full (measured; see PLAN.md report) / ~1 min `--fast` | a few live discovery calls to Claude Haiku on the full run; $0 on `--fast` |
| `company-name-search` | **Type a company name, get its job board** — the intent test over `POST /api/companies/search-by-name`, against a curated case list. See `company-name-search/README.md` | ~30 s full (measured) | **~30 live Browserbase Search calls ≈ $0.21 per run.** Prints the count; `--max-searches` caps it; `--replay` re-judges for $0 |

Adding a section = one directory under `e2e/` (its own `PLAN.md`, `CASES.md`, `api/`, `ui/`),
one file under `.claude/skills/e2e-gate/sections/`, one row above. See
`add-companies/PLAN.md` §1 for the three-rule convention.

## Non-negotiables (every section)

- Its own backend/frontend/DB — never the owner's `:8000`/`:8100`/`:3000` stack.
- `CAPTURE_USE_BROWSERBASE=false`, asserted at boot. Browser hours are the expensive
  line and no section may ever bill one.
- A blank Browserbase key, asserted at boot — with ONE deliberate exception.
  `company-name-search` tests the feature whose first step *is* a paid Browserbase
  Search call, so it requires the key and asserts its presence instead. It still
  refuses to boot with `CAPTURE_USE_BROWSERBASE=true`, so it can bill searches
  ($0.007 each, counted and printed) and can never bill a browser hour. It carries
  its own guards in `company-name-search/stack_app.py` rather than weakening
  `e2e/shared/stack/e2e_app.py`, which protects the far more frequently run gate.
- Re-runnable back to back with no manual reset.
- A third-party outage reads as **BLOCKED**, never as a code regression (PASS/FAIL/BLOCKED,
  never a silent pass-or-fail binary).
