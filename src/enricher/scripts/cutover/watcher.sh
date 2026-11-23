#!/bin/bash
# The merge trigger for the enricher cutover. launchd (com.bp.jvn-enricher-cutover)
# runs a COPY of this file from the state dir every 5 minutes; install_watcher.sh
# puts it there. It never runs from a checkout's working tree: branches move.
#
# Each fire:
#   1. state.json terminal (DONE / FAILED / ROLLED_BACK) -> retire this agent and exit.
#   2. single flight (mkdir lock + pid; a dead or pre-boot holder is reclaimed).
#   3. refresh the bare JVN mirror (main + tags). Network down -> retry next interval.
#   4. main lacks src/enricher/scripts/cutover/cutover.py -> "not merged yet", exit 0.
#   5. extract src/enricher/scripts from MERGED main and exec its cutover.sh --run,
#      so the cutover that runs is always the reviewed, merged one.
#
# bash 3.2-safe (macOS /bin/bash). Wall-clock deadlines only (`date +%s`) polled in
# 1 s steps — never one long sleep, which stalls while the laptop sleeps.
set -u

STATE="${CUTOVER_STATE_DIR:-$HOME/Library/Application Support/jvn-enricher-cutover}"
REMOTE="${JVN_REMOTE_URL:-https://github.com/brendanpotter00/Job-Visualizer-Notifier.git}"
LAUNCHCTL="${LAUNCHCTL:-launchctl}"
GIT="${CUTOVER_GIT_BIN:-git}"
LABEL="com.bp.jvn-enricher-cutover"
PLIST="${CUTOVER_WATCHER_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}"
NET_TIMEOUT="${CUTOVER_WATCHER_NET_TIMEOUT_S:-300}"
CUTOVER_REL="src/enricher/scripts/cutover/cutover.py"

export GIT_TERMINAL_PROMPT=0 GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=30

log() { echo "[watcher $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# run_with_timeout SECONDS CMD... -> the command's status, or 124 when killed.
run_with_timeout() {
  local secs="$1"; shift
  "$@" &
  local pid=$!
  local deadline=$(( $(date +%s) + secs ))
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      kill -TERM "$pid" 2>/dev/null
      sleep 2
      kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
    sleep 1
  done
  wait "$pid"
}

boot_epoch() {
  sysctl -n kern.boottime 2>/dev/null | sed -n 's/.*sec = \([0-9][0-9]*\).*/\1/p'
}

mkdir -p "$STATE" || { log "cannot create $STATE"; exit 0; }

# 1. Terminal state: this agent's job is over.
if [ -f "$STATE/state.json" ] \
   && grep -Eq '^  "phase": "(DONE|FAILED|ROLLED_BACK)"' "$STATE/state.json"; then
  PHASE="$(sed -n 's/^  "phase": "\([A-Z_]*\)".*/\1/p' "$STATE/state.json" | head -1)"
  log "cutover is $PHASE; retiring the watcher"
  mkdir -p "$STATE/retired"
  if [ -f "$PLIST" ]; then
    mv -f "$PLIST" "$STATE/retired/" || log "could not move $PLIST"
  fi
  "$LAUNCHCTL" remove "$LABEL" 2>/dev/null || true
  exit 0
fi

# 2. Single flight. The lock outlives an `exec` into the cutover (same pid), so a
#    running cutover also blocks the next fire; a dead or pre-boot holder is reclaimed.
LOCK="$STATE/watcher.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  HOLDER="$(cat "$LOCK/pid" 2>/dev/null || echo '')"
  case "$HOLDER" in ''|*[!0-9]*) HOLDER='' ;; esac
  BOOT="$(boot_epoch)"
  MTIME="$(stat -f %m "$LOCK" 2>/dev/null || echo 0)"
  PRE_BOOT=0
  if [ -n "$BOOT" ] && [ "$MTIME" -lt "$BOOT" ]; then PRE_BOOT=1; fi
  if [ "$PRE_BOOT" = "0" ] && [ -n "$HOLDER" ] && kill -0 "$HOLDER" 2>/dev/null; then
    log "another watcher/cutover is running (pid $HOLDER); exiting"
    exit 0
  fi
  if [ "$PRE_BOOT" = "0" ] && [ -z "$HOLDER" ] && [ $(( $(date +%s) - MTIME )) -lt 5 ]; then
    log "another watcher is starting; exiting"
    exit 0
  fi
  rm -rf "$LOCK"
  mkdir "$LOCK" 2>/dev/null || { log "lost the race for $LOCK; exiting"; exit 0; }
fi
echo "$$" > "$LOCK/pid"
release_lock() { rm -rf "$LOCK"; }
trap release_lock EXIT

# 3. Refresh the mirror.
MIRROR="$STATE/jvn.git"
if [ ! -f "$MIRROR/HEAD" ]; then
  TMP="$STATE/jvn.git.tmp-$$"
  rm -rf "$TMP"
  if ! run_with_timeout "$NET_TIMEOUT" "$GIT" clone --bare --quiet "$REMOTE" "$TMP"; then
    rm -rf "$TMP"
    log "clone of $REMOTE failed; retry next interval"
    exit 0
  fi
  mv "$TMP" "$MIRROR"
fi
if ! run_with_timeout "$NET_TIMEOUT" "$GIT" -C "$MIRROR" fetch --quiet --prune --tags origin \
     '+refs/heads/main:refs/heads/main'; then
  log "fetch failed, retry next interval"
  exit 0
fi

# 4. Merged yet?
if ! "$GIT" -C "$MIRROR" cat-file -e "main:$CUTOVER_REL" 2>/dev/null; then
  log "not merged yet (main has no $CUTOVER_REL)"
  exit 0
fi

# 5. Run the cutover FROM MERGED MAIN.
SHA="$("$GIT" -C "$MIRROR" rev-parse main)"
RUN_DIR="$STATE/run/$SHA"
if [ ! -f "$RUN_DIR/src/enricher/scripts/cutover/cutover.sh" ]; then
  TMP="$STATE/run/.tmp-$$"
  rm -rf "$TMP"
  mkdir -p "$TMP"
  "$GIT" -C "$MIRROR" archive main src/enricher/scripts | tar -x -C "$TMP"
  if [ ! -f "$TMP/src/enricher/scripts/cutover/cutover.sh" ] \
     || [ ! -f "$TMP/src/enricher/scripts/lib/park_worker.py" ]; then
    rm -rf "$TMP"
    log "could not extract src/enricher/scripts from main $SHA; retry next interval"
    exit 0
  fi
  rm -rf "$RUN_DIR"
  mv "$TMP" "$RUN_DIR"
fi
log "main $SHA contains the cutover; running it"
trap - EXIT   # the lock now belongs to the cutover (same pid after exec)
exec /bin/sh "$RUN_DIR/src/enricher/scripts/cutover/cutover.sh" --run
