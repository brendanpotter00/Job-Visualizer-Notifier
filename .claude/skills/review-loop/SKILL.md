---
name: review-loop
description: |
  Iteratively review-and-fix a PR or branch until it converges. A main
  orchestrator thread spawns fresh-context Opus review subagents (the
  pr-review-toolkit suite + the prod verifiers), collects their findings into a
  durable REVIEW_LOOP_LOG.md, spawns a fresh fix subagent to resolve every
  Critical/Important issue (committing once per round), then spawns brand-new
  review subagents to re-review with zero memory of the prior round. The loop
  runs until TWO consecutive clean rounds (no Critical/Important findings) or a
  6-round hard cap. A Decision Ledger + an oscillation guard prevent the
  classic A→B→A infinite revert cycle (one agent makes change A, the next flags
  A and reverts to B, repeat forever). After the loop converges it ALWAYS starts
  the local dev environment and drives a Playwright end-to-end smoke + feature
  verification in a real browser, treating any broken flow as a fresh Critical
  finding that re-enters the fix loop. Use when the user says "review loop",
  "review and fix until clean", "iterate the review", or wants a PR/branch
  driven to a clean review without babysitting each round.
trigger_phrases:
  - review loop
  - run the review loop
  - review and fix until clean
  - iterate the review until it's clean
  - loop review on this PR
  - keep reviewing and fixing until nothing is left
mode: read-write
---

# Review Loop

A self-converging **review → fix → re-review** loop. The thread you are running
in is the **orchestrator**: it never reviews and never edits code itself. Its
only jobs are to dispatch fresh-context subagents, maintain the
`REVIEW_LOOP_LOG.md` durable record, enforce the anti-oscillation rules, and
decide when the PR has converged.

Every review subagent and every fix subagent starts with **fresh context** — a
new `Agent` call has zero memory of any prior round. The *only* cross-round
memory is `REVIEW_LOOP_LOG.md`. That is deliberate: fresh eyes each round, with
a written ledger as the single source of truth for "what was already decided and
why." This is what stops the loop from chasing its own tail.

## Core invariants (do not violate)

1. **The orchestrator never edits code or writes review findings itself.** It
   only spawns subagents and records their outputs. If you catch yourself about
   to `Edit` a source file, stop — that is a fix agent's job.
2. **Every subagent is fresh.** Never reuse a subagent across rounds or across
   roles. Spawning a new `Agent` *is* the "clear the context" step.
3. **`REVIEW_LOOP_LOG.md` is the only shared memory.** Every agent reads it
   first and writes to it before finishing. If a decision isn't in the log, it
   didn't happen.
