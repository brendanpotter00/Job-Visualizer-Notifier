# scraper-health-watch — daily watchdog runbook

The daily agentic watchdog for JVN's scrape pipeline. The logic lives in
`.claude/skills/scraper-health-watch/SKILL.md` (single source of truth — any
Claude session can invoke it interactively). This directory is the scheduling
shell around it.

**What a daily run does:** read-only SQL against prod (silent-zero/staleness,
mass-closure, worker heartbeat) → if something is wrong, probe the dead board,
research where it moved (subagent), open a fix PR (**never merges**), and text
Brendan via the `message-brendan` skill (SendBlue) with the PR link. Healthy
runs are silent except a heartbeat log line; one all-clear text goes out if
none has been sent for ~a week, so a silent watchdog is distinguishable from a
healthy system.

## Pieces

| Path | Role |
|---|---|
| `.claude/skills/scraper-health-watch/SKILL.md` | The watchdog procedure (+ `templates/` for the fix migration & PR body) |
| `.claude/commands/health-watch-once.md` | Headless shim the wrapper invokes (`claude -p /health-watch-once`) |
| `scripts/health_watch/wrapper.sh` | launchd entry point: 90-min hard timeout, process-group kill, single-flight lock, heartbeat-advance check, 72h-cooldown failure text |
| `scripts/health_watch/com.bp.jvn-health-watch.plist.template` | LaunchAgent definition (daily 09:00, `StartCalendarInterval`) |
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

- **Dedupe is stateless-first:** open PRs labeled `scraper-health` carry a
  machine-readable `Companies:` line; companies already covered by an open PR
  never re-text. Non-PR alerts (worker dead, prod unreachable, mass closure,
  research dead-end) cool down 72h via `state.json`.
- **Safety boundary:** the skill's §0 hard rules — prod strictly read-only,
  never merge/deploy, repo writes only in a throwaway worktree. The fix
  migration's stale-row close-out executes only when Brendan merges + deploys.
- **Sleep semantics:** `StartCalendarInterval` fires once on wake if the Mac
  slept through 09:00; a fully-off Mac skips that day. The wrapper's 90-min cap
  means a wedged run can never block the next day's fire (see job-watcher's
  2026-07-26 44h-wedge incident for why this is load-bearing).
- **Failure visibility:** wrapper failures (nonzero exit, or exit 0 without the
  heartbeat advancing) text Brendan at most once per 72h. If SendBlue itself is
  down, the watchdog is dark — which is exactly what the weekly all-clear text
  makes detectable (its absence over ~a week means check the logs).
- `claude` binary path is hardcoded to `/Users/bpotter/.local/bin/claude` in
  the wrapper (the installer-managed symlink); a Claude Code install-path
  change silently broke job-watcher once. If ticks start failing with
  "binary not found", fix `CLAUDE_BIN` there.
- The daily fire runs from the **main checkout** (`PROJECT_DIR`), so
  `/health-watch-once` and the skill resolve from whatever branch is checked
  out there. If that branch predates the watchdog files, the run fails — the
  heartbeat-advance check catches it and the wrapper texts (72h cooldown).
  Keep the main checkout on `main`, or export `JVN_HEALTH_PROJECT_DIR` to a
  checkout that has the files.
