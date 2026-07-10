#!/bin/sh
# Install the StartInterval enrichment worker as a launchd agent.
set -eu
PLIST="$HOME/Library/LaunchAgents/com.bp.job-enricher.plist"
PROJECT="/Users/bpotter/developer/personal/job-enricher"
INTERVAL="${ENRICH_INTERVAL_SECS:-600}"

cat > "$PLIST" <<PLEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bp.job-enricher</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT/scripts/enrich_tick_wrapper.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT</string>
    <key>StartInterval</key>
    <integer>$INTERVAL</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/job-enricher.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/job-enricher.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "installed + loaded $PLIST (StartInterval=$INTERVAL)"
