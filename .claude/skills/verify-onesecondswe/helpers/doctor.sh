#!/usr/bin/env bash
# verify-onesecondswe :: Doctor
#
# Read-only "is this instance worth driving?". Three checks, in order:
#   1. /health          -> OK 200 (hard fail otherwise)
#   2. /health/worker   -> 200 (SOFT: polled ~30s, warns on lingering 503 — no
#                          tool needs the worker, the lanes just heartbeat late)
#   3. window.__webmcp__.list() -> exactly the 14 expected tool names (hard fail;
#                          a short/missing shim means VITE_WEBMCP didn't take)
#
# Usage: doctor.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"

BACKEND=http://127.0.0.1:8201
FRONTEND=http://127.0.0.1:3201

# --- Node pin (Playwright shim probe hangs on 22.1.0) ----------------------
if [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  [ -d "$NVM_NODE" ] && export PATH="$NVM_NODE:$PATH"
fi

echo "doctor: 1/3 backend /health"
if ! curl -fsS "$BACKEND/health" >/dev/null 2>&1; then
  echo "doctor: FAIL — $BACKEND/health did not return 200. Is the stack up? (launch.sh)" >&2
  exit 1
fi
echo "doctor: /health OK"

echo "doctor: 2/3 worker /health/worker (soft, polling ~30s)"
WORKER_OK=0
for _ in $(seq 1 15); do
  if curl -fsS "$BACKEND/health/worker" >/dev/null 2>&1; then WORKER_OK=1; break; fi
  sleep 2
done
if [ "$WORKER_OK" = "1" ]; then
  echo "doctor: /health/worker OK"
else
  echo "doctor: WARN — /health/worker still 503 after ~30s (Procrastinate lanes not yet" \
       "heartbeating). None of the 14 tools need the worker, so driving read/CRUD tools is" \
       "still valid; only worker-backed side effects would be affected." >&2
fi

echo "doctor: 3/3 window.__webmcp__ shim probe (expects 14 tools)"
if [ ! -d "$REPO_ROOT/e2e/node_modules/@playwright" ]; then
  echo "doctor: installing e2e Playwright deps (first run)…"
  ( cd "$REPO_ROOT/e2e" && npm install --no-audit --no-fund >/dev/null 2>&1 && npx playwright install chromium >/dev/null 2>&1 ) || true
fi
(
  cd "$REPO_ROOT/e2e"
  npx playwright test \
    --config="$SKILL_DIR/helpers/verify.playwright.config.ts" \
    --grep '@doctor'
)
PROBE_RC=$?
if [ "$PROBE_RC" != "0" ]; then
  echo "doctor: FAIL — shim probe failed. If /health passed but the shim is missing/short," \
       "VITE_WEBMCP did not reach the vite child — re-run launch.sh (or launch.sh --env-file)." >&2
  exit 1
fi
echo "doctor: all checks passed — safe to drive."
