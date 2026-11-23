# north-star loop — runbook

An agent that proposes ONE improvement a week aimed at the North Star (7-day+ return, see USER-METRICS.md), texts Brendan a 5-line summary, and builds it only after he replies yes. The procedure lives in `.claude/skills/north-star-loop/SKILL.md`; this directory is the state store and the scheduling shell around it.

## Flow

```
propose ──text──> Brendan ──"yes N"──> build N ──> PR (via no-mistakes) ──merge──> readout N ──text
   │                  └─"no N <why>"──> rejected (the reason steers every later proposal)
   └─ no reply in 7 days ──> expired
```

- **propose** (at most weekly, only when no idea is open): reads STRATEGY.md, every past idea (rejected ones and Brendan's reasons first), the PostHog North Star dashboard, the prod `metrics` views, and the ClickUp list (so it never duplicates a ticket and can raise an existing one instead). Scores 3 candidates by Impact × Confidence ÷ Effort against the drivers of 7-day+ return (SKILL.md §1), keeps only ones STRATEGY.md's align test passes, saves the full brief, sends one text. No ClickUp write, branch, or repo change yet.
- **build N** (after "yes N"): plan doc at `docs/north-star-loop/ns-N-<slug>.md` (brief, plan, every decision it made), ClickUp task in list `1000430000001112` (or a comment on the existing ticket it raised), change + test in a throwaway worktree, PR through no-mistakes. Never merges.
- **readout N** (38+ days after merge, deferred until 30+ post-ship signups or 120 days): before/after 7-day+ return, the targeted driver and guardrails with n, confounders named, verdict keep / revert suggested / inconclusive.

## Pieces

| Path | Role |
|---|---|
| `.claude/skills/north-star-loop/SKILL.md` | The procedure, hard rules, metric hierarchy + scoring, text formats |
| `.claude/commands/north-star-once.md` | Headless shim: `claude -p "/north-star-once <action>"` |
| `scripts/north_star_loop/loop.py` | SQLite state: ideas, briefs, decisions, mistakes; `sync` + `next` pick the action; `publish` mirrors to git |
| `scripts/north_star_loop/notify.sh` | Sends a text and writes it into Brendan's Boop conversation history |
| `scripts/north_star_loop/wrapper.sh` | launchd entry: lock, `sync`/`next` (no tokens when idle), 90-min cap, failure text, `publish` |
| `scripts/north_star_loop/com.bp.jvn-north-star-loop.plist.template` | LaunchAgent, 09:30 / 13:30 / 17:30 / 21:30 |
| `scripts/north_star_loop/install_launch_agent.sh` | Idempotent install |

Runtime state on the server: `~/Library/Application Support/jvn-north-star-loop/` (`loop.db`, `heartbeat.log`, `notify.env`, the `loop-state` worktree, build worktrees) and `~/Library/Logs/jvn-north-star-loop.{log,err}`.

## State in git

Every scheduled fire ends with `loop.py publish`: it commits `loop.db` and a generated `LOG.md` (every idea, its text, full brief, decisions and mistakes, newest first) to the **`loop-state`** branch and pushes it. It commits only when something changed. That branch is an orphan that never merges into `main` and needs no PR. CI runs only on `main` pushes and PRs, and Vercel deploys only `main`. Any agent can read the history:

```sh
git fetch origin loop-state && git show origin/loop-state:LOG.md
```

The server's local `loop.db` is the authoritative copy; the branch is its mirror (at most one fire behind).

## Texts and replies (Boop)

`notify.sh` sends through `message-brendan/send.sh` (Sendblue), then writes the same text into Brendan's Boop conversation as an assistant message via Convex `messages:send` (the call Boop's own automations use). The stored copy carries a note telling Boop what to run, so when he replies "yes 3" Boop already has the idea in context. One-time setup on the server, in `~/Library/Application Support/jvn-north-star-loop/notify.env` (not in git):

```sh
BOOP_DIR=/path/to/boop-agent            # the checkout whose .env.local points at Boop's Convex deployment
BOOP_CONVERSATION_ID=sms:+1XXXXXXXXXX   # the id Boop uses for Brendan's thread ("sms:" + his number)
# SEND_WRITES_BOOP_HISTORY=1            # only if send.sh already records into Boop
```

Without it, texts still go out, but `notify.sh` exits 4 and the run logs a mistake, because Boop would see the reply without the question. Boop turns a reply into one command, run from the repo root on the server:

```sh
python3 scripts/north_star_loop/loop.py decide <N> yes
python3 scripts/north_star_loop/loop.py decide <N> no <reason words...>
```

The next scheduled fire (within ~4h) starts the build. Without Boop, run the command yourself.

A "NS-N paused" text means a no-mistakes gate is waiting on you; the idea stays `paused` (holding the one-idea slot, never rebuilt by the schedule) until you answer the gate and then run one of:

```sh
python3 scripts/north_star_loop/loop.py set <N> status=pr_open pr_url=<url>   # the PR went up
python3 scripts/north_star_loop/loop.py set <N> status=approved               # rebuild from scratch (fresh branch, 2 attempts)
```

## Ops

```sh
sh scripts/north_star_loop/install_launch_agent.sh               # install / reinstall
launchctl kickstart gui/$(id -u)/com.bp.jvn-north-star-loop      # fire now
launchctl bootout gui/$(id -u)/com.bp.jvn-north-star-loop        # pause
python3 scripts/north_star_loop/loop.py list                     # every idea and its status
python3 scripts/north_star_loop/loop.py show <N>                 # full brief + decisions + mistakes
python3 scripts/north_star_loop/loop.py dump                     # everything, as LOG.md holds it
tail -5 "$HOME/Library/Application Support/jvn-north-star-loop/heartbeat.log"
```

Dry run anywhere (no texts, ClickUp writes, pushes or publish): invoke the `north-star-loop` skill in a Claude session with `JVN_LOOP_DRY_RUN=1`, `JVN_LOOP_DB` pointing at a throwaway file, and `JVN_LOOP_STATE_DIR` at a throwaway folder. A real run with a missing `send.sh` is an error, not a silent dry run. `JVN_LOOP_SEND` overrides the send script path.

## Design notes

- **The brief is the hand-off.** The builder reads the proposer's full evidence, scores and reasoning, not one sentence. Unapproved ideas never reach `main`; they live in the DB and on `loop-state`.
- **One idea open at a time**, so before/after readouts are not confounded by the loop's own changes. Shipped ideas being measured do not block the next proposal; the readout lists them as confounders.
- **No size cap.** Ideas are ranked by Impact × Confidence ÷ Effort, so a bigger change has to earn its effort. Every build still goes through no-mistakes and Brendan's merge, and STRATEGY.md is the only hard filter.
- **No A/B split yet.** At ~10 signups a month a 50/50 flag halves an already tiny sample; readouts are before/after with named confounders and say "inconclusive" when n is small. Revisit flags once weekly signups reach ~60.
- The wrapper and paths assume the server laptop (`/Users/bpotter`, main checkout at `~/developer/personal/Job-Visualizer-Notifier`), like `scripts/health_watch/`. Keep that checkout on `main`; skill edits take effect only once it has them.
