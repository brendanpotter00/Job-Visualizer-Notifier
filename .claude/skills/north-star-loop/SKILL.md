---
name: north-star-loop
description: The north-star improvement loop. Once a week it sends Brendan ONE short text with up to 3 small improvements aimed at the North Star (7-day+ return) that the loop can build on its own, plus one line naming the best big initiative for him to build himself. Ideas are ranked against past ideas and existing ClickUp work, checked against STRATEGY.md, and the text is also written into his Boop conversation so his reply has context. Only the small ideas he picks ("yes 4 6") get a plan doc, a ClickUp task, a build in a worktree and a PR through no-mistakes (never merged); big initiatives are never built by the loop. After merge it reads out the result. State stays in a local SQLite file on the server. Use when asked to run the north-star loop, propose improvements, build an approved NS idea, or read one out. Headless runs come from scripts/north_star_loop/wrapper.sh.
---

# north-star-loop

One number, two kinds of idea. Each week the loop finds the evidence-backed changes most likely to raise 7-day+ return. **Small** ones it can build itself once Brendan picks them; the best **big** initiative it only brings to his attention, because he will build that one himself and read every line. It shows its work either way.

State: `scripts/north_star_loop/loop.py` (SQLite at `~/Library/Application Support/jvn-north-star-loop/loop.db`; overrides `JVN_LOOP_STATE_DIR`, `JVN_LOOP_DB`). Below, `LOOP` is shorthand for `python3 scripts/north_star_loop/loop.py`: type the full command each time (a `$LOOP` shell variable does not word-split in zsh). `LOOP show N` prints the full brief and every event for idea NS-N; that brief is the hand-off between runs, so write it for a reader with zero context. Other agents on the server read the same state with `LOOP list`, `LOOP show N` or `LOOP dump` (every idea, text, brief and event as markdown); it never goes into git.

## §0 Hard rules

1. **Read-only data.** Prod Postgres (`mcp__postgres-prod__query`): `SELECT` only. PostHog: read only (queries, insights, dashboards); no flag, insight, dashboard, or cohort writes. ClickUp: read freely; write only in build step 6.
2. **Nothing before approval.** No ClickUp write, branch, worktree, or repo change for NS-N until `LOOP show N` says `status: approved` (or `building`). An idea Brendan has not picked is only a row in the DB and a line in one text.
3. **Big initiatives are never built by the loop.** It researches, scores and names them; Brendan builds them. `LOOP decide N yes` refuses a big one.
4. **Never merge, deploy, or push to `main`.** A small idea's PR is the end of its build; it goes out only through no-mistakes (`no-mistakes axi run`). Brendan merges.
5. **Limits, enforced by loop.py — do not work around them:** one batch a week; at most 3 small ideas per batch; at most 3 small ideas in flight (approved, building, paused or PR open) at once; at most 1 big initiative a week.
6. **Aligned with STRATEGY.md, every time.** Read its Vision and the align/resist tests before choosing. An idea must satisfy "A change aligns when…" (quote the clause it meets in the brief) and must not trip any "A change should be resisted when…" clause — most of all "adds engagement for its own sake": no nags, streaks, notifications or emails that do not earn their send, dark patterns. Drop any idea that conflicts and say why under **Ranked candidates**. The goal is people coming back because the board got them to a real, fresh opening faster, not because we pestered them.
7. **Show your work.** Every choice you make without asking: `LOOP log N decision "<choice> because <why>"`. Every error you notice (a wrong assumption, a failing test, a step you redid): `LOOP log N mistake "<what went wrong>"`. Never hide or soften a mistake; Brendan reads this log when something goes wrong.
8. **Budget.** Propose: at most ~25 data queries (SQL/HogQL that return rows; tool-help and schema lookups do not count). Build: the wrapper's 90-minute cap. At most 1 text per run, plus 1 if the run failed.
9. **Texts** go through `sh scripts/north_star_loop/notify.sh "<msg>"`, never `send.sh` directly and never the Skill tool. It sends the iMessage **and writes the same text into Brendan's Boop conversation history**, with a note telling Boop how to act on his reply, so the reply arrives with context. Exit 0 = sent and recorded. Exit 4 or 5 = sent but NOT in Boop's history: `LOOP log N mistake "text not in Boop history: <stderr>"` on each idea it named (his reply will lack context; say so in the status block). Exit 2 or 3 = not sent: an **error** (`LOOP log N mistake ...`, heartbeat `outcome=error`, nonzero status line). With `JVN_LOOP_DRY_RUN=1`, notify.sh only prints `[DRY-RUN TEXT] <msg>`; also skip ClickUp writes and pushes.
10. No AI-attribution footers in commits or PR bodies.
11. Headless: follow the exit discipline in `.claude/commands/north-star-once.md`.

## §1 What to improve, and in what order

