---
name: north-star-loop
description: The north-star improvement loop. Once a week it proposes ONE small improvement aimed at the North Star (7-day+ return) and texts Brendan a 5-line summary. Only after he replies "yes N" does it write the plan doc, create the ClickUp task, build the change in a worktree and open a PR through no-mistakes (never merges). After merge it reads out the result. Use when asked to run the north-star loop, propose an improvement, build an approved NS idea, or read one out. Headless runs come from scripts/north_star_loop/wrapper.sh.
---

# north-star-loop

One idea at a time, aimed at one number. The loop earns trust by proposing small, evidence-backed improvements; Brendan decides; the loop builds only what he approved and shows its work.

State: `scripts/north_star_loop/loop.py` (SQLite at `~/Library/Application Support/jvn-north-star-loop/loop.db`, override `JVN_LOOP_DB`). Below, `LOOP` is shorthand for `python3 scripts/north_star_loop/loop.py`: type the full command each time (a `$LOOP` shell variable does not word-split in zsh). `LOOP show N` prints the full brief and every event for idea NS-N; that brief is the hand-off between runs, so write it for a reader with zero context.

## §0 Hard rules

1. **Read-only data.** Prod Postgres (`mcp__postgres-prod__query`): `SELECT` only. PostHog: read only (queries, insights); no flag, insight, dashboard, or cohort writes.
2. **Nothing before approval.** No ClickUp task, branch, worktree, or repo write for NS-N until `LOOP show N` says `status: approved` (or `building`). An idea Brendan has not answered is only a row in the DB and one text.
3. **Never merge, deploy, or push to `main`.** The PR is the end of a build; it goes out only through no-mistakes (`no-mistakes axi run`). Brendan merges.
4. **One idea open at a time.** `LOOP add` refuses a second; do not work around it.
5. **Strategy first.** Every idea passes the align test in STRATEGY.md. Drop any idea the resist test fires on, most of all "adds engagement for its own sake": no nags, streaks, extra emails or notifications, dark patterns. The goal is people coming back because the board got them to a real opening faster, not because we pestered them.
6. **Show your work.** Every choice you make without asking: `LOOP log N decision "<choice> because <why>"`. Every error you notice (a wrong assumption, a failing test, a step you redid): `LOOP log N mistake "<what went wrong>"`. Never hide or soften a mistake; Brendan reads this log when something goes wrong.
7. **Budget.** Propose: at most ~20 data queries (SQL/HogQL that return rows; tool-help and schema lookups do not count). Build: the wrapper's 90-minute cap. At most 1 text per run, plus 1 if the run failed.
8. **Texts** go through `bash "${JVN_LOOP_SEND:-/Users/bpotter/.claude/skills/message-brendan/send.sh}" "<msg>"` (call the script; not the Skill tool). Only when `JVN_LOOP_DRY_RUN=1` is set: print `[DRY-RUN TEXT] <msg>` instead, skip ClickUp writes and any push, and write the heartbeat under `$JVN_LOOP_STATE_DIR`. A missing or failing send script in a real run is an **error**, never a silent dry run: `LOOP log N mistake "text not sent: <why>"`, heartbeat `outcome=error`, and end with a nonzero status line so the wrapper flags the run.
9. No AI-attribution footers in commits or PR bodies.
10. Headless: follow the exit discipline in `.claude/commands/north-star-once.md`.

## §1 Constants

- `NORTH_STAR` = **7-day+ return** per weekly signup cohort, exactly as defined in USER-METRICS.md (`metrics.north_star_weekly.frac_back_day7plus`, mature rows only). Every idea targets this, and only this.
- `GUARDRAILS` = 3-day+ return, signup conversion, apply clicks per session. A drop of more than 10% (relative) in any of them is a regression.
- `TRUST_LEVEL` = **1**. Level 1 allows `kind=improvement` only: at most 5 non-test files and ~200 changed non-test lines (tests are free); no migrations or schema changes, auth, billing/Stripe, email or notification sending, scrapers or ingestion, new dependencies, env vars, or infra. Level 2 (features) needs Brendan to raise this constant in a PR; suggest it in a readout text after 3 ideas were kept with no revert.

