---
name: north-star-loop
description: The north-star improvement loop. Once a week it proposes ONE small improvement aimed at the North Star (7-day+ return) and texts Brendan a 4-line summary. Only after he replies "yes N" does it write the plan doc, create the ClickUp task, build the change in a worktree and open a PR through no-mistakes (never merges). After merge it reads out the result. Use when asked to run the north-star loop, propose an improvement, build an approved NS idea, or read one out. Headless runs come from scripts/north_star_loop/wrapper.sh.
---

# north-star-loop

One idea at a time, aimed at one number. The loop earns trust by proposing small, evidence-backed improvements; Brendan decides; the loop builds only what he approved and shows its work.

State: `scripts/north_star_loop/loop.py` (SQLite at `~/Library/Application Support/jvn-north-star-loop/loop.db`, override `JVN_LOOP_DB`). Below, `LOOP` means `python3 scripts/north_star_loop/loop.py`. `LOOP show N` prints the full brief and every event for idea NS-N; that brief is the hand-off between runs, so write it for a reader with zero context.

## §0 Hard rules

1. **Read-only data.** Prod Postgres (`mcp__postgres-prod__query`): `SELECT` only. PostHog: read only (queries, insights); no flag, insight, dashboard, or cohort writes.
2. **Nothing before approval.** No ClickUp task, branch, worktree, or repo write for NS-N until `LOOP show N` says `status: approved` (or `building`). An idea Brendan has not answered is only a row in the DB and one text.
3. **Never merge, deploy, or push to `main`.** The PR is the end of a build; it goes out only through no-mistakes (`no-mistakes axi run`). Brendan merges.
4. **One idea open at a time.** `LOOP add` refuses a second; do not work around it.
5. **Strategy first.** Every idea passes the align test in STRATEGY.md. Drop any idea the resist test fires on, most of all "adds engagement for its own sake": no nags, streaks, extra emails or notifications, dark patterns. The goal is people coming back because the board got them to a real opening faster, not because we pestered them.
6. **Show your work.** Every choice you make without asking: `LOOP log N decision "<choice> because <why>"`. Every error you notice (a wrong assumption, a failing test, a step you redid): `LOOP log N mistake "<what went wrong>"`. Never hide or soften a mistake; Brendan reads this log when something goes wrong.
7. **Budget.** Propose: at most ~20 read queries. Build: the wrapper's 90-minute cap. At most 1 text per run, plus 1 if the run failed.
8. **Texts** go through `bash /Users/bpotter/.claude/skills/message-brendan/send.sh "<msg>"` (call the script; not the Skill tool). If `JVN_LOOP_DRY_RUN=1` or the script is missing, print `[DRY-RUN TEXT] <msg>` instead, and also skip ClickUp writes and any push.
9. No AI-attribution footers in commits or PR bodies.
10. Headless: follow the exit discipline in `.claude/commands/north-star-once.md`.

## §1 Constants

- `NORTH_STAR` = **7-day+ return** per weekly signup cohort, exactly as defined in USER-METRICS.md (`metrics.north_star_weekly.frac_back_day7plus`, mature rows only). Every idea targets this, and only this.
- `GUARDRAILS` = 3-day+ return, signup conversion, apply clicks per session. A drop of more than 10% (relative) in any of them is a regression.
- `TRUST_LEVEL` = **1**. Level 1 allows `kind=improvement` only: at most 5 files and ~200 changed lines excluding tests; no migrations or schema changes, auth, billing/Stripe, email or notification sending, scrapers or ingestion, new dependencies, env vars, or infra. Level 2 (features) needs Brendan to raise this constant in a PR; suggest it in a readout text after 3 ideas were kept with no revert.

## §2 Modes

Pick the mode from the argument (`propose`, `build N`, `readout N`). With no argument, run `LOOP sync` then `LOOP next` and do what it prints (`none` → write the heartbeat and stop).

### propose

1. Read STRATEGY.md and USER-METRICS.md. Run `LOOP list` and `LOOP show` on recent ideas: never re-propose a rejected or expired idea, and read the decision notes and mistakes for what Brendan does not want.
2. Gather evidence for where retention leaks, read-only: the `metrics` views, `user_visits`, `job_apply_clicks`, saved filters, onboarding answers, and PostHog funnels and paths. Prefer facts about what returning users do that one-time users do not.
3. Draft 3 candidate improvements internally, each tied to a number you found. Pick the one with the best (likely effect on 7-day+ return × confidence) ÷ size that fits `TRUST_LEVEL` and the strategy test. Small and surely-good beats big and maybe-great.
4. Write the brief to a temp file, with these headings:
   - **Problem**: what users do now, with the numbers and the exact SQL/HogQL you ran.
   - **Change**: the behaviour after, precisely; the files you expect to touch; size estimate.
   - **Why it moves 7-day+ return**: the causal story, in two or three sentences.
   - **Risk**: what could break or get worse, which guardrail it could hurt; rollback (revert the PR).
   - **Measurement**: the readout rule (§2 readout), how many signups a month that implies, and one leading signal to watch early.
   - **Rejected alternatives**: the other 2 candidates, one line each, and why not.
