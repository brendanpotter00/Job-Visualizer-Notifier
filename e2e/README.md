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

Adding a section = one directory under `e2e/` (its own `PLAN.md`, `CASES.md`, `api/`, `ui/`),
one file under `.claude/skills/e2e-gate/sections/`, one row above. See
`add-companies/PLAN.md` §1 for the three-rule convention.

## Non-negotiables (every section)

- Its own backend/frontend/DB — never the owner's `:8000`/`:8100`/`:3000` stack.
- `CAPTURE_USE_BROWSERBASE=false` and a blank Browserbase key, asserted at boot.
- Re-runnable back to back with no manual reset.
- A third-party outage reads as **BLOCKED**, never as a code regression (PASS/FAIL/BLOCKED,
  never a silent pass-or-fail binary).