- **NORTH_STAR** = **7-day+ return** per weekly signup cohort, exactly as defined in USER-METRICS.md (`metrics.north_star_weekly.frac_back_day7plus`, mature rows only). Every idea must say how it moves this number.
- **DRIVERS** — where 7-day+ return comes from. Re-measure them every propose run (the numbers below are the 2026-11-23 snapshot, not constants) and aim at the biggest leak first:
  1. **First return** — share of signups who come back at all after signup day (47% never do).
  2. **Week-1 → later** — share of week-1 returners who also come back on day 7-30 (45%; 77% of all day-7+ returners came back in week 1 first).
  3. **Visit value** — apply clicks per session: a return visit that finds nothing worth applying to is the reason not to return.
  4. **Signup conversion** — does not move the rate, but more signups make every readout readable sooner.
- **GUARDRAILS** = 3-day+ return, signup conversion, apply clicks per session. A drop of more than 10% (relative) in any of them is a regression.
- **SCORING** — rate each candidate 1-5 on three axes and rank by `Impact × Confidence ÷ Effort` (max 25):
  - **Impact**: the effect on **7-day+ return**, through the driver: size of the driver's leak × how much of it the change can plausibly close. Driver 4 (signup conversion) does not move the rate, so a signup-conversion idea scores Impact at most 2 however big its own leak is.
  - **Confidence** (what is likely to work): 5 = a pattern proven at other job boards or products (name it) *and* supported by our data; 4 = proven elsewhere; 3 = a strong correlation in our data with a causal story; 2 = a weak or confounded correlation; 1 = a hunch.
  - **Effort**: 1 = a small diff in a day; 3 = several files or a migration; 5 = multi-week or new infrastructure.
  - Ties go to the smaller change.
- **SCOPE** — you judge each candidate **small** or **big**, and give a one-line reason in its brief. There is no fixed rule; ask: *would Brendan merge this after a skim, or would he want to design it and read every line?*
  - **Small**: the loop can build it in one autonomous run ending in one PR, nothing has to be done by Brendan first, and a mistake is cheap to revert.
  - **Big**: anything he would want to own. Typical signs: a new external service or account, sending email or notifications, schema/auth/billing changes, more than one PR, a product decision only he can make, or a change whose mistakes would reach users in a way a revert cannot undo. For a big initiative the brief sketches the stages and what Brendan must do first.

## §2 Modes

Pick the mode from the argument (`propose`, `text`, `build N`, `readout N`). With no argument, run `LOOP sync` then `LOOP next` and do what it prints (`none` → write the heartbeat and stop).

### propose

