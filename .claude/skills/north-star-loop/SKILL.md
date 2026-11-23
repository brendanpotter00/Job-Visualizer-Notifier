---
name: north-star-loop
description: The north-star improvement loop. Once a week it proposes ONE improvement aimed at the North Star (7-day+ return), ranked against the other candidates and existing ClickUp work and checked against STRATEGY.md, and texts Brendan a 5-line summary (also written into his Boop conversation so his reply has context). Only after he replies "yes N" does it write the plan doc, create or reuse the ClickUp task, build the change in a worktree and open a PR through no-mistakes (never merges). After merge it reads out the result. Its state is mirrored to the `loop-state` git branch. Use when asked to run the north-star loop, propose an improvement, build an approved NS idea, or read one out. Headless runs come from scripts/north_star_loop/wrapper.sh.
---

# north-star-loop

One idea at a time, aimed at one number. The loop proposes the evidence-backed change most likely to raise 7-day+ return; Brendan decides; the loop builds only what he approved and shows its work.

State: `scripts/north_star_loop/loop.py` (SQLite at `~/Library/Application Support/jvn-north-star-loop/loop.db`; overrides `JVN_LOOP_STATE_DIR`, `JVN_LOOP_DB`). Below, `LOOP` is shorthand for `python3 scripts/north_star_loop/loop.py`: type the full command each time (a `$LOOP` shell variable does not word-split in zsh). `LOOP show N` prints the full brief and every event for idea NS-N; that brief is the hand-off between runs, so write it for a reader with zero context. Agents anywhere can read the same history from git: `git fetch origin loop-state && git show origin/loop-state:LOG.md` (`LOOP publish` keeps it current).

## §0 Hard rules

1. **Read-only data.** Prod Postgres (`mcp__postgres-prod__query`): `SELECT` only. PostHog: read only (queries, insights, dashboards); no flag, insight, dashboard, or cohort writes. ClickUp: read freely; write only in build step 6.
2. **Nothing before approval.** No ClickUp write, branch, worktree, or repo change for NS-N until `LOOP show N` says `status: approved` (or `building`). An idea Brendan has not answered is only a row in the DB and one text.
3. **Never merge, deploy, or push to `main`.** The PR is the end of a build; it goes out only through no-mistakes (`no-mistakes axi run`). Brendan merges. The only direct push is `LOOP publish` to the `loop-state` branch.
4. **One idea open at a time.** `LOOP add` refuses a second; do not work around it.
5. **Aligned with STRATEGY.md, every time.** Read its Vision and the align/resist tests before choosing. An idea must satisfy "A change aligns when…" (quote the clause it meets in the brief) and must not trip any "A change should be resisted when…" clause — most of all "adds engagement for its own sake": no nags, streaks, notifications or emails that do not earn their send, dark patterns. If the best-scoring idea conflicts, drop it and say why under **Ranked candidates**. The goal is people coming back because the board got them to a real, fresh opening faster, not because we pestered them.
6. **Show your work.** Every choice you make without asking: `LOOP log N decision "<choice> because <why>"`. Every error you notice (a wrong assumption, a failing test, a step you redid): `LOOP log N mistake "<what went wrong>"`. Never hide or soften a mistake; Brendan reads this log when something goes wrong.
7. **Budget.** Propose: at most ~20 data queries (SQL/HogQL that return rows; tool-help and schema lookups do not count). Build: the wrapper's 90-minute cap. At most 1 text per run, plus 1 if the run failed.
8. **Texts** go through `sh scripts/north_star_loop/notify.sh "<msg>"`, never `send.sh` directly and never the Skill tool. It sends the iMessage **and writes the same text into Brendan's Boop conversation history**, with a note telling Boop how to act on "yes N" / "no N", so his reply arrives with context. Exit 0 = sent and recorded. Exit 4 or 5 = sent but NOT in Boop's history: `LOOP log N mistake "text not in Boop history: <stderr>"` (his reply will lack context; say so in the status block). Exit 2 or 3 = not sent: an **error** (`LOOP log N mistake ...`, heartbeat `outcome=error`, nonzero status line). With `JVN_LOOP_DRY_RUN=1`, notify.sh only prints `[DRY-RUN TEXT] <msg>`; also skip ClickUp writes, pushes and `LOOP publish`.
9. No AI-attribution footers in commits or PR bodies.
10. Headless: follow the exit discipline in `.claude/commands/north-star-once.md`.

