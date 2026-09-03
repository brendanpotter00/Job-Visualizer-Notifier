#!/usr/bin/env bash
# Kill by pidfile; never kills anything it did not start (PLAN.md §2).
# Safe to call even if the stack never came up (no pidfiles / stale pidfiles).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"

_kill_pidfile() {
  local name="$1"
  local pidfile="$PID_DIR/$name.pid"
  if [ ! -f "$pidfile" ]; then
    return 0
  fi
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "stack_down.sh: stopping $name (pid $pid)"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
  else
    echo "stack_down.sh: $name pidfile present but process not running"
  fi
  rm -f "$pidfile"
}

_kill_pidfile frontend
_kill_pidfile backend

echo "stack_down.sh: done"
