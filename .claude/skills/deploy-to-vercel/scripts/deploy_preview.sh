#!/usr/bin/env bash
#
# Trigger an on-demand Vercel PREVIEW deployment for the current git branch via
# the Vercel REST API (git-source deployment). Because Vercel builds it from the
# branch commit on GitHub, the Vercel GitHub App posts its native preview comment
# on the open PR -- exactly like the old auto-deploys, but only when you ask.
#
# Auto preview deploys are disabled in vercel.json (git.deploymentEnabled), so
# this manual API call is the supported way to get a one-off preview. Manual
# deployments are NOT gated by deploymentEnabled (same reason deploy hooks keep
# working when auto-deploy is off).
#
# Usage:  scripts/deploy_preview.sh [--prod]
#   (no args)  -> preview deployment of the current branch (default)
#   --prod     -> production deployment (rarely needed; main still auto-deploys)
#
# Requires: VERCEL_TOKEN (a Vercel access token with deploy scope).
#   Provide it via the environment, or a `VERCEL_TOKEN=...` line in repo .env.local.
#   Create one at https://vercel.com/account/tokens

set -euo pipefail

# --- Project constants (job-visualizer-notifier on team brendanpotter00s-projects) ---
TEAM_ID="team_k1U3D3dnN1fV5XnqAzCUg0MF"
PROJECT_ID="prj_7moC3xZ9H5vKmEkGb0ROXMARzmtT"
PROJECT_NAME="job-visualizer-notifier"
REPO_ID="1097855088"   # github.com/brendanpotter00/Job-Visualizer-Notifier

TARGET="preview"
if [ "${1:-}" = "--prod" ] || [ "${1:-}" = "--production" ]; then
  TARGET="production"
fi

ROOT="$(git rev-parse --show-toplevel)"

# --- Resolve the Vercel token: env var first, then repo .env.local ---
TOKEN="${VERCEL_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f "$ROOT/.env.local" ]; then
  TOKEN="$(grep -E '^[[:space:]]*(export[[:space:]]+)?VERCEL_TOKEN[[:space:]]*=' "$ROOT/.env.local" | head -1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^["'"'"']//' -e 's/["'"'"']$//' || true)"
fi
if [ -z "$TOKEN" ]; then
  cat >&2 <<'EOF'
ERROR: VERCEL_TOKEN is not set.

This skill triggers a *git-source* deployment so the real Vercel bot comment
appears on the PR, which requires a Vercel API token.

Fix it one of two ways:
  1. Create a token at https://vercel.com/account/tokens (scope: this team),
     then:  export VERCEL_TOKEN=xxxxxxxx
  2. Or add a line to repo .env.local:  VERCEL_TOKEN=xxxxxxxx
EOF
  exit 1
fi

# --- Branch + commit. The deploy builds from GitHub, so HEAD must be pushed. ---
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" = "HEAD" ]; then
  echo "ERROR: detached HEAD -- check out a branch first." >&2
  exit 1
fi

echo ">> Pushing $BRANCH to origin so Vercel builds your latest commit..."
if ! git push origin "HEAD:$BRANCH"; then
  echo "ERROR: 'git push origin HEAD:$BRANCH' failed. Resolve it (e.g. set upstream / non-fast-forward) and retry." >&2
  exit 1
fi
SHA="$(git rev-parse HEAD)"

echo ">> Requesting $TARGET deployment of $PROJECT_NAME @ $BRANCH ($(git rev-parse --short HEAD))..."

PAYLOAD="$(REPO_ID="$REPO_ID" PROJECT_ID="$PROJECT_ID" PROJECT_NAME="$PROJECT_NAME" BRANCH="$BRANCH" SHA="$SHA" TARGET="$TARGET" python3 - <<'PY'
import json, os
body = {
    "name": os.environ["PROJECT_NAME"],
    "project": os.environ["PROJECT_ID"],
    "gitSource": {
        "type": "github",
        "repoId": int(os.environ["REPO_ID"]),
        "ref": os.environ["BRANCH"],
        "sha": os.environ["SHA"],
    },
}
# Preview is the default target; only send target when deploying production.
if os.environ["TARGET"] == "production":
    body["target"] = "production"
print(json.dumps(body))
PY
)"

RESP="$(curl -sS -X POST \
  "https://api.vercel.com/v13/deployments?teamId=${TEAM_ID}&forceNew=1&skipAutoDetectionConfirmation=1" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")"

RESP_JSON="$RESP" RESP_TARGET="$TARGET" python3 - <<'PY'
import json, os, sys
raw = os.environ.get("RESP_JSON", "")
try:
    d = json.loads(raw)
except Exception:
    print("Unexpected non-JSON response from Vercel:\n" + raw, file=sys.stderr)
    sys.exit(1)

err = d.get("error")
if err:
    print(f"Vercel API error [{err.get('code')}]: {err.get('message')}", file=sys.stderr)
    sys.exit(1)

dpl_id = d.get("id", "?")
url = d.get("url")
inspector = d.get("inspectorUrl")
state = d.get("readyState") or d.get("status") or "QUEUED"

print("")
print("✅ Deployment created:")
print(f"   id        : {dpl_id}")
print(f"   target    : {os.environ.get('RESP_TARGET')}")
print(f"   state     : {state}")
if url:
    print(f"   preview   : https://{url}")
if inspector:
    print(f"   inspector : {inspector}")
print("")
print("Vercel is building now. Its GitHub App will post/update the preview")
print("comment on the open PR for this branch once the build is READY.")
PY
