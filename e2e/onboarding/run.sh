#!/usr/bin/env bash
# e2e/run.sh onboarding [--fast] [--case OB-U1] [--refresh-db] [--keep-up]
#
# Stack up (backend :8205, frontend :3205, db jobscraper_e2e_onboarding)
#   -> seed -> pytest (API tier, OB-01..OB-09) -> re-seed
#   -> playwright (UI tier, OB-U1..OB-U12) -> purge this run's identities
#   -> stack down.
#
# COSTS $0, unconditionally. No LLM call, no Browserbase session, no Stripe, no
# PostHog, no request to any host but its own stack: `env.onboarding` blanks
# every key that could reach one, `stack_app.py` refuses to boot with a PostHog
# token, `e2e_app.py` refuses a Browserbase one, and the UI tier aborts any
# browser request that is not to 127.0.0.1.
#
# --fast skips the UI tier (the API tier is the gate's fast half).
#
# Its own ports, database, pidfiles and lock (PLAN.md §3), so it runs alongside
# every other section and never alongside a second copy of itself — which would
# purge this run's identities out from under it.

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
    *) echo "onboarding/run.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

echo "onboarding: COST — \$0, unconditionally. No LLM call, no Browserbase session, no" \
     "PostHog event, no network beyond this section's own stack."

# Playwright hangs silently on Node < 22.12 (repo memory note).
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  [ -d "$NVM_NODE" ] && export PATH="$NVM_NODE:$PATH"
fi
echo "onboarding: node $(node -v 2>/dev/null || echo 'NOT FOUND')"

# --- The stack this section owns -------------------------------------------
# Exported (not flags) because they must reach vite's config, Playwright's
# config, pytest's conftest, the Python CLIs the UI tier shells out to, and the
# backend. See stack_up.sh's header for every knob and its default.
export E2E_BACKEND_PORT=8205
export E2E_FRONTEND_PORT=3205
export E2E_BACKEND_URL="http://127.0.0.1:${E2E_BACKEND_PORT}"
export E2E_FRONTEND_URL="http://127.0.0.1:${E2E_FRONTEND_PORT}"
export E2E_TARGET_DB="jobscraper_e2e_onboarding"
export E2E_EXPECTED_DB="$E2E_TARGET_DB"
export E2E_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/${E2E_TARGET_DB}"
export E2E_ENV_FILE="$SCRIPT_DIR/env.onboarding"
export E2E_PID_DIR="$SCRIPT_DIR/.pids"
export E2E_DB_SCHEMA_ONLY=1
export E2E_APP_MODULE="e2e.onboarding.stack_app:app"
# Schema-only clone source (only ever READ, by pg_dump): the shared default,
# else the local dev database — the same fallback billing/run.sh uses.
if [ -z "${E2E_SOURCE_DB:-}" ]; then
  if docker exec "${E2E_PG_CONTAINER:-jobscraper-postgres}" psql -U postgres -Atc \
       "SELECT 1 FROM pg_database WHERE datname='jobscraper_pr243'" 2>/dev/null | grep -q 1; then
    export E2E_SOURCE_DB="jobscraper_pr243"
  else
    export E2E_SOURCE_DB="jobscraper"
  fi
fi
echo "onboarding: schema source $E2E_SOURCE_DB (read-only)"

# --- Run lock (per section; see subcategories/run.sh) ------------------------
LOCK_DIR="${TMPDIR:-/tmp}/jvn-e2e-$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)/onboarding.lock"
HELD_LOCK=0
mkdir -p "$(dirname "$LOCK_DIR")"
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
else
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && ps -p "$OTHER_PID" -o pid= >/dev/null 2>&1; then
    echo "onboarding: REFUSING TO START — another onboarding run (pid $OTHER_PID) holds" \
         ":8205/:3205 and would have its identities purged mid-test. Wait for it, or stop" \
         "it, then re-run." >&2
    exit 2
  fi
  echo "onboarding: clearing a stale run lock left by pid ${OTHER_PID:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { echo "onboarding: could not take the run lock" >&2; exit 2; }
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
fi
echo "onboarding: run lock acquired (pid $$)"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export E2E_RUN_ID="$RUN_ID"
export E2E_ARTIFACTS_DIR="$SCRIPT_DIR/artifacts/$RUN_ID"
mkdir -p "$E2E_ARTIFACTS_DIR/stack" "$E2E_ARTIFACTS_DIR/cases"

START_TS=$(date +%s)
EXIT_CODE=0
INTERRUPTED=0
STACK_UP=0

