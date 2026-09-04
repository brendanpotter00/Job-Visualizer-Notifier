#!/usr/bin/env bash
# verify-onesecondswe :: Cleanup
#
# Tears down what a run created and NOTHING else:
#   1. stack_down.sh  — kills only pidfile-recorded backend/frontend, never by name
#   2. reset_user     — sweeps BOTH test identities' owned companies through the
#                       product's own DELETE path (mirrors fixtures.ts)
#   3. reset_tier3    — clears the Tier-3 side-effect rows reset_user does NOT touch:
#                       the drive's anonymous feedback + user_enabled_companies /
#                       user_saved_filters / feature_upvotes for both fixtures
#   4. removes ONLY the marker-comment + VITE_WEBMCP=1 block launch.sh --env-file
#                       appended (a user's own VITE_WEBMCP=1 elsewhere is preserved;
#                       the default process-env launch leaves the tree untouched)
#   5. re-confirms the evidence still exists at the run's artifacts dir
#
# Usage: cleanup.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"

echo "cleanup: 1/5 stack down"
bash "$REPO_ROOT/e2e/shared/stack/stack_down.sh" || true

echo "cleanup: 2/5 sweep both test identities' owned companies (product delete path)"
( cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" -m e2e.shared.db.reset_user http://127.0.0.1:8201 ) \
  || echo "cleanup: reset_user sweep failed (non-fatal; the next launch's DB scrub is the backstop)"

echo "cleanup: 3/5 reset Tier-3 side-effect state (anonymous feedback + enabled-companies/saved-filters/upvotes)"
( cd "$REPO_ROOT" && "$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/reset_tier3.py" ) \
  || echo "cleanup: reset_tier3 failed (non-fatal; the next launch's DB scrub is the backstop)"

echo "cleanup: 4/5 remove VITE_WEBMCP scaffolding, if any"
MARKER="$SKILL_DIR/artifacts/.env-file-scaffolding"
if [ -f "$MARKER" ]; then
  ENV_LOCAL="$(cat "$MARKER" 2>/dev/null || true)"
  if [ -n "$ENV_LOCAL" ] && [ -f "$ENV_LOCAL" ]; then
    # Remove ONLY the block launch.sh --env-file appended: its marker comment and
    # the VITE_WEBMCP=1 line IMMEDIATELY under it. A global `grep -v VITE_WEBMCP=1`
    # would also eat a flag a user set for their own reasons elsewhere in the file.
    tmp="$(mktemp)"
    awk '
      /^# added by verify-onesecondswe\/launch\.sh --env-file/ { pending=1; next }
      pending && $0 == "VITE_WEBMCP=1" { pending=0; next }
      { pending=0; print }
    ' "$ENV_LOCAL" > "$tmp" && mv "$tmp" "$ENV_LOCAL"
    echo "cleanup: removed VITE_WEBMCP scaffolding from $ENV_LOCAL"
  fi
  rm -f "$MARKER"
else
  echo "cleanup: no .env scaffolding recorded — nothing to undo"
fi

echo "cleanup: 5/5 confirm evidence survives teardown"
RUN_ID="$(cat "$SKILL_DIR/artifacts/.current-run" 2>/dev/null || true)"
if [ -n "$RUN_ID" ] && [ -d "$SKILL_DIR/artifacts/$RUN_ID" ]; then
  echo "cleanup: evidence preserved at $SKILL_DIR/artifacts/$RUN_ID"
  ls -1 "$SKILL_DIR/artifacts/$RUN_ID" 2>/dev/null | sed 's/^/  - /'
else
  echo "cleanup: no current-run evidence dir found (a run that never launched, or never drove)"
fi
echo "cleanup: done."
