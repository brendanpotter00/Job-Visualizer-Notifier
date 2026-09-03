#!/usr/bin/env bash
# verify-onesecondswe :: Launch
#
# Boots the REAL app on the isolated e2e stack (:8201 backend, :3201 frontend,
# jobscraper_e2e DB) with the WebMCP tool surface turned on, by reusing
# e2e/shared/stack/stack_up.sh verbatim. Adds nothing to the harness; the ONLY
# thing this wrapper contributes is:
#   1. pinning Node 22.14.0 (the shell default here is 22.1.0, which hangs
#      Vite/Playwright silently — same pin e2e/run.sh makes), and
#   2. exporting VITE_WEBMCP=1 so the `vite dev` child registers window.__webmcp__.
#
# Never touches :8000/:8100/:3000 — inherited from stack_up.sh's own guards.
#
# Usage: launch.sh [--env-file] [--refresh-db]
#   --env-file    ALSO write VITE_WEBMCP=1 into src/frontend/.env.local (fallback
#                 for a Vite that ignores process-env VITE_ vars); recorded so
#                 cleanup.sh can remove exactly the line we added.
#   --refresh-db  force ensure_db.sh to re-clone jobscraper_e2e from source.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"

ENV_FILE=0
REFRESH_DB=0
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE=1; shift ;;
    --refresh-db) REFRESH_DB=1; shift ;;
    *) echo "launch.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

# --- Node pin (22.1.0 hangs the forks/Playwright toolchain) ----------------
if [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  if [ -d "$NVM_NODE" ]; then
    export PATH="$NVM_NODE:$PATH"
  fi
fi
echo "launch.sh: node $(node -v 2>/dev/null || echo 'NOT FOUND')"

# --- Prerequisite checks (fail loudly, not deep in stack_up) ---------------
if ! docker exec "${E2E_PG_CONTAINER:-jobscraper-postgres}" pg_isready -U postgres >/dev/null 2>&1; then
  echo "launch.sh: postgres container not reachable — run 'docker compose up -d postgres'" >&2
  exit 1
fi
if [ ! -x "$REPO_ROOT/.venv/bin/python" ]; then
  echo "launch.sh: $REPO_ROOT/.venv/bin/python missing — create the backend venv first" >&2
  exit 1
fi

# --- Artifacts dir (survives teardown; evidence lives here too) ------------
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACTS_DIR="$SKILL_DIR/artifacts/$RUN_ID"
mkdir -p "$ARTIFACTS_DIR/stack"
# Record the current run id so doctor/drive/cleanup target the same dir.
echo "$RUN_ID" > "$SKILL_DIR/artifacts/.current-run"
echo "launch.sh: run id=$RUN_ID  artifacts=$ARTIFACTS_DIR"

# --- The WebMCP flag -------------------------------------------------------
export VITE_WEBMCP=1
echo "launch.sh: exported VITE_WEBMCP=1 (process-scoped; stack_up's vite child inherits it)"

if [ "$ENV_FILE" = "1" ]; then
  ENV_LOCAL="$REPO_ROOT/src/frontend/.env.local"
  if ! grep -qsE '^VITE_WEBMCP=' "$ENV_LOCAL" 2>/dev/null; then
    printf '\n# added by verify-onesecondswe/launch.sh --env-file; removed by cleanup.sh\nVITE_WEBMCP=1\n' >> "$ENV_LOCAL"
    echo "$ENV_LOCAL" > "$SKILL_DIR/artifacts/.env-file-scaffolding"
    echo "launch.sh: wrote VITE_WEBMCP=1 scaffolding into $ENV_LOCAL"
  else
    echo "launch.sh: $ENV_LOCAL already sets VITE_WEBMCP — leaving it (cleanup will not touch it)"
  fi
fi

# --- Boot the stack (reused verbatim) --------------------------------------
STACK_ARGS=(--artifacts-dir "$ARTIFACTS_DIR/stack")
if [ "$REFRESH_DB" = "1" ]; then
  STACK_ARGS+=(--refresh)
fi
echo "launch.sh: === stack up ==="
bash "$REPO_ROOT/e2e/shared/stack/stack_up.sh" "${STACK_ARGS[@]}"

echo "launch.sh: stack is up. Next: doctor.sh (proves /health + the 14-tool shim)."