5. `LOOP add --title "<the change, ≤12 words>" --metric "7d return" --expected "<now%> → <hoped%>" --risk low|medium|high --sms "<text>" --brief-file <file>` (prints N). Then send the text (§3, proposal).

### build N

1. `LOOP show N`. It must be `approved` (or `building` from an interrupted run; if so, `LOOP log N mistake "previous build run did not finish"` and resume). `LOOP set N status=building`.
2. Re-run the brief's key query. If the problem no longer holds, log a mistake, `LOOP set N status=blocked`, text (§3, blocked), stop.
3. `git fetch origin main` and create a worktree outside the checkout: `git worktree add "$HOME/Library/Application Support/jvn-north-star-loop/worktrees/ns-N" -b loop/ns-N-<slug> origin/main`. Work only there. `LOOP set N branch=loop/ns-N-<slug>`.
4. Write the plan doc `docs/north-star-loop/ns-N-<slug>.md`: the brief verbatim, then **Plan** (ordered steps, files), **Decisions** (every choice made without asking, each with why — also `LOOP log`ged), **Log** (empty; the readout fills it). If any measured idea has a result not yet in its own plan doc, append it there too. `LOOP set N plan_path=docs/north-star-loop/ns-N-<slug>.md`.
5. If the plan breaks `TRUST_LEVEL` limits, stop: log it, `LOOP set N status=blocked`, text (§3, blocked).
6. Only now create the ClickUp task: list `1000430000001112`, name `NS-N · <title>`, description = the Change + Measurement sections and the plan doc path. `LOOP set N clickup_id=<id>`. If the ClickUp tools are missing or fail, `LOOP log N warn ...` and go on; the PR is what matters.
7. Implement. Follow the area AGENTS.md files. Add or update a behaviour test for the change. Run the targeted tests and `npm run type-check` (frontend) or the touched backend tests. Commit on the branch.
8. Ship: `no-mistakes axi run --intent-file <file>`, where the intent is the brief plus "Approved by Brendan by text on <decided_at>; built autonomously by the north-star loop at trust level 1". At a gate: fix `auto-fix` findings; for an `ask-user` finding, leave the run parked, log it, text (§3, needs you), stop. On `checks-passed`: `LOOP set N status=pr_open pr_url=<url>`.
9. Remove the worktree (`git worktree remove`). Text (§3, PR ready).

### readout N

1. `LOOP show N`. Post-ship cohorts = signup weeks starting on or after `shipped_at` that are mature. Baseline = the 8 mature cohort weeks before `shipped_at`. Use the 7-day+ SQL in USER-METRICS.md (`WHERE NOT is_internal`).
2. If post-ship mature signups < 30 and `shipped_at` is under 120 days ago: `LOOP set N readout_at=<now + 14 days>`, `LOOP log N note "too early: n=<n>"`, no text, stop.
3. Compare NORTH_STAR and each GUARDRAIL, before vs after, with n on both sides. List confounders: other loop ideas shipped in the window (`LOOP list`), weeks whose signups were over 2× the median (a social post or launch), other user-facing merges to `main` in the window (`git log`).
4. Verdict: **keep** (north star up, guardrails hold), **revert suggested** (a guardrail regressed with n ≥ 30), or **inconclusive** (anything else; say so plainly). Never revert by yourself.
5. `LOOP set N status=measured result="<verdict>: 7d <before>% → <after>% (n=<b> vs <a>)"`. Text (§3, readout). The result reaches the plan doc on the next build (build step 4).

## §3 Texts

Short enough to read on a lock screen. No greeting, no sign-off.

- Proposal (≤ 5 lines):
  ```
  NS-N idea → 7d return <now%>→<hoped%>
  <the change, ≤12 words>
  Why: <the evidence, ≤12 words>
  Risk: <low|med|high> · ~<k> files · undo = revert PR
  Reply "yes N" or "no N <why>"
  ```
- PR ready: `NS-N PR ready, checks green: <url>` / `Merge = ship. Readout ~<date>.`
- Needs you: `NS-N paused: <one line>. <url or "LOOP show N">`
- Blocked: `NS-N blocked: <one line>. Nothing shipped.`
- Readout: `NS-N result: <verdict>. 7d <before>%→<after>% (n=<b>/<a>). <one confounder or "no confounders">`

## §4 Heartbeat

Last step of every run, even a failed one: append one line to `~/Library/Application Support/jvn-north-star-loop/heartbeat.log`:
`<UTC ISO time> mode=<mode> ns=<N or -> outcome=<proposed|pr_open|blocked|paused|deferred|measured|none|error> texts=<k>`
Then print a 3-line status block and end the turn.
