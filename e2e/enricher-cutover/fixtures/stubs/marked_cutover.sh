#!/bin/sh
# WT-03/WT-04: a MARKED variant of cutover.sh that conftest commits to the fake
# JVN remote's main in place of the real one. When the watcher runs it, it
# proves which copy ran (its own path, pid and args) and, for WT-04, holds the
# watcher lock until $FAKE_MARKER_RELEASE exists (at most 30 s).
{
  echo "path=$0"
  echo "pid=$$"
  echo "args=$*"
} > "${FAKE_MARKER:?}"
if [ -n "${FAKE_MARKER_RELEASE:-}" ]; then
  END=$(( $(date +%s) + 30 ))
  while [ ! -e "$FAKE_MARKER_RELEASE" ] && [ "$(date +%s)" -lt "$END" ]; do
    sleep 0.1
  done
fi
exit 0
