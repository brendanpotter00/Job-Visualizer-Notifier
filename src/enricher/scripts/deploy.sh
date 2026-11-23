#!/bin/sh
# Controlled production deploy: pause the launchd worker, move the PROD checkout to a
# target ref, resync deps, resume, sanity-check. Run FROM the prod checkout
# (~/developer/personal/app). See docs/ENVIRONMENTS.md.
#
# Usage:
#   scripts/deploy.sh           # fast-forward the current branch (e.g. main)
#   scripts/deploy.sh <ref>     # check out an exact tag / branch / sha (also used to roll back)
set -eu

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.bp.job-enricher.plist"
UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"
LOCK_FILE="$PROJECT_DIR/data/.tick.lock"
TARGET_REF="${1:-}"

cd "$PROJECT_DIR"

# 0. Safety: only ever deploy the checkout that is marked prod.
ROLE="$(cat .checkout-role 2>/dev/null || echo '')"
if [ "$ROLE" != "prod" ]; then
  echo "[deploy] refusing: $PROJECT_DIR is not marked prod (.checkout-role='$ROLE'). See docs/ENVIRONMENTS.md." >&2
  exit 1
fi

# 1. Arm the resume trap BEFORE pausing the worker. Defining resume() and installing
#    the EXIT trap ahead of `launchctl unload` closes the tiny window where an exit
#    between unload and the trap would strand prod with no worker, and guarantees the
#    worker is reloaded on EVERY exit path (success or abort). The reload is always
#    attempted; a FAILED reload is loud and forces a non-zero exit so a workerless prod
#    is never mistaken for a healthy deploy.
resume() {
  status=$?                         # capture the pending exit status FIRST, before any command resets $?
  echo "[deploy] resuming launchd worker…"
  if ! launchctl load "$PLIST"; then
    echo "[deploy] WARN: worker reload FAILED — prod has NO enrichment worker. Run scripts/install_launchagents.sh from the prod checkout." >&2
    if [ "$status" -eq 0 ]; then status=1; fi   # keep any worse earlier failure; never exit 0 with the worker down
  fi
  exit "$status"
}
trap resume EXIT

echo "[deploy] pausing launchd worker…"
launchctl unload "$PLIST" 2>/dev/null || echo "[deploy] worker not loaded (continuing)"

# 1b. Verify the worker actually stopped. `launchctl unload` returns non-zero both when
#     the job "wasn't loaded" (benign) and when unload FAILED while the job is still
#     loaded (dangerous — a 600s tick could fire mid-deploy). Ask launchd directly: if
#     the label is still listed the worker is live, so hard-abort BEFORE touching the
#     tree. A truly not-loaded worker is absent from the list and proceeds (no false abort).
if launchctl list | grep -q "com.bp.job-enricher"; then
  echo "[deploy] ABORT: worker still loaded after unload — refusing to move the tree while a tick could fire. Investigate launchctl." >&2
  exit 1
fi

# 2. Refuse to deploy over a tick that is still running (unload does not kill an
#    already-spawned wrapper).
if [ -f "$LOCK_FILE" ]; then
  LOCK_PID="$(cut -d'|' -f1 "$LOCK_FILE" 2>/dev/null || echo '')"
  case "$LOCK_PID" in ''|*[!0-9]*) LOCK_PID='' ;; esac
  if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
    echo "[deploy] a tick is running (pid=$LOCK_PID). Aborting — retry when idle." >&2
    exit 1
  fi
fi

# 3. Prod must stay pristine (no tracked local edits to clobber).
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[deploy] prod has uncommitted tracked changes — aborting so nothing is clobbered." >&2
  exit 1
fi

# 4. Move to the target code.
git fetch origin
if [ -n "$TARGET_REF" ]; then
  git checkout "$TARGET_REF"
else
  git pull --ff-only
fi

# 5. Resync deps (no-op when uv.lock is unchanged).
"$UV_BIN" sync

# 6. Sanity-check the freshly-deployed tree. The worker is reloaded by the EXIT trap
#    regardless (intended) — we do NOT gate the resume on health. But a FAILED health
#    check must be loud and must make this script exit non-zero, so a broken checkout is
#    never reported as a clean deploy.
echo "[deploy] deployed $(git rev-parse --short HEAD). Running health check…"
if ! "$UV_BIN" run python -m job_enricher.cli health; then
  echo "[deploy] WARN: health check FAILED — prod may be unhealthy. Investigate / consider rollback: scripts/deploy.sh <previous-tag-or-sha>." >&2
  exit 1
fi
echo "[deploy] done. Watch the next tick: tail -f \"\$HOME/Library/Logs/job-enricher.log\""
