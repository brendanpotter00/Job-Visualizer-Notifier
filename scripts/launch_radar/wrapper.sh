#!/bin/sh
# Wraps `claude -p /launch-radar-once` for the daily LaunchAgent
# (com.bp.jvn-launch-radar). Copied from scripts/health_watch/wrapper.sh — lock,
# process-group watchdog, hard wall-clock cap, heartbeat mtime check — with
# these differences:
#
#   * CLAUDE_BIN and PROJECT_DIR come from the environment the plist sets
#     (install_launch_agent.sh fills them in). Nothing user-specific is
#     hard-coded here, so the same file runs on this laptop and the server one.
#   * NO --dangerously-skip-permissions. The radar reads web text and runs with
#     the backend's internal key in reach (inside radar.sh), so a prompt
#     injection must not get a free shell, a way to upload a file, or a push to
#     main. The session gets an explicit --allowedTools allowlist (the
#     ALLOWED_TOOLS block below is the ONE place it is defined; SKILL.md §0
#     quotes it) and anything outside it is denied in headless mode. Every Bash
#     entry is a FIXED command or one of two fixed entry points:
#       - scripts/launch_radar/radar.sh with the exact headless arguments
#         (so the per-run limits of 3 companies / $1.00 are not just prose);
#       - scripts/launch_radar/pr_step.py, which validates every value and runs
#         git / gh / pip / the logo scripts itself with fixed argv lists.
#     There is deliberately NO generic git, gh, curl, python, pip or npm entry:
#     each of those can run code or send a local file anywhere. File tools are
#     scoped to this checkout, writes to the temp radar-* worktrees only, and
#     the env file, dotfiles and .env files are denied outright.
#   * This wrapper never sources or exports a secret. radar.sh loads
#     ~/.config/jvn-launch-radar/env into its own process tree only.
#   * No texting: failures land in ~/Library/Logs/jvn-launch-radar.err and the
#     heartbeat log.

set -u

: "${CLAUDE_BIN:?CLAUDE_BIN must be set (the plist sets it)}"
: "${PROJECT_DIR:?PROJECT_DIR must be set (the plist sets it)}"

STATE_DIR="$HOME/Library/Application Support/jvn-launch-radar"
HEARTBEAT="$STATE_DIR/heartbeat.log"
LOCK_DIR="$STATE_DIR/.run.lock"
TOTAL_TIMEOUT_SECS="${JVN_RADAR_TIMEOUT_SECS:-5400}"   # 90 min hard cap

log()     { echo "[wrapper] $(date -u +%FT%TZ) $*"; }
log_err() { echo "[wrapper] $(date -u +%FT%TZ) $*" >&2; }

mkdir -p "$STATE_DIR"

# Single-flight: launchd serialises same-label fires, but a manual run can
# overlap a scheduled one. mkdir is atomic; a stale lock older than the total
# timeout is reclaimed.
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

# --- process-group control (from scripts/health_watch/wrapper.sh) -------------
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
  reap_group "$_rb_label" "$_rb_pid" 5
}
# -----------------------------------------------------------------------------

log "start (timeout=${TOTAL_TIMEOUT_SECS}s) host=$(hostname -s)"
cd "$PROJECT_DIR" || { log_err "cd to project dir failed"; exit 1; }

BEAT_BEFORE=$(stat -f %m "$HEARTBEAT" 2>/dev/null || echo 0)

# ALLOWED_TOOLS-BEGIN (tests/unit/test_launch_radar_wrapper.py parses this block)
run_bounded launch-radar "$TOTAL_TIMEOUT_SECS" \
  "$CLAUDE_BIN" -p /launch-radar-once \
  --allowedTools "Read(./**)" "Edit(./.claude/worktrees/radar-*/**)" "Write(./.claude/worktrees/radar-*/**)" "Agent" \
    "WebSearch" "WebFetch" \
    "Bash(scripts/launch_radar/radar.sh monitors-ensure)" \
    "Bash(scripts/launch_radar/radar.sh run --max-companies 3 --budget 1.00)" \
    "Bash(scripts/launch_radar/radar.sh run --max-companies 0 --budget 1.00)" \
    "Bash(scripts/launch_radar/radar.sh pr-candidates --limit 1)" \
    "Bash(scripts/launch_radar/radar.sh set-pr:*)" "Bash(scripts/launch_radar/radar.sh heartbeat:*)" \
    "Bash(scripts/launch_radar/pr_step.py:*)" \
  --disallowedTools "Read(~/.config/jvn-launch-radar/**)" "Read(~/.ssh/**)" "Read(~/.aws/**)" \
    "Read(~/.zshrc)" "Read(~/.zprofile)" "Read(~/.zshenv)" "Read(~/.bash_profile)" "Read(~/.bashrc)" \
    "Read(~/.netrc)" "Read(~/.config/gh/**)" "Read(./**/.env)" "Read(./**/.env.*)" "Read(./.vercel/**)" \
    "Read(./.git/**)" "Read(./.idea/**)" "Read(./.vscode/**)" "Read(./.mcp.json)" "Read(./.claude/settings*.json)" \
    "Read(./.playwright/**)" "Read(./.playwright-mcp/**)" \
    "Edit(./.claude/worktrees/*/.git)" "Write(./.claude/worktrees/*/.git)" \
    "Bash(env:*)" "Bash(printenv:*)"
# ALLOWED_TOOLS-END
STATUS=$RUN_BOUNDED_STATUS

# The skill's LAST step appends a heartbeat line. Exit 0 without the file's
# mtime advancing means the session ended early or wedged.
BEAT_AFTER=$(stat -f %m "$HEARTBEAT" 2>/dev/null || echo 0)
if [ "$STATUS" -eq 0 ] && [ "$BEAT_AFTER" -le "$BEAT_BEFORE" ]; then
  log_err "claude exited 0 but heartbeat did not advance — marking failed"
  STATUS=97
fi

# claude exits 0 even when the skill recorded a failed run (radar.sh exit 1, a
# company erroring every day, a 422 on a card, a failed PR step). Surface that
# in the .err log and launchd's exit status instead of only in heartbeat.log.
# The line is "<iso-ts> status=<ok|error> <note>": read field 2 only, so a note
# that happens to contain the text "status=error" cannot trip it.
if [ "$STATUS" -eq 0 ]; then
  LAST_BEAT=$(tail -n 1 "$HEARTBEAT" 2>/dev/null || true)
  BEAT_STATUS=$(printf '%s\n' "$LAST_BEAT" | awk '{print $2}')
  if [ "$BEAT_STATUS" = "status=error" ]; then
    log_err "launch-radar reported status=error: $LAST_BEAT"
    STATUS=98
  fi
fi

if [ "$STATUS" -ne 0 ]; then
  log_err "launch-radar FAILED exit=$STATUS"
fi
log "end status=${STATUS}"
exit "$STATUS"
