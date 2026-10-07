# Launch Radar loop — runbook

Finds startups that just announced a round or a launch, researches each one with the
Parallel API, and posts one card per company to the admin page `/admin/launch-radar`.
At most one card per run becomes an add-company PR (opened by Claude, never merged).

The procedure lives in `.claude/skills/launch-radar/SKILL.md`; this directory is the
Python loop plus the launchd shell around it. The design is in
`docs/implementations/launch-radar/` (`CONTRACT.md` §6 is this unit).

## Pieces

| Path | Role |
|---|---|
| `radar.sh` | The only entry point. Loads the env file into its own process, then runs `python -m scripts.launch_radar.radar` under `uv` with `parallel-web` and `httpx` |
| `radar.py` | CLI: `monitors-ensure`, `run`, `monitors-cancel`, `pr-candidates`, `set-pr`, `heartbeat` |
| `pipeline.py` | One `run` invocation and the per-company research (FindAll → pedigree Task Group → brief + team tally → ATS check → score → `POST /cards`) |
| `monitors.py` · `leaders.py` · `research.py` · `ats.py` · `scoring.py` · `card.py` | One concern each (see the module docstrings) |
| `backend_client.py` | The backend's internal routes (`/api/internal/launch-radar/*`, `X-Internal-Key`) |
| `state.py` | Resumable local state: `queue.json`, `companies/<domain>.json`, `heartbeat.log` |
| `pr_step.py` | The PR step's only entry point (stdlib, no secrets): worktree, scaffold, Alembic head check, logo fetch/compose, commit + push + `gh pr create` with validated values and a fixed file allowlist |
| `wrapper.sh` | launchd entry: 90-min cap, process-group kill, single-flight lock, heartbeat check (exit 97 if it did not advance, 98 if the skill recorded `status=error`), `--allowedTools` allowlist |
| `com.bp.jvn-launch-radar.plist.template` · `install_launch_agent.sh` | The daily 07:00 LaunchAgent |
| `.claude/commands/launch-radar-once.md` | The headless shim the wrapper runs (`claude -p /launch-radar-once`) |

## How spend is capped

Every billed Parallel call is reserved first with `POST /runs/{uuid}/reserve`. The
backend ledger (`launch_radar_spend`) refuses with 402 past the run's `--budget` or the
global cap (`LAUNCH_RADAR_SPEND_CAP_USD`, default **$5.00**, set only on the backend).
Monitor executions are billed by Parallel on their own schedule, so each run records
them as accrued spend, and when less than $0.10 of the cap is left the loop **cancels the
Monitors** and stops. One company costs about $0.27-0.31:

| step | Parallel call | price |
|---|---|---|
| leaders | FindAll, generator `preview`, `match_limit` 8 | $0.10 |
| brief | Task run on `core` | $0.025 |
| team tally | Task run on `pro` (display only) | $0.10 |
| pedigree | Task Group, one `base` run per leader | $0.01 × leaders |
| Monitors | 3 × `event_stream` on `base`, daily | $0.03 / day |

The ATS board check uses the free public Greenhouse/Ashby/Lever APIs.

## Setup on the always-on server laptop

1. **Checkout + tools.** Clone the repo where launchd should run it, check out `main`,
   and install `uv` at `/opt/homebrew/bin/uv` (`brew install uv`), the Claude Code CLI
   (`claude`, logged in), and `gh` (logged in with push + PR rights on
   `brendanpotter00/Job-Visualizer-Notifier`). Create the PR label once:
   `gh label create launch-radar --description "Opened by the Launch Radar loop"`.
2. **Secrets file**, readable only by you:

   ```sh
   mkdir -p ~/.config/jvn-launch-radar
   install -m 600 /dev/null ~/.config/jvn-launch-radar/env
   ${EDITOR:-vi} ~/.config/jvn-launch-radar/env
   ```

   ```sh
   BACKEND_URL=https://<railway backend host>    # the backend directly, never the Vercel proxy
   INTERNAL_API_KEY=<the backend's INTERNAL_API_KEY>
   PARALLEL_API_KEY=<parallel key>
   ```

   **Do not** export `PARALLEL_API_KEY` (or the internal key) from that laptop's
   `~/.zshrc`. Only `radar.sh` should ever have them, so Claude's own Bash never sees
   them. Leave `LAUNCH_RADAR_STATE_DIR` unset: the wrapper checks the heartbeat in the
   default `~/Library/Application Support/jvn-launch-radar/`.
