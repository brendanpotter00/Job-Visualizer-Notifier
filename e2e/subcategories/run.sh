#!/usr/bin/env bash
# e2e/run.sh subcategories [--fast] [--case SC-02] [--refresh-db] [--keep-up]
#
# Stack up (backend :8203, frontend :3203, db jobscraper_e2e_subcategories)
#   -> seed -> pytest (API tier) -> playwright (UI tier) -> stack down.
#
# COSTS $0, unconditionally and with no opt-in that changes that. No LLM call,
# no Browserbase session, no request to any host but its own stack: every fact
# this gate asserts is a property of `enrichment_subcategories && ARRAY[...]`
# over eleven rows `seed.py` wrote. `e2e_app.py` refuses to boot with
# CAPTURE_USE_BROWSERBASE=true or a Browserbase key set, and
# `env.subcategories` blanks both.
#
# --fast skips the UI tier. The API tier is the SQL truth and takes seconds;
# the UI tier drives a real browser and is the slow half. Neither tier is
# "live" in the add-companies sense — there is nothing here to be live to.
#
# WHY ITS OWN PORTS, DATABASE, PIDFILES AND LOCK. `live-view` reuses
# add-companies' stack because it needs exactly that stack. This section needs
# the opposite: a database it SEEDS, which it therefore may not share. Once the
# database is its own, sharing the ports would only mean the two gates could
# never run at the same time for no reason. So it takes a lock keyed on its own
# section name and leaves :8201/:3201 alone.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

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
    *) echo "subcategories/run.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

echo "subcategories: COST — \$0. No LLM call, no Browserbase session, no network" \
     "beyond this section's own stack."

# Vitest and Playwright both hang on Node < 22.12 with no output (repo memory
# note). run.sh's own attempt happens before the hand-off, but this script is
# also runnable directly, so it repeats the fix rather than relying on that.
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  if [ -d "$NVM_NODE" ]; then
    export PATH="$NVM_NODE:$PATH"
  fi
fi
echo "subcategories: node $(node -v 2>/dev/null || echo 'NOT FOUND')"

# --- The stack this section owns -----------------------------------------
# Exported, not passed as flags, because these same values have to reach four
# processes this script does not invoke directly: vite's config, Playwright's
# config, pytest's conftest and the backend. See stack_up.sh's header.
export E2E_BACKEND_PORT=8203
export E2E_FRONTEND_PORT=3203
export E2E_BACKEND_URL="http://127.0.0.1:${E2E_BACKEND_PORT}"
export E2E_FRONTEND_URL="http://127.0.0.1:${E2E_FRONTEND_PORT}"
export E2E_TARGET_DB="jobscraper_e2e_subcategories"
export E2E_EXPECTED_DB="$E2E_TARGET_DB"
export E2E_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/${E2E_TARGET_DB}"
export E2E_ENV_FILE="$SCRIPT_DIR/env.subcategories"
export E2E_PID_DIR="$SCRIPT_DIR/.pids"
export E2E_DB_SCHEMA_ONLY=1

# --- Run lock -------------------------------------------------------------
# Keyed on repo path AND section, so this can run ALONGSIDE the add-companies
# gate (different ports, different pidfiles, different database) but never
# alongside a second copy of ITSELF — which would reseed the fixtures out from
# under the first run's assertions.
#
# Outside the repo, deliberately: `vercel dev` watches the repo root and a lock
# directory churning under it has taken the owner's dev server down before.
LOCK_DIR="${TMPDIR:-/tmp}/jvn-e2e-$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)/subcategories.lock"
HELD_LOCK=0
mkdir -p "$(dirname "$LOCK_DIR")"
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"
  HELD_LOCK=1
else
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && ps -p "$OTHER_PID" -o pid= >/dev/null 2>&1; then
    echo "subcategories: REFUSING TO START — another subcategories run (pid $OTHER_PID)" \
      "holds the stack on :8203/:3203 and is reseeding the same fixtures. Wait for it," \
      "or stop it, then re-run." >&2
    exit 2
  fi
  echo "subcategories: clearing a stale run lock left by pid ${OTHER_PID:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { echo "subcategories: could not take the run lock" >&2; exit 2; }
  echo $$ > "$LOCK_DIR/pid"
  HELD_LOCK=1
fi
echo "subcategories: run lock acquired (pid $$)"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export E2E_ARTIFACTS_DIR="$SCRIPT_DIR/artifacts/$RUN_ID"
mkdir -p "$E2E_ARTIFACTS_DIR/stack" "$E2E_ARTIFACTS_DIR/cases"

START_TS=$(date +%s)
EXIT_CODE=0
INTERRUPTED=0