## §2 Modes

Pick the mode from the argument (`propose`, `build N`, `readout N`). With no argument, run `LOOP sync` then `LOOP next` and do what it prints (`none` → write the heartbeat and stop).

### propose

1. Run `LOOP sync` then `LOOP next`. If it does not print `propose`, write the heartbeat (`outcome=none`) and stop before spending any queries.
2. Read STRATEGY.md and USER-METRICS.md. Run `LOOP list` and `LOOP show` on recent ideas: never re-propose a rejected or expired idea, and read the decision notes and mistakes for what Brendan does not want.
3. Gather evidence for where retention leaks, read-only. **Postgres is the source of truth for returns** (`metrics` views, `user_visits`, `users`, `user_saved_filters`, `user_keyword_lists`, `users.onboarding_completed_at`). PostHog person-level data does not match Postgres for cohorts before about 2026-11 (`user_visited` starts with PR #382), so use PostHog only for recent behaviour such as pageviews and funnels. `job_apply_clicks` starts 2026-11-22; do not treat its early weeks as evidence. Prefer facts about what returning users do that one-time users do not. Keep a list of every choice you make here; you will `LOOP log` them after step 6 creates N.
4. Draft 3 candidate improvements internally, each tied to a number you found. Pick the one with the best (likely effect on 7-day+ return × confidence) ÷ size that fits `TRUST_LEVEL` and the strategy test. Small and surely-good beats big and maybe-great.
5. Write the brief to a temp file, with these headings:
   - **Problem**: what users do now, with the numbers and the load-bearing queries verbatim (not every query you ran).
   - **Change**: the behaviour after, precisely; the files you expect to touch; size estimate.
   - **Why it moves 7-day+ return**: the causal story, in two or three sentences.
   - **Risk**: what could break or get worse, which guardrail it could hurt; rollback (revert the PR).
   - **Measurement**: when the readout can land at the current signup rate (time to 30 post-ship signups + 31 days), whether a lift of the hoped size is detectable at that n (say "likely inconclusive" plainly if not), and one **leading signal** that can be read weekly from week 1. At today's volume the leading signal is the real test.
   - **Rejected alternatives**: the other 2 candidates, one line each, and why not.
6. `LOOP add --title "<the change, ≤12 words>" --metric "7d return" --expected "<now%> → <hoped%>" --risk low|medium|high --sms "<text>" --brief-file <file>` (prints N). `now%` is the pooled 7-day+ return over all mature cohorts, with n in the brief. Write `{N}` wherever the text needs the id; `add` fills it in. Then `LOOP log N decision ...` each choice from step 3-4, and send the stored text (`LOOP show N`, field `sms`) (§3, proposal).

### build N

1. `LOOP show N`. It must be `approved` (or `building` from an interrupted run; if so, `LOOP log N mistake "previous build run did not finish"` and resume, reusing the branch and worktree from step 3 if they exist). `LOOP set N status=building`.
2. Re-run the brief's key query. If the problem no longer holds, log a mistake, `LOOP set N status=blocked`, text (§3, blocked), stop.
3. `git fetch origin main` and create a worktree outside the checkout: `git worktree add "$HOME/Library/Application Support/jvn-north-star-loop/worktrees/ns-N" -b loop/ns-N-<slug> origin/main`. If that worktree or a `loop/ns-N-*` branch already exists from an earlier run: when step 1 found `building`, reuse it (`git worktree add <path> loop/ns-N-<slug>` when only the branch is left); when step 1 found `approved` (a fresh build or a rebuild from scratch), remove them first (`git worktree remove --force <path>`, `git branch -D <branch>`) and `LOOP log N decision "removed stale worktree/branch from an earlier run"`. Work only there. `LOOP set N branch=loop/ns-N-<slug>`.
4. Write the plan doc `docs/north-star-loop/ns-N-<slug>.md`: the brief verbatim, then **Plan** (ordered steps, files), **Decisions** (every choice made without asking, each with why — also `LOOP log`ged), **Log** (empty; the readout fills it). If any measured idea has a result not yet in its own plan doc, append it there too. `LOOP set N plan_path=docs/north-star-loop/ns-N-<slug>.md`.
5. If the plan breaks `TRUST_LEVEL` limits, stop: log it, `LOOP set N status=blocked`, text (§3, blocked).
6. Only now create the ClickUp task: list `1000430000001112`, name `NS-N · <title>`, description = the Change + Measurement sections and the plan doc path. `LOOP set N clickup_id=<id>`. If the ClickUp tools are missing or fail, `LOOP log N warn ...` and go on; the PR is what matters.
7. Implement. Follow the area AGENTS.md files. Add or update a behaviour test for the change. Run the targeted tests and `npm run type-check` (frontend) or the touched backend tests. Commit on the branch.
8. Ship: `no-mistakes axi run --intent-file <file>`, where the intent is the brief plus "Approved by Brendan by text on <decided_at>; built autonomously by the north-star loop at trust level 1". At a gate: fix `auto-fix` findings; for an `ask-user` finding, leave the run parked, log it, `LOOP set N status=paused`, text (§3, needs you), stop. A paused idea holds the one-idea slot and is never rebuilt by the schedule; Brendan answers the parked gate, then runs `LOOP set N status=pr_open pr_url=<url>` (or `status=approved` to rebuild from scratch). On `checks-passed`: `LOOP set N status=pr_open pr_url=<url>`.
9. Remove the worktree (`git worktree remove`). Text (§3, PR ready).

### readout N

1. `LOOP show N`. Post-ship cohorts = signup weeks starting on or after `shipped_at` that are mature. Baseline = the 8 mature cohort weeks before `shipped_at`. Use the 7-day+ SQL in USER-METRICS.md (`WHERE NOT is_internal`).
2. If post-ship mature signups < 30 and `shipped_at` is under 120 days ago: `LOOP set N readout_at=<now + 14 days>`, `LOOP log N note "too early: n=<n>"`, no text, stop.
3. Compare NORTH_STAR and each GUARDRAIL, before vs after, with n on both sides. List confounders: other loop ideas shipped in the window (`LOOP list`), weeks whose signups were over 2× the median (a social post or launch), other user-facing merges to `main` in the window (`git log`).
4. Verdict: **keep** (north star up, guardrails hold), **revert suggested** (a guardrail regressed with n ≥ 30), or **inconclusive** (anything else; say so plainly). Never revert by yourself.
   Also report the brief's leading signal for the same window; when the north star is inconclusive, the leading signal decides whether the readout leans keep or revert.
5. `LOOP set N status=measured result="<verdict>: 7d <before>% → <after>% (n=<b> vs <a>)"`. Text (§3, readout). The result reaches the plan doc on the next build (build step 4).

## §3 Texts

Short enough to read on a lock screen. No greeting, no sign-off.

- Proposal (≤ 5 lines):
  ```
  NS-{N} idea → 7d return <now%>→<hoped%>
  <the change, ≤12 words>
  Why: <the evidence, ≤12 words>
  Risk: <low|med|high> · ~<k> files · undo = revert PR
  Reply "yes {N}" or "no {N} <why>"
  ```
- PR ready: `NS-N PR ready, checks green: <url>` / `Merge = ship. Readout ~<date>.`
- Needs you: `NS-N paused: <one line>. <url or "LOOP show N">` / `After the gate: loop.py set N status=pr_open pr_url=<url>`
- Blocked: `NS-N blocked: <one line>. Nothing shipped.`
- Readout: `NS-N result: <verdict>. 7d <before>%→<after>% (n=<b>/<a>). <one confounder or "no confounders">`

## §4 Heartbeat

Last step of every run, even a failed one: append one line to `${JVN_LOOP_STATE_DIR:-$HOME/Library/Application Support/jvn-north-star-loop}/heartbeat.log`:
`<UTC ISO time> mode=<mode> ns=<N or -> outcome=<proposed|pr_open|blocked|paused|deferred|measured|none|error> texts=<k>` (`k` counts texts actually sent; dry-run prints are 0).
Then print a 3-line status block and end the turn.
