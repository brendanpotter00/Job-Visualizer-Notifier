#!/bin/sh
# FAKE enricher wrapper — an e2e fixture (e2e/enricher-cutover/PLAN.md §2), run
# by the stub launchctl the way launchd runs the real one. It keeps the real
# scripts/enrich_tick_wrapper.sh's lock protocol and nothing else:
#   tick-acquire (exit 75 -> "lock held; skipping this fire", exit 0)
#   -> rewrite the lock with THIS wrapper's pid, export ENRICH_LOCK_OWNER_PID
#   -> the "work" -> tick-end (closes the tick, releases the delegated lock)
#   EXIT trap: clears only a lock that still records our own pid.
set -u

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_FILE="$PROJECT_DIR/data/.tick.lock"
ACQUIRED=0

cleanup_lock() {
  [ "$ACQUIRED" = "1" ] || return 0
  [ -f "$LOCK_FILE" ] || return 0
  if [ "$(cut -d'|' -f1 "$LOCK_FILE")" = "$$" ]; then
    rm -f "$LOCK_FILE" && echo "[fake-wrapper] cleared own lock (pid=$$)"
  fi
}
on_term() {
  # Like the real wrapper TERMed mid-tick (launchd's unload): the tick stays
  # 'running', and the EXIT trap still runs (macOS /bin/sh does run it on SIGTERM),
  # clearing our own lock. Only a SIGKILL or a power loss leaves an orphan lock.
  # A fire TERMed before it owned a tick (it was still starting, or about to exit
  # 75 on a lock the cutover holds) is not a mid-tick kill: launchd's unload can
  # always race a fire that just started, and that fire holds nothing. Only a
  # kill while this wrapper owned a tick counts as "killed".
  if [ "$ACQUIRED" = "1" ]; then
    echo "[fake-wrapper] SIGTERM mid-tick (pid=$$)"
    ev=killed
  else
    echo "[fake-wrapper] SIGTERM before owning a tick (pid=$$)"
    ev=killed_idle
  fi
  if [ -n "${FAKE_EVENTS:-}" ]; then
    printf '{"ev": "%s", "pid": %s, "dir": "%s"}\n' "$ev" "$$" "$PROJECT_DIR" >> "$FAKE_EVENTS"
  fi
  exit 143
}
trap cleanup_lock EXIT
trap on_term TERM

cd "$PROJECT_DIR" || exit 1

if ! uv run python -m job_enricher.cli should-start; then
  echo "[fake-wrapper] control says this checkout does not tick; exiting"
  exit 0
fi

ACQ_OUT=$(uv run python -m job_enricher.cli tick-acquire 2>&1)
ACQ=$?
printf '%s\n' "$ACQ_OUT"
if [ "$ACQ" -eq 75 ]; then
  echo "[fake-wrapper] lock held; skipping this fire"
  exit 0
elif [ "$ACQ" -ne 0 ]; then
  echo "[fake-wrapper] tick-acquire failed (exit=$ACQ)"
  exit "$ACQ"
fi
ACQUIRED=1

printf '%s|%s' "$$" "$(date -u +%FT%TZ)" > "$LOCK_FILE"
ENRICH_LOCK_OWNER_PID="$$"
export ENRICH_LOCK_OWNER_PID
TICK_ID=$(printf '%s\n' "$ACQ_OUT" | sed -n 's/.*tick_id=\([0-9][0-9]*\).*/\1/p' | head -1)

uv run python -m job_enricher.cli work --tick-id "$TICK_ID" || echo "[fake-wrapper] work failed (continuing)"
uv run python -m job_enricher.cli tick-end --tick-id "$TICK_ID"
