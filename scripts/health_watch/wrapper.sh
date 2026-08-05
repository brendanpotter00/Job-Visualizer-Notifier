#!/bin/sh
# Wraps `claude -p /health-watch-once` with a hard wall-clock timeout so a hung
# session can't wedge the daily LaunchAgent. Pattern ported from
# job-watcher/scripts/watch_tick_wrapper.sh (see its header for the incident
# history behind every choice here: the 44h unbounded-fetch wedge, the
# end-anchored StartInterval gotcha, and the process-group kill rationale).
#
# This agent uses StartCalendarInterval (daily 09:00), which is wall-clock
# anchored and fires once on wake if the Mac slept through it — but a run that
# never exits still blocks the NEXT day's fire, so the cap stays load-bearing.
#
# Healthy path: ~3-5 min (SQL checks + heartbeat). Incident path adds a research
# subagent (~10 min), an `npm ci` in a throwaway worktree, and a PR — 90 min is
# generous headroom without letting a wedge eat the day.

set -u

# Claude Code moved from the old npm-local shim to the native installer path.
# The old path's removal silently broke job-watcher's ticks on 2026-06-30 —
# hardcode the installer-managed symlink, never rely on PATH.
CLAUDE_BIN="/Users/bpotter/.local/bin/claude"
PROJECT_DIR="/Users/bpotter/developer/personal/Job-Visualizer-Notifier"
SEND="/Users/bpotter/.claude/skills/message-brendan/send.sh"
STATE_DIR="$HOME/Library/Application Support/jvn-health-watch"
HEARTBEAT="$STATE_DIR/heartbeat.log"
LOCK_DIR="$STATE_DIR/.run.lock"
FAIL_TEXT_STAMP="$STATE_DIR/wrapper-fail-last-text"

TOTAL_TIMEOUT_SECS="${JVN_HEALTH_TIMEOUT_SECS:-5400}"   # 90 min hard cap
FAIL_TEXT_COOLDOWN_SECS=259200                          # 72h between wrapper-failure texts

log()     { echo "[wrapper] $(date -u +%FT%TZ) $*"; }
log_err() { echo "[wrapper] $(date -u +%FT%TZ) $*" >&2; }

mkdir -p "$STATE_DIR"

# Single-flight: launchd serialises same-label fires, but a manual run can
# overlap a scheduled one. mkdir is atomic; a stale lock older than the total
# timeout is reclaimed (the previous holder is dead or about to be killed).
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  lock_age=$(( $(date +%s) - $(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0) ))
  if [ "$lock_age" -gt "$TOTAL_TIMEOUT_SECS" ]; then
    log "reclaiming stale run lock (age=${lock_age}s)"
    rmdir "$LOCK_DIR" 2>/dev/null || true
    mkdir "$LOCK_DIR" 2>/dev/null || { log "lock contention after reclaim; skipping fire"; exit 0; }
  else
    log "another run holds the lock (age=${lock_age}s); skipping fire"
    exit 0
  fi
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# --- process-group control, ported from job-watcher ---------------------------
# Killing a hung step means killing the whole tree (claude -> node -> child
# shells). Process groups survive the leader's death, so signal the GROUP, and
# test liveness on the GROUP — never the leader pid.
group_alive()  { kill -0 "-$1" 2>/dev/null; }
signal_group() { kill "-$1" "-$2" 2>/dev/null || true; }

reap_group() {
  _label="$1"; _pgid="$2"; _grace="$3"
  group_alive "$_pgid" || return 0
  log_err "${_label}: SIGTERM process group ${_pgid}"
  signal_group TERM "$_pgid"
  _waited=0
  while [ "$_waited" -lt "$_grace" ] && group_alive "$_pgid"; do
    sleep 1
    _waited=$((_waited + 1))
  done
  if group_alive "$_pgid"; then
    log_err "${_label}: survivors after ${_grace}s — SIGKILL group ${_pgid}"
    signal_group KILL "$_pgid"
  fi
}

watchdog() {
  _label="$1"; _pgid="$2"; _budget="$3"
  sleep "$_budget"
  group_alive "$_pgid" || return 0
  log_err "${_label} exceeded ${_budget}s"
  reap_group "$_label" "$_pgid" 15
}

stop_watchdog() {
  [ -n "${1:-}" ] || return 0
  signal_group TERM "$1"
  wait "$1" 2>/dev/null || true
}

# Run "$@" under a wall-clock budget, in its own process group. Sets
# RUN_BOUNDED_STATUS (143/137 when the watchdog killed it).
run_bounded() {
  _rb_label="$1"; _rb_budget="$2"
  shift 2
  set -m
  "$@" &
  _rb_pid=$!
  set +m
  set -m
  watchdog "$_rb_label" "$_rb_pid" "$_rb_budget" &
  _rb_timer=$!
  set +m
  wait "$_rb_pid"
  RUN_BOUNDED_STATUS=$?
  stop_watchdog "$_rb_timer"
  # `wait` returns when the LEADER exits; a wedged descendant would outlive it.
  reap_group "$_rb_label" "$_rb_pid" 5
}
# -----------------------------------------------------------------------------

cooldown_expired() {
  # $1 = stamp file, $2 = cooldown seconds. True if no stamp or stamp is old.
  [ -f "$1" ] || return 0
  _age=$(( $(date +%s) - $(stat -f %m "$1" 2>/dev/null || echo 0) ))
  [ "$_age" -ge "$2" ]
}

log "start (timeout=${TOTAL_TIMEOUT_SECS}s)"
cd "$PROJECT_DIR" || { log_err "cd to project dir failed"; exit 1; }

BEAT_BEFORE=$(stat -f %m "$HEARTBEAT" 2>/dev/null || echo 0)

run_bounded health-watch "$TOTAL_TIMEOUT_SECS" \
  "$CLAUDE_BIN" -p /health-watch-once --dangerously-skip-permissions
STATUS=$RUN_BOUNDED_STATUS

# The skill's LAST step appends a heartbeat line. Exit 0 without the file's
# mtime advancing means the session ended early/wedged — treat as failure so
# a silently-dead watchdog can never look healthy.
BEAT_AFTER=$(stat -f %m "$HEARTBEAT" 2>/dev/null || echo 0)
if [ "$STATUS" -eq 0 ] && [ "$BEAT_AFTER" -le "$BEAT_BEFORE" ]; then
  log_err "claude exited 0 but heartbeat did not advance — marking failed"
  STATUS=97
fi

if [ "$STATUS" -ne 0 ]; then
  log_err "health-watch FAILED exit=$STATUS"
  # Text at most once per 72h about the watchdog itself being broken. If send
  # ALSO fails, the watchdog is fully dark — logs are the only trace, which is
  # exactly why the weekly all-clear text exists (its absence is the signal).
  if cooldown_expired "$FAIL_TEXT_STAMP" "$FAIL_TEXT_COOLDOWN_SECS"; then
    if "$SEND" "JVN health-watch FAILED to run (exit $STATUS). Check ~/Library/Logs/jvn-health-watch.err"; then
      touch "$FAIL_TEXT_STAMP"
    else
      log_err "send.sh ALSO failed — watchdog is dark"
    fi
  else
    log "failure text suppressed (72h cooldown)"
  fi
fi

log "end status=${STATUS}"
exit "$STATUS"
