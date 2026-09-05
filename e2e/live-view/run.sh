#!/usr/bin/env bash
# e2e/run.sh live-view [--case LV-02] [--refresh-db] [--keep-up]
#
# Stack up (backend :8201, frontend :3201) -> playwright -> stack down.
#
# COSTS $0. No Browserbase session is ever opened: the hosted iframe and the list
# endpoint's `liveViewUrl` are both served by the test (see standin.ts), and the
# shared e2e stack refuses to boot with CAPTURE_USE_BROWSERBASE=true or a Browserbase
# key set. Everything else — the frontend, the poll, React's timers, the cross-origin
# iframe and its postMessage — is real.
#
# Reuses e2e/shared/stack/stack_up.sh, so it shares the add-companies gate's ports and
# pidfiles. It therefore also shares e2e/run.sh's run lock, which is why this script is
# invoked THROUGH e2e/run.sh rather than directly.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CASE=""
REFRESH_DB=0
KEEP_UP=0
LIVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --case) CASE="$2"; shift 2 ;;
    --refresh-db) REFRESH_DB=1; shift ;;
    --keep-up) KEEP_UP=1; shift ;;
    --live) LIVE=1; shift ;;
    *) echo "live-view/run.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

# Vitest and Playwright both hang on Node < 22.12 (see the repo's memory note).
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  if [ -d "$NVM_NODE" ]; then
    export PATH="$NVM_NODE:$PATH"
  fi
fi
echo "live-view: node $(node -v 2>/dev/null || echo 'NOT FOUND')"

# --- Run lock -------------------------------------------------------------
# THE SAME LOCK e2e/run.sh takes, by the same formula, because this section reuses
# add-companies' stack: same ports, same pidfiles. Without it, starting this while that
# gate is mid-run would call stack_down.sh on its backend and make it report a pile of
# connection-refused "regressions" it did not have. Outside the repo, deliberately —
# `vercel dev` watches the repo root and a lock file churning under it has taken the
# owner's dev server down before.
LOCK_DIR="${TMPDIR:-/tmp}/jvn-e2e-$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)/run.lock"
HELD_LOCK=0
mkdir -p "$(dirname "$LOCK_DIR")"
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"
  HELD_LOCK=1
else
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && ps -p "$OTHER_PID" -o pid= >/dev/null 2>&1; then
    echo "live-view: REFUSING TO START — another e2e run (pid $OTHER_PID) holds the" \
      "stack on :8201/:3201. Wait for it, or stop it, then re-run." >&2
    exit 2
  fi
  echo "live-view: clearing a stale run lock left by pid ${OTHER_PID:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { echo "live-view: could not take the run lock" >&2; exit 2; }
  echo $$ > "$LOCK_DIR/pid"
  HELD_LOCK=1
fi
echo "live-view: run lock acquired (pid $$)"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export E2E_ARTIFACTS_DIR="$SCRIPT_DIR/artifacts/$RUN_ID"
mkdir -p "$E2E_ARTIFACTS_DIR/stack" "$E2E_ARTIFACTS_DIR/ui"

EXIT_CODE=0

cleanup() {
  local rc=$?
  if [ "$KEEP_UP" = "1" ]; then
    echo "live-view: --keep-up given; leaving the stack running on :8201/:3201"
  else
    echo "live-view: tearing down the stack"
    bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true
  fi
  echo "live-view: artifacts in $E2E_ARTIFACTS_DIR"
  if [ "$HELD_LOCK" = "1" ]; then
    rm -rf "$LOCK_DIR"
  fi
  exit "$rc"
}
trap cleanup EXIT

echo "live-view: === stack up ==="
if [ "$LIVE" = "1" ]; then
  echo "live-view: --live — this run WILL open one real Browserbase session (~1 billed minute)"
  if ! bash "$SCRIPT_DIR/stack_up_live.sh" --artifacts-dir "$E2E_ARTIFACTS_DIR/stack"; then
    echo "live-view: live stack failed to come up" >&2
    exit 1
  fi
  PW_CONFIG="$SCRIPT_DIR/playwright.live.config.ts"
else
  STACK_UP_ARGS=(--artifacts-dir "$E2E_ARTIFACTS_DIR/stack")
  if [ "$REFRESH_DB" = "1" ]; then
    STACK_UP_ARGS+=(--refresh)
  fi
  if ! bash "$REPO_ROOT/e2e/shared/stack/stack_up.sh" "${STACK_UP_ARGS[@]}"; then
    echo "live-view: stack failed to come up" >&2
    exit 1
  fi
  PW_CONFIG="$SCRIPT_DIR/playwright.config.ts"
fi

echo "live-view: === playwright ==="
GREP_ARG=""
if [ -n "$CASE" ]; then
  GREP_ARG="--grep=$CASE"
fi
# NOT under $E2E_ARTIFACTS_DIR/ui — Playwright wipes its own outputDir on start, which
# deletes a log `tee` has already created there.
OUT="$E2E_ARTIFACTS_DIR/playwright-stdout.txt"
(
  cd "$REPO_ROOT/e2e"
  E2E_ARTIFACTS_DIR="$E2E_ARTIFACTS_DIR" npx playwright test \
    --config="$PW_CONFIG" $GREP_ARG
) 2>&1 | tee "$OUT"
EXIT_CODE=${PIPESTATUS[0]}

echo
if [ "$EXIT_CODE" = "0" ]; then
  echo "live-view: VERDICT PASS — the frame stayed on screen for every scripted session"
else
  echo "live-view: VERDICT FAIL — see the timeline above; the failing assertion names the closer"
fi
exit "$EXIT_CODE"