cleanup() {
  local rc=$?
  if [ "$KEEP_UP" = "1" ]; then
    echo "subcategories: --keep-up given; leaving the stack on :8203/:3203"
  else
    echo "subcategories: tearing down the stack"
    bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true
  fi
  write_summary "$rc"
  if [ "$HELD_LOCK" = "1" ]; then
    rm -rf "$LOCK_DIR"
  fi
  exit "$rc"
}
# INT/TERM mark the run ABORTED before falling through to cleanup, so the
# summary does not publish the resulting teardown cascade as a list of case
# failures (see write_summary.py's four verdicts).
on_signal() {
  INTERRUPTED=1
  echo "subcategories: received a shutdown signal — the run is being ABORTED, not completed" >&2
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

write_summary() {
  local final_rc="$1"
  local end_ts elapsed
  end_ts=$(date +%s)
  elapsed=$((end_ts - START_TS))
  "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/e2e/write_summary.py" \
    --artifacts-dir "$E2E_ARTIFACTS_DIR" \
    --section subcategories \
    --elapsed-seconds "$elapsed" \
    --exit-code "$final_rc" \
    --blocked "" \
    --interrupted "$INTERRUPTED" \
    --fast "$FAST" || echo "subcategories: write_summary.py failed (non-fatal)" >&2
  echo "subcategories: summary written to $E2E_ARTIFACTS_DIR/summary.md"
}

echo "subcategories: === stack up ==="
STACK_UP_ARGS=(--artifacts-dir "$E2E_ARTIFACTS_DIR/stack")
if [ "$REFRESH_DB" = "1" ]; then
  STACK_UP_ARGS+=(--refresh)
fi
if ! bash "$REPO_ROOT/e2e/shared/stack/stack_up.sh" "${STACK_UP_ARGS[@]}"; then
  echo "subcategories: stack failed to come up" >&2
  EXIT_CODE=1
  exit "$EXIT_CODE"
fi

echo "subcategories: === seed ==="
# BEFORE pytest as well as before Playwright. The API tier reseeds per test
# (conftest autouse), but the taxonomy check inside seed.py is a PROVISIONING
# assertion: a database missing the 17 dimension rows makes the UI tree expand
# into nothing and every UI case fail for a reason that looks like a product
# regression. Fail here instead, where the message names the fix.
if ! "$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/seed.py" 2>&1 | tee "$E2E_ARTIFACTS_DIR/seed.txt"; then
  echo "subcategories: seeding failed — see $E2E_ARTIFACTS_DIR/seed.txt" >&2
  EXIT_CODE=1
  exit "$EXIT_CODE"
fi

echo "subcategories: === pytest (API tier) ==="
PYTEST_ARGS=(-v -s --timeout=120)
if [ -n "$CASE" ]; then
  # Test functions are named test_sc02_..., so "SC-02" normalizes to "sc02"
  # for pytest's -k substring match. Playwright's describe titles carry the
  # hyphen literally, so its --grep below uses $CASE unnormalized.
  PYTEST_K="$(echo "$CASE" | tr '[:upper:]' '[:lower:]' | tr -d '-')"
  PYTEST_ARGS+=(-k "$PYTEST_K")
fi
"$REPO_ROOT/.venv/bin/python" -m pytest "$SCRIPT_DIR/api" "${PYTEST_ARGS[@]}" \
  --junitxml="$E2E_ARTIFACTS_DIR/pytest-junit.xml"
PYTEST_RC=$?
if [ "$PYTEST_RC" != "0" ]; then
  EXIT_CODE=1
fi

echo "subcategories: === playwright (UI tier) ==="
if [ "$FAST" = "1" ] && [ -z "$CASE" ]; then
  echo "subcategories: --fast skips the UI tier (the API tier is the SQL truth and is the cheap half)"
else
  # Re-seed with the reveal flag ON: the API tier's last test may have left it
  # off (SC-05 turns it off deliberately), and a UI run against a flag-off
  # database would find no subcategory control and fail four cases for a
  # fixture reason. SC-05's own UI spec turns it off again itself.
  "$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/seed.py" >/dev/null
  PLAYWRIGHT_GREP=""
  if [ -n "$CASE" ]; then
    PLAYWRIGHT_GREP="--grep=$CASE"
  fi
  # NOT under $E2E_ARTIFACTS_DIR/ui — Playwright wipes its own outputDir on
  # start, which deletes a log `tee` has already created there.
  PLAYWRIGHT_OUT="$E2E_ARTIFACTS_DIR/playwright-stdout.txt"
  (
    cd "$REPO_ROOT/e2e"
    npx playwright test --config="$SCRIPT_DIR/playwright.config.ts" $PLAYWRIGHT_GREP
  ) 2>&1 | tee "$PLAYWRIGHT_OUT"
  PLAYWRIGHT_RC=${PIPESTATUS[0]}
  if [ "$PLAYWRIGHT_RC" != "0" ]; then
    # `--case SC-06` matches no UI spec title on purpose — SC-06 is a wire-format
    # fact with no rendered surface (see CASES.md). Playwright treats a --grep
    # that matches zero tests as a hard error; that is not this case failing.
    if [ -n "$CASE" ] && grep -q "No tests found" "$PLAYWRIGHT_OUT"; then
      echo "subcategories: no UI spec matches --case $CASE (it is an API-tier-only case) — not a failure"
    else
      EXIT_CODE=1
    fi
  fi
fi

echo "subcategories: === done (exit=$EXIT_CODE) ==="
exit "$EXIT_CODE"