write_summary() {
  local final_rc="$1" end_ts elapsed
  end_ts=$(date +%s); elapsed=$((end_ts - START_TS))
  "$PY" "$REPO_ROOT/e2e/write_summary.py" \
    --artifacts-dir "$E2E_ARTIFACTS_DIR" --section onboarding \
    --elapsed-seconds "$elapsed" --exit-code "$final_rc" \
    --blocked "" --interrupted "$INTERRUPTED" --fast "$FAST" \
    || echo "onboarding: write_summary.py failed (non-fatal)" >&2
  echo "onboarding: summary written to $E2E_ARTIFACTS_DIR/summary.md"
}

cleanup() {
  local rc=$?
  if [ "$KEEP_UP" = "1" ]; then
    echo "onboarding: --keep-up given; leaving the stack on :8205/:3205 and this run's identities"
  else
    if [ "$STACK_UP" = "1" ]; then
      # Every identity this run minted (users row + saved filters). The next
      # run's seed would purge them too; doing it now leaves the database the
      # way the run found it.
      (cd "$REPO_ROOT" && "$PY" -m e2e.onboarding.identities purge) \
        || echo "onboarding: identity purge failed (non-fatal; the next seed retries it)" >&2
    fi
    echo "onboarding: tearing down the stack"
    bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true
  fi
  write_summary "$rc"
  [ "$HELD_LOCK" = "1" ] && rm -rf "$LOCK_DIR"
  exit "$rc"
}
on_signal() {
  INTERRUPTED=1
  echo "onboarding: received a shutdown signal — the run is being ABORTED, not completed" >&2
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

echo "onboarding: === stack up ==="
STACK_UP_ARGS=(--artifacts-dir "$E2E_ARTIFACTS_DIR/stack")
[ "$REFRESH_DB" = "1" ] && STACK_UP_ARGS+=(--refresh)
if ! bash "$REPO_ROOT/e2e/shared/stack/stack_up.sh" "${STACK_UP_ARGS[@]}"; then
  echo "onboarding: stack failed to come up" >&2
  exit 1
fi
STACK_UP=1

echo "onboarding: === seed ==="
# A provisioning failure (no specialties, no location catalog) must fail HERE,
# where the message names the fix, not as twenty cases that look like
# product regressions. (pipefail is on, so the seeder's status survives `tee`.)
if ! (cd "$REPO_ROOT" && "$PY" -m e2e.onboarding.seed) 2>&1 | tee "$E2E_ARTIFACTS_DIR/seed.txt"; then
  echo "onboarding: seeding failed — see $E2E_ARTIFACTS_DIR/seed.txt" >&2
  exit 1
fi

echo "onboarding: === pytest (API tier) ==="
PYTEST_ARGS=(-v -s --timeout=120)
if [ -n "$CASE" ]; then
  # test_ob03_... <- "OB-03". UI ids (OB-U1) normalise to "obu1", which no API
  # test carries, so pytest selects nothing and exits 5 — handled below.
  PYTEST_ARGS+=(-k "$(echo "$CASE" | tr '[:upper:]' '[:lower:]' | tr -d '-')")
fi
"$PY" -m pytest "$SCRIPT_DIR/api" "${PYTEST_ARGS[@]}" --junitxml="$E2E_ARTIFACTS_DIR/pytest-junit.xml"
PYTEST_RC=$?
if [ "$PYTEST_RC" != "0" ] && ! { [ -n "$CASE" ] && [ "$PYTEST_RC" = "5" ]; }; then
  EXIT_CODE=1
fi

echo "onboarding: === playwright (UI tier) ==="
if [ "$FAST" = "1" ] && [ -z "$CASE" ]; then
  echo "onboarding: --fast skips the UI tier"
else
  # Re-seed: the UI tier starts from the same state the API tier did — no
  # identity but the pre-existing account, which is stamped again.
  (cd "$REPO_ROOT" && "$PY" -m e2e.onboarding.seed) >/dev/null
  PLAYWRIGHT_GREP=""
  [ -n "$CASE" ] && PLAYWRIGHT_GREP="--grep=$CASE"
  # Not under $E2E_ARTIFACTS_DIR/ui: Playwright wipes its outputDir on start.
  PLAYWRIGHT_OUT="$E2E_ARTIFACTS_DIR/playwright-stdout.txt"
  ( cd "$REPO_ROOT/e2e" && npx playwright test --config="$SCRIPT_DIR/playwright.config.ts" $PLAYWRIGHT_GREP ) \
    2>&1 | tee "$PLAYWRIGHT_OUT"
  PLAYWRIGHT_RC=${PIPESTATUS[0]}
  if [ "$PLAYWRIGHT_RC" != "0" ]; then
    if [ -n "$CASE" ] && grep -q "No tests found" "$PLAYWRIGHT_OUT"; then
      echo "onboarding: no UI spec matches --case $CASE (it is an API-tier case) — not a failure"
    else
      EXIT_CODE=1
    fi
  fi
fi

echo "onboarding: === done (exit=$EXIT_CODE) ==="
exit "$EXIT_CODE"