## §1 What to improve, and in what order

- **NORTH_STAR** = **7-day+ return** per weekly signup cohort, exactly as defined in USER-METRICS.md (`metrics.north_star_weekly.frac_back_day7plus`, mature rows only). Every idea must say how it moves this number.
- **DRIVERS** — where 7-day+ return comes from. Re-measure them every propose run (the numbers below are the 2026-11-23 snapshot, not constants) and aim at the biggest leak first:
  1. **First return** — share of signups who come back at all after signup day (47% never do).
  2. **Week-1 → later** — share of week-1 returners who also come back on day 7-30 (45%; 77% of all day-7+ returners came back in week 1 first).
  3. **Visit value** — apply clicks per session: a return visit that finds nothing worth applying to is the reason not to return.
  4. **Signup conversion** — does not move the rate, but more signups make every readout readable sooner. Target it only when readouts are starved.
- **GUARDRAILS** = 3-day+ return, signup conversion, apply clicks per session. A drop of more than 10% (relative) in any of them is a regression.
- **SCORING** — rate each candidate 1-5 on three axes and rank by `Impact × Confidence ÷ Effort` (max 25):
  - **Impact**: the effect on **7-day+ return**, through the driver: size of the driver's leak × how much of it the change can plausibly close. Driver 4 (signup conversion) does not move the rate, so a signup-conversion idea scores Impact at most 2 however big its own leak is.
  - **Confidence** (what is likely to work): 5 = a pattern proven at other job boards or products (name it) *and* supported by our data; 4 = proven elsewhere; 3 = a strong correlation in our data with a causal story; 2 = a weak or confounded correlation; 1 = a hunch.
  - **Effort**: 1 = a small diff in a day; 3 = several files or a migration; 5 = multi-week or new infrastructure. Bigger is allowed; the score just has to earn it.
  - Ties go to the smaller change.
- **STAGES** — a build is one autonomous run that ends in one PR. If the winner needs more than one PR, or steps only Brendan can do (create an account, add DNS records, set a secret, make a product decision), the brief's **Change** section splits it into stages and lists those human prerequisites. NS-N proposes and builds **stage 1 only**: the first PR-sized step that stands on its own. Later stages come back as their own ideas on later propose runs, re-scored. Name any human prerequisite of stage 1 in the text (§3) so Brendan sees it before saying yes.

## §2 Modes

Pick the mode from the argument (`propose`, `build N`, `readout N`). With no argument, run `LOOP sync` then `LOOP next` and do what it prints (`none` → write the heartbeat and stop).

### propose

