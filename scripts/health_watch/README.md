# scraper-health-watch — every-3h watchdog runbook

The agentic watchdog for JVN's scrape pipeline, fired **every 3h** by launchd.
The logic lives in `.claude/skills/scraper-health-watch/SKILL.md` (single source
of truth — any Claude session can invoke it interactively). This directory is the
scheduling shell around it.

**What a run does:** read-only SQL against prod (silent-zero/staleness,
**fleet-wide coverage collapse**, mass-closure, worker heartbeat) → if something is
wrong, probe the dead board, research where it moved (subagent), open a fix PR
(**never merges**), and text Brendan via the `message-brendan` skill (SendBlue).
An **active outage** (worker dead, coverage collapse, mass closure) re-alerts on
**every run** until it clears — no 72h self-suppression (that silenced the
2026-08-29 outage after one text). Drift (a single moved board) still dedupes on
its open PR. Healthy runs are silent except a heartbeat log line; one all-clear
text goes out if none has been sent for ~a week, so a silent watchdog is
distinguishable from a healthy system.

## Pieces

| Path | Role |
|---|---|
| `.claude/skills/scraper-health-watch/SKILL.md` | The watchdog procedure (+ `templates/` for the fix migration & PR body) |
| `.claude/commands/health-watch-once.md` | Headless shim the wrapper invokes (`claude -p /health-watch-once`) |
| `scripts/health_watch/wrapper.sh` | launchd entry point: 90-min hard timeout, process-group kill, single-flight lock, heartbeat-advance check, 6h-cooldown failure text |
| `scripts/health_watch/com.bp.jvn-health-watch.plist.template` | LaunchAgent definition (every 3h — `StartCalendarInterval` array of 8 slots) |
| `scripts/health_watch/install_launch_agent.sh` | Idempotent install/reinstall |

Runtime state (not in the repo):

- `~/Library/Application Support/jvn-health-watch/heartbeat.log` — one line per
  run (any verdict). `tail -1` proves the watchdog ran and what it found.
- `~/Library/Application Support/jvn-health-watch/state.json` — last-texted
  timestamps per alert key + `last_allclear` (weekly all-clear gate).
- `~/Library/Logs/jvn-health-watch.{log,err}` — full run output. **No rotation;
  grows unbounded** (same caveat as job-watcher).

## Ops

```sh
sh scripts/health_watch/install_launch_agent.sh          # install / reinstall
launchctl kickstart gui/$(id -u)/com.bp.jvn-health-watch # fire now
launchctl print gui/$(id -u)/com.bp.jvn-health-watch     # status + next fire
launchctl bootout gui/$(id -u)/com.bp.jvn-health-watch   # pause (uninstall)
tail -f ~/Library/Logs/jvn-health-watch.log              # watch a run
tail -5 "$HOME/Library/Application Support/jvn-health-watch/heartbeat.log"
sh scripts/health_watch/wrapper.sh                       # manual headless run
```

Supervised interactive run (recommended after changing the skill): in a Claude
session at the repo root, invoke the `scraper-health-watch` skill and watch it
end-to-end. Drills that exercise the alert path without real findings:
`scraper-health-watch drill unknown`, `drill heartbeat` (texts get a `[DRILL]`
prefix; 72h cooldown per scenario).

## Design notes / caveats

- **Dedupe drift, never an outage:** open PRs labeled `scraper-health` carry a
  machine-readable `Companies:` line; companies already covered by an open PR
  never re-text. **CRITICAL alerts (worker dead, coverage collapse, mass closure,
  prod unreachable) re-text every run** with an escalating duration — no cooldown
  (SKILL.md §4.2). Only informational, known-needs-human alerts (`notfound:*`,
  drills) cool down 72h via `state.json`.
- **Safety boundary:** the skill's §0 hard rules — prod strictly read-only,
  never merge/deploy, repo writes only in a throwaway worktree. The fix
  migration's stale-row close-out executes only when Brendan merges + deploys.
- **Sleep semantics:** `StartCalendarInterval` fires once on wake if the Mac
  slept through a 3h slot; a fully-off Mac skips those slots. The wrapper's 90-min
  cap means a wedged run can never block the next slot's fire (see job-watcher's
  2026-07-26 44h-wedge incident for why this is load-bearing).
- **Failure visibility:** wrapper failures (nonzero exit, or exit 0 without the
  heartbeat advancing) text Brendan at most once per 6h. If SendBlue itself is
  down, the watchdog is dark — which is exactly what the weekly all-clear text
  makes detectable (its absence over ~a week means check the logs).
- `claude` binary path is hardcoded to `/Users/bpotter/.local/bin/claude` in
  the wrapper (the installer-managed symlink); a Claude Code install-path
  change silently broke job-watcher once. If ticks start failing with
  "binary not found", fix `CLAUDE_BIN` there.
- The scheduled fire runs from the **main checkout** (`PROJECT_DIR`), so
  `/health-watch-once` and the skill resolve from whatever branch is checked
  out there. If that branch predates the watchdog files, the run fails — the
  heartbeat-advance check catches it and the wrapper texts (6h cooldown).
  Keep the main checkout on `main`, or export `JVN_HEALTH_PROJECT_DIR` to a
  checkout that has the files. **Editing the skill only takes effect once the
  main checkout has the new SKILL.md** (merge to `main` + update that checkout,
  or point `JVN_HEALTH_PROJECT_DIR` at a checkout that already has it).
