#!/usr/bin/env bash
# e2e/run.sh enricher-cutover [--fast] [--case CO-07] [--keep]
#
# The sandboxed end-to-end test of the enricher cutover + its merge-trigger
# watcher (src/enricher/scripts/cutover/). Every case builds a throwaway
# "machine" — fake HOME, fake old prod / old dev git checkouts, a local bare
# repo standing in for GitHub JVN, a stub launchd that really fires the worker —
# and runs the REAL cutover.sh / watcher.sh / install_watcher.sh against it.
#
# COSTS $0 and touches NO network: no stack, no ports, no Postgres, no LLM.
# Remotes are local paths (GIT_ALLOW_PROTOCOL=file), uv runs OFFLINE from the
# real cache, gh / send.sh / launchctl are stubs. It never touches the real
# HOME, real launchd, ~/developer/personal/{app,job-enricher}, or the real
# cutover state dir — and checks that: a fingerprint of those is taken before
# and after the run, and any difference fails it as an ISOLATION BREACH (a
# case in the summary, so the verdict reads RED).
#
# --fast        the `fast` cases only (refusals, preflight, the watcher's no-ops)
# --case CO-07  one case (pytest -k co07); CO-REAL -> -k coreal, WT-03 -> -k wt03
# --keep        keep the sandboxes (under $TMPDIR/jvn-e2e-<hash>/enricher-cutover/)
#
# E2E_CUTOVER_SRC=<dir with cutover/ and lib/> tests those scripts instead of the
# working tree's (how PLAN.md §6's "proven to bite" mutations were run).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

FAST=0
CASE=""
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --fast) FAST=1; shift ;;
    --case) CASE="${2:-}"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    *) echo "enricher-cutover/run.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

echo "enricher-cutover: COST — \$0. No network (local file remotes, uv offline, stub gh/" \
     "send.sh/launchctl), no ports, no Postgres, no LLM."

# The test interpreter: the root venv when it can run pytest, else the
# enricher's own project env (what CI has — there is no root venv there).
PY=()
if [ -x "$REPO_ROOT/.venv/bin/python" ] && "$REPO_ROOT/.venv/bin/python" -c 'import pytest' 2>/dev/null; then
  PY=("$REPO_ROOT/.venv/bin/python")
elif command -v uv >/dev/null 2>&1; then
  PY=(uv run --project "$REPO_ROOT/src/enricher" --frozen python)
else
  echo "enricher-cutover: no root .venv with pytest and no uv on PATH" >&2
  exit 2
fi
echo "enricher-cutover: python: ${PY[*]}"

# --- Run lock (keyed on repo path AND section; outside the repo) ----------
REPO_HASH="$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)"
BASE="${TMPDIR:-/tmp}"
BASE="${BASE%/}/jvn-e2e-${REPO_HASH}"
LOCK_DIR="$BASE/enricher-cutover.lock"
HELD_LOCK=0
mkdir -p "$BASE"
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
else
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && ps -p "$OTHER_PID" -o pid= >/dev/null 2>&1; then
    echo "enricher-cutover: REFUSING TO START — another enricher-cutover run (pid $OTHER_PID)" \
         "is in flight. Wait for it, or stop it." >&2
    exit 2
  fi
  echo "enricher-cutover: clearing a stale run lock left by pid ${OTHER_PID:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { echo "enricher-cutover: could not take the run lock" >&2; exit 2; }
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
fi

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export E2E_ARTIFACTS_DIR="$SCRIPT_DIR/artifacts/$RUN_ID"
mkdir -p "$E2E_ARTIFACTS_DIR/cases"
# Sandboxes live OUTSIDE the repo: they hold git repos, venvs and fire loops,
# and a dev server watching the repo must never see them churn.
SANDBOX_ROOT="$BASE/enricher-cutover/$RUN_ID"
mkdir -p "$(dirname "$SANDBOX_ROOT")"

START_TS=$(date +%s)
EXIT_CODE=0
INTERRUPTED=0

