---
name: e2e-gate
description: >
  Regression gate that runs before any agent says "ready to test" on a feature
  that has an e2e/ section — starting with Add Companies. Lists sections and
  dispatches; per-section detail lives in sections/<name>.md. Use when about
  to claim a change to a gated feature is ready, before opening a PR that
  touches gated files, or when the user says "run the e2e gate" / "e2e-gate".
---

# e2e-gate

A **regression gate**, not a demo. If it goes green and the feature is still broken, the
suite failed. Read `e2e/README.md` for the section list and the shared-infra layout.

## When to run this

- Before any message containing "ready to test".
- Before opening a PR that touches a file a section's runbook names as gated.
- Whenever you are about to claim a change to a gated feature works.

## How to run it

```bash
e2e/run.sh <section>              # full gate — required before "ready to test"
e2e/run.sh <section> --fast       # cheap subset — run on every commit
e2e/run.sh <section> --case AC-06 # one case, for a fix loop
```

Node 22.14.0 via nvm is required (`export PATH="$HOME/.nvm/versions/node/v22.14.0/bin:$PATH"`
if `node -v` isn't already 22.12+) — older Node hangs frontend tooling silently. `run.sh`
attempts this itself but a pre-set `PATH` wins.

## Sections

| Section | Runbook |
|---|---|
| `add-companies` | `sections/add-companies.md` |

Adding a section: create `e2e/<section>/` (its own `PLAN.md`, `CASES.md`, `api/`, `ui/`),
add a row here and to `e2e/README.md`, and write `sections/<section>.md`. Never grow
per-feature detail in this file.

## One run at a time

`run.sh` takes an exclusive run lock. If a gate is already in flight it **refuses to start**
(`REFUSING TO START — another e2e run (pid N) is already in flight`, exit 2) rather than
starting anyway. That refusal is correct behaviour, not a failure: two runs share one stack
(`:8201`/`:3201`) and one pidfile directory, so the second one used to kill the first
mid-test and make it report a screenful of failures it never had. Wait for the other run, or
stop it. A lock whose owning process is genuinely gone is reclaimed automatically, with a
line saying so.

## What green means

`run.sh` writes `e2e/<section>/artifacts/<run>/summary.md` and `summary.json` every run.
**Green = every collected case PASS, zero FAIL, zero BLOCKED.** Read `summary.md` first — its
last line is the verdict, and there are four:

| Verdict | Meaning |
|---|---|
| **GREEN** | Every collected case passed. This is the only green. |
| **RED** | At least one case failed — or zero cases were collected, which means nothing ran and nothing was proved (usually the stack failing to boot; read `stack/backend.log`). |
| **BLOCKED** | A live board was unreachable at preflight. Not a code regression — but those cases did not run, so it is **not** green either. |
| **ABORTED** | The run was interrupted (Ctrl-C, harness timeout, SIGTERM) before finishing. The stack was torn down under the running suite, so cases after that point failed on a dead backend, not on their own assertions. **This is not a red gate — it is no result. Re-run it.** |

Never read an ABORTED run's case table as a list of regressions, and never quote its
PASS/FAIL counts as a result.

## What to do with a red

**Read the failing case's artifact directory before changing code.** Every run writes
`e2e/<section>/artifacts/<run>/cases/<case>/step.txt` naming the exact step that failed, in
words — not just an assertion dump. UI failures also get a screenshot and a Playwright trace
under the same run's `ui/` output. Re-run just that case with `--case AC-XX` once you have a
theory.

**If the failure is in code a section's runbook marks as "not yours to fix"**: report it,
do not fix it there, and do not weaken the test to make it pass. A test bent to fit a bug is
worse than no test — see the section runbook for exactly which files that applies to.
