#!/bin/sh
# Install (or reinstall) the scraper-health-watch LaunchAgent (fires every 3h).
# Idempotent: safe to re-run after editing the plist template or wrapper.
set -eu

TEMPLATE="$(cd "$(dirname "$0")" && pwd)/com.bp.jvn-health-watch.plist.template"
DEST="$HOME/Library/LaunchAgents/com.bp.jvn-health-watch.plist"
LABEL="com.bp.jvn-health-watch"
UID_N="$(id -u)"

[ -f "$TEMPLATE" ] || { echo "template not found: $TEMPLATE" >&2; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents"
cp "$TEMPLATE" "$DEST"
plutil -lint "$DEST"

# bootout is a no-op error if not currently loaded — ignore.
launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_N" "$DEST"

echo "installed: $DEST"
echo "next fire (see 'events' below — StartCalendarInterval, every 3h):"
launchctl print "gui/$UID_N/$LABEL" | grep -A 6 "events = " || true
echo
echo "manual fire now:   launchctl kickstart gui/$UID_N/$LABEL"
echo "pause (uninstall): launchctl bootout gui/$UID_N/$LABEL"
echo "logs:              tail -f ~/Library/Logs/jvn-health-watch.log"
