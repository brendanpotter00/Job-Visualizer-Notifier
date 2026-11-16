#!/usr/bin/env bash
# e2e/run.sh billing [--fast] [--case BL-06] [--refresh-db] [--keep-up]
#
# Stripe preflight -> stack up (backend :8204, frontend :3204, db
# jobscraper_e2e_billing) -> a `stripe listen` forwarding real signed webhooks
# to :8204 -> cleanup -> pytest (API tier) -> playwright (UI tier) -> cleanup
# -> stack down.
#
# COSTS $0: Stripe SANDBOX only (a live key is refused here, in stack_app.py
# and in stripe_env.py). An unreachable sandbox is BLOCKED, not a regression.
# Local-only: the webhook forwarder needs the developer's `stripe login`.
#
# --fast skips the UI tier (the hosted Checkout page is the slow half).

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
    *) echo "billing/run.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

echo "billing: COST — \$0. Stripe SANDBOX only (a live key is refused at three layers);" \
     "no LLM call, no Browserbase session."

if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  [ -d "$NVM_NODE" ] && export PATH="$NVM_NODE:$PATH"
fi
echo "billing: node $(node -v 2>/dev/null || echo 'NOT FOUND')"

# --- The stack this section owns -------------------------------------------
export E2E_BACKEND_PORT=8204
export E2E_FRONTEND_PORT=3204
export E2E_BACKEND_URL="http://127.0.0.1:${E2E_BACKEND_PORT}"
export E2E_FRONTEND_URL="http://127.0.0.1:${E2E_FRONTEND_PORT}"
export E2E_TARGET_DB="jobscraper_e2e_billing"
export E2E_EXPECTED_DB="$E2E_TARGET_DB"
export E2E_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/${E2E_TARGET_DB}"
export E2E_ENV_FILE="$SCRIPT_DIR/env.billing"
export E2E_PID_DIR="$SCRIPT_DIR/.pids"
export E2E_DB_SCHEMA_ONLY=1
export E2E_APP_MODULE="e2e.billing.stack_app:app"
# Schema-only clone source (read, never written): the shared default, else local `jobscraper`.
if [ -z "${E2E_SOURCE_DB:-}" ]; then
  if docker exec "${E2E_PG_CONTAINER:-jobscraper-postgres}" psql -U postgres -Atc \
       "SELECT 1 FROM pg_database WHERE datname='jobscraper_pr243'" 2>/dev/null | grep -q 1; then
    export E2E_SOURCE_DB="jobscraper_pr243"
  else
    export E2E_SOURCE_DB="jobscraper"
  fi
fi

# billing_service.HANDLED_EVENT_TYPES; Stripe CLI 1.55+ requires an explicit list.
STRIPE_EVENTS="checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.paid,invoice.payment_failed"

# --- Run lock (per section; see subcategories/run.sh) ----------------------
LOCK_DIR="${TMPDIR:-/tmp}/jvn-e2e-$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)/billing.lock"
HELD_LOCK=0
mkdir -p "$(dirname "$LOCK_DIR")"
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
else
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && ps -p "$OTHER_PID" -o pid= >/dev/null 2>&1; then
    echo "billing: REFUSING TO START — another billing run (pid $OTHER_PID) holds :8204/:3204" \
         "and its Stripe objects. Wait for it, or stop it, then re-run." >&2
    exit 2
  fi
  echo "billing: clearing a stale run lock left by pid ${OTHER_PID:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { echo "billing: could not take the run lock" >&2; exit 2; }
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
fi
echo "billing: run lock acquired (pid $$)"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export E2E_ARTIFACTS_DIR="$SCRIPT_DIR/artifacts/$RUN_ID"
export E2E_RUN_ID="$RUN_ID"
mkdir -p "$E2E_ARTIFACTS_DIR/stack" "$E2E_ARTIFACTS_DIR/cases" "$E2E_PID_DIR"

START_TS=$(date +%s)
EXIT_CODE=0
INTERRUPTED=0
BLOCKED=""
STACK_UP=0
LISTEN_PIDFILE="$E2E_PID_DIR/stripe-listen.pid"

stop_listener() {
  if [ -f "$LISTEN_PIDFILE" ]; then
    local pid; pid="$(cat "$LISTEN_PIDFILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "billing: stopping stripe listen (pid $pid)"
      # The npm `stripe` is a wrapper; the listener is its child.
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$LISTEN_PIDFILE"
  fi
}