_kill_sandbox_processes() {
  local pids
  pids="$(pgrep -f -- "$SANDBOX_ROOT/" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "enricher-cutover: stopping leftover sandbox processes: $(echo $pids)"
    kill -9 $pids 2>/dev/null || true
  fi
}

cleanup() {
  local rc=$?
  _kill_sandbox_processes
  if [ -d "$SANDBOX_ROOT" ]; then
    if [ "$KEEP" = "1" ]; then
      echo "enricher-cutover: --keep given; sandboxes kept at $SANDBOX_ROOT"
    else
      case "$SANDBOX_ROOT" in
        "$BASE"/enricher-cutover/*) rm -rf "$SANDBOX_ROOT" ;;
        *) echo "enricher-cutover: NOT removing unexpected path $SANDBOX_ROOT" >&2 ;;
      esac
    fi
  fi
  "${PY[@]}" "$REPO_ROOT/e2e/write_summary.py" \
    --artifacts-dir "$E2E_ARTIFACTS_DIR" \
    --section enricher-cutover \
    --elapsed-seconds "$(( $(date +%s) - START_TS ))" \
    --exit-code "$rc" \
    --blocked "" \
    --interrupted "$INTERRUPTED" \
    --fast "$FAST" || echo "enricher-cutover: write_summary.py failed (non-fatal)" >&2
  echo "enricher-cutover: summary written to $E2E_ARTIFACTS_DIR/summary.md"
  if [ "$HELD_LOCK" = "1" ]; then
    rm -rf "$LOCK_DIR"
  fi
  exit "$rc"
}
on_signal() {
  INTERRUPTED=1
  echo "enricher-cutover: received a shutdown signal — the run is being ABORTED" >&2
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

echo "enricher-cutover: === fingerprint the real machine paths (before) ==="
"${PY[@]}" "$SCRIPT_DIR/real_manifest.py" > "$E2E_ARTIFACTS_DIR/real-before.json" || {
  echo "enricher-cutover: could not fingerprint the real machine" >&2; exit 1; }

echo "enricher-cutover: === pytest ==="
PYTEST_ARGS=(-v -s -p no:cacheprovider --basetemp "$SANDBOX_ROOT")
if "${PY[@]}" -c 'import pytest_timeout' 2>/dev/null; then
  PYTEST_ARGS+=(--timeout=600)
fi
if [ -n "$CASE" ]; then
  PYTEST_ARGS+=(-k "$(echo "$CASE" | tr '[:upper:]' '[:lower:]' | tr -d '-')")
elif [ "$FAST" = "1" ]; then
  PYTEST_ARGS+=(-m fast)
fi
"${PY[@]}" -m pytest "$SCRIPT_DIR/api" "${PYTEST_ARGS[@]}" \
  --junitxml="$E2E_ARTIFACTS_DIR/pytest-junit.xml"
if [ "$?" != "0" ]; then
  EXIT_CODE=1
fi

echo "enricher-cutover: === fingerprint the real machine paths (after) ==="
_kill_sandbox_processes
"${PY[@]}" "$SCRIPT_DIR/real_manifest.py" > "$E2E_ARTIFACTS_DIR/real-after.json"
# Recorded as a case in the JUnit file, so summary.md's verdict counts it.
if ! "${PY[@]}" "$SCRIPT_DIR/real_manifest.py" verdict "$E2E_ARTIFACTS_DIR/real-before.json" \
     "$E2E_ARTIFACTS_DIR/real-after.json" "$E2E_ARTIFACTS_DIR/pytest-junit.xml" >&2; then
  echo "enricher-cutover: ISOLATION BREACH — the real com.bp.* LaunchAgents, cutover state dir" \
       "or ~/developer/personal/{app,job-enricher,enricher-prod} changed during the run (diff above)" >&2
  EXIT_CODE=1
else
  echo "enricher-cutover: real machine paths unchanged (real-before.json == real-after.json)"
fi

echo "enricher-cutover: === done (exit=$EXIT_CODE) ==="
exit "$EXIT_CODE"
