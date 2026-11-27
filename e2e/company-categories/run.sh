#!/usr/bin/env bash
# e2e/run.sh company-categories [--fast] [--case CC-02] [--refresh-db] [--keep-up]
#
# Stack up (backend :8208, frontend :3208, db jobscraper_e2e_company_categories)
#   -> seed -> pytest (API tier) -> playwright (UI tier) -> stack down.
#
# COSTS $0, unconditionally. No LLM call, no Browserbase session, no PostHog
# event, no host but its own stack. Every fact it asserts is about the
# company-category tables the backend seeds from the committed JSON on boot,
# and nine job rows seed.py wrote.
#
# --fast skips the UI tier (the API tier is the SQL truth and takes seconds).
#
# PORTS: :8208/:3208. Not :8206/:3206: :8206 is already the
# enricher section's kill-switch backend (EN-08).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python"

FAST=0
CASE=""
REFRESH_DB=0
KEEP_UP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --fast) FAST=1; shift ;;
    --case) CASE="$2"; shift 2 ;;
    --refresh-db) REFRESH_DB=1; shift ;;
    --keep-up) KEEP_UP=1; shift ;;
    *) echo "company-categories/run.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

echo "company-categories: COST — \$0. No LLM call, no Browserbase session, no PostHog" \
     "event, no network beyond this section's own stack."

# Vitest and Playwright both hang on Node < 22.12 with no output.
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  [ -d "$NVM_NODE" ] && export PATH="$NVM_NODE:$PATH"
fi
echo "company-categories: node $(node -v 2>/dev/null || echo 'NOT FOUND')"

# --- The stack this section owns -----------------------------------------
export E2E_BACKEND_PORT=8208
export E2E_FRONTEND_PORT=3208
export E2E_BACKEND_URL="http://127.0.0.1:${E2E_BACKEND_PORT}"
export E2E_FRONTEND_URL="http://127.0.0.1:${E2E_FRONTEND_PORT}"
export E2E_TARGET_DB="jobscraper_e2e_company_categories"
export E2E_EXPECTED_DB="$E2E_TARGET_DB"
export E2E_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/${E2E_TARGET_DB}"
export E2E_ENV_FILE="$SCRIPT_DIR/env.company_categories"
export E2E_PID_DIR="$SCRIPT_DIR/.pids"
export E2E_DB_SCHEMA_ONLY=1
# Schema source: jobscraper_pr243 when it exists, else the local dev DB (the
# onboarding section's rule). Read-only either way.
if [ -z "${E2E_SOURCE_DB:-}" ]; then
  if docker exec "${E2E_PG_CONTAINER:-jobscraper-postgres}" psql -U postgres -Atc \
       "SELECT 1 FROM pg_database WHERE datname='jobscraper_pr243'" 2>/dev/null | grep -q 1; then
    export E2E_SOURCE_DB="jobscraper_pr243"
  else
    export E2E_SOURCE_DB="jobscraper"
  fi
fi
echo "company-categories: schema source $E2E_SOURCE_DB (read-only)"

# --- Run lock (repo path + section) ---------------------------------------
LOCK_DIR="${TMPDIR:-/tmp}/jvn-e2e-$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)/company-categories.lock"
HELD_LOCK=0
mkdir -p "$(dirname "$LOCK_DIR")"
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
else
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && ps -p "$OTHER_PID" -o pid= >/dev/null 2>&1; then
    echo "company-categories: REFUSING TO START — another run (pid $OTHER_PID) holds" \
         ":8208/:3208 and is reseeding the same fixtures." >&2
    exit 2
  fi
  echo "company-categories: clearing a stale run lock left by pid ${OTHER_PID:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { echo "company-categories: could not take the run lock" >&2; exit 2; }
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
fi
echo "company-categories: run lock acquired (pid $$)"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export E2E_RUN_ID="$RUN_ID"
export E2E_ARTIFACTS_DIR="$SCRIPT_DIR/artifacts/$RUN_ID"
mkdir -p "$E2E_ARTIFACTS_DIR/stack" "$E2E_ARTIFACTS_DIR/cases"

START_TS=$(date +%s)
EXIT_CODE=0
INTERRUPTED=0