write_summary() {
  local final_rc="$1" end_ts elapsed
  end_ts=$(date +%s); elapsed=$((end_ts - START_TS))
  "$PY" "$REPO_ROOT/e2e/write_summary.py" \
    --artifacts-dir "$E2E_ARTIFACTS_DIR" --section billing \
    --elapsed-seconds "$elapsed" --exit-code "$final_rc" \
    --blocked "$BLOCKED" --interrupted "$INTERRUPTED" --fast "$FAST" \
    || echo "billing: write_summary.py failed (non-fatal)" >&2
  echo "billing: summary written to $E2E_ARTIFACTS_DIR/summary.md"
}

cleanup() {
  local rc=$?
  if [ "$STACK_UP" = "1" ] && [ -z "$BLOCKED" ] && [ "$KEEP_UP" != "1" ]; then
    echo "billing: deleting this run's Stripe objects and rows"
    (cd "$REPO_ROOT" && "$PY" -m e2e.billing.stripe_env cleanup) \
      || echo "billing: cleanup failed (non-fatal; the next run's pre-clean retries it)" >&2
  fi
  if [ "$KEEP_UP" = "1" ]; then
    echo "billing: --keep-up given; leaving the stack on :8204/:3204 and stripe listen running"
  else
    stop_listener
    bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true
  fi
  write_summary "$rc"
  [ "$HELD_LOCK" = "1" ] && rm -rf "$LOCK_DIR"
  exit "$rc"
}
on_signal() {
  INTERRUPTED=1
  echo "billing: received a shutdown signal — the run is being ABORTED, not completed" >&2
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

# --- Stripe credentials (never stored under e2e/) --------------------------
if [ -z "${STRIPE_SECRET_KEY:-}" ] && [ -f "$REPO_ROOT/.env.local" ]; then
  STRIPE_SECRET_KEY="$(grep -E '^STRIPE_SECRET_KEY=' "$REPO_ROOT/.env.local" | tail -1 | cut -d= -f2- | tr -d '"')"
fi
export STRIPE_SECRET_KEY="${STRIPE_SECRET_KEY:-}"
case "$STRIPE_SECRET_KEY" in
  sk_test_*|rk_test_*) ;;
  sk_live_*|rk_live_*)
    echo "billing: REFUSING TO RUN — STRIPE_SECRET_KEY is a LIVE key. This gate pays a real" \
         "Checkout; it may only ever run against a sandbox." >&2
    exit 1 ;;
  *)
    echo "billing: no Stripe sandbox key. Set STRIPE_SECRET_KEY (sk_test_…) or run" \
         "docs/implementations/pricingStripe/set_stripe_key.sh." >&2
    exit 1 ;;
esac

echo "billing: === stripe preflight ==="
PREFLIGHT_OUT="$(cd "$REPO_ROOT" && "$PY" -m e2e.billing.stripe_env preflight 2> "$E2E_ARTIFACTS_DIR/preflight.txt")"
PREFLIGHT_RC=$?
cat "$E2E_ARTIFACTS_DIR/preflight.txt"
if [ "$PREFLIGHT_RC" = "3" ]; then
  BLOCKED="stripe"
elif [ "$PREFLIGHT_RC" != "0" ]; then
  echo "billing: Stripe preflight failed (setup, not a product regression) — see above" >&2
  exit 1
else
  export STRIPE_PRICE_ID_PRO="${PREFLIGHT_OUT#STRIPE_PRICE_ID_PRO=}"
  echo "billing: sandbox price $STRIPE_PRICE_ID_PRO"
  if ! command -v stripe >/dev/null 2>&1; then
    echo "billing: the Stripe CLI is not installed (npm install -g @stripe/cli). It forwards" \
         "the real signed webhooks this gate asserts on." >&2
    exit 1
  fi
  STRIPE_WEBHOOK_SECRET="$(stripe listen --print-secret 2>/dev/null | grep -o 'whsec_[A-Za-z0-9]*' | head -1)"
  if [ -z "$STRIPE_WEBHOOK_SECRET" ]; then
    echo "billing: the Stripe CLI is not logged in to the sandbox — run 'stripe login'" \
         "and authorize the SAME sandbox as STRIPE_SECRET_KEY." >&2
    exit 1
  fi
  export STRIPE_WEBHOOK_SECRET
fi