1. Run `LOOP sync` then `LOOP next`. If it does not print `propose`, write the heartbeat (`outcome=none`) and stop before spending any queries.
2. **Strategy and history.** Read STRATEGY.md (Vision + align/resist tests) and USER-METRICS.md. Then read **every past idea**: `LOOP list`, and `LOOP show N` on each (or `LOOP dump`). For each **rejected** idea, note Brendan's reason (`decision_note`) and treat it as a rule about what he does not want; for expired ones (no reply), note that too; read every logged mistake. Never re-propose a rejected idea, or a lightly reworded version of one, unless the brief names what changed since and answers his reason directly. An expired idea got no answer (check its events: if it was never actually sent, e.g. a dry run, it carries no signal at all); it may come back after 4 weeks, re-scored, with the earlier expiry named. Ideas a past brief ranked but did not pick are fair candidates again; re-score them.
3. **Current numbers.** Read the PostHog **North Star dashboard** (project 483508, dashboard 2397096: apply clicks per session, signup conversion, 3-day+ / 7-day+ return, weeks returned, comeback) and the prod `metrics` views (`metrics.north_star_weekly`, `metrics.signup_retention`, `metrics.apply_clicks_weekly`). Recompute the §1 DRIVERS. **Postgres is the source of truth for returns**; PostHog person-level data does not match it for cohorts before about 2026-11 (`user_visited` starts with PR #382), so use PostHog for recent behaviour and the dashboard tiles. `job_apply_clicks` starts 2026-11-22; do not treat its early weeks as evidence.
4. **Existing work.** Search the ClickUp list `1000430000001112` (open tasks, and recently closed ones) for work that targets the same leak. Do not propose a duplicate. If an existing ticket would move a driver, it is a candidate in its own right: propose raising it (name and link it) instead of inventing a parallel idea.
5. **Evidence.** Dig into the biggest leaks with read-only queries (`user_visits`, `users`, `user_saved_filters`, `user_keyword_lists`, `users.onboarding_completed_at`, PostHog funnels for recent weeks). Prefer facts about what returning users do that one-time users do not. Keep a list of every choice you make; you will `LOOP log` them after step 8 creates N.
6. **Rank.** Draft 3 candidates (new ideas or existing ClickUp tickets), score each per §1, check each against STRATEGY.md (§0.5), and pick the top aligned one.
7. Write the brief to a temp file, with these headings:
   - **Problem**: which driver leaks, what users do now, with the numbers and the load-bearing queries verbatim (not every query you ran).
   - **Change**: the behaviour after, precisely; the files you expect to touch; size estimate. If it raises an existing ClickUp ticket, link it.
   - **Why it moves 7-day+ return**: the causal story through the driver, in two or three sentences.
   - **Strategy check**: the STRATEGY.md align clause it meets (quoted) and why no resist clause fires.
   - **Existing work**: related ClickUp tickets found in step 4 and how this idea relates (new, raises #…, or none found).
   - **Past ideas**: each earlier NS idea, its status, and for rejected ones Brendan's reason quoted; say how this idea differs and how it respects those reasons ("none yet" if the DB is empty).
   - **Risk**: what could break or get worse, which guardrail it could hurt; rollback (revert the PR).
   - **Measurement**: when the readout can land at the current signup rate (time to 30 post-ship signups + 31 days), whether a lift of the hoped size is detectable at that n (say "likely inconclusive" plainly if not), and one **leading signal** readable weekly from week 1. At today's volume the leading signal is the real test.
   - **Ranked candidates**: a table of all 3 with Impact, Confidence, Effort, score, strategy verdict, and one line each; why the winner won.
8. `LOOP add --title "<the change, ≤12 words>" --kind improvement|feature --metric "7d return" --expected "<now%> → <hoped%>" --risk low|medium|high --sms "<text>" --brief-file <file>` (prints N). `now%` is the pooled 7-day+ return over all mature cohorts, with n in the brief. Write `{N}` wherever the text needs the id; `add` fills it in. Then `LOOP log N decision ...` each choice from steps 3-6, and send the stored text (`LOOP show N`, field `sms`) with notify.sh (§3, proposal).

### build N

1. `LOOP show N`. It must be `approved` (or `building` from an interrupted run; if so, `LOOP log N mistake "previous build run did not finish"` and resume). `LOOP set N status=building`.
2. Re-run the brief's key query. If the problem no longer holds, log a mistake, `LOOP set N status=blocked`, text (§3, blocked), stop. If stage 1 has a human prerequisite that is not yet done (check it, do not assume), `LOOP set N status=paused`, text (§3, needs you) with the checklist, stop; Brendan sets `status=approved` once it is done.
3. `git fetch origin main` and create a worktree outside the checkout: `git worktree add "$HOME/Library/Application Support/jvn-north-star-loop/worktrees/ns-N" -b loop/ns-N-<slug> origin/main`. If that worktree or a `loop/ns-N-*` branch already exists from an earlier run: when step 1 found `building`, reuse it (`git worktree add <path> loop/ns-N-<slug>` when only the branch is left); when step 1 found `approved` (a fresh build or a rebuild from scratch), remove them first (`git worktree remove --force <path>`, `git branch -D <branch>`) and `LOOP log N decision "removed stale worktree/branch from an earlier run"`. Work only there. `LOOP set N branch=loop/ns-N-<slug>`.
4. Write the plan doc `docs/north-star-loop/ns-N-<slug>.md`: the brief verbatim, then **Plan** (ordered steps, files), **Decisions** (every choice made without asking, each with why — also `LOOP log`ged), **Log** (empty; the readout fills it). If any measured idea has a result not yet in its own plan doc, append it there too. `LOOP set N plan_path=docs/north-star-loop/ns-N-<slug>.md`.
5. Re-check the plan against STRATEGY.md (§0.5). Building can surface what proposing missed; if it now conflicts, stop: log it, `LOOP set N status=blocked`, text (§3, blocked).
6. ClickUp, only now: if the brief raised an existing ticket, comment on it with the plan doc path and use its id; otherwise create a task in list `1000430000001112` named `NS-N · <title>`, description = the Change + Measurement sections and the plan doc path. `LOOP set N clickup_id=<id>`. If the ClickUp tools are missing or fail, `LOOP log N warn ...` and go on; the PR is what matters.
7. Implement. Follow the area AGENTS.md files. Add or update a behaviour test for the change. Run the targeted tests and `npm run type-check` (frontend) or the touched backend tests. Commit on the branch.
8. Ship: `no-mistakes axi run --intent-file <file>`, where the intent is the brief plus "Approved by Brendan by text on <decided_at>; built autonomously by the north-star loop". At a gate: fix `auto-fix` findings; for an `ask-user` finding, leave the run parked, log it, `LOOP set N status=paused`, text (§3, needs you), stop. A paused idea holds the one-idea slot and is never rebuilt by the schedule; Brendan answers the parked gate, then runs `LOOP set N status=pr_open pr_url=<url>` (or `status=approved` to rebuild from scratch). On `checks-passed`: `LOOP set N status=pr_open pr_url=<url>`.
9. Remove the worktree (`git worktree remove`). Text (§3, PR ready).

### readout N

1. `LOOP show N`. Post-ship cohorts = signup weeks starting on or after `shipped_at` that are mature. Baseline = the 8 mature cohort weeks before `shipped_at`. Use the 7-day+ SQL in USER-METRICS.md (`WHERE NOT is_internal`).
2. If post-ship mature signups < 30 and `shipped_at` is under 120 days ago: `LOOP set N readout_at=<now + 14 days>`, `LOOP log N note "too early: n=<n>"`, no text, stop.
3. Compare NORTH_STAR, the targeted DRIVER, and each GUARDRAIL, before vs after, with n on both sides. List confounders: other loop ideas shipped in the window (`LOOP list`), weeks whose signups were over 2× the median (a social post or launch), other user-facing merges to `main` in the window (`git log`).
4. Verdict: **keep** (north star up, guardrails hold), **revert suggested** (a guardrail regressed with n ≥ 30), or **inconclusive** (anything else; say so plainly). Never revert by yourself. Also report the brief's leading signal for the same window; when the north star is inconclusive, the leading signal decides whether the readout leans keep or revert.
5. `LOOP set N status=measured result="<verdict>: 7d <before>% → <after>% (n=<b> vs <a>)"`. Text (§3, readout). The result reaches the plan doc on the next build (build step 4).

## §3 Texts

Short enough to read on a lock screen. No greeting, no sign-off. notify.sh adds the Boop-history copy; do not add instructions for Boop to the text itself.

- Proposal (≤ 5 lines):
  ```
  NS-{N} idea → 7d return <now%>→<hoped%>
  <the change, ≤12 words>
  Why: <the evidence, ≤12 words>
  Risk: <low|med|high> · ~<k> files · score <s>/25 · undo = revert PR
  Reply "yes {N}" or "no {N} <why>"
  ```
  If stage 1 needs something from Brendan first, replace the Why line with `Needs you first: <≤10 words>`. If the idea has later stages, end the change line with `(stage 1 of <m>)`.
- PR ready: `NS-N PR ready, checks green: <url>` / `Merge = ship. Readout ~<date>.`
- Needs you: `NS-N paused: <one line>. <url or "LOOP show N">` / `After the gate: loop.py set N status=pr_open pr_url=<url>`
- Blocked: `NS-N blocked: <one line>. Nothing shipped.`
- Readout: `NS-N result: <verdict>. 7d <before>%→<after>% (n=<b>/<a>). <one confounder or "no confounders">`

## §4 Publish and heartbeat

Last steps of every run, even a failed one:
1. `LOOP publish` (skipped in a dry run) — mirrors loop.db and LOG.md to the `loop-state` branch. A failure here is a `warn`, not an error; the wrapper publishes again after the run.
2. Append one line to `${JVN_LOOP_STATE_DIR:-$HOME/Library/Application Support/jvn-north-star-loop}/heartbeat.log`:
   `<UTC ISO time> mode=<mode> ns=<N or -> outcome=<proposed|pr_open|blocked|paused|deferred|measured|none|error> texts=<k>` (`k` counts texts actually sent; dry-run prints are 0).
3. Print a 3-line status block and end the turn.