write_summary() {
  local final_rc="$1" end_ts elapsed
  end_ts=$(date +%s); elapsed=$((end_ts - START_TS))
  "$PY" "$REPO_ROOT/e2e/write_summary.py" \
    --artifacts-dir "$E2E_ARTIFACTS_DIR" --section company-categories \
    --elapsed-seconds "$elapsed" --exit-code "$final_rc" \
    --blocked "" --interrupted "$INTERRUPTED" --fast "$FAST" \
    || echo "company-categories: write_summary.py failed (non-fatal)" >&2
  echo "company-categories: summary written to $E2E_ARTIFACTS_DIR/summary.md"
}

cleanup() {
  local rc=$?
  if [ "$KEEP_UP" = "1" ]; then
    echo "company-categories: --keep-up given; leaving the stack on :8208/:3208"
  else
    echo "company-categories: tearing down the stack"
    bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true
  fi
  write_summary "$rc"
  [ "$HELD_LOCK" = "1" ] && rm -rf "$LOCK_DIR"
  exit "$rc"
}
on_signal() {
  INTERRUPTED=1
  echo "company-categories: received a shutdown signal — the run is being ABORTED, not completed" >&2
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

echo "company-categories: === stack up ==="
STACK_UP_ARGS=(--artifacts-dir "$E2E_ARTIFACTS_DIR/stack")
[ "$REFRESH_DB" = "1" ] && STACK_UP_ARGS+=(--refresh)
if ! bash "$REPO_ROOT/e2e/shared/stack/stack_up.sh" "${STACK_UP_ARGS[@]}"; then
  echo "company-categories: stack failed to come up" >&2
  exit 1
fi

echo "company-categories: === seed ==="
# Fails HERE, naming the fix, if the backend's boot seed did not write the
# membership tables — not as eleven cases that look like a broken filter.
if ! "$PY" "$SCRIPT_DIR/seed.py" 2>&1 | tee "$E2E_ARTIFACTS_DIR/seed.txt"; then
  echo "company-categories: seeding failed — see $E2E_ARTIFACTS_DIR/seed.txt" >&2
  exit 1
fi

echo "company-categories: === pytest (API tier) ==="
PYTEST_ARGS=(-v -s --timeout=120)
if [ -n "$CASE" ]; then
  # test_cc02_... <- "CC-02". UI ids (CC-U1) select no API test (exit 5).
  PYTEST_ARGS+=(-k "$(echo "$CASE" | tr '[:upper:]' '[:lower:]' | tr -d '-')")
fi
"$PY" -m pytest "$SCRIPT_DIR/api" "${PYTEST_ARGS[@]}" --junitxml="$E2E_ARTIFACTS_DIR/pytest-junit.xml"
PYTEST_RC=$?
if [ "$PYTEST_RC" != "0" ] && ! { [ -n "$CASE" ] && [ "$PYTEST_RC" = "5" ]; }; then
  EXIT_CODE=1
fi

echo "company-categories: === playwright (UI tier) ==="
if [ "$FAST" = "1" ] && [ -z "$CASE" ]; then
  echo "company-categories: --fast skips the UI tier"
else
  "$PY" "$SCRIPT_DIR/seed.py" >/dev/null
  PLAYWRIGHT_GREP=""
  [ -n "$CASE" ] && PLAYWRIGHT_GREP="--grep=$CASE"
  # Not under $E2E_ARTIFACTS_DIR/ui: Playwright wipes its outputDir on start.
  PLAYWRIGHT_OUT="$E2E_ARTIFACTS_DIR/playwright-stdout.txt"
  ( cd "$REPO_ROOT/e2e" && npx playwright test --config="$SCRIPT_DIR/playwright.config.ts" $PLAYWRIGHT_GREP ) \
    2>&1 | tee "$PLAYWRIGHT_OUT"
  PLAYWRIGHT_RC=${PIPESTATUS[0]}
  if [ "$PLAYWRIGHT_RC" != "0" ]; then
    if [ -n "$CASE" ] && grep -q "No tests found" "$PLAYWRIGHT_OUT"; then
      echo "company-categories: no UI spec matches --case $CASE (an API-tier case) — not a failure"
    else
      EXIT_CODE=1
    fi
  fi
fi

echo "company-categories: === done (exit=$EXIT_CODE) ==="
exit "$EXIT_CODE"