if [ -n "$BLOCKED" ]; then
  # conftest skips every case on E2E_STRIPE_BLOCKED, so the summary reads BLOCKED.
  echo "billing: Stripe sandbox unreachable — recording every case as BLOCKED"
  export E2E_STRIPE_BLOCKED="Stripe sandbox unreachable at preflight"
  "$PY" -m pytest "$SCRIPT_DIR/api" -q --junitxml="$E2E_ARTIFACTS_DIR/pytest-junit.xml" || true
  exit 0
fi

echo "billing: === stack up ==="
STACK_UP_ARGS=(--artifacts-dir "$E2E_ARTIFACTS_DIR/stack")
[ "$REFRESH_DB" = "1" ] && STACK_UP_ARGS+=(--refresh)
if ! bash "$REPO_ROOT/e2e/shared/stack/stack_up.sh" "${STACK_UP_ARGS[@]}"; then
  echo "billing: stack failed to come up" >&2
  exit 1
fi
STACK_UP=1

echo "billing: === stripe listen -> :$E2E_BACKEND_PORT ==="
stop_listener
LISTEN_LOG="$E2E_ARTIFACTS_DIR/stack/stripe-listen.log"
nohup stripe listen --forward-to "http://127.0.0.1:${E2E_BACKEND_PORT}/api/billing/webhook" \
  --events "$STRIPE_EVENTS" > "$LISTEN_LOG" 2>&1 &
echo $! > "$LISTEN_PIDFILE"
LISTEN_READY=0
for _ in $(seq 1 30); do
  if grep -q "Ready!" "$LISTEN_LOG" 2>/dev/null; then LISTEN_READY=1; break; fi
  if ! kill -0 "$(cat "$LISTEN_PIDFILE")" 2>/dev/null; then break; fi
  sleep 1
done
if [ "$LISTEN_READY" != "1" ]; then
  echo "billing: stripe listen did not become ready — see $LISTEN_LOG" >&2
  tail -n 20 "$LISTEN_LOG" >&2 || true
  exit 1
fi
echo "billing: webhooks forwarding (log: $LISTEN_LOG)"

echo "billing: === pre-clean (a prior run may have been aborted) ==="
(cd "$REPO_ROOT" && "$PY" -m e2e.billing.stripe_env cleanup) || {
  echo "billing: pre-clean failed" >&2; exit 1; }

echo "billing: === pytest (API tier) ==="
PYTEST_ARGS=(-v -s --timeout=600)
if [ -n "$CASE" ]; then
  PYTEST_ARGS+=(-k "$(echo "$CASE" | tr '[:upper:]' '[:lower:]' | tr -d '-')")
fi
"$PY" -m pytest "$SCRIPT_DIR/api" "${PYTEST_ARGS[@]}" --junitxml="$E2E_ARTIFACTS_DIR/pytest-junit.xml"
PYTEST_RC=$?
# pytest exits 5 when -k selects nothing: a UI-only --case, not a failure.
if [ "$PYTEST_RC" != "0" ] && ! { [ -n "$CASE" ] && [ "$PYTEST_RC" = "5" ]; }; then
  EXIT_CODE=1
fi

echo "billing: === playwright (UI tier) ==="
if [ "$FAST" = "1" ] && [ -z "$CASE" ]; then
  echo "billing: --fast skips the UI tier (the hosted Checkout page is the slow half)"
else
  PLAYWRIGHT_GREP=""
  [ -n "$CASE" ] && PLAYWRIGHT_GREP="--grep=$CASE"
  PLAYWRIGHT_OUT="$E2E_ARTIFACTS_DIR/playwright-stdout.txt"
  ( cd "$REPO_ROOT/e2e" && npx playwright test --config="$SCRIPT_DIR/playwright.config.ts" $PLAYWRIGHT_GREP ) \
    2>&1 | tee "$PLAYWRIGHT_OUT"
  PLAYWRIGHT_RC=${PIPESTATUS[0]}
  if [ "$PLAYWRIGHT_RC" != "0" ]; then
    if [ -n "$CASE" ] && grep -q "No tests found" "$PLAYWRIGHT_OUT"; then
      echo "billing: no UI spec matches --case $CASE (it is an API-tier-only case) — not a failure"
    else
      EXIT_CODE=1
    fi
  fi
fi

echo "billing: === done (exit=$EXIT_CODE) ==="
exit "$EXIT_CODE"