4. **The Decision Ledger is append-only and authoritative.** A prior decision is
   reversed only by a *superseding* entry backed by NEW evidence — never by
   silent re-editing. See [Anti-oscillation](#anti-oscillation-the-loop-breaker).
5. **"Done" = two consecutive clean rounds.** A clean round is one where the
   fresh reviewers return zero Critical and zero Important findings (only
   Suggestions/Nits, or nothing). One clean round is not enough — regressions
   hide. Two in a row, with independent fresh agents, confirms convergence.
6. **Hard cap = 6 rounds.** If the loop hasn't converged by round 6, STOP,
   report the remaining findings honestly, and hand back to the user. Never
   claim convergence that didn't happen.

## Inputs

- `$1` (optional) — a GitHub PR number (`149` or `#149`). If given, the loop
  reviews that PR (checks it out / diffs against its base).
- If `$1` is empty, the loop reviews the **current branch** diffed against its
  base (default `main`).
- The orchestrator auto-detects the base branch; if it can't, it asks once.

## Severity taxonomy

Use the pr-review-toolkit vocabulary throughout. Map the user's "low / very-low
priority" onto the bottom two tiers:

| Tier | Meaning | Blocks convergence? |
|---|---|---|
| **Critical** | Bug, data loss, security hole, broken build/tests, prod-deploy breaker | **Yes — must fix** |
| **Important** | Real correctness/maintainability issue with bounded scope | **Yes — must fix** |
| **Suggestion** | "nice to have," cleaner approach, minor risk | No (low priority) |
| **Nit** | Style, naming, wording | No (very-low priority) |

The loop drives **Critical + Important to zero**. Suggestions and Nits are
recorded but never block convergence and are never auto-fixed (they're left for
the human to triage).

## Pre-flight

Run from the repo root. Report each check in one short sentence. **Stop and ask**
if a hard check fails.

1. **Inside a git repo** and **on a branch, not `main`** (`git rev-parse --abbrev-ref HEAD`).
   If on `main`, stop and ask which branch to review — never run the loop on `main`.
2. **Determine the diff scope:**
   - PR mode (`$1` set): `gh pr view <n> --json baseRefName,headRefName,number`. Check out the head if not already on it. Base = `baseRefName`.
   - Branch mode: base = `main` unless the upstream tracking branch says otherwise. Diff = `git diff origin/<base>...HEAD`.
   - Confirm the diff is **non-empty** (`git diff --stat origin/<base>...HEAD`). If empty, stop — nothing to review.
3. **Working tree is clean-ish** (`git status --short`). Uncommitted changes that
   belong to this PR are fine (they'll be reviewed and committed by the first fix
   round); unrelated noise is a risk — flag it.
4. **`gh auth status`** is green if in PR mode or if the user will want to push.
5. **Prod-verifier MCP availability (soft check — do NOT block):** record which
   of the three can run so the review rounds know what to dispatch:
   - Vercel: `vercel whoami` returns a user, else note "vercel-prod-verifier will skip."
   - Postgres prod: `mcp__postgres-prod__query` is available and `SELECT 1` succeeds.
   - Railway: `mcp__railway-mcp-server__*` is available and reports status.
   Report which of the three are ready in one line.
6. **Identify the project gates** so fix rounds can self-verify. For this repo:
   `npm run type-check`, `npm test`, and backend `pytest` (run the subset the diff
   touches). Confirm the commands exist before relying on them.

## Setting up the durable record

The loop's memory lives in **`REVIEW_LOOP_LOG.md`** at the repo root.

- Keep it **out of git history by default** so per-round fix commits stay clean:
  add it to `.git/info/exclude` (local-only ignore — does not modify the tracked
  `.gitignore`). If the user explicitly wants the audit trail committed with the
  PR, skip the exclude and let the fix agent `git add` it each round instead.
- If the file already exists from a prior run on this branch, **append a new run
  header** rather than wiping it — prior ledger entries still apply.

Create it (if absent) with this skeleton:

```markdown
# Review Loop — <branch or PR #N>

**Purpose:** Single source of truth for this review loop. EVERY agent (reviewer
and fixer) MUST read this file before doing anything, and append to it before
finishing. The Decision Ledger below is authoritative: do not silently reverse a
ledger decision — see the rules at the top of the ledger.

**Base:** origin/<base> · **Head:** <branch> · **Started:** <YYYY-MM-DD>
**Prod verifiers available this run:** vercel=<y/n> postgres=<y/n> railway=<y/n>

---

## Decision Ledger (append-only, authoritative)

> RULES FOR ALL AGENTS:
> 1. Before flagging or changing anything, read every ACTIVE ledger entry below.
> 2. Do NOT re-flag or revert an ACTIVE decision unless you bring NEW evidence
>    that it is wrong (a failing test, a runtime error, a spec/doc citation, a
>    prod-schema fact). "I'd have done it differently" is NOT new evidence.
> 3. To overturn a decision, append a SUPERSEDING entry citing that evidence and
>    mark the old entry `status: superseded by #<id>`. Never flip a decision on
>    opinion alone.
> 4. If you find yourself reversing a change that a previous round already
>    reversed (an A→B→A oscillation), STOP and flag it `status: CONTESTED` — the
>    orchestrator will escalate it to the human instead of auto-fixing.

<!-- entries appended here as: -->
<!-- ### Ledger #N — <file:line> — <short title> -->
<!-- - **Round:** N  **Status:** active -->
<!-- - **Decision:** changed <X> → <Y> -->
<!-- - **Why:** <rationale> -->
<!-- - **Evidence:** <test result / line ref / prod fact> -->

---

## Rounds

<!-- one `### Round N — <date>` section appended per round -->
```

## The loop

Run rounds `1, 2, 3, …` up to the hard cap of **6**. Maintain a `clean_streak`
counter (starts at 0). **Converge when `clean_streak == 2`.**

For each round **N**:

### Step 1 — Open the round

Append to `REVIEW_LOOP_LOG.md`:

```markdown
### Round N — <YYYY-MM-DD>

**Diff at round start:** <output of `git diff --stat origin/<base>...HEAD`>
```

Report to the user: `Round N: dispatching reviewers…`

### Step 2 — Pick the reviewers (by diff)

Always dispatch the three universal pr-review-toolkit agents; add the others and
the prod verifiers only when the diff justifies them:

| Agent | Dispatch when… |
|---|---|
| `pr-review-toolkit:code-reviewer` | always |
| `pr-review-toolkit:silent-failure-hunter` | always |
| `pr-review-toolkit:pr-test-analyzer` | always |
| `pr-review-toolkit:type-design-analyzer` | diff adds/modifies types, interfaces, dataclasses, Pydantic/SQLAlchemy models |
| `pr-review-toolkit:comment-analyzer` | diff adds/changes comments or docstrings |
| `vercel-prod-verifier` | diff touches `api/*.ts`, `vercel.json`, `vercel.ts`, `next.config.*`, `middleware.ts`, anything reading `process.env.*`, or frontend build config — AND vercel was available at pre-flight |
| `postgres-prod-verifier` | diff touches `scripts/shared/migrations/**`, `**/models.py`, raw SQL, ORM query code, or anything importing SQLAlchemy/Alembic — AND postgres was available at pre-flight |
| `railway-prod-verifier` | diff touches `src/backend/**`, `Dockerfile`, `railway.toml`, `railway.json`, `Procfile`, or backend env-var references — AND railway was available at pre-flight |

If a verifier matches the diff but was unavailable at pre-flight, record under
the round: `- <verifier>: **Could not verify** — <reason>.` If it simply doesn't
match the diff: `- <verifier>: not dispatched (no matching diff signal).`

### Step 3 — Dispatch all reviewers in parallel (fresh Opus)

Send every selected agent in **one tool-call batch** so they run concurrently.
Each is a fresh `Agent` call.

- pr-review-toolkit agents: pass **`model: opus`** (the user wants Opus reviews).
- prod verifiers: let them inherit their own definitions (their tooling, not the
  model, is what matters); Opus preferred if overridable.

Brief **every** reviewer with:

- The diff scope command: `git diff origin/<base>...HEAD` (and the file list).
- The **absolute path to `REVIEW_LOOP_LOG.md`**, with these instructions
  verbatim:
  - "Read this entire file first, especially the Decision Ledger."
  - "Do NOT re-flag any ACTIVE ledger decision unless you have NEW evidence it is
    wrong (failing test, runtime error, spec citation, prod fact). If you have
    such evidence, say so explicitly and cite the ledger entry number."
  - "Do NOT propose reverting a change a prior round deliberately made; if you
    think it must be reverted, label the finding `REVERTS Ledger #<id>` and
    attach your new evidence."
- The severity taxonomy (Critical / Important / Suggestion / Nit) and a request
  to return findings as a list, each with: `severity · file:line · what · why ·
  (optional) REVERTS Ledger #id + evidence`.
- For prod verifiers: the diff scope, current branch, base branch, and any known
  resource names (Vercel project slug, Railway service `Job-Visualizer-Notifier`,
  prod DB). Remind them: **read-only against production — no writes/deploys/env
  mutations.**

Wait for all reviewers to finish.

### Step 4 — Aggregate + screen findings

Collect every finding into the Round N section of the log. Dedup near-identical
findings across agents (same file:line + same issue → one entry, note which
agents raised it). Group by severity:

```markdown
#### Findings — Round N

**Critical:**
- <file:line> — <issue> (agents: …)

**Important:**
- <file:line> — <issue> (agents: …)

**Suggestion / Nit (not fixed — recorded for human triage):**
- …

**Prod-environment findings:**
- <file:line | resource> — <issue> (agent: vercel/postgres/railway-prod-verifier)

**Could not verify:**
- <verifier> — <reason>
```

Then run the **anti-oscillation screen** on every Critical/Important finding
before deciding to fix it (next section). Move any rejected/contested finding out
of the fix list and into a clearly-labeled subsection so the fix agent never
touches it.

### Anti-oscillation (the loop-breaker)

This is the mechanism the user specifically asked for. Before any finding is sent
to a fix agent, the orchestrator screens it:

1. **Compute a fingerprint** for the finding: `normalize(file path) +
   approximate line region + normalized one-line description`. Track fingerprints
   across all rounds in the log (a `Fingerprints seen` running list is fine).

2. **Ledger conflict check.** Does the finding target — or explicitly REVERT — an
   **active** Decision Ledger entry?
   - **No new evidence** (the reviewer didn't cite a failing test / runtime error
     / spec / prod fact that contradicts the ledger): **reject the finding.** Log
     it under `#### Rejected — contradicts ledger without new evidence` with the
     ledger id it conflicts with. Do **not** fix it.
   - **New evidence present:** allow it through as a *superseding* candidate. The
     fix agent (Step 6) must add a superseding ledger entry, not a silent revert.

3. **Oscillation check.** Has this fingerprint already been *fixed and then
   reversed* in a prior round (i.e., we changed A→B, then a later round changed
   B→A)? If the same locus is now being flipped a **second** time:
   - Mark it `status: CONTESTED` in the ledger.
   - **Freeze it:** do not auto-fix. Add to a `#### CONTESTED — needs human
     decision` list with both sides' reasoning and evidence.
   - Surface it to the user immediately: "Round N: locus <file:line> is
     oscillating between two fixes; freezing it for your decision."
   This is the hard stop that guarantees the loop can't run A→B→A→B forever.

Only findings that survive this screen are eligible for fixing.

### Step 5 — Decide: clean or fix?

Count the **surviving** Critical + Important findings (after the screen; contested
and rejected ones don't count).

- **Zero surviving Critical AND zero surviving Important** → this is a **CLEAN
  round.** `clean_streak += 1`.
  - If `clean_streak == 2` → **CONVERGED.** Go to [Completion](#completion).
  - Else → record `Round N: clean (streak 1/2). Re-reviewing with fresh agents to
    confirm.` and loop to round N+1 with **brand-new** reviewers. (No fix agent
    this round — there's nothing to fix.)
- **Any surviving Critical/Important** → `clean_streak = 0`. Proceed to Step 6.

### Step 6 — Dispatch ONE fix agent (fresh Opus)

Spawn a single `general-purpose` agent with **`model: opus`**, fresh context.
Brief it with:

- The absolute path to `REVIEW_LOOP_LOG.md`. Instructions:
  - "Read the whole file first, especially the Decision Ledger and this round's
    findings."
  - "Fix ONLY the surviving Critical and Important findings in this round's fix
    list. Do not touch Suggestions, Nits, Rejected, or CONTESTED items."
  - "For every fix, append a Decision Ledger entry: file:line, what you changed
    (X → Y), why, and the evidence (the test you ran, the line, the prod fact).
    This is what stops a future round from blindly reverting you."
  - "If a finding is a sanctioned `REVERTS Ledger #id` (it came with new
    evidence), append a **superseding** ledger entry and mark the old one
    `superseded by #<new id>`. Never silently flip a decision."
- **Prod-finding special handling** (carry over from the e2e convention):
  - If a fix requires setting a Vercel/Railway env var, **do not** run
    `vercel env add` / Railway `set-variables`. Document the variable + value
    shape under `**Manual action required before merge:**` in the log and surface
    it to the user.
  - If a fix requires a schema migration, regenerate via
    `alembic revision --autogenerate` per the repo's standing rule — never
    hand-edit migration files.
- **Self-verify before committing:** run the project gates the diff touches
  (`npm run type-check`, relevant `npm test`, backend `pytest`). If a gate is red
  after the fixes, the fix agent must resolve it before committing — a red gate is
  itself a Critical finding.
- **Commit once** with message `review-loop(<N>): <short summary>` (one logical
  commit; split only if fixes span clearly separate concerns). Do **not** push,
  do **not** open/merge a PR.

After the fix agent returns:

- Append to the log under Round N:
  ```markdown
  #### Fixes applied — Round N
  - Commit: <sha> — <summary>
  - Files: <list>
  - New ledger entries: #<ids>
  - Manual actions required before merge: <list or "none">
  ```
- Re-run the gates yourself (cheap confirmation). If red, the next round's
  reviewers will see it as Critical; note it.

Report: `Round N: <M> findings fixed (commit <sha>); re-reviewing.`

### Step 7 — Loop

Go to round N+1 with fresh reviewers. Stop only on convergence (`clean_streak ==
2`) or the 6-round cap.

## Completion

When the loop ends, write a final summary to the log and report to the user.

> **Before declaring the loop done, ALWAYS run the
> [Post-convergence end-to-end verification](#post-convergence-end-to-end-verification-local-dev--playwright)
> below.** Static reviews passing is necessary but not sufficient — the app must
> be driven end-to-end in a real browser against a running local environment.
> Only report the loop as finished after that pass (and after any e2e-surfaced
> Critical/Important findings have re-entered and cleared the fix loop). If the
> 6-round cap was hit without static convergence, still run the e2e pass to
> describe the real state honestly.

**If converged (two clean rounds):**

```markdown
## Result — CONVERGED

- Rounds run: N
- Findings fixed: <count> Critical, <count> Important across <commits>
- Decision ledger entries: <count>
- Contested / frozen (need human decision): <list or none>
- Suggestions/Nits left for triage: <count>
- Final gates: type-check <pass/fail> · tests <pass/fail> · pytest <pass/fail>
- Manual actions required before merge: <consolidated list or none>
```

Tell the user, in 2–3 sentences: converged after N rounds, what was fixed, any
CONTESTED items they must decide, and any required manual actions. Offer to
`git push` (and, if PR mode, that the commits are ready on the PR) — but do not
push or merge without the user's go-ahead.

**If the 6-round cap was hit without convergence:**

Do **not** claim success. Report:

```markdown
## Result — CAP REACHED (not converged)

- Rounds run: 6
- Remaining Critical: <list>
- Remaining Important: <list>
- Contested / frozen: <list>
- Why it didn't converge: <one-paragraph honest assessment>
```

Tell the user plainly that it did not converge, summarize what's left, and ask
how they want to proceed.

## Post-convergence end-to-end verification (local dev + Playwright)

A static review passing is necessary but **not sufficient**. Before the loop is
declared done, the app is driven **end-to-end in a real browser against a running
local dev environment**. This runs **every time the loop terminates** — after
convergence (two clean rounds) and also after a 6-round cap — and **regardless of
what the diff touched** (always run it; do not diff-gate it).

**Who drives it:** the **orchestrator thread drives this directly.** It is
verification, not code-editing, so it does not violate invariant #1. Do NOT
delegate it to a subagent — the background dev servers and the Playwright MCP
browser session must outlive any single subagent, and the screenshots/results
should be first-class evidence in the main thread for the user to see.

### Step E1 — Start the local dev environment

1. **Decide the backend topology first.** Read `api/jobs.ts` and check the Vercel
   dev env to learn where the frontend's `/api/jobs` (and `/api/admin`) proxy
   points in local dev. Per the **"Vercel Dev env var trap"** memory, cloud env
   vars can make `npm run dev:vercel` proxy to the **prod Railway backend** — in
   which case you do NOT need a local backend at all and should verify against the
   already-live prod data. Only stand up a local backend if the proxy is wired to
   `localhost`:
   - `docker compose up -d postgres`
   - `source .venv/bin/activate && PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload` (background)
   - Wait for `http://localhost:8000/health` to return 200. If the local DB has no
     seeded data the feature flows need, seed it (`src/backend/seed/…`) or fall
     back to the prod-backend topology.
2. **Frontend (always required):** `npm run dev:vercel -w src/frontend`
   (background — REQUIRED over plain `npm run dev`; the Vercel serverless proxies
   in `api/` are what serve `/api/jobs`, `/api/admin`, etc.). Wait for the dev URL
   (typically `http://localhost:3000`) to be reachable.
3. Record the chosen topology in the log: `local-frontend → {local|prod} backend`.

Start servers with `run_in_background: true` and keep their task IDs for teardown
(Step E4). If a server does not come up after a reasonable wait, that is itself a
**Critical** finding — surface it and stop.

### Step E2 — Drive the verification with Playwright (MCP)

Load the Playwright MCP tools in ONE ToolSearch call (`browser_navigate`,
`browser_snapshot`, `browser_click`, `browser_type`, `browser_take_screenshot`,
`browser_console_messages`, `browser_wait_for`, `browser_select_option`). Then:

- **Smoke (always):** navigate to the app, wait for load, snapshot, and read the
  console — require **zero uncaught errors / failed network requests** on the
  surfaces under test. Confirm the primary navigation works (e.g. selecting a
  company renders the graph and the job list).
- **Feature flow(s) (match the diff):** drive the specific user-facing behavior
  the PR changed, click-by-click, asserting the visible result. Capture a
  labelled screenshot at each key assertion as durable evidence.

> **For this branch (location normalization)** the feature flow is the
> **location-hierarchy filter** plus the new **Admin → Location Normalization**
> page: pick a company, open the location filter, confirm the normalized
> country→state→city hierarchy renders, filter by a state (e.g. California) and a
> city (e.g. Texas → Austin) and assert the job list narrows correctly; then open
> the admin page and confirm its health / alias-browser / problem-jobs panels
> render without errors. Save screenshots as `loc-e2e-*.png`.

Severity mapping: a broken **primary** flow or a console error on a tested
surface is **Critical**; a degraded-but-working surface is **Important**.

### Step E3 — Record results + act on failures

Append an `## End-to-end verification` section to `REVIEW_LOOP_LOG.md`:

```markdown
## End-to-end verification — <YYYY-MM-DD>

- Topology: local-frontend → <local|prod> backend
- Smoke: <pass/fail> — <notes, console error count>
- Feature flow(s): <pass/fail per flow> — <notes>
- Screenshots: <paths>
- New findings: <none | list with severity>
```

- **All green →** the loop is truly done; proceed to the final report.
- **Any Critical/Important e2e finding →** it's a regression the static review
  missed. Reset `clean_streak = 0`, open a new round in the log, dispatch a fresh
  fix agent (loop Step 6) to resolve it, then **re-run the affected e2e flow**.
  Respect the 6-round hard cap; if exceeded, report the e2e failure honestly
  rather than hiding it.

### Step E4 — Tear down

Stop the background dev servers (frontend, and backend/postgres if you started
them) via their task IDs. Leave the `loc-e2e-*.png` screenshots in place as
evidence and cite their paths in the final report. Note any server you
intentionally leave running (e.g. the user asked to keep the app up).

## Status reporting (breadcrumbs)

This skill runs long with many subagents. One sentence per milestone, no
subagent-output dumps:

- `Round N: dispatching <k> reviewers…`
- `Round N: <c> Critical, <i> Important, <s> Suggestions; <r> rejected/contested by ledger screen.`
- `Round N: fixing <m> issues (fix agent)…` → `Round N: fixed, commit <sha>.`
- `Round N: clean (streak X/2).`
- On a frozen locus: `Round N: <file:line> is oscillating — frozen for your decision.`
- `Converged — starting local dev env for end-to-end Playwright verification…`
- `E2e: smoke <pass/fail>, location filter <pass/fail>, admin page <pass/fail>.`
- At the end: the Completion summary (including the e2e result).

## Model summary

| Role | Agent type | Model |
|---|---|---|
| Orchestrator | (this thread) | — |
| Reviewers — code | `pr-review-toolkit:*` | **opus** |
| Reviewers — prod | `vercel/postgres/railway-prod-verifier` | inherit (definition) |
| Fix agent | `general-purpose` | **opus** |

## Failure modes & safeguards

- **Reviewer raises something already in the ledger with no new evidence** →
  rejected at the screen, never fixed. (Stops opinion-churn.)
- **A→B→A oscillation** → second flip freezes the locus as CONTESTED and escalates
  to the human. (The user's core requirement.)
- **Fix agent can't make gates pass** → it must not commit; the orchestrator stops
  the round and surfaces the failure.
- **Loop won't converge** → 6-round hard cap stops it; report honestly.
- **Prod verifier MCP unavailable** → record `Could not verify`, never block.
- **User interrupts mid-run** → the log + git history are the checkpoint; rerunning
  the skill on the same branch appends a new run and the ledger still applies.

## What this skill does NOT do

- It does not author plans or implement features — pair it with `e2eimplementation`
  for greenfield work; this skill only reviews-and-fixes existing diffs.
- It does not push or merge. Commits land locally per round; the user ships them.
- It does not auto-fix Suggestions/Nits — those are recorded for human triage.
- It does not silently reverse prior decisions — every reversal is a logged,
  evidence-backed superseding ledger entry, or it's frozen as contested.
- It does not mutate production (env vars, deploys, migrations-apply) — those are
  surfaced as manual actions before merge.

## Invocation

```
/review-loop            # review + fix the current branch vs main, loop to convergence
/review-loop 149        # review + fix GitHub PR #149, loop to convergence
```
