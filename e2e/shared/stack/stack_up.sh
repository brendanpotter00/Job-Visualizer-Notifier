#!/usr/bin/env bash
# postgres check -> db ensure -> backend :8201 -> vite :3201 -> wait-for-ready
# (PLAN.md §1, §2, §12 steps 3-4).
#
# Usage: stack_up.sh [--refresh] [--artifacts-dir DIR]
#   --refresh          force ensure_db.sh to re-clone jobscraper_e2e
#   --artifacts-dir    where backend.log / frontend.log go (default: a
#                       scratch dir under e2e/add-companies/artifacts/.boot/)
#
# Never touches :8000/:8100/:3000 — the owner's stack. Only starts processes
# on :8201/:3201, and only ever kills what stack_down.sh's pidfiles record.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"
mkdir -p "$PID_DIR"

REFRESH=0
ARTIFACTS_DIR="$REPO_ROOT/e2e/add-companies/artifacts/.boot"
while [ $# -gt 0 ]; do
  case "$1" in
    --refresh) REFRESH=1; shift ;;
    --artifacts-dir) ARTIFACTS_DIR="$2"; shift 2 ;;
    *) echo "stack_up.sh: unknown arg $1" >&2; exit 1 ;;
  esac
done
mkdir -p "$ARTIFACTS_DIR"

# Idempotent self-cleanup FIRST (PLAN.md §8 "re-runnable back-to-back"): stop
# anything OUR pidfiles remember from a prior run before claiming the ports
# again. Without this, a second stack_up.sh call can fail to bind :8201/:3201
# (already held by the previous run's still-alive process), yet its health
# check happily curls the OLD server and reports success — silently testing
# stale code while the new (dead-on-arrival) process leaks as an orphan.
bash "$SCRIPT_DIR/stack_down.sh"

_port_owner_pid() {
  # `|| true`: lsof exits 1 when nothing matches (the normal case — the port
  # is free), and under `set -e -o pipefail` that would otherwise abort this
  # script right here via the command-substitution assignment at the call site.
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -1 || true
}

for port in 8201 3201; do
  owner="$(_port_owner_pid "$port")"
  if [ -n "$owner" ]; then
    echo "stack_up.sh: refusing to start — port $port is already held by pid $owner," \
      "which is NOT one of ours (stack_down.sh just ran and found nothing to stop)." \
      "Something else is using this e2e-only port; investigate before re-running." >&2
    exit 1
  fi
done

echo "stack_up.sh: checking postgres"
if ! docker exec "${E2E_PG_CONTAINER:-jobscraper-postgres}" pg_isready -U postgres >/dev/null 2>&1; then
  echo "stack_up.sh: postgres container not reachable — run 'docker compose up -d postgres'" >&2
  exit 1
fi

echo "stack_up.sh: ensuring jobscraper_e2e"
if [ "$REFRESH" = "1" ]; then
  bash "$SCRIPT_DIR/../db/ensure_db.sh" --refresh
else
  bash "$SCRIPT_DIR/../db/ensure_db.sh"
fi

# --- Backend -----------------------------------------------------------
echo "stack_up.sh: starting backend on :8201"

# Export env.e2e's variables into THIS shell so the uvicorn child inherits
# them. `set -a` auto-exports every var assigned while sourcing.
set -a
# shellcheck disable=SC1091
source "$SCRIPT_DIR/env.e2e"
set +a
# Defensive: env.e2e deliberately never sets this (see its comment) — but if
# the calling shell already exported one, drop it so the middleware sees
# settings.internal_api_key as None, not a stale non-empty string.
unset INTERNAL_API_KEY

# ANTHROPIC_API_KEY is deliberately absent from env.e2e (PLAN.md — no secret
# lives under e2e/). Inherit it from the calling shell if present, else fall
# back to the root .env.local the same way the rest of the app does.
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$REPO_ROOT/.env.local" ]; then
  ANTHROPIC_API_KEY="$(grep -E '^ANTHROPIC_API_KEY=' "$REPO_ROOT/.env.local" | head -1 | cut -d= -f2-)"
  export ANTHROPIC_API_KEY
fi

cd "$REPO_ROOT"
nohup "$REPO_ROOT/.venv/bin/python" -m uvicorn e2e.shared.stack.e2e_app:app \
  --host 127.0.0.1 --port 8201 \
  > "$ARTIFACTS_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_DIR/backend.pid"
echo "stack_up.sh: backend pid=$BACKEND_PID log=$ARTIFACTS_DIR/backend.log"

echo "stack_up.sh: waiting for backend health"
BACKEND_READY=0
for i in $(seq 1 60); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "stack_up.sh: backend process died during startup — see $ARTIFACTS_DIR/backend.log" >&2
    tail -n 60 "$ARTIFACTS_DIR/backend.log" >&2 || true
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:8201/health" >/dev/null 2>&1; then
    BACKEND_READY=1
    break
  fi
  sleep 1
done
if [ "$BACKEND_READY" != "1" ]; then
  echo "stack_up.sh: backend did not become healthy within 60s" >&2
  tail -n 60 "$ARTIFACTS_DIR/backend.log" >&2 || true
  exit 1
fi
echo "stack_up.sh: backend healthy"

# --- Frontend ------------------------------------------------------------
echo "stack_up.sh: starting frontend on :3201"
cd "$REPO_ROOT/src/frontend"
nohup npx vite dev --config "$SCRIPT_DIR/vite.e2e.config.ts" \
  > "$ARTIFACTS_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
cd "$REPO_ROOT"
echo "$FRONTEND_PID" > "$PID_DIR/frontend.pid"
echo "stack_up.sh: frontend pid=$FRONTEND_PID log=$ARTIFACTS_DIR/frontend.log"

FRONTEND_READY=0
for i in $(seq 1 60); do
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "stack_up.sh: frontend process died during startup — see $ARTIFACTS_DIR/frontend.log" >&2
    tail -n 60 "$ARTIFACTS_DIR/frontend.log" >&2 || true
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:3201/" >/dev/null 2>&1; then
    FRONTEND_READY=1
    break
  fi
  sleep 1
done
if [ "$FRONTEND_READY" != "1" ]; then
  echo "stack_up.sh: frontend did not become ready within 60s" >&2
  tail -n 60 "$ARTIFACTS_DIR/frontend.log" >&2 || true
  exit 1
fi
echo "stack_up.sh: frontend ready"

echo "stack_up.sh: stack is up (backend :8201, frontend :3201)"
