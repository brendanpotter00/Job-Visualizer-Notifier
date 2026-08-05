#!/usr/bin/env bash
# Run one replay round across every recipe and print the drift vs round 1.
#
# The spike's central claim is that a recipe keeps working with no agent in
# the loop, so it has to be measured over real elapsed time, not once.
#
#   ./replay_round.sh replay-1     # right after discovery
#   ./replay_round.sh replay-2     # ~24h later
#   ./replay_round.sh replay-3     # ~48h later
#   ./drift.py                     # summarise all rounds
set -euo pipefail

LABEL="${1:-replay-manual}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$HERE/.venv/bin/python" "$HERE/replay.py" --all --label "$LABEL"
echo
"$HERE/.venv/bin/python" "$HERE/drift.py" || true
