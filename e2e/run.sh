#!/usr/bin/env bash
# e2e/run.sh <section> [--fast] [--case AC-06] [--refresh-db]
#
# Stack-up -> pre-flight -> pytest -> playwright -> stack-down -> summary
# (PLAN.md §9). ALWAYS tears the stack down, including on failure and on
# Ctrl-C — the trap below runs regardless of how the script exits.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SECTION="${1:-}"
if [ -z "$SECTION" ]; then
  echo "usage: e2e/run.sh <section> [--fast] [--case AC-ID] [--refresh-db]" >&2
  exit 2
fi
shift

FAST=0
CASE=""
REFRESH_DB=0
while [ $# -gt 0 ]; do
  case "$1" in
    --fast) FAST=1; shift ;;
    --case) CASE="$2"; shift 2 ;;
    --refresh-db) REFRESH_DB=1; shift ;;
    *) echo "run.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

if [ "$SECTION" != "add-companies" ]; then
  echo "run.sh: only section 'add-companies' exists today" >&2
  exit 2
fi

if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  if [ -d "$NVM_NODE" ]; then
    export PATH="$NVM_NODE:$PATH"
  fi
fi
echo "run.sh: node $(node -v 2>/dev/null || echo 'NOT FOUND')"

SECTION_DIR="$REPO_ROOT/e2e/$SECTION"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export E2E_ARTIFACTS_DIR="$SECTION_DIR/artifacts/$RUN_ID"
mkdir -p "$E2E_ARTIFACTS_DIR/stack" "$E2E_ARTIFACTS_DIR/cases"

START_TS=$(date +%s)
EXIT_CODE=0
BLOCKED_BOARDS=""
INTERRUPTED=0

# --- Run lock -------------------------------------------------------------
# ONE run.sh at a time. Without this, a second invocation's stack_up.sh calls
# stack_down.sh, which kills the FIRST run's backend and frontend by pidfile
# mid-flight — the first run then reports `httpx.ConnectError: Connection
# refused` on every remaining case and `net::ERR_CONNECTION_REFUSED at
# http://127.0.0.1:3201` on every UI spec, and writes a summary that reads like
# a pile of product regressions.
#
# That is not hypothetical. Measured in artifacts/20260827T002919Z: its backend
# logged `uvicorn.error: Shutting down` at 19:33:41 — the exact second run
# 20260827T003341Z started — and it reported 7 FAILs it had not actually had.
# CASES.md flagged this as "Known limitation, not fixed"; this is the fix.
#
# `mkdir` is the lock because it is atomic on POSIX: two racing runs cannot both
# create the same directory, and the winner is decided by the kernel rather than
# by a check-then-write window.
#
# MUST come before `trap cleanup EXIT` is installed: cleanup runs stack_down.sh
# unconditionally, so a run that refused the lock and then fired its own trap
# would tear down the stack belonging to the run it just declined to disturb.
# Exiting here, before any trap exists, is what makes the refusal harmless.
# OUTSIDE the repo, deliberately. This lock lived at
# e2e/shared/stack/.pids/run.lock and took down the owner's dev server: `vercel
# dev` watches the whole repo root, and when a finishing run removed the lock its
# file watcher died with
#     ENOENT: no such file or directory, scandir '.../.pids/run.lock'
# taking the frontend on :3000 with it. Every completed e2e run killed the stack.
# .gitignore does not help -- vercel's watcher does not consult it. The only fix
# is for the churn to happen somewhere the watcher never looks.
#
# Keyed by repo path so two checkouts of this repo do not share a lock.
LOCK_DIR="${TMPDIR:-/tmp}/jvn-e2e-$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)/run.lock"
HELD_LOCK=0
mkdir -p "$(dirname "$LOCK_DIR")"

_take_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo $$ > "$LOCK_DIR/pid"
    HELD_LOCK=1
    return 0
  fi
  return 1
}

