#!/bin/sh
# Controlled production deploy: park the launchd worker BETWEEN ticks, move the PROD
# checkout to a target ref, resync deps, resume, sanity-check. Run it FROM the prod
# checkout (~/developer/personal/enricher-prod/src/enricher), or point
# DEPLOY_PROJECT_DIR at it (the first deploy of main runs main's copy of this script
# against a prod still on the old tag). See docs/ENVIRONMENTS.md.
#
# Usage:
#   scripts/deploy.sh <ref>     # check out an exact tag / branch / sha (also used to roll back)
#   scripts/deploy.sh           # fast-forward the current BRANCH (refused on a detached HEAD)
#
# Knobs: DEPLOY_PROJECT_DIR (the prod src/enricher), DEPLOY_PARK_BUDGET_S (how long to
# wait for the running tick to end; default 14400), DEPLOY_PYTHON, UV_BIN.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${DEPLOY_PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.bp.job-enricher.plist"
UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"
LOCK_FILE="$PROJECT_DIR/data/.tick.lock"
WRAPPER="$PROJECT_DIR/scripts/enrich_tick_wrapper.sh"
PARK="$SCRIPT_DIR/lib/park_worker.py"
PARK_BUDGET_S="${DEPLOY_PARK_BUDGET_S:-14400}"
TARGET_REF="${1:-}"

cd "$PROJECT_DIR"

# 0. Safety: only ever deploy the checkout that is marked prod.
ROLE="$(cat .checkout-role 2>/dev/null || echo '')"
if [ "$ROLE" != "prod" ]; then
  echo "[deploy] refusing: $PROJECT_DIR is not marked prod (.checkout-role='$ROLE'). See docs/ENVIRONMENTS.md." >&2
  exit 1
fi

# 0b. The no-arg form fast-forwards a BRANCH. The prod checkout is a detached JVN
#     clone (pinned to the deployed ref), where `git pull` has nothing to follow.
if [ -z "$TARGET_REF" ] && ! git symbolic-ref -q HEAD >/dev/null; then
  echo "[deploy] refusing: prod is on a detached HEAD ($(git rev-parse --short HEAD)); pass a ref: scripts/deploy.sh <tag|sha|branch>" >&2
  exit 1
fi

# 0c. The parking helper must sit next to THIS script (copy the whole scripts/ dir).
if [ ! -f "$PARK" ]; then
  echo "[deploy] refusing: $PARK is missing — run deploy.sh from a full scripts/ directory (see docs/ENVIRONMENTS.md)." >&2
  exit 1
fi
PY="${DEPLOY_PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then PY="$PROJECT_DIR/.venv/bin/python"; else PY="$(command -v python3 || echo python3)"; fi
fi

# 1. Arm the resume trap BEFORE parking. resume() releases the tick lock we claimed
#    (only if it still records OUR pid) and reloads the worker once the unload has
#    been issued — on EVERY exit path, success or abort. A FAILED reload is loud and
#    forces a non-zero exit so a workerless prod is never mistaken for a healthy deploy.
#    The release is plain sh on purpose: by then step 4 may have checked out a ref with
#    no scripts/lib/park_worker.py (every pre-consolidation tag, e.g. a rollback to
#    enricher-prod-eeff1c9) and step 5 may have rebuilt the venv under $PY. A lock left
#    naming our dead pid would make every worker fire skip for 3 h.
CLAIMED=0
UNLOADED=0
release_tick_lock() {
  [ -f "$LOCK_FILE" ] || return 0
  holder="$(cut -d'|' -f1 "$LOCK_FILE" 2>/dev/null | head -n 1 | tr -d '[:space:]')"
  if [ "$holder" = "$$" ]; then
    rm -f "$LOCK_FILE" && echo "[deploy] released our tick lock"
  else
    echo "[deploy] the tick lock is not ours (holder='$holder'); left alone"
  fi
}
resume() {
  status=$?                         # capture the pending exit status FIRST, before any command resets $?
  if [ "$CLAIMED" = "1" ]; then
    release_tick_lock || echo "[deploy] WARN: could not release the tick lock" >&2
  fi
  if [ "$UNLOADED" = "1" ]; then
    echo "[deploy] resuming launchd worker…"
    if ! launchctl load "$PLIST"; then
      echo "[deploy] WARN: worker reload FAILED — prod has NO enrichment worker. Run scripts/install_launchagents.sh from the prod checkout." >&2
      if [ "$status" -eq 0 ]; then status=1; fi   # keep any worse earlier failure; never exit 0 with the worker down
    fi
  fi
  exit "$status"
}
trap resume EXIT
trap 'exit 130' INT TERM