1. Run `LOOP sync` then `LOOP next`. If it does not print `propose`, write the heartbeat (`outcome=none`) and stop before spending any queries.
2. **Strategy and history.** Read STRATEGY.md (Vision + align/resist tests) and USER-METRICS.md. Then read **every past idea**: `LOOP list`, and `LOOP show N` on each (or `LOOP dump`). For each **rejected** idea, note Brendan's reason (`decision_note`) and treat it as a rule about what he does not want; for expired ones (not picked within a week), note that too; read every logged mistake. Never re-propose a rejected idea, or a lightly reworded version of one, unless the brief names what changed since and answers his reason directly. An expired idea carries a weak signal (he saw it and picked others; if its events show it was never actually sent, e.g. a dry run, none at all); it may come back after 4 weeks, re-scored, with the earlier expiry named. Do not flag the same big initiative two weeks running unless the brief names new evidence; ideas a past brief ranked but did not pick are fair candidates again.
3. **Current numbers.** Read the PostHog **North Star dashboard** (project 483508, dashboard 2397096: apply clicks per session, signup conversion, 3-day+ / 7-day+ return, weeks returned, comeback) and the prod `metrics` views (`metrics.north_star_weekly`, `metrics.signup_retention`, `metrics.apply_clicks_weekly`). Recompute the §1 DRIVERS. **Postgres is the source of truth for returns**; PostHog person-level data does not match it for cohorts before about 2026-11 (`user_visited` starts with PR #382), so use PostHog for recent behaviour and the dashboard tiles. `job_apply_clicks` starts 2026-11-22; do not treat its early weeks as evidence.
4. **Existing work.** Search the ClickUp list `1000430000001112` (open tasks, and recently closed ones) for work that targets the same leaks. Do not propose a duplicate. If an existing ticket would move a driver, it is a candidate in its own right: propose raising it (name and link it) instead of inventing a parallel idea.
5. **Evidence.** Dig into the biggest leaks with read-only queries (`user_visits`, `users`, `user_saved_filters`, `user_keyword_lists`, `users.onboarding_completed_at`, PostHog funnels for recent weeks). Prefer facts about what returning users do that one-time users do not. Keep a list of every choice you make; you will `LOOP log` them after step 8 creates the ids.
6. **Rank.** Draft 5-6 candidates (new ideas or existing ClickUp tickets), score each per §1, check each against STRATEGY.md (§0.6), and label each small or big (§1 SCOPE). Pick the **top 3 aligned small ideas** (fewer if fewer qualify) and the **top aligned big initiative** (none if none beats the small ones on Impact or none is new).
7. Write one brief per picked idea to temp files, with these headings:
   - **Scope**: small or big, and the one-line reason.
   - **Problem**: which driver leaks, what users do now, with the numbers and the load-bearing queries verbatim (not every query you ran).
   - **Change**: the behaviour after, precisely; the files you expect to touch; size estimate. If it raises an existing ClickUp ticket, link it. For a big initiative: the stages and what Brendan must do first.
   - **Why it moves 7-day+ return**: the causal story through the driver, in two or three sentences.
   - **Strategy check**: the STRATEGY.md align clause it meets (quoted) and why no resist clause fires.
   - **Existing work**: related ClickUp tickets found in step 4 and how this idea relates (new, raises #…, or none found).
   - **Past ideas**: earlier NS ideas that bear on this one, their status, and for rejected ones Brendan's reason quoted; say how this idea differs and respects those reasons ("none yet" if the DB is empty).
   - **Risk**: what could break or get worse, which guardrail it could hurt; rollback (revert the PR).
   - **Measurement**: when the readout can land at the current signup rate (time to 30 post-ship signups + 31 days), whether a lift of the hoped size is detectable at that n (say "likely inconclusive" plainly if not), and one **leading signal** readable weekly from week 1. At today's volume the leading signal is the real test.
   - **Ranked candidates**: the week's full table (every candidate from step 6 with Impact, Confidence, Effort, score, scope, strategy verdict, one line each), identical in every brief of the batch, and why the picked ones won.
8. Record them, small ideas first in rank order: `LOOP add --scope small|big --title "<the change, ≤12 words>" --metric "7d return" --expected "<now%> → <hoped%>" --risk low|medium|high --brief-file <file>` (each prints its id). `now%` is the pooled 7-day+ return over all mature cohorts, with n in the brief. Right after the last `add`, before anything else: compose the weekly text (§3) with the real ids, record it with `LOOP texted "<text>" <every id in the text>`, and send it with notify.sh. Only then `LOOP log N decision ...` each choice from steps 3-6 on the idea it concerns. (If the run dies between `add` and `texted`, the next fire's `LOOP next` prints `text` and finishes the batch.)

### text

The weekly batch was saved but its text never went out (a propose run died between `add` and `texted`).

1. Run `LOOP sync` then `LOOP next`. If it does not print `text`, write the heartbeat (`outcome=none`) and stop.
2. `LOOP list`, then `LOOP show N` on every `proposed` or `flagged` idea with no `sms:` line. No new research, no new ideas, no data queries: the saved briefs are the whole input.
3. Compose the weekly text (§3) from those briefs (7d return and scores as the briefs state them), record it with `LOOP texted "<text>" <every id in the text>`, and send it with notify.sh. If notify.sh exits 2 or 3, clear nothing: log the mistake per §0.9 and end with `outcome=error` (the wrapper's failure text fires; Brendan can rerun).
4. `LOOP log N mistake "weekly text sent late by a text run: the propose run stopped before texting"` on each idea it named.

### build N

Only small ideas are ever built.

1. `LOOP show N`. It must be a small idea that is `approved` (or `building` from an interrupted run; if so, `LOOP log N mistake "previous build run did not finish"` and resume). `LOOP set N status=building`.
2. Re-run the brief's key query. If the problem no longer holds, log a mistake, `LOOP set N status=blocked`, text (§3, blocked), stop. If the work turns out to need something from Brendan first, or more than one PR, it was mis-scoped as small: `LOOP log N mistake "mis-scoped: <why>"`, `LOOP set N status=blocked`, text (§3, blocked) saying it is bigger than it looked, stop.
3. `git fetch origin main` and create a worktree outside the checkout: `git worktree add "$HOME/Library/Application Support/jvn-north-star-loop/worktrees/ns-N" -b loop/ns-N-<slug> origin/main`. If that worktree or a `loop/ns-N-*` branch already exists from an earlier run: when step 1 found `building`, reuse it (`git worktree add <path> loop/ns-N-<slug>` when only the branch is left); when step 1 found `approved` (a fresh build or a rebuild from scratch), remove them first (`git worktree remove --force <path>`, `git branch -D <branch>`) and `LOOP log N decision "removed stale worktree/branch from an earlier run"`. Work only there. `LOOP set N branch=loop/ns-N-<slug>`.
4. Write the plan doc `docs/north-star-loop/ns-N-<slug>.md`: the brief verbatim, then **Plan** (ordered steps, files), **Decisions** (every choice made without asking, each with why — also `LOOP log`ged), **Log** (empty; the readout fills it). If any measured idea has a result not yet in its own plan doc, append it there too. `LOOP set N plan_path=docs/north-star-loop/ns-N-<slug>.md`.
5. Re-check the plan against STRATEGY.md (§0.6). Building can surface what proposing missed; if it now conflicts, stop: log it, `LOOP set N status=blocked`, text (§3, blocked).
6. ClickUp, only now: if the brief raised an existing ticket, comment on it with the plan doc path and use its id; otherwise create a task in list `1000430000001112` named `NS-N · <title>`, description = the Change + Measurement sections and the plan doc path. `LOOP set N clickup_id=<id>`. If the ClickUp tools are missing or fail, `LOOP log N warn ...` and go on; the PR is what matters.
7. Implement. Follow the area AGENTS.md files. Add or update a behaviour test for the change. Run the targeted tests and `npm run type-check` (frontend) or the touched backend tests. Commit on the branch.
8. Ship: `no-mistakes axi run --intent-file <file>`, where the intent is the brief plus "Approved by Brendan by text on <decided_at>; built autonomously by the north-star loop". At a gate: fix `auto-fix` findings; for an `ask-user` finding, leave the run parked, log it, `LOOP set N status=paused`, text (§3, needs you), stop. A paused idea keeps its in-flight slot and is never rebuilt by the schedule; Brendan answers the parked gate, then runs `LOOP set N status=pr_open pr_url=<url>` (or `status=approved` to rebuild from scratch). On `checks-passed`: `LOOP set N status=pr_open pr_url=<url>`.
9. Remove the worktree (`git worktree remove`). Text (§3, PR ready).

### readout N

1. `LOOP show N`. Post-ship cohorts = signup weeks starting on or after `shipped_at` that are mature. Baseline = the 8 mature cohort weeks before `shipped_at`. Use the 7-day+ SQL in USER-METRICS.md (`WHERE NOT is_internal`).
2. If post-ship mature signups < 30 and `shipped_at` is under 120 days ago: `LOOP set N readout_at=<now + 14 days>`, `LOOP log N note "too early: n=<n>"`, no text, stop.
3. Compare NORTH_STAR, the targeted DRIVER, and each GUARDRAIL, before vs after, with n on both sides. List confounders: other loop ideas shipped in the window (`LOOP list` — with up to 3 in flight this is common, so name them), weeks whose signups were over 2× the median (a social post or launch), other user-facing merges to `main` in the window (`git log`).
4. Verdict: **keep** (north star up, guardrails hold), **revert suggested** (a guardrail regressed with n ≥ 30), or **inconclusive** (anything else; say so plainly). Never revert by yourself. Also report the brief's leading signal for the same window; when the north star is inconclusive, the leading signal decides whether the readout leans keep or revert.
5. `LOOP set N status=measured result="<verdict>: 7d <before>% → <after>% (n=<b> vs <a>)"`. Text (§3, readout). The result reaches the plan doc on the next build (build step 4).

## §3 Texts

Short enough to read on a lock screen. No greeting, no sign-off. notify.sh adds the Boop-history copy; do not add instructions for Boop to the text itself.

- **Weekly** (one text, ≤ 6 lines; each idea line ≤ 10 words before the score):
  ```
  NS weekly · 7d return <now%>
  <N1>) <small idea> · <score> · <low|med|high>
  <N2>) <small idea> · <score> · <risk>
  <N3>) <small idea> · <score> · <risk>
  Big (yours): <initiative> · <score> · NS-<N4>
  Reply e.g. "yes <N1> <N3>" or "no <N2> <why>"
  ```
  List fewer small ideas if fewer qualified; drop the Big line if there is none this week.
- PR ready: `NS-N PR ready, checks green: <url>` / `Merge = ship. Readout ~<date>.`
- Needs you (no-mistakes `ask-user`, build step 8): `NS-N paused: <one line>. <url or "LOOP show N">` / `After the gate: loop.py set N status=pr_open pr_url=<url>`
- Blocked: `NS-N blocked: <one line>. Nothing shipped.`
- Readout: `NS-N result: <verdict>. 7d <before>%→<after>% (n=<b>/<a>). <one confounder or "no confounders">`

## §4 Heartbeat

Last steps of every run, even a failed one:
1. Append one line to `${JVN_LOOP_STATE_DIR:-$HOME/Library/Application Support/jvn-north-star-loop}/heartbeat.log`:
   `<UTC ISO time> mode=<mode> ns=<ids or -> outcome=<proposed|texted|pr_open|blocked|paused|deferred|measured|none|error> texts=<k>` (`k` counts texts actually sent; dry-run prints are 0).
2. Print a 3-line status block and end the turn.