_pid_is_alive() {
  # `ps -p`, not `kill -0`: `kill -0` fails with EPERM for a process owned by
  # ANOTHER user, which bash reports identically to "no such process" — so a
  # lock genuinely held by someone else's run would be reclaimed as stale, and
  # this guard would defeat itself in exactly the case it exists for.
  ps -p "$1" -o pid= >/dev/null 2>&1
}

if ! _take_lock; then
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && _pid_is_alive "$OTHER_PID"; then
    echo "run.sh: REFUSING TO START — another e2e run (pid $OTHER_PID) is already in" \
      "flight. Two runs share one stack (:8201/:3201) and one pidfile directory, so" \
      "starting now would kill that run mid-test and make it report failures it did" \
      "not have. Wait for it, or stop it, then re-run." >&2
    # Don't leave a stub artifacts dir for a run that never happened — an
    # empty run directory is a thing someone will later try to interpret.
    rmdir "$E2E_ARTIFACTS_DIR/stack" "$E2E_ARTIFACTS_DIR/cases" "$E2E_ARTIFACTS_DIR" 2>/dev/null || true
    exit 2
  fi
  # The holder is gone: a previous run was SIGKILLed before it could release.
  # Say so out loud — a silently-reclaimed lock is how this class of bug hides.
  echo "run.sh: clearing a stale run lock left by pid ${OTHER_PID:-unknown} (no such process)"
  rm -rf "$LOCK_DIR"
  if ! _take_lock; then
    echo "run.sh: could not acquire the run lock at $LOCK_DIR even after clearing it" >&2
    exit 2
  fi
fi
echo "run.sh: run lock acquired (pid $$)"

