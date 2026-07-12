#!/bin/sh
# Canonical way to (re)launch the local dashboard: always from the main dev
# checkout on an up-to-date `main`, never from a scratch git worktree. See
# docs/handoffs/2026-07-12-prod-monitoring-after-ollama-cutover.md for the
# incident this guards against — a stale `.claude/worktrees/` checkout
# silently served a UI build from before the engine-swap feature landed.
# `cli dashboard` itself refuses to run from a worktree path as a backstop;
# this script is the supported entry point.
#
# Usage: scripts/run_dashboard.sh [-- <extra cli-dashboard args>]
set -eu

PROJECT_DIR="$HOME/developer/personal/job-enricher"
UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"

cd "$PROJECT_DIR"

# 0. Safety: the dashboard is a dev-only local tool — never run it from prod.
ROLE="$(cat .checkout-role 2>/dev/null || echo '')"
if [ "$ROLE" = "prod" ]; then
  echo "[run-dashboard] refusing: $PROJECT_DIR is marked prod (.checkout-role=prod). Run this from the dev checkout instead. See docs/ENVIRONMENTS.md." >&2
  exit 1
fi

# 1. Refuse a dirty tree rather than silently stashing/clobbering work.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[run-dashboard] uncommitted tracked changes in $PROJECT_DIR — aborting so nothing is clobbered. Commit or stash first." >&2
  exit 1
fi

# 2. Update to the latest main.
echo "[run-dashboard] updating to origin/main…"
git fetch origin
git switch main
git pull --ff-only origin main

# 3. Rebuild the SPA. dashboard/dist is gitignored, so a fresh build is the
#    only way to guarantee the served UI matches the checked-out commit.
echo "[run-dashboard] building dashboard…"
(cd dashboard && npm ci && npm run build)

# 4. Serve.
echo "[run-dashboard] serving at http://127.0.0.1:8788 (Ctrl-C to stop)…"
exec "$UV_BIN" run python -m job_enricher.cli dashboard "$@"
