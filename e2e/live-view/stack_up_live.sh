#!/usr/bin/env bash
# stack_up_live.sh --artifacts-dir DIR
#
# The ``--live`` variant of e2e/shared/stack/stack_up.sh: same database, same ports
# (:8201 / :3201), same pidfiles — so `stack_down.sh` still stops it — but it exports
# `env.live` and launches `live-view/stack_app.py`, which is the one entrypoint in this
# repo that permits CAPTURE_USE_BROWSERBASE=true.
#
# Deliberately NOT a flag on the shared script. That script is what protects the
# frequently-run add-companies gate from ever billing a browser hour, and the way to
# keep a guard trustworthy is to not give it an off switch.

set -euo pipefail

SECTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SECTION_DIR/../.." && pwd)"
SHARED="$REPO_ROOT/e2e/shared/stack"
PID_DIR="$SHARED/.pids"
mkdir -p "$PID_DIR"

ARTIFACTS_DIR="$SECTION_DIR/artifacts/.boot"
while [ $# -gt 0 ]; do
  case "$1" in
    --artifacts-dir) ARTIFACTS_DIR="$2"; shift 2 ;;
    *) echo "stack_up_live.sh: unknown arg $1" >&2; exit 1 ;;
  esac
done
mkdir -p "$ARTIFACTS_DIR"

bash "$SHARED/stack_down.sh"

for port in 8201 3201; do
  owner="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  if [ -n "$owner" ]; then
    echo "stack_up_live.sh: port $port is held by pid $owner, which is not ours" >&2
    exit 1
  fi
done

if ! docker exec "${E2E_PG_CONTAINER:-jobscraper-postgres}" pg_isready -U postgres >/dev/null 2>&1; then
  echo "stack_up_live.sh: postgres not reachable — run 'docker compose up -d postgres'" >&2
  exit 1
fi
bash "$SHARED/../db/ensure_db.sh"

set -a
# shellcheck disable=SC1091
source "$SECTION_DIR/env.live"
set +a
unset INTERNAL_API_KEY

# The three secrets, read from the repo-root .env.local exactly the way the shared
# script reads ANTHROPIC_API_KEY. None of them is ever written under e2e/.
for var in ANTHROPIC_API_KEY BROWSERBASE_API_KEY BROWSERBASE_PROJECT_ID; do
  if [ -z "${!var:-}" ] && [ -f "$REPO_ROOT/.env.local" ]; then
    value="$(grep -E "^${var}=" "$REPO_ROOT/.env.local" | head -1 | cut -d= -f2-)"
    export "$var=$value"
  fi
  if [ -z "${!var:-}" ]; then
    echo "stack_up_live.sh: $var is not set and is not in .env.local — --live needs it" >&2
    exit 1
  fi
done

echo "stack_up_live.sh: *** THIS RUN WILL BILL ONE BROWSERBASE SESSION ***"

cd "$REPO_ROOT"
PYTHONPATH="$REPO_ROOT" nohup "$REPO_ROOT/.venv/bin/python" -m uvicorn \
  --app-dir "$SECTION_DIR" stack_app:app \
  --host 127.0.0.1 --port 8201 \
  > "$ARTIFACTS_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_DIR/backend.pid"

for _ in $(seq 1 60); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "stack_up_live.sh: backend died on startup" >&2
    tail -n 40 "$ARTIFACTS_DIR/backend.log" >&2 || true
    exit 1
  fi
  curl -fsS "http://127.0.0.1:8201/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:8201/health" >/dev/null 2>&1 || {
  echo "stack_up_live.sh: backend never became healthy" >&2
  tail -n 40 "$ARTIFACTS_DIR/backend.log" >&2 || true
  exit 1
}
echo "stack_up_live.sh: backend healthy on :8201"

cd "$REPO_ROOT/src/frontend"
nohup npx vite dev --config "$SHARED/vite.e2e.config.ts" \
  > "$ARTIFACTS_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
cd "$REPO_ROOT"
echo "$FRONTEND_PID" > "$PID_DIR/frontend.pid"
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:3201/" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:3201/" >/dev/null 2>&1 || {
  echo "stack_up_live.sh: frontend never became ready" >&2
  tail -n 40 "$ARTIFACTS_DIR/frontend.log" >&2 || true
  exit 1
}
echo "stack_up_live.sh: stack is up (backend :8201 WITH Browserbase, frontend :3201)"
