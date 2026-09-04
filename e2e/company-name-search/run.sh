#!/usr/bin/env bash
# e2e/run.sh company-name-search [--runs N] [--case KEY] [--tag TAG] [--max-searches N]
#
# Boot a backend on :8202 against jobscraper_e2e with a REAL Browserbase Search
# key -> run the intent test over HTTP against it -> tear the backend down.
# The teardown trap runs however this script exits, including Ctrl-C.
#
# THIS RUN COSTS REAL MONEY. ~$0.007 per Browserbase Search call, one or two per
# case. The harness prints the count and the dollar figure and refuses to exceed
# --max-searches (default 60, the WHOLE invocation — raise it for --runs N).
# Never wire this into CI or a commit hook.

set -uo pipefail

SECTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SECTION_DIR/../.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python"
PORT=8202

# Everything mutable lives OUTSIDE the repo. `vercel dev` watches the repo root
# and does not consult .gitignore; the add-companies gate learned the hard way
# that a pidfile churning inside e2e/ kills the owner's frontend on :3000.
STATE_DIR="${TMPDIR:-/tmp}/jvn-name-search-$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)"
mkdir -p "$STATE_DIR"
PIDFILE="$STATE_DIR/backend.pid"
LOCK_DIR="$STATE_DIR/run.lock"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACTS="$SECTION_DIR/artifacts/$RUN_ID"
mkdir -p "$ARTIFACTS"

HELD_LOCK=0
BACKEND_PID=""

# ── one run at a time (:8202 is a single shared port) ──────────────────────
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
else
  OTHER="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER" ] && ps -p "$OTHER" -o pid= >/dev/null 2>&1; then
    echo "run.sh: REFUSING TO START — another name-search run (pid $OTHER) holds :$PORT." >&2
    rmdir "$ARTIFACTS" 2>/dev/null || true
    exit 2
  fi
  echo "run.sh: clearing a stale run lock left by pid ${OTHER:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" && echo $$ > "$LOCK_DIR/pid" && HELD_LOCK=1
fi

cleanup() {
  local rc=$?
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "run.sh: stopping backend (pid $BACKEND_PID)"
    kill "$BACKEND_PID" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$BACKEND_PID" 2>/dev/null || break; sleep 0.25; done
    kill -9 "$BACKEND_PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  [ "$HELD_LOCK" = "1" ] && rm -rf "$LOCK_DIR"
  exit "$rc"
}
trap cleanup EXIT INT TERM

# ── preconditions ──────────────────────────────────────────────────────────
if [ ! -x "$PY" ]; then
  echo "run.sh: no venv python at $PY" >&2; exit 1
fi
if ! docker exec "${E2E_PG_CONTAINER:-jobscraper-postgres}" pg_isready -U postgres >/dev/null 2>&1; then
  echo "run.sh: postgres not reachable — run 'docker compose up -d postgres'" >&2; exit 1
fi
if lsof -tiTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "run.sh: port $PORT is already held by something we did not start — investigate" >&2
  exit 1
fi

echo "run.sh: ensuring jobscraper_e2e (shared with the add-companies gate; read-only here)"
bash "$REPO_ROOT/e2e/shared/db/ensure_db.sh" || exit 1

# ── env: the file, then the secrets from .env.local ────────────────────────
set -a
# shellcheck disable=SC1091
source "$SECTION_DIR/env.name-search"
set +a
unset INTERNAL_API_KEY

_from_env_local() {
  grep -E "^$1=" "$REPO_ROOT/.env.local" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"
}
for key in BROWSERBASE_API_KEY BROWSERBASE_PROJECT_ID; do
  if [ -z "${!key:-}" ]; then
    val="$(_from_env_local "$key")"
    [ -n "$val" ] && export "$key=$val"
  fi
done
if [ -z "${BROWSERBASE_API_KEY:-}" ]; then
  echo "run.sh: BROWSERBASE_API_KEY not found in the environment or $REPO_ROOT/.env.local." >&2
  echo "run.sh: this suite cannot run without it — every case would 503." >&2
  exit 1
fi
# Never printed, never written to an artifact. The only thing said out loud is
# that one is present.
echo "run.sh: Browserbase Search key present (searches WILL be billed)"

# ── backend ────────────────────────────────────────────────────────────────
echo "run.sh: starting backend on :$PORT (log: $ARTIFACTS/backend.log)"
cd "$REPO_ROOT"
PYTHONPATH="$SECTION_DIR:$REPO_ROOT" nohup "$PY" -m uvicorn stack_app:app \
  --host 127.0.0.1 --port "$PORT" > "$ARTIFACTS/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PIDFILE"

READY=0
for _ in $(seq 1 60); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "run.sh: backend died during startup:" >&2
    tail -n 40 "$ARTIFACTS/backend.log" >&2
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then READY=1; break; fi
  sleep 1
done
if [ "$READY" != "1" ]; then
  echo "run.sh: backend did not become healthy in 60s" >&2
  tail -n 40 "$ARTIFACTS/backend.log" >&2
  exit 1
fi

# ── the suite ──────────────────────────────────────────────────────────────
"$PY" "$SECTION_DIR/intent_test.py" \
  --base-url "http://127.0.0.1:$PORT" \
  --json "$ARTIFACTS/results.json" \
  "$@" 2>&1 | tee "$ARTIFACTS/summary.txt"
RC=${PIPESTATUS[0]}

echo "run.sh: artifacts in $ARTIFACTS"
exit "$RC"
