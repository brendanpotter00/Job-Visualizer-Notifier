#!/bin/sh
# Install the StartInterval enrichment worker as a launchd agent.
set -eu
PLIST="$HOME/Library/LaunchAgents/com.bp.job-enricher.plist"
# Anchor to the checkout this script is run FROM (its parent dir), so the generated plist
# points the launchd worker at whichever checkout you install from — run it from the prod
# checkout (~/developer/personal/enricher-prod/src/enricher). See docs/ENVIRONMENTS.md.
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
# 60s = "continuous worker": the local (ollama) engine has no fan-out, so a batch
# tick runs for many minutes. The single-flight O_EXCL lock makes every fire during
# a running tick a cheap exit-75 no-op, so a short interval just means the next
# batch starts within ~60s of the previous finishing — effectively always-working,
# with zero changes to the lock/tick lifecycle. Override with ENRICH_INTERVAL_SECS
# (e.g. 600 for the old Claude 10-min cadence). See the handoff doc.
INTERVAL="${ENRICH_INTERVAL_SECS:-60}"

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
