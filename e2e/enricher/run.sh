#!/usr/bin/env bash
# e2e/run.sh enricher [--fast] [--case EN-04] [--refresh-db] [--keep-up] [--enricher-ref REF]
#
# Stack up (backend :8207, NO frontend, db jobscraper_e2e_enricher, internal-key
# middleware ARMED) -> stub ollama on :8215 -> sandbox enricher (a copy of
# src/enricher, or `git archive REF:src/enricher`) -> boot guards -> pytest
# (API tier: real wrapper, real CLI) -> collect -> tear down.
#
# COSTS $0, unconditionally. The enricher's only model is stub_ollama.py on
# loopback; its config can only come from the sandbox .env.local the guards
# check; the wrapper's in-process path never reaches `claude -p` (the guards
# refuse to start unless `cli health` reports ollama/ollama); the backend runs
# with Browserbase off and a BLANK Anthropic key. Nothing here touches the real
# ollama on :11434, real JVN, or any prod database.
#
# --fast          the `fast` cases only (EN-00, EN-01, EN-04, EN-10)
# --case EN-04    one case (pytest -k en04)
# --enricher-ref  run the same cases against another version of the enricher,
#                 notably `enricher-prod-eeff1c9` — the code the cutover will
#                 put in prod. Cases marked `v7` are DESELECTED (not collected,
#                 so they cannot read as BLOCKED) when that ref's CLI has no
#                 `subcategory-push`.
# --keep-up       leave the backend, the stub and the sandbox up for a fix loop
# --refresh-db    re-provision jobscraper_e2e_enricher from scratch

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

FAST=0
CASE=""
REFRESH_DB=0
KEEP_UP=0
ENRICHER_REF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --fast) FAST=1; shift ;;
    --case) CASE="${2:-}"; shift 2 ;;
    --refresh-db) REFRESH_DB=1; shift ;;
    --keep-up) KEEP_UP=1; shift ;;
    --enricher-ref) ENRICHER_REF="${2:-}"; shift 2 ;;
    *) echo "enricher/run.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

echo "enricher: COST — \$0. Stub model on loopback, no claude, no real ollama, no" \
     "Browserbase, a blank Anthropic key on the backend, no host but this stack."

PY="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "enricher: $PY is missing — create the root venv (backend + scripts requirements)" >&2
  exit 2
fi

# --- The stack this section owns -----------------------------------------
export E2E_BACKEND_PORT=8207
export E2E_FRONTEND_PORT=3207          # never started (E2E_SKIP_FRONTEND=1)
export E2E_BACKEND_URL="http://127.0.0.1:${E2E_BACKEND_PORT}"
export E2E_TARGET_DB="jobscraper_e2e_enricher"
export E2E_EXPECTED_DB="$E2E_TARGET_DB"
export E2E_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/${E2E_TARGET_DB}"
export E2E_ENV_FILE="$SCRIPT_DIR/env.enricher"
export E2E_PID_DIR="$SCRIPT_DIR/.pids"
export E2E_DB_SCHEMA_ONLY=1
export E2E_SKIP_FRONTEND=1
export E2E_BLANK_ANTHROPIC_KEY=1
E2E_INTERNAL_API_KEY="$(grep -E '^INTERNAL_API_KEY=' "$E2E_ENV_FILE" | head -1 | cut -d= -f2-)"
export E2E_INTERNAL_API_KEY
export E2E_STUB_PORT=8215
export E2E_STUB_URL="http://127.0.0.1:${E2E_STUB_PORT}"
export E2E_KILLSWITCH_PORT=8206
case "$E2E_INTERNAL_API_KEY" in
  *not-a-secret*) : ;;
  *) echo "enricher: env.enricher must carry the TEST internal key" >&2; exit 2 ;;
esac

# --- Run lock (keyed on repo path AND section; outside the repo) ----------
REPO_HASH="$(printf '%s' "$REPO_ROOT" | shasum | cut -c1-12)"
LOCK_DIR="${TMPDIR:-/tmp}/jvn-e2e-${REPO_HASH}/enricher.lock"
HELD_LOCK=0
mkdir -p "$(dirname "$LOCK_DIR")"
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
else
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && ps -p "$OTHER_PID" -o pid= >/dev/null 2>&1; then
    echo "enricher: REFUSING TO START — another enricher run (pid $OTHER_PID) holds" \
      ":8207/:8215 and reseeds the same fixtures. Wait for it, or stop it." >&2
    exit 2
  fi
  echo "enricher: clearing a stale run lock left by pid ${OTHER_PID:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { echo "enricher: could not take the run lock" >&2; exit 2; }
  echo $$ > "$LOCK_DIR/pid"; HELD_LOCK=1