3. **Smoke test, free:**

   ```sh
   scripts/launch_radar/radar.sh pr-candidates      # backend reachable + key accepted
   scripts/launch_radar/radar.sh run --dry-run      # reads events and /seen; spends nothing
   ```

4. **Create the Monitors** ($0.03, reserved first): `scripts/launch_radar/radar.sh monitors-ensure`.
5. **Headless test of the whole skill** (the same command launchd runs):

   ```sh
   PROJECT_DIR="$PWD" CLAUDE_BIN="$(command -v claude)" sh scripts/launch_radar/wrapper.sh
   tail -3 "$HOME/Library/Application Support/jvn-launch-radar/heartbeat.log"
   ```

6. **Install the LaunchAgent** (daily 07:00): `sh scripts/launch_radar/install_launch_agent.sh`
   (add `--claude-bin /path/to/claude` if `claude` is not on `PATH`).

## Ops

```sh
launchctl kickstart gui/$(id -u)/com.bp.jvn-launch-radar     # fire now
launchctl print gui/$(id -u)/com.bp.jvn-launch-radar         # status + next fire
sh scripts/launch_radar/install_launch_agent.sh --uninstall  # remove the agent
tail -f ~/Library/Logs/jvn-launch-radar.log                  # watch a run
tail -5 "$HOME/Library/Application Support/jvn-launch-radar/heartbeat.log"
scripts/launch_radar/radar.sh monitors-cancel                # stop all Monitor spend (free); confirms each
```

`radar.sh` exit codes: `0` done · `1` error · `2` stopped on the budget · `3` incomplete
(state is saved under `companies/<domain>.json`; the next `run` resumes and never
re-creates a saved step). Exit 3 also covers a transient error (HTTP 429/5xx, a dropped
connection) while collecting a paid-for result or checking the job board: the company
keeps its state and is retried, and only after 6 such invocations is its card posted
with the gap listed under "Research incomplete". A create call that failed in a way
that may still have reached Parallel is reserved again under a `#retryN` step, so the
ledger over-counts a possible double charge rather than missing it.

To pause the radar without losing anything: `monitors-cancel`, then uninstall the agent.
`monitors-ensure` creates fresh Monitors later.

## Design notes

- **Untrusted input.** Monitor events, FindAll candidates and Task outputs are web
  research. The loop copies only known fields, clips text, keeps only http(s) URLs and
  plain board tokens, and never acts on their content. The skill's §0 says the same for
  Claude.
- **No permission skipping.** The wrapper runs `claude` with an explicit
  `--allowedTools` allowlist (one `ALLOWED_TOOLS` block in `wrapper.sh`).
  It never uses `--dangerously-skip-permissions`;
  `tests/unit/test_launch_radar_wrapper.py` fails if that changes. Every Bash entry is
  an exact `radar.sh` command or `pr_step.py`; there is no generic `git`, `gh`, `curl`,
  `python`, `pip` or `npm` entry (each can run code or upload a local file). File
  reads are scoped to the checkout, writes to `.claude/worktrees/radar-*`.
- **Residual risk: PR CI.** A radar PR changes `companies.ts`, `changelog.ts` and a
  seed migration, which the PR's CI executes. `pr_step.py publish` refuses any other
  path (workflows, tests, scripts), but those three files are code. Keep `main`
  protected (require a PR review) and do not expose deploy secrets to `pull_request`
  runs from `radar/*` branches.
- **Missing domains.** News events rarely carry a website, so `resolve.py` looks up each
  domain-less event with one Search API call (`fast`, ~$0.001, reserved first) and keeps the
  top result whose host carries the company name (news, directory and social hosts are skipped).
- **Dedupe.** One card per normalized domain, ever: the loop asks `GET /seen` before any
  spend, and `POST /cards` returns 409 for a domain already posted (archived and deleted
  cards included), which the loop logs as a skip.
- **Tests.** `cd scripts && pytest tests/unit -k launch_radar` — the Parallel SDK and the
  backend are faked (`tests/unit/launch_radar_fakes.py`); nothing touches the network.
