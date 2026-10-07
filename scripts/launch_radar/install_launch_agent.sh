#!/bin/sh
# Install (or reinstall) the Launch Radar LaunchAgent (daily at 07:00).
# Run from the checkout launchd should use (its path becomes PROJECT_DIR):
#
#   sh scripts/launch_radar/install_launch_agent.sh [--claude-bin /path/to/claude]
#   sh scripts/launch_radar/install_launch_agent.sh --uninstall
#
# Idempotent: safe to re-run after editing the template or the wrapper.
set -eu

LABEL="com.bp.jvn-launch-radar"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_N="$(id -u)"
TEMPLATE="$(cd "$(dirname "$0")" && pwd)/$LABEL.plist.template"
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CLAUDE_BIN=""
UNINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --claude-bin) CLAUDE_BIN="${2:?--claude-bin needs a path}"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ "$UNINSTALL" -eq 1 ]; then
  launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
  rm -f "$DEST"
  echo "uninstalled: $LABEL"
  exit 0
fi

[ -f "$TEMPLATE" ] || { echo "template not found: $TEMPLATE" >&2; exit 1; }
[ -n "$CLAUDE_BIN" ] || CLAUDE_BIN="$(command -v claude || true)"
[ -n "$CLAUDE_BIN" ] && [ -x "$CLAUDE_BIN" ] || { echo "claude not found; pass --claude-bin" >&2; exit 1; }
case "$PROJECT_DIR$CLAUDE_BIN$HOME" in
  *'|'*) echo "paths must not contain '|'" >&2; exit 1 ;;
esac
# radar.sh resolves uv from the plist's PATH; warn now rather than at 07:00.
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" command -v uv >/dev/null 2>&1 || \
  echo "warning: uv not found in /opt/homebrew/bin or /usr/local/bin; radar.sh will exit 1 until it is installed" >&2
[ -f "$HOME/.config/jvn-launch-radar/env" ] || \
  echo "warning: $HOME/.config/jvn-launch-radar/env is missing; radar.sh will exit 1 until it exists" >&2

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__CLAUDE_BIN__|$CLAUDE_BIN|g" \
    -e "s|__HOME__|$HOME|g" "$TEMPLATE" > "$DEST"
plutil -lint "$DEST"

# bootout is a no-op error if not currently loaded: ignore it.
launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_N" "$DEST"

echo "installed: $DEST"
echo "  PROJECT_DIR=$PROJECT_DIR"
echo "  CLAUDE_BIN=$CLAUDE_BIN"
launchctl print "gui/$UID_N/$LABEL" | grep -A 6 "events = " || true
echo
echo "manual fire now:   launchctl kickstart gui/$UID_N/$LABEL"
echo "uninstall:         sh scripts/launch_radar/install_launch_agent.sh --uninstall"
echo "logs:              tail -f ~/Library/Logs/jvn-launch-radar.log"
