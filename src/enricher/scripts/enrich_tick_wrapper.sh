#!/bin/sh
# Headless wrapper for the launchd StartInterval worker. Mirrors job-watcher:
# pre-acquire the lock, pre-pull + pre-clean deterministically, then run the
# classify -> judge -> write-back -> tick-end pipeline. For the local in-process
# engines (ollama/opencode) that pipeline runs HERE in the shell (deterministic
# CLI calling the local model; see the engine branch below); only the
# `claude-code` fan-out engine hands off to `claude -p /enrich-tick-once`.
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
# Anchor to THIS checkout, not a hardcoded path: the wrapper lives at <root>/scripts/,
# so its parent is the repo root. Derived so prod and dev each target their own tree and
# relocating a checkout needs no edit here (see docs/ENVIRONMENTS.md).
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
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

# Deterministic pre-work (safe to fail softly; retried next tick)
"$UV_BIN" run python -m job_enricher.cli pull  || echo "[wrapper] pull failed (continuing)"
"$UV_BIN" run python -m job_enricher.cli clean || echo "[wrapper] clean failed (continuing)"

# Which engine drives classify? The local in-process engines (ollama/opencode)
# run the whole classify -> judge -> write-back -> tick-end pipeline as
# deterministic CLI that calls the local model directly — NO agent is needed,
# and a single `classify-run` can take ~1h, FAR longer than the `claude -p`
# agent's per-Bash-call ceiling. Delegating it to the agent orphaned every tick
# (the agent backgrounds the long run, its headless turn ends, and the wrapper
# returns before judge/write-back/tick-end ever happen). So run those engines
# HERE in the shell, under the same 3h watchdog. Only the `claude-code` fan-out
# engine needs `claude -p` (it drives sub-agents within its own turn).
# Read the resolved engines with a stable prefix so stray uv/stdout lines can't
# be mistaken for a value (same defensive parse as tick_id= above). 2>/dev/null
# drops uv's progress chatter; the getters fall back to the committed defaults.
ENGINE_CFG=$("$UV_BIN" run python - <<'PY' 2>/dev/null
from job_enricher.store import Store
import job_enricher.enrich_config as ec
s = Store()
print("CLASSIFY_ENGINE=" + ec.get_classify_engine(s))
print("JUDGE_ENGINE=" + ec.get_judge_engine(s))
PY
)
CLASSIFY_ENGINE=$(printf '%s\n' "$ENGINE_CFG" | sed -n 's/^CLASSIFY_ENGINE=//p' | head -1)
JUDGE_ENGINE=$(printf '%s\n' "$ENGINE_CFG" | sed -n 's/^JUDGE_ENGINE=//p' | head -1)

run_inprocess_llm_stages() {
  # classify-queue / judge-queue cap the slice at enrich:per_tick_limit and write
  # the chunk files that classify-run / judge-run read (which call the local
  # model). judge-queue self-gates on judge:enabled + judge:scope (a no-op when
  # judge is off), so no extra gating is needed here.
  "$UV_BIN" run python -m job_enricher.cli classify-queue || echo "[wrapper] classify-queue failed (continuing)"
  "$UV_BIN" run python -m job_enricher.cli classify-run   || echo "[wrapper] classify-run failed (continuing)"
  case "$JUDGE_ENGINE" in
    ollama|opencode)
      "$UV_BIN" run python -m job_enricher.cli judge-queue || echo "[wrapper] judge-queue failed (continuing)"
      "$UV_BIN" run python -m job_enricher.cli judge-run   || echo "[wrapper] judge-run failed (continuing)"
      ;;
    *)
      echo "[wrapper] judge engine '$JUDGE_ENGINE' is not in-process — skipping judge this tick"
      ;;
  esac
}

case "$CLASSIFY_ENGINE" in
  ollama|opencode)
    echo "[wrapper] in-process engine (classify=$CLASSIFY_ENGINE judge=$JUDGE_ENGINE) — running the pipeline in the shell (no claude -p)"
    run_inprocess_llm_stages &
    PID=$!
    ( sleep "$TIMEOUT_SECS"; kill -TERM "$PID" 2>/dev/null; sleep 10; kill -KILL "$PID" 2>/dev/null ) &
    WATCHDOG=$!
    wait "$PID"
    STATUS=$?
    kill "$WATCHDOG" 2>/dev/null
    # Delivery-first: ALWAYS write back what got enriched and close the tick, even
    # if the watchdog killed the stages above. write-back marks a row sent only on
    # a 2xx (unsent rows retry next tick, JVN is idempotent); tick-end refuses to
    # close a tick it doesn't own. Both are safe after a partial/killed run.
    "$UV_BIN" run python -m job_enricher.cli write-back || echo "[wrapper] write-back failed (continuing)"
    "$UV_BIN" run python -m job_enricher.cli tick-end   || echo "[wrapper] tick-end failed (continuing)"
    ;;
  *)
    # claude-code fan-out (or unknown engine): the agent orchestrates classify /
    # judge sub-agents and calls write-back + tick-end itself, inside its turn.
    "$CLAUDE_BIN" -p /enrich-tick-once --dangerously-skip-permissions &
    PID=$!
    ( sleep "$TIMEOUT_SECS"; kill -TERM "$PID" 2>/dev/null; sleep 10; kill -KILL "$PID" 2>/dev/null ) &
    WATCHDOG=$!
    wait "$PID"
    STATUS=$?
    kill "$WATCHDOG" 2>/dev/null
    ;;
esac

# Best-effort metrics push to JVN — always runs, even after a timeout/kill
# (the tick may report status running/error). Never fails the wrapper.
"$UV_BIN" run python -m job_enricher.cli metrics-push \
  || echo "[wrapper] metrics-push failed (continuing)"

exit "$STATUS"
