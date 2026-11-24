#!/bin/sh
# CO-REAL's faked first tick (FAKE_JOB_OVERRIDE). The stub launchctl runs this
# instead of the REAL wrapper, which hardcodes /opt/homebrew/bin/uv and would
# call JVN and ollama. Only the NEW prod ticks (the old one idles), and the tick
# goes through the REAL CLI's lifecycle at the prod tag — tick-acquire (exit 75
# while held), the wrapper's lock hand-over, tick-end — with no pull, no model.
NEW="$(cd "${FAKE_NEW_ENRICHER:?}" 2>/dev/null && pwd -P)"
[ "$(pwd -P)" = "$NEW" ] || exit 0

OUT=$(uv run python -m job_enricher.cli tick-acquire 2>&1)
RC=$?
printf '%s\n' "$OUT"
[ "$RC" -eq 75 ] && exit 0
[ "$RC" -eq 0 ] || exit "$RC"
TICK_ID=$(printf '%s\n' "$OUT" | sed -n 's/.*tick_id=\([0-9][0-9]*\).*/\1/p' | head -1)
printf '%s|%s' "$$" "$(date -u +%FT%TZ)" > data/.tick.lock
ENRICH_LOCK_OWNER_PID=$$ ENRICH_TICK_ID="$TICK_ID" \
  uv run python -m job_enricher.cli tick-end --tick-id "$TICK_ID" --status ok
