#!/bin/sh
# Stub message-brendan/send.sh for the enricher-cutover e2e section: appends the
# message to $FAKE_SEND_LOG (one line each) and exits $FAKE_SEND_EXIT (default 0).
# It never sends a text.
printf '%s\n' "$*" >> "${FAKE_SEND_LOG:?FAKE_SEND_LOG is not set}"
if [ "${FAKE_SEND_EXIT:-0}" != "0" ]; then
  echo "stub send.sh: failing on purpose (FAKE_SEND_EXIT=${FAKE_SEND_EXIT})" >&2
fi
exit "${FAKE_SEND_EXIT:-0}"