fi
echo "enricher: run lock acquired (pid $$)"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export E2E_ARTIFACTS_DIR="$SCRIPT_DIR/artifacts/$RUN_ID"
mkdir -p "$E2E_ARTIFACTS_DIR/stack" "$E2E_ARTIFACTS_DIR/cases" "$E2E_PID_DIR"

# The sandbox lives OUTSIDE the repo (sandbox.py's header says why).
SANDBOX_BASE="${TMPDIR:-/tmp}/jvn-e2e-${REPO_HASH}/enricher-sandbox"
export E2E_SANDBOX_ROOT="$SANDBOX_BASE/$RUN_ID"
export E2E_SANDBOX_DIR="$E2E_SANDBOX_ROOT/enricher"
export E2E_SANDBOX_INFO="$E2E_ARTIFACTS_DIR/sandbox.json"
export E2E_ENRICHER_REF="$ENRICHER_REF"

# EN-10's baseline: what the DEV tree's package-relative data dir looked like
# before anything ran. The sandbox must leave it exactly as found.
export E2E_DEV_DATA_BEFORE="$E2E_ARTIFACTS_DIR/dev-data-before.txt"
_dev_data_state() {
  local d="$REPO_ROOT/src/enricher/data"
  if [ -e "$d" ]; then
    echo "present"
    find "$d" -type f -exec stat -f '%N %z %m' {} + 2>/dev/null | sort
  else
    echo "absent"
  fi
}
_dev_data_state > "$E2E_DEV_DATA_BEFORE"

START_TS=$(date +%s)
EXIT_CODE=0
INTERRUPTED=0

_kill_pidfile() {
  local f="$E2E_PID_DIR/$1.pid"
  [ -f "$f" ] || return 0
  local pid
  pid="$(cat "$f" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "enricher: stopping $1 (pid $pid)"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$f"
}

_kill_sandbox_processes() {
  # Anything still running FROM this run's sandbox (a wrapper a failed case left
  # behind, or its CLI children). Scoped to the sandbox path, which nothing
  # outside this run can carry — the prod worker's path is a different tree.
  local pids
  pids="$(pgrep -f -- "$E2E_SANDBOX_DIR/" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "enricher: stopping leftover sandbox processes: $(echo $pids)"
    kill $pids 2>/dev/null || true
    sleep 1
    kill -9 $pids 2>/dev/null || true
  fi
}

write_summary() {
  local final_rc="$1"
  local elapsed=$(( $(date +%s) - START_TS ))
  "$PY" "$REPO_ROOT/e2e/write_summary.py" \
    --artifacts-dir "$E2E_ARTIFACTS_DIR" \
    --section enricher \
    --elapsed-seconds "$elapsed" \
    --exit-code "$final_rc" \
    --blocked "" \
    --interrupted "$INTERRUPTED" \
    --fast "$FAST" || echo "enricher: write_summary.py failed (non-fatal)" >&2
  echo "enricher: summary written to $E2E_ARTIFACTS_DIR/summary.md"
}