# 2. Park between ticks: wait (wall clock, <= DEPLOY_PARK_BUDGET_S) until no tick
#    runs, then hold the enricher's own lock with OUR pid. Every launchd fire from
#    here on exits 75 ("lock held"). Ticks run back to back with a ~60 s gap, so
#    "abort if a tick is running" could never succeed; waiting for the gap does.
echo "[deploy] waiting for the gap between ticks (budget ${PARK_BUDGET_S}s)…"
if ! "$PY" -I "$PARK" claim --lock "$LOCK_FILE" --wrapper "$WRAPPER" \
     --budget-s "$PARK_BUDGET_S" --owner-pid "$$"; then
  echo "[deploy] a tick is still running after ${PARK_BUDGET_S}s (wedged?). Aborting — nothing was changed." >&2
  exit 1
fi
CLAIMED=1
# Let the finishing wrapper (its final metrics-push) exit before launchd SIGTERMs it.
"$PY" -I "$PARK" wait-idle --wrapper "$WRAPPER" --budget-s 120 || true

echo "[deploy] pausing launchd worker…"
UNLOADED=1
launchctl unload "$PLIST" 2>/dev/null || echo "[deploy] worker not loaded (continuing)"

# 2b. Verify the worker actually stopped. `launchctl unload` returns non-zero both when
#     the job "wasn't loaded" (benign) and when unload FAILED while the job is still
#     loaded (dangerous). Ask launchd directly: if the label is still listed the worker
#     is live, so hard-abort BEFORE touching the tree.
# Exact label match: a future com.bp.job-enricher-* agent must not read as "still loaded".
if launchctl list | awk '{print $3}' | grep -qx "com.bp.job-enricher"; then
  echo "[deploy] ABORT: worker still loaded after unload — refusing to move the tree while a tick could fire. Investigate launchctl." >&2
  exit 1
fi

# 2c. Belt and braces: the lock must be OURS now. A different LIVE pid (kill -0)
#     means a tick is running — never move the tree under it.
LOCK_PID="$(cut -d'|' -f1 "$LOCK_FILE" 2>/dev/null || echo '')"
case "$LOCK_PID" in ''|*[!0-9]*) LOCK_PID='' ;; esac
if [ "$LOCK_PID" != "$$" ] && [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
  echo "[deploy] a tick is running (pid=$LOCK_PID). Aborting — retry when idle." >&2
  exit 1
fi
if ! "$PY" -I "$PARK" wait-idle --wrapper "$WRAPPER" --budget-s 120; then
  echo "[deploy] a wrapper is still running after the unload. Aborting." >&2
  exit 1
fi

# 3. Prod must stay pristine (no tracked local edits to clobber).
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[deploy] prod has uncommitted tracked changes — aborting so nothing is clobbered." >&2
  exit 1
fi

# 4. Move to the target code. A branch name resolves to origin's copy (the local
#    branch in a fresh clone is stale); the checkout is always detached at a commit.
git fetch --tags origin
if [ -n "$TARGET_REF" ]; then
  if git rev-parse -q --verify "refs/remotes/origin/$TARGET_REF^{commit}" >/dev/null; then
    TARGET_COMMIT="$(git rev-parse "refs/remotes/origin/$TARGET_REF^{commit}")"
  else
    TARGET_COMMIT="$(git rev-parse --verify "$TARGET_REF^{commit}")"
  fi
  echo "[deploy] $TARGET_REF -> $TARGET_COMMIT"
  git -c advice.detachedHead=false checkout --detach "$TARGET_COMMIT"
else
  git pull --ff-only
fi

# 5. Resync deps exactly to the committed uv.lock (never re-resolve in prod).
"$UV_BIN" sync --frozen

# 6. Sanity-check the freshly-deployed tree (the worker is still parked: any schema
#    migration runs HERE). The worker is reloaded by the EXIT trap regardless — we do
#    NOT gate the resume on health. But a FAILED health check must be loud and make
#    this script exit non-zero, so a broken checkout is never reported as a clean deploy.
echo "[deploy] deployed $(git rev-parse --short HEAD). Running health check…"
if ! "$UV_BIN" run python -m job_enricher.cli health; then
  echo "[deploy] WARN: health check FAILED — prod may be unhealthy. Investigate / consider rollback: scripts/deploy.sh <previous-tag-or-sha>." >&2
  exit 1
fi
echo "[deploy] done. Watch the next tick: tail -f \"\$HOME/Library/Logs/job-enricher.log\""
