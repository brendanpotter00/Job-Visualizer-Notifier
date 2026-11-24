#!/bin/sh
# Install (or re-arm) the enricher cutover's merge trigger, the launchd agent
# com.bp.jvn-enricher-cutover. It idles until JVN main contains the cutover,
# then runs the merged cutover once. See README.md next to this file.
#
#   install_watcher.sh             copy watcher.sh into the state dir, render + lint the plist, load it
#   install_watcher.sh --dry-run   print the plan and the rendered plist; writes nothing, runs no launchctl
#   install_watcher.sh --rearm     after a terminal FAILED / ROLLED_BACK: archive state.json, then install
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.bp.jvn-enricher-cutover"
STATE="${CUTOVER_STATE_DIR:-$HOME/Library/Application Support/jvn-enricher-cutover}"
LA_DIR="${CUTOVER_LAUNCHAGENTS_DIR:-$HOME/Library/LaunchAgents}"
PLIST="$LA_DIR/$LABEL.plist"
LAUNCHCTL="${LAUNCHCTL:-launchctl}"
PLUTIL="${CUTOVER_PLUTIL_BIN:-/usr/bin/plutil}"
NEW_PROD="${CUTOVER_NEW_PROD:-$HOME/developer/personal/enricher-prod}"
TEMPLATE="$HERE/$LABEL.plist.template"

DRY=0
REARM=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  --rearm) REARM=1 ;;
  "") ;;
  *) echo "usage: $0 [--dry-run|--rearm]" >&2; exit 2 ;;
esac

say() { echo "[install-watcher] $*"; }
do_or_say() {
  if [ "$DRY" = "1" ]; then say "would run: $*"; else "$@"; fi
}

# sed replacement safety: these characters would corrupt the render.
case "$STATE$HOME" in
  *'|'*|*'&'*|*'<'*|*'>'*|*'\'*) echo "refusing: \$HOME or the state dir contains | & < > or \\" >&2; exit 2 ;;
esac

render() {
  sed -e "s|__STATE_DIR__|$STATE|g" -e "s|__HOME__|$HOME|g" "$TEMPLATE"
}

# 1. A terminal state means the last cutover already finished one way or another.
if [ -f "$STATE/state.json" ] \
   && grep -Eq '^  "phase": "(DONE|FAILED|ROLLED_BACK)"' "$STATE/state.json"; then
  PHASE="$(sed -n 's/^  "phase": "\([A-Z_]*\)".*/\1/p' "$STATE/state.json" | head -1)"
  if [ "$PHASE" = "DONE" ]; then
    echo "refusing: the cutover is already DONE ($STATE/state.json). Nothing to arm." >&2
    exit 1
  fi
  if [ "$REARM" != "1" ]; then
    echo "refusing: the last cutover ended $PHASE. Read $STATE/state.json, fix the cause, then run: $0 --rearm" >&2
    exit 1
  fi
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  do_or_say mkdir -p "$STATE/archive"
  do_or_say mv "$STATE/state.json" "$STATE/archive/state-$STAMP.json"
fi

# 2. A leftover new prod the cutover did not make (or that a rollback kept for
#    diagnosis) would make the cutover refuse. A human decides what to do with it.
if [ -e "$NEW_PROD" ] && [ ! -f "$NEW_PROD/.cutover-owned" ]; then
  echo "refusing: $NEW_PROD exists and was not created by an unfinished cutover. Move it aside first." >&2
  exit 1
fi

# 3. Render + lint (stdin, so a dry run writes nothing).
if ! render | "$PLUTIL" -lint - >/dev/null; then
  echo "refusing: the rendered plist does not lint" >&2
  exit 1
fi
say "rendered plist lints OK"

if [ "$DRY" = "1" ]; then
  say "DRY RUN — nothing will be written and launchctl will not be called"
  say "would copy $HERE/watcher.sh -> $STATE/watcher.sh (mode 755)"
  say "would write $PLIST:"
  render
  say "would run: $LAUNCHCTL load $PLIST"
  exit 0
fi

# 4. Install.
mkdir -p "$STATE" "$HOME/Library/Logs" "$LA_DIR"
cp "$HERE/watcher.sh" "$STATE/watcher.sh.tmp-$$"
chmod 755 "$STATE/watcher.sh.tmp-$$"
mv -f "$STATE/watcher.sh.tmp-$$" "$STATE/watcher.sh"
say "copied watcher.sh -> $STATE/watcher.sh"

if "$LAUNCHCTL" list | awk '{print $3}' | grep -qx "$LABEL"; then
  say "unloading the previously installed watcher"
  "$LAUNCHCTL" unload "$PLIST" 2>/dev/null || "$LAUNCHCTL" remove "$LABEL" 2>/dev/null || true
fi
TMP_PLIST="$LA_DIR/.$LABEL.plist.tmp-$$"
render > "$TMP_PLIST"
"$PLUTIL" -lint "$TMP_PLIST" >/dev/null
chmod 644 "$TMP_PLIST"
mv -f "$TMP_PLIST" "$PLIST"
say "wrote $PLIST"

"$LAUNCHCTL" load "$PLIST"
if "$LAUNCHCTL" list | awk '{print $3}' | grep -qx "$LABEL"; then
  say "loaded $LABEL (fires at load, then every 300 s)"
else
  echo "[install-watcher] WARNING: $LABEL does not show in launchctl list" >&2
  exit 1
fi

cat <<EOF
[install-watcher] Next:
  tail -f "$HOME/Library/Logs/jvn-enricher-cutover.log"   # "not merged yet" until the PR merges
  sh "$HERE/cutover.sh" --status                           # the cutover's state once it starts
  The watcher removes itself once the cutover ends (DONE, FAILED or ROLLED_BACK).
EOF
