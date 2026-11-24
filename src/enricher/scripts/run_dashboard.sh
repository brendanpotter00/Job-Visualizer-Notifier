#!/bin/sh
# Canonical way to (re)launch the local dashboard from a DEV checkout of the
# enricher (your JVN checkout's src/enricher). See
# docs/handoffs/2026-07-12-prod-monitoring-after-ollama-cutover.md for the
# incident behind it: a stale `.claude/worktrees/` checkout silently served a
# UI build from before the engine-swap feature landed. `cli dashboard` itself
# refuses to run from a worktree path and warns when not on `main`; that
# warning is the staleness signal.
#
# It serves whatever is checked out and never touches git state: in the JVN
# monorepo, switching branches or pulling here would move your whole JVN checkout (and
# com.bp.jvn-health-watch runs from that working tree). Update it yourself.
#
# Usage: scripts/run_dashboard.sh [-- <extra cli-dashboard args>]
set -eu

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"

cd "$PROJECT_DIR"

# 0. Safety: the dashboard is a dev-only local tool — never run it from prod.
ROLE="$(cat .checkout-role 2>/dev/null || echo '')"
if [ "$ROLE" = "prod" ]; then
  echo "[run-dashboard] refusing: $PROJECT_DIR is marked prod (.checkout-role=prod). Run this from a dev checkout instead. See docs/ENVIRONMENTS.md." >&2
  exit 1
fi

# 1. Refuse uncommitted enricher changes: the served build should match a commit.
if ! git diff --quiet -- . || ! git diff --cached --quiet -- .; then
  echo "[run-dashboard] uncommitted tracked changes under $PROJECT_DIR — aborting. Commit or stash first." >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
SHA="$(git rev-parse --short HEAD)"
echo "[run-dashboard] serving $PROJECT_DIR at $BRANCH @ $SHA"

# 2. Rebuild the SPA. dashboard/dist is gitignored, so a fresh build is the
#    only way to guarantee the served UI matches the checked-out commit.
echo "[run-dashboard] building dashboard…"
(cd dashboard && npm ci && npm run build)

# 3. Serve.
echo "[run-dashboard] serving at http://127.0.0.1:8788 (Ctrl-C to stop)…"
exec "$UV_BIN" run python -m job_enricher.cli dashboard "$@"
