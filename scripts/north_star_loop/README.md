# north-star loop — runbook

An agent that, once a week, texts Brendan up to 3 **small** improvements aimed at the North Star (7-day+ return, see USER-METRICS.md) that it can build on its own, plus one line naming the best **big** initiative for him to build himself. It builds only the small ideas he picks. The procedure lives in `.claude/skills/north-star-loop/SKILL.md`; this directory is the state store and the scheduling shell around it.

## Flow

```
propose ──weekly text──> Brendan ──"yes 4 6"──> build 4, build 6 ──> PRs (via no-mistakes) ──merge──> readout ──text
   │  (3 small + 1 big)      └─"no 5 <why>"──> rejected (the reason steers every later proposal)
   ├─ run died or send failed before the text was recorded ──> next fire: text (sends the saved batch, no new research)
   ├─ small ideas not picked in 7 days ──> expired
   └─ the big initiative stays "flagged": a record for Brendan, never built by the loop
```

- **propose** (weekly, once last week's ideas are answered or expired and fewer than 3 small ideas are in flight): reads STRATEGY.md, every past idea (rejected ones and Brendan's reasons first), the PostHog North Star dashboard, the prod `metrics` views, and the ClickUp list (so it never duplicates a ticket and can raise an existing one instead). Scores 5-6 candidates by Impact × Confidence ÷ Effort against the drivers of 7-day+ return (SKILL.md §1), keeps only ones STRATEGY.md's align test passes, and judges each small or big with a one-line reason. Saves a full brief for the top 3 small and the top big, then sends one text. No ClickUp write, branch, or repo change yet.
- **text** (a propose run saved its ideas but died, or its send failed, before recording the text): the next fire composes the weekly text from the saved briefs and sends it, and keeps retrying each fire until a send succeeds. No new research, no new ideas. The text is recorded only after it is sent, so the worst case is a duplicate text if a run dies between the two.
- **build N** (a small idea he picked): plan doc at `docs/north-star-loop/ns-N-<slug>.md` (brief, plan, every decision it made), ClickUp task in list `1000430000001112` (or a comment on the existing ticket it raised), change + test in a throwaway worktree, PR through no-mistakes. Never merges.
- **readout N** (38+ days after merge, deferred until 30+ post-ship signups or 120 days): before/after 7-day+ return, the targeted driver and guardrails with n, confounders named, verdict keep / revert suggested / inconclusive.

## Pieces

| Path | Role |
|---|---|
| `.claude/skills/north-star-loop/SKILL.md` | The procedure, hard rules, metric hierarchy + scoring, text formats |
| `.claude/commands/north-star-once.md` | Headless shim: `claude -p "/north-star-once <action>"` |
| `scripts/north_star_loop/loop.py` | SQLite state: ideas, briefs, decisions, mistakes; `sync` + `next` pick the action; `dump` prints it all as markdown |
| `scripts/north_star_loop/notify.sh` | Sends a text and writes it into Brendan's Boop conversation history |
| `scripts/north_star_loop/wrapper.sh` | launchd entry: lock, `sync`/`next` (no tokens when idle), 90-min cap, failure text |
| `scripts/north_star_loop/com.bp.jvn-north-star-loop.plist.template` | LaunchAgent, 09:30 / 13:30 / 17:30 / 21:30 |
| `scripts/north_star_loop/install_launch_agent.sh` | Idempotent install |

Runtime state on the server: `~/Library/Application Support/jvn-north-star-loop/` (`loop.db`, `heartbeat.log`, `notify.env`, build worktrees) and `~/Library/Logs/jvn-north-star-loop.{log,err}`.

State never goes into git: briefs quote prod data and the repo is public. Agents on the server read it with `loop.py list`, `loop.py show <N>`, or `loop.py dump` (every idea, its text, full brief, decisions and mistakes, newest first, as markdown).

## Texts and replies (Boop)

`notify.sh` sends through `message-brendan/send.sh` (Sendblue), then writes the same text into Brendan's Boop conversation as an assistant message via Convex `messages:send` (the call Boop's own automations use). The stored copy carries a note telling Boop what to run, so when he replies "yes 4 6" Boop already has the ideas in context. One-time setup on the server, in `~/Library/Application Support/jvn-north-star-loop/notify.env` (not in git):

```sh
BOOP_DIR=/path/to/boop-agent            # the checkout whose .env.local points at Boop's Convex deployment
BOOP_CONVERSATION_ID=sms:+1XXXXXXXXXX   # the id Boop uses for Brendan's thread ("sms:" + his number)
# SEND_WRITES_BOOP_HISTORY=1            # only if send.sh already records into Boop
```

Without it, texts still go out, but `notify.sh` exits 4 and the run logs a mistake, because Boop would see the reply without the question. Boop turns a reply into one command per number, run from the repo root on the server:

```sh
python3 scripts/north_star_loop/loop.py decide <N> yes                    # once per picked small idea
python3 scripts/north_star_loop/loop.py decide <N> no <reason words...>   # small or big
```

`decide` refuses a yes on a big initiative (the loop never builds those) and a yes beyond 3 small ideas in flight. Each scheduled fire (every ~4h) builds the next picked idea. Without Boop, run the commands yourself.

A **"NS-N paused: ..."** text means a no-mistakes gate is waiting on you; the idea keeps its in-flight slot and is never rebuilt by the schedule. Answer the gate, then run one of:

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
python3 scripts/north_star_loop/loop.py dump                     # everything as markdown: texts, briefs, events
tail -5 "$HOME/Library/Application Support/jvn-north-star-loop/heartbeat.log"
```

Dry run anywhere (no texts, ClickUp writes or pushes): invoke the `north-star-loop` skill in a Claude session with `JVN_LOOP_DRY_RUN=1`, `JVN_LOOP_DB` pointing at a throwaway file, and `JVN_LOOP_STATE_DIR` at a throwaway folder. A real run with a missing `send.sh` is an error, not a silent dry run. `JVN_LOOP_SEND` overrides the send script path.

## Design notes

- **The brief is the hand-off.** The builder reads the proposer's full evidence, scores and reasoning, not one sentence. Unapproved ideas never reach `main`; they live only in the local DB.
- **Small vs big is the agent's judgment**, stated in each brief: small = it could build it in one run and one PR, with nothing Brendan must do first, and he would merge after a skim; big = he would want to own it. Big initiatives are surfaced, never built. There is no size cap; ideas are ranked by Impact × Confidence ÷ Effort.
- **Up to 3 small ideas in flight** (approved through PR open). Ideas shipped close together confound each other's before/after readouts; each readout names the others in its window.
- **No A/B split yet.** At ~10 signups a month a 50/50 flag halves an already tiny sample; readouts are before/after with named confounders and say "inconclusive" when n is small. Revisit flags once weekly signups reach ~60.
- The wrapper and paths assume the server laptop (`/Users/bpotter`, main checkout at `~/developer/personal/Job-Visualizer-Notifier`), like `scripts/health_watch/`. Keep that checkout on `main`; skill edits take effect only once it has them.
