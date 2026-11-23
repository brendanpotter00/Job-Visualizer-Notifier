# north-star loop — runbook

An agent that proposes ONE small improvement a week aimed at the North Star (7-day+ return, see USER-METRICS.md), texts Brendan a 5-line summary, and builds it only after he replies yes. The procedure lives in `.claude/skills/north-star-loop/SKILL.md`; this directory is the state store and the scheduling shell around it.

## Flow

```
propose ──text──> Brendan ──"yes N"──> build N ──> PR (via no-mistakes) ──merge──> readout N ──text
   │                  └─"no N <why>"──> rejected (the note steers later ideas)
   └─ no reply in 7 days ──> expired
```

- **propose** (at most weekly, only when no idea is open): read-only evidence from prod Postgres + PostHog, a full brief saved to SQLite, one text. No ClickUp task, branch, or repo write yet.
- **build N** (after "yes N"): plan doc at `docs/north-star-loop/ns-N-<slug>.md` (brief, plan, every decision it made), ClickUp task in list `1000430000001112`, change + test in a throwaway worktree, PR through no-mistakes. Never merges.
- **readout N** (38+ days after merge, deferred until 30+ post-ship signups or 120 days): before/after 7-day+ return and guardrails with n, confounders named, verdict keep / revert suggested / inconclusive.

## Pieces

| Path | Role |
|---|---|
| `.claude/skills/north-star-loop/SKILL.md` | The procedure, hard rules, trust level, text formats |
| `.claude/commands/north-star-once.md` | Headless shim: `claude -p "/north-star-once <action>"` |
| `scripts/north_star_loop/loop.py` | SQLite state: ideas, briefs, decisions, mistakes; `sync` + `next` pick the action |
| `scripts/north_star_loop/wrapper.sh` | launchd entry: lock, `sync`/`next` (no tokens when idle), 90-min cap, failure text |
| `scripts/north_star_loop/com.bp.jvn-north-star-loop.plist.template` | LaunchAgent, 09:30 / 13:30 / 17:30 / 21:30 |
| `scripts/north_star_loop/install_launch_agent.sh` | Idempotent install |

Runtime state (not in the repo): `~/Library/Application Support/jvn-north-star-loop/` (`loop.db`, `heartbeat.log`, build worktrees) and `~/Library/Logs/jvn-north-star-loop.{log,err}`.

## Replying from iMessage

Texts go out through `message-brendan/send.sh` (Sendblue), like the health watch. Replies reach the server's iMessage agent (Boop); it must turn them into one command, run from the repo root on the server:

```sh
python3 scripts/north_star_loop/loop.py decide <N> yes
python3 scripts/north_star_loop/loop.py decide <N> no <reason words...>
```

Tell Boop once: *when I text "yes N" or "no N …", run that command and reply with its output.* The next scheduled fire (within ~4h) starts the build. Without Boop, run the command yourself.

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
tail -5 "$HOME/Library/Application Support/jvn-north-star-loop/heartbeat.log"
```

Dry run anywhere (no texts, ClickUp writes, or pushes): invoke the `north-star-loop` skill in a Claude session with `JVN_LOOP_DRY_RUN=1`, `JVN_LOOP_DB` pointing at a throwaway file, and `JVN_LOOP_STATE_DIR` at a throwaway folder (heartbeat). A real run with a missing `send.sh` is an error, not a silent dry run. `JVN_LOOP_SEND` overrides the send script path.

## Design notes

- **Why SQLite outside the repo:** the brief is the hand-off between agents (the builder reads the proposer's full evidence, not one sentence), and unapproved ideas must not land in git. Worktrees and the main checkout all see the same file.
- **One idea open at a time**, so before/after readouts are not confounded by the loop's own changes. Shipped ideas being measured do not block the next proposal; the readout lists them as confounders.
- **No A/B split yet.** At ~10 signups a month a 50/50 flag halves an already tiny sample; readouts are before/after with named confounders and say "inconclusive" when n is small. Revisit flags once weekly signups reach ~60.
- **Trust level 1** (SKILL.md §1) allows small improvements only. Raising it is a PR by Brendan, never the agent.
- The wrapper and paths assume the server laptop (`/Users/bpotter`, main checkout at `~/developer/personal/Job-Visualizer-Notifier`), like `scripts/health_watch/`. Keep that checkout on `main`; skill edits take effect only once it has them.
