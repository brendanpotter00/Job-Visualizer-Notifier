#!/bin/sh
# Headless wrapper for the launchd StartInterval worker. Mirrors job-watcher:
# pre-acquire the lock, pre-pull + pre-clean deterministically, THEN hand off to
# `claude -p /enrich-tick-once` for the agentic classify/judge/write-back.
#
# Lock ownership: tick-acquire's own PID dies immediately (it is a short-lived
# subprocess), so after a successful acquire the wrapper REWRITES the lock with
# its OWN pid — the wrapper lives for the whole tick, making `kill -0` checks
# meaningful — and exports ENRICH_LOCK_OWNER_PID so tick-end (a child process,
# hence a different pid) can still release the delegated lock. The EXIT trap
# only ever runs when THIS wrapper acquired the lock (never on the exit-75
# "lock held" path), only removes a lock that records OUR pid, and age-gates
# (3h, mirroring lock.py's stale backstop) the never-expected case of a dead
# foreign holder.
set -u

CLAUDE_BIN="/Users/bpotter/.local/bin/claude"
PROJECT_DIR="/Users/bpotter/developer/personal/job-enricher"
UV_BIN="/opt/homebrew/bin/uv"
LOCK_FILE="$PROJECT_DIR/data/.tick.lock"
TIMEOUT_SECS="${ENRICH_TICK_TIMEOUT_SECS:-10800}"
STALE_SECS=10800  # 3h — keep in sync with lock.py DEFAULT_STALE_HOURS

ACQUIRED=0

cleanup_lock() {
  # No-op unless THIS wrapper acquired the lock — a lock observed on the
  # exit-75 path belongs to a live tick and must never be touched.
  [ "$ACQUIRED" = "1" ] || return 0
  [ -f "$LOCK_FILE" ] || return 0
  LOCK_PID=$(cut -d'|' -f1 "$LOCK_FILE")
  if [ "$LOCK_PID" = "$$" ]; then
    # Our own lock survived (tick crashed before tick-end) — safe to clear.
    rm -f "$LOCK_FILE" && echo "[wrapper] $(date -u +%FT%TZ) cleared own lock (pid=$$)"
    return 0
  fi
  # Someone else's lock (a new tick started after ours released). Only clear
  # it if the holder is dead AND the file has aged past the stale backstop.
  case "$LOCK_PID" in
    ''|0|*[!0-9]*) return 0 ;;
  esac
  if kill -0 "$LOCK_PID" 2>/dev/null; then
    return 0  # live holder — leave it
  fi
  NOW=$(date +%s)
  MTIME=$(stat -f %m "$LOCK_FILE" 2>/dev/null || echo "$NOW")
  AGE=$((NOW - MTIME))
  if [ "$AGE" -ge "$STALE_SECS" ]; then
    rm -f "$LOCK_FILE" && echo "[wrapper] $(date -u +%FT%TZ) cleared stale foreign lock (dead pid=$LOCK_PID age=${AGE}s)"
  fi
}
trap cleanup_lock EXIT

cd "$PROJECT_DIR" || exit 1

ACQ_OUT=$("$UV_BIN" run python -m job_enricher.cli tick-acquire 2>&1)
ACQ=$?
printf '%s\n' "$ACQ_OUT"
if [ "$ACQ" -eq 75 ]; then
  echo "[wrapper] lock held; skipping this fire"
  exit 0
elif [ "$ACQ" -ne 0 ]; then
  echo "[wrapper] tick-acquire failed (exit=$ACQ)"
  exit "$ACQ"
fi
ACQUIRED=1

# Take ownership of the lock for the tick's lifetime (see header comment).
printf '%s|%s' "$$" "$(date -u +%FT%TZ)" > "$LOCK_FILE" \
  || echo "[wrapper] failed to rewrite lock owner (continuing)"
ENRICH_LOCK_OWNER_PID="$$"
export ENRICH_LOCK_OWNER_PID

# Export the tick id so tick-end can refuse to close a tick it doesn't own.
TICK_ID=$(printf '%s\n' "$ACQ_OUT" | sed -n 's/.*tick_id=\([0-9][0-9]*\).*/\1/p' | head -1)
if [ -n "$TICK_ID" ]; then
  ENRICH_TICK_ID="$TICK_ID"
  export ENRICH_TICK_ID
fi

# Deterministic pre-work (safe to fail softly; the agent can retry inside)
"$UV_BIN" run python -m job_enricher.cli pull  || echo "[wrapper] pull failed (continuing)"
"$UV_BIN" run python -m job_enricher.cli clean || echo "[wrapper] clean failed (continuing)"

"$CLAUDE_BIN" -p /enrich-tick-once --dangerously-skip-permissions &
PID=$!
( sleep "$TIMEOUT_SECS"; kill -TERM "$PID" 2>/dev/null; sleep 10; kill -KILL "$PID" 2>/dev/null ) &
WATCHDOG=$!
wait "$PID"
STATUS=$?
kill "$WATCHDOG" 2>/dev/null

# Best-effort metrics push to JVN — always runs, even after a timeout/kill
# (the tick may report status running/error). Never fails the wrapper.
"$UV_BIN" run python -m job_enricher.cli metrics-push \
  || echo "[wrapper] metrics-push failed (continuing)"

exit "$STATUS"