cleanup() {
  local rc=$?
  echo "run.sh: tearing down the stack"
  bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true
  write_summary "$rc"
  if [ "$HELD_LOCK" = "1" ]; then
    rm -rf "$LOCK_DIR"
  fi
  exit "$rc"
}
# INT/TERM set INTERRUPTED before falling through to cleanup, so write_summary
# can label the run ABORTED rather than publishing the resulting teardown
# cascade as a list of case failures (see write_summary.py).
on_signal() {
  INTERRUPTED=1
  echo "run.sh: received a shutdown signal — the run is being ABORTED, not completed" >&2
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

write_summary() {
  local final_rc="$1"
  local end_ts
  end_ts=$(date +%s)
  local elapsed=$((end_ts - START_TS))
  "$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/write_summary.py" \
    --artifacts-dir "$E2E_ARTIFACTS_DIR" \
    --elapsed-seconds "$elapsed" \
    --exit-code "$final_rc" \
    --blocked "$BLOCKED_BOARDS" \
    --interrupted "$INTERRUPTED" \
    --fast "$FAST" || echo "run.sh: write_summary.py failed (non-fatal)" >&2
  echo "run.sh: summary written to $E2E_ARTIFACTS_DIR/summary.md"
}

echo "run.sh: === stack up ==="
STACK_UP_ARGS=(--artifacts-dir "$E2E_ARTIFACTS_DIR/stack")
if [ "$REFRESH_DB" = "1" ]; then
  STACK_UP_ARGS+=(--refresh)
fi
if ! bash "$REPO_ROOT/e2e/shared/stack/stack_up.sh" "${STACK_UP_ARGS[@]}"; then
  echo "run.sh: stack failed to come up" >&2
  EXIT_CODE=1
  exit "$EXIT_CODE"
fi

echo "run.sh: === pre-flight ==="
PREFLIGHT_URLS=$("$REPO_ROOT/.venv/bin/python" -c "
import sys
sys.path.insert(0, '$SECTION_DIR')
import boards
print(' '.join(b.url for b in boards.ALL_BOARDS))
")
PREFLIGHT_OUT="$E2E_ARTIFACTS_DIR/preflight.txt"
"$REPO_ROOT/.venv/bin/python" -m e2e.shared.stack.preflight $PREFLIGHT_URLS > "$PREFLIGHT_OUT" 2>&1
cat "$PREFLIGHT_OUT"
# Map any BLOCKED line back to its board label (via boards.py) for
# E2E_BLOCKED_BOARDS, which conftest.py's require_reachable() reads.
BLOCKED_BOARDS=$("$REPO_ROOT/.venv/bin/python" - "$PREFLIGHT_OUT" "$SECTION_DIR" <<'PYEOF'
import sys
preflight_out, section_dir = sys.argv[1], sys.argv[2]
sys.path.insert(0, section_dir)
import boards
blocked_urls = set()
for line in open(preflight_out):
    parts = line.rstrip("\n").split("\t")
    if parts and parts[0] == "BLOCKED":
        blocked_urls.add(parts[-1])
labels = [b.label for b in boards.ALL_BOARDS if b.url in blocked_urls]
print(",".join(labels))
PYEOF
)
export E2E_BLOCKED_BOARDS="$BLOCKED_BOARDS"
if [ -n "$BLOCKED_BOARDS" ]; then
  echo "run.sh: BLOCKED boards this run: $BLOCKED_BOARDS"
fi

echo "run.sh: === pytest (API tier) ==="
PYTEST_ARGS=(-v -s --timeout=280)
if [ -n "$CASE" ]; then
  # Test functions are named test_ac06_..., test_ac06a_..., etc (no hyphen —
  # not a valid Python identifier character), so "AC-06" must normalize to
  # "ac06" for pytest's -k substring match. Playwright's describe titles
  # literally contain "AC-06" with the hyphen, so its --grep below uses $CASE
  # unnormalized.
  PYTEST_K="$(echo "$CASE" | tr '[:upper:]' '[:lower:]' | tr -d '-')"
  PYTEST_ARGS+=(-k "$PYTEST_K")
elif [ "$FAST" = "1" ]; then
  PYTEST_ARGS+=(-m "not live")
fi
"$REPO_ROOT/.venv/bin/python" -m pytest "$SECTION_DIR/api" "${PYTEST_ARGS[@]}" \
  --junitxml="$E2E_ARTIFACTS_DIR/pytest-junit.xml"
PYTEST_RC=$?
if [ "$PYTEST_RC" != "0" ]; then
  EXIT_CODE=1
fi

echo "run.sh: === playwright (UI tier) ==="
if [ "$FAST" = "1" ] && [ -z "$CASE" ]; then
  echo "run.sh: --fast skips the UI tier entirely (all three specs are live-board journeys)"
else
  PLAYWRIGHT_GREP=""
  if [ -n "$CASE" ]; then
    PLAYWRIGHT_GREP="--grep=$CASE"
  fi
  PLAYWRIGHT_OUT="$E2E_ARTIFACTS_DIR/ui/playwright-stdout.txt"
  mkdir -p "$E2E_ARTIFACTS_DIR/ui"
  (
    cd "$REPO_ROOT/e2e"
    E2E_ARTIFACTS_DIR="$E2E_ARTIFACTS_DIR" npx playwright test \
      --config="$SECTION_DIR/playwright.config.ts" $PLAYWRIGHT_GREP
  ) 2>&1 | tee "$PLAYWRIGHT_OUT"
  PLAYWRIGHT_RC=${PIPESTATUS[0]}
  if [ "$PLAYWRIGHT_RC" != "0" ]; then
    # `--case` for a case with no UI spec title (AC-02/04/05/06a/07/09-12 —
    # their UI-visible half, if any, lives folded into a DIFFERENT case's
    # spec, e.g. AC-07's dialog copy is asserted inside add-delete.spec.ts's
    # "AC-08" describe) makes --grep match zero tests, which Playwright
    # itself treats as a hard error. That is not this case failing — there
    # is nothing to run — so it must not report as a case FAIL.
    if [ -n "$CASE" ] && grep -q "No tests found" "$PLAYWRIGHT_OUT"; then
      echo "run.sh: no UI spec matches --case $CASE (its UI coverage, if any, lives under a different case's spec title) — not a failure"
    else
      EXIT_CODE=1
    fi
  fi
fi

echo "run.sh: === done (exit=$EXIT_CODE) ==="
exit "$EXIT_CODE"
