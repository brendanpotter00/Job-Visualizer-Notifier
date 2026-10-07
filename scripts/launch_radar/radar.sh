#!/bin/sh
# Launch Radar launcher: the ONLY entry point the skill (and its --allowedTools
# allowlist) may run. It loads the secrets into THIS process tree only, so the
# Claude session that calls it never has PARALLEL_API_KEY or INTERNAL_API_KEY
# in its own environment, and never needs to read the env file.
#
#   scripts/launch_radar/radar.sh run --max-companies 3 --budget 1.00
#
# Env file (mode 600, KEY=value lines): BACKEND_URL, INTERNAL_API_KEY,
# PARALLEL_API_KEY, optional LAUNCH_RADAR_STATE_DIR.
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

ENV_FILE="${LAUNCH_RADAR_ENV_FILE:-$HOME/.config/jvn-launch-radar/env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

# uv comes from PATH (the LaunchAgent plist lists /opt/homebrew/bin and /usr/local/bin),
# so Apple Silicon and Intel Homebrew, and a non-Homebrew install, all work.
UV="$(command -v uv)" || { echo "radar.sh: uv not found on PATH" >&2; exit 1; }
exec "$UV" run --no-project --python '>=3.11' \
  --with 'parallel-web>=1.3.5' --with 'httpx>=0.27' \
  python -m scripts.launch_radar.radar "$@"