cleanup() {
  local rc=$?
  if [ "$KEEP_UP" = "1" ]; then
    echo "enricher: --keep-up given; leaving backend :8207, stub :8215 and the sandbox" \
         "at $E2E_SANDBOX_DIR"
  else
    _kill_sandbox_processes
    _kill_pidfile killswitch
    _kill_pidfile stub
    echo "enricher: tearing down the stack"
    bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true
  fi
  if [ -d "$E2E_SANDBOX_ROOT" ]; then
    "$PY" "$SCRIPT_DIR/sandbox.py" collect --root "$E2E_SANDBOX_ROOT" \
      --to "$E2E_ARTIFACTS_DIR/enricher-data" || echo "enricher: collect failed (non-fatal)" >&2
    if [ "$KEEP_UP" != "1" ]; then
      case "$E2E_SANDBOX_ROOT" in
        "$SANDBOX_BASE"/*) rm -rf "$E2E_SANDBOX_ROOT" ;;
        *) echo "enricher: NOT removing unexpected sandbox path $E2E_SANDBOX_ROOT" >&2 ;;
      esac
    fi
  fi
  write_summary "$rc"
  if [ "$HELD_LOCK" = "1" ]; then
    rm -rf "$LOCK_DIR"
  fi
  exit "$rc"
}
on_signal() {
  INTERRUPTED=1
  echo "enricher: received a shutdown signal — the run is being ABORTED, not completed" >&2
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

echo "enricher: === stack up (backend only) ==="
STACK_UP_ARGS=(--artifacts-dir "$E2E_ARTIFACTS_DIR/stack")
if [ "$REFRESH_DB" = "1" ]; then
  STACK_UP_ARGS+=(--refresh)
fi
if ! bash "$REPO_ROOT/e2e/shared/stack/stack_up.sh" "${STACK_UP_ARGS[@]}"; then
  echo "enricher: stack failed to come up" >&2
  exit 1
fi

echo "enricher: === repair the source clone's known drift (seed.py docstring) ==="
if ! "$PY" "$SCRIPT_DIR/seed.py" --repair 2>&1 | tee "$E2E_ARTIFACTS_DIR/drift-repair.txt"; then
  echo "enricher: drift repair failed — see $E2E_ARTIFACTS_DIR/drift-repair.txt" >&2
  exit 1
fi

echo "enricher: === stub ollama on :$E2E_STUB_PORT ==="
_kill_pidfile stub
for port in "$E2E_STUB_PORT" "$E2E_KILLSWITCH_PORT"; do
  owner="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  if [ -n "$owner" ]; then
    echo "enricher: refusing to start — :$port is held by pid $owner, which is not ours" >&2
    exit 1
  fi
done
nohup "$PY" "$SCRIPT_DIR/stub_ollama.py" --host 127.0.0.1 --port "$E2E_STUB_PORT" \
  > "$E2E_ARTIFACTS_DIR/stub.log" 2>&1 &
echo $! > "$E2E_PID_DIR/stub.pid"
STUB_READY=0
for _ in $(seq 1 40); do
  if curl -fsS "$E2E_STUB_URL/__stub/requests" >/dev/null 2>&1; then STUB_READY=1; break; fi
  sleep 0.25
done
if [ "$STUB_READY" != "1" ]; then
  echo "enricher: stub ollama did not come up — see $E2E_ARTIFACTS_DIR/stub.log" >&2
  exit 1
fi

echo "enricher: === sandbox (${ENRICHER_REF:-working tree}) ==="
SANDBOX_ARGS=(build --root "$E2E_SANDBOX_ROOT" --env-file "$E2E_ENV_FILE" --out "$E2E_SANDBOX_INFO")
if [ -n "$ENRICHER_REF" ]; then
  SANDBOX_ARGS+=(--ref "$ENRICHER_REF")
fi
if ! "$PY" "$SCRIPT_DIR/sandbox.py" "${SANDBOX_ARGS[@]}" 2>&1 | tee "$E2E_ARTIFACTS_DIR/sandbox.txt"; then
  echo "enricher: sandbox build failed — see $E2E_ARTIFACTS_DIR/sandbox.txt" >&2
  exit 1
fi
if ! "$PY" "$SCRIPT_DIR/sandbox.py" guard --root "$E2E_SANDBOX_ROOT" 2>&1 | tee -a "$E2E_ARTIFACTS_DIR/sandbox.txt"; then
  echo "enricher: boot guards refused — see $E2E_ARTIFACTS_DIR/sandbox.txt" >&2
  exit 1
fi
V7="$("$PY" -c "import json,sys; print(1 if json.load(open(sys.argv[1]))['v7'] else 0)" "$E2E_SANDBOX_INFO")"
export E2E_ENRICHER_V7="$V7"

echo "enricher: === pytest (API tier) ==="
PYTEST_ARGS=(-v -s --timeout=300)
MARKS=""
if [ -n "$CASE" ]; then
  PYTEST_ARGS+=(-k "$(echo "$CASE" | tr '[:upper:]' '[:lower:]' | tr -d '-')")
elif [ "$FAST" = "1" ]; then
  MARKS="fast"
fi
if [ "$V7" != "1" ]; then
  echo "enricher: this enricher has no \`subcategory-push\` (pre-v7) — deselecting v7 cases"
  MARKS="${MARKS:+$MARKS and }not v7"
fi
if [ -n "$MARKS" ]; then
  PYTEST_ARGS+=(-m "$MARKS")
fi
"$PY" -m pytest "$SCRIPT_DIR/api" "${PYTEST_ARGS[@]}" \
  --junitxml="$E2E_ARTIFACTS_DIR/pytest-junit.xml"
if [ "$?" != "0" ]; then
  EXIT_CODE=1
fi

# Belt and braces behind EN-10: the dev tree's data dir, after EVERYTHING ran.
if ! diff -q "$E2E_DEV_DATA_BEFORE" <(_dev_data_state) >/dev/null; then
  echo "enricher: ISOLATION BREACH — $REPO_ROOT/src/enricher/data changed during the run" >&2
  EXIT_CODE=1
fi

echo "enricher: === done (exit=$EXIT_CODE) ==="
exit "$EXIT_CODE"
