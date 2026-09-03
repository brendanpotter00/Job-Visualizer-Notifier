#!/usr/bin/env bash
# verify-onesecondswe :: Cleanup
#
# Tears down what a run created and NOTHING else:
#   1. stack_down.sh  — kills only pidfile-recorded backend/frontend, never by name
#   2. reset_user     — sweeps BOTH test identities' owned companies through the
#                       product's own DELETE path (mirrors fixtures.ts)
#   3. removes any VITE_WEBMCP=1 line launch.sh --env-file wrote (the default
#                       process-env launch leaves the tree untouched — nothing to undo)
#   4. re-confirms the evidence still exists at the run's artifacts dir
#
# Usage: cleanup.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"

echo "cleanup: 1/4 stack down"
bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true

echo "cleanup: 2/4 sweep both test identities' owned companies (product delete path)"
( cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" -m e2e.shared.db.reset_user http://127.0.0.1:8201 ) \
  || echo "cleanup: reset_user sweep failed (non-fatal; the next launch's DB scrub is the backstop)"

echo "cleanup: 3/4 remove VITE_WEBMCP scaffolding, if any"
MARKER="$SKILL_DIR/artifacts/.env-file-scaffolding"
if [ -f "$MARKER" ]; then
  ENV_LOCAL="$(cat "$MARKER" 2>/dev/null || true)"
  if [ -n "$ENV_LOCAL" ] && [ -f "$ENV_LOCAL" ]; then
    # Delete the exact two-line block launch.sh appended (its comment + the flag).
    tmp="$(mktemp)"
    grep -vE '^VITE_WEBMCP=1$|^# added by verify-onesecondswe/launch\.sh --env-file' "$ENV_LOCAL" > "$tmp" && mv "$tmp" "$ENV_LOCAL"
    echo "cleanup: removed VITE_WEBMCP scaffolding from $ENV_LOCAL"
  fi
  rm -f "$MARKER"
else
  echo "cleanup: no .env scaffolding recorded — nothing to undo"
fi

echo "cleanup: 4/4 confirm evidence survives teardown"
RUN_ID="$(cat "$SKILL_DIR/artifacts/.current-run" 2>/dev/null || true)"
if [ -n "$RUN_ID" ] && [ -d "$SKILL_DIR/artifacts/$RUN_ID" ]; then
  echo "cleanup: evidence preserved at $SKILL_DIR/artifacts/$RUN_ID"
  ls -1 "$SKILL_DIR/artifacts/$RUN_ID" 2>/dev/null | sed 's/^/  - /'
else
  echo "cleanup: no current-run evidence dir found (a run that never launched, or never drove)"
fi
echo "cleanup: done."
