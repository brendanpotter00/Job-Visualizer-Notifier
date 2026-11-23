#!/bin/sh
# Send one north-star loop text to Brendan AND record it in his Boop
# conversation history, so a reply like "yes 3" reaches Boop with context.
#
#   sh scripts/north_star_loop/notify.sh "<message>"
#
# Exit: 0 sent + recorded · 2 send script missing · 3 send failed
#       4 sent, Boop history not configured · 5 sent, Boop history write failed
#
# Config (server only, not in git): $STATE_DIR/notify.env, sourced if present:
#   BOOP_DIR=/path/to/boop-agent              # checkout with Convex configured
#   BOOP_CONVERSATION_ID=sms:+1XXXXXXXXXX     # Brendan's Boop conversation id
#   SEND_WRITES_BOOP_HISTORY=1                # set if send.sh already records it
# Boop stores history through its Convex `messages:send` mutation, the same
# call its own automations use for outbound texts (role "assistant").
set -u

MSG="${1:?usage: notify.sh <message>}"
STATE_DIR="${JVN_LOOP_STATE_DIR:-$HOME/Library/Application Support/jvn-north-star-loop}"
[ -f "$STATE_DIR/notify.env" ] && . "$STATE_DIR/notify.env"
SEND="${JVN_LOOP_SEND:-/Users/bpotter/.claude/skills/message-brendan/send.sh}"
PROJECT_DIR="${JVN_LOOP_PROJECT_DIR:-/Users/bpotter/developer/personal/Job-Visualizer-Notifier}"

if [ "${JVN_LOOP_DRY_RUN:-0}" = "1" ]; then
  echo "[DRY-RUN TEXT] $MSG"
  exit 0
fi

[ -f "$SEND" ] || { echo "notify: send script missing: $SEND" >&2; exit 2; }
bash "$SEND" "$MSG" || { echo "notify: send failed" >&2; exit 3; }

[ "${SEND_WRITES_BOOP_HISTORY:-0}" = "1" ] && exit 0
if [ -z "${BOOP_DIR:-}" ] || [ -z "${BOOP_CONVERSATION_ID:-}" ]; then
  echo "notify: sent, but BOOP_DIR / BOOP_CONVERSATION_ID are not set in $STATE_DIR/notify.env; Boop has no record of this text" >&2
  exit 4
fi

CONTENT=$(printf '[north-star loop]\n\n%s\n\n(For Boop: this came from the north-star loop. If Brendan replies "yes N" or "no N <reason>", run `python3 scripts/north_star_loop/loop.py decide N yes` (or `decide N no <reason words>`) from %s and reply with its output. `loop.py show N` gives the full brief.)' "$MSG" "$PROJECT_DIR")
ARGS=$(python3 -c 'import json, sys; print(json.dumps({"conversationId": sys.argv[1], "role": "assistant", "content": sys.argv[2]}))' "$BOOP_CONVERSATION_ID" "$CONTENT")
if ! (cd "$BOOP_DIR" && npx --yes convex run messages:send "$ARGS") >/dev/null; then
  echo "notify: sent, but writing Boop history failed (cd $BOOP_DIR && npx convex run messages:send)" >&2
  exit 5
fi
exit 0
