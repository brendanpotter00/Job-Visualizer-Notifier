#!/bin/sh
# One-time setup of the Launch Radar PR step's logo venv (saved-pr/PLAN.md D12).
# Run it BY HAND on the server, once, and again after the logo requirements change:
#
#   brew install cairo
#   sh scripts/launch_radar/logo_setup.sh
#
# It creates $STATE_DIR/logo-venv and installs Pillow + cairosvg into it. The nightly
# run never installs packages: pr_step.py only runs the venv's python (with -I), and
# radar.sh pr-next's preflight refuses to claim a card when the venv cannot import
# PIL and cairosvg. Not in the headless allowlist.
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE_DIR="${LAUNCH_RADAR_STATE_DIR:-$HOME/Library/Application Support/jvn-launch-radar}"
VENV="$STATE_DIR/logo-venv"
REQUIREMENTS="$ROOT/.claude/skills/fetch-company-logo/scripts/requirements.txt"
PYTHON="${PYTHON:-python3}"

command -v brew >/dev/null 2>&1 || {
  echo "logo_setup.sh: Homebrew not found; install it, then: brew install cairo" >&2
  exit 1
}
CAIRO_PREFIX="$(brew --prefix cairo 2>/dev/null || true)"
if [ -z "$CAIRO_PREFIX" ] || [ ! -d "$CAIRO_PREFIX/lib" ]; then
  echo "logo_setup.sh: cairo is not installed (cairosvg needs libcairo): brew install cairo" >&2
  exit 1
fi
[ -f "$REQUIREMENTS" ] || { echo "logo_setup.sh: missing $REQUIREMENTS" >&2; exit 1; }

mkdir -p "$STATE_DIR"
if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r "$REQUIREMENTS"
"$VENV/bin/python" -I -c "import PIL, cairosvg" || {
  echo "logo_setup.sh: the venv cannot import PIL and cairosvg (is libcairo on the loader path?)" >&2
  exit 1
}
echo "logo venv ready: $VENV"
