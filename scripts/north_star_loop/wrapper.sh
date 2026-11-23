#!/bin/sh
# launchd entry point for the north-star loop (see README.md here).
#
# Token-free when there is nothing to do: `loop.py sync` (merge detection,
# expiry) and `loop.py next` run first, and Claude starts only when `next`
# names an action. Same safety shell as scripts/health_watch/wrapper.sh:
# single-flight lock, hard wall-clock cap with a process-group kill,
# heartbeat-advance check, and a failure text at most once per 6h.
set -u

CLAUDE_BIN="/Users/bpotter/.local/bin/claude"
PROJECT_DIR="${JVN_LOOP_PROJECT_DIR:-/Users/bpotter/developer/personal/Job-Visualizer-Notifier}"
STATE_DIR="${JVN_LOOP_STATE_DIR:-$HOME/Library/Application Support/jvn-north-star-loop}"
HEARTBEAT="$STATE_DIR/heartbeat.log"
LOCK_DIR="$STATE_DIR/.run.lock"
FAIL_STAMP="$STATE_DIR/wrapper-fail-last-text"
TIMEOUT_SECS="${JVN_LOOP_TIMEOUT_SECS:-5400}"   # 90 min
FAIL_COOLDOWN_SECS=21600                         # 6h

log() { echo "[north-star] $(date -u +%FT%TZ) $*"; }
mkdir -p "$STATE_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  age=$(( $(date +%s) - $(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0) ))
  if [ "$age" -le "$TIMEOUT_SECS" ]; then log "another run holds the lock; skipping"; exit 0; fi
  log "reclaiming stale lock (age=${age}s)"
  rmdir "$LOCK_DIR" 2>/dev/null; mkdir "$LOCK_DIR" 2>/dev/null || exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

cd "$PROJECT_DIR" || { log "cd $PROJECT_DIR failed" >&2; exit 1; }
LOOP="python3 scripts/north_star_loop/loop.py"
NOTIFY="scripts/north_star_loop/notify.sh"   # send.sh + Boop history

$LOOP sync || log "sync failed (continuing)" >&2
ACTION=$($LOOP next) || { log "next failed" >&2; exit 1; }
if [ "$ACTION" = "none" ]; then
  echo "$(date -u +%FT%TZ) mode=idle ns=- outcome=none texts=0" >> "$HEARTBEAT"
  log "nothing to do"
  exit 0
fi

log "action: $ACTION (timeout=${TIMEOUT_SECS}s)"
BEAT_BEFORE=$(stat -f %m "$HEARTBEAT" 2>/dev/null || echo 0)

# Run claude in its own process group; a timer kills the whole group at the cap.
set -m
"$CLAUDE_BIN" -p "/north-star-once $ACTION" --dangerously-skip-permissions &
PID=$!
( sleep "$TIMEOUT_SECS"; kill -TERM "-$PID" 2>/dev/null; sleep 15; kill -KILL "-$PID" 2>/dev/null ) &
TIMER=$!
set +m
wait "$PID"; STATUS=$?
kill -TERM "-$TIMER" 2>/dev/null; kill "$TIMER" 2>/dev/null
kill -KILL "-$PID" 2>/dev/null || true   # reap any descendant that outlived the leader

BEAT_AFTER=$(stat -f %m "$HEARTBEAT" 2>/dev/null || echo 0)
if [ "$STATUS" -eq 0 ] && [ "$BEAT_AFTER" -le "$BEAT_BEFORE" ]; then
  log "claude exited 0 but the heartbeat did not advance" >&2
  STATUS=97
fi

if [ "$STATUS" -ne 0 ]; then
  log "FAILED exit=$STATUS" >&2
  if [ ! -f "$FAIL_STAMP" ] || [ $(( $(date +%s) - $(stat -f %m "$FAIL_STAMP") )) -ge "$FAIL_COOLDOWN_SECS" ]; then
    sh "$NOTIFY" "North-star loop FAILED ($ACTION, exit $STATUS). See ~/Library/Logs/jvn-north-star-loop.err"
    # 0 = sent + in Boop history; 4/5 = sent but not in history. Either way it went out.
    case $? in 0|4|5) touch "$FAIL_STAMP" ;; esac
  fi
fi
log "end status=$STATUS"
exit "$STATUS"
