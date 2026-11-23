#!/bin/sh
# Entry point for the enricher cutover (see README.md next to this file).
#
# Runs cutover.py under the OLD prod's own base interpreter (the `home` line of
# <old prod>/.venv/pyvenv.cfg + /python3), falling back to `uv python find 3.12`,
# always with -I (isolated: no user site, no PYTHON* env, no script dir on sys.path).
#
#   cutover.sh --preflight [--jvn-repo PATH] [--json]   read-only report
#   cutover.sh --rehearse --scratch DIR [--jvn-repo PATH]
#   cutover.sh --run                                     the resumable cutover (the watcher calls this)
#   cutover.sh --status                                  print the state file
#
# Exit: 0 done/no-op, 10 deferred, 20 failed before any swap, 30 rolled back, 2 usage.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
OLD_PROD="${CUTOVER_OLD_PROD:-$HOME/developer/personal/app}"
UV="${UV_BIN:-/opt/homebrew/bin/uv}"

PY="${CUTOVER_PYTHON:-}"
if [ -z "$PY" ] && [ -f "$OLD_PROD/.venv/pyvenv.cfg" ]; then
  VENV_HOME="$(sed -n 's/^home[[:space:]]*=[[:space:]]*//p' "$OLD_PROD/.venv/pyvenv.cfg" | head -1)"
  if [ -n "$VENV_HOME" ] && [ -x "$VENV_HOME/python3" ]; then
    PY="$VENV_HOME/python3"
  fi
fi
if [ -z "$PY" ] && [ -x "$UV" ]; then
  PY="$("$UV" python find 3.12 2>/dev/null || true)"
fi
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "[cutover] no Python 3.12 interpreter: none in $OLD_PROD/.venv/pyvenv.cfg and \`uv python find 3.12\` found none" >&2
  exit 20
fi

exec "$PY" -I "$HERE/cutover.py" "$@"
