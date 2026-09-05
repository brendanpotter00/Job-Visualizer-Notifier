#!/usr/bin/env bash
# verify-onesecondswe :: Company name search
#
# "Type a company name into the add box, get that company's job board." This is the
# folded entry point for that feature inside this skill.
#
# THE COST MODEL IS THE POINT OF THIS SCRIPT. The intent suite spends REAL MONEY —
# ~$0.007 per Browserbase Search call, ~38-39 calls for a full pass, ~$0.27 a run. This
# skill is otherwise local-only and $0. So the default here is free and the paid run is
# behind an explicit flag, and every mode prints its own price before it does anything.
#
#   name_search.sh              $0  cases.toml validity + the dead-endpoint judge pins +
#                                   re-judge a RECORDED green run + the @name-search drive
#   name_search.sh --prove-it   $0  proves the judge still FAILS a dead endpoint
#   name_search.sh --live      ~$0.27, REAL MONEY — delegates to e2e/run.sh
#
# The default mode judges STORED response bodies with the same `judge()` a live run uses,
# so truth provenance, the job-list shape rule (recorded truth AND returned answers), the
# vacuous rule and `known_limitation` are all enforced for nothing. It does not re-state
# any of those rules; re-stating them is how they drift.
#
# Usage: name_search.sh [--prove-it | --live [extra args passed to e2e/run.sh]]

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"

PY="$REPO_ROOT/.venv/bin/python"
SECTION="$REPO_ROOT/e2e/company-name-search"
RECORDING="$SECTION/recorded/20260905T021303Z.json"

MODE=default
if [ $# -gt 0 ]; then
  case "$1" in
    --prove-it) MODE=prove; shift ;;
    --live) MODE=live; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "name_search.sh: unknown arg $1 (expected --prove-it or --live)" >&2; exit 2 ;;
  esac
fi

# --- Node pin (22.1.0 hangs Playwright silently) ---------------------------
if [[ "$(node -v 2>/dev/null)" != v22.1[24].* ]]; then
  NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
  [ -d "$NVM_NODE" ] && export PATH="$NVM_NODE:$PATH"
fi

if [ ! -x "$PY" ]; then
  echo "name_search.sh: no venv python at $PY — create the backend venv first" >&2
  exit 1
fi

# ── the paid rung ──────────────────────────────────────────────────────────
if [ "$MODE" = "live" ]; then
  echo "=============================================================================="
  echo "name_search.sh --live : COST ~\$0.27 OF REAL MONEY (~38-39 Browserbase Search"
  echo "                        calls at \$0.007 each). This is the ONLY entry point in"
  echo "                        this skill that spends anything."
  echo "=============================================================================="
  echo "name_search.sh: delegating to e2e/run.sh company-name-search (it owns the :8202"
  echo "                stack, the real key, and the --max-searches ceiling)"
  exec bash "$REPO_ROOT/e2e/run.sh" company-name-search "$@"
fi

if [ ! -f "$RECORDING" ]; then
  echo "name_search.sh: no recording at $RECORDING" >&2
  echo "name_search.sh: the \$0 modes replay a stored paid run — see $SECTION/recorded/README.md" >&2
  exit 1
fi

# ── the fail-first rung ────────────────────────────────────────────────────
# A suite that cannot fail is not evidence. This re-judges the SAME cases against a DEAD
# endpoint and requires the run to go red. It is the harness-level twin of
# LIVE_VIEW_SEED_CLIPPED=1, and like it, it edits no source: the mutated copy is written
# to a scratch dir outside the repo.
if [ "$MODE" = "prove" ]; then
  echo "=============================================================================="
  echo "name_search.sh --prove-it : COST \$0. Re-judges every case against a DEAD"
  echo "                            endpoint ({\"candidates\": [], \"careersUrl\": null})."
  echo "                            The replay MUST go red. A green one means the"
  echo "                            assertions have stopped asserting."
  echo "=============================================================================="
  DEAD="${TMPDIR:-/tmp}/jvn-name-search-dead-$$.json"
  "$PY" - "$RECORDING" "$DEAD" <<'PYEOF'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
record = json.loads(open(src, encoding="utf-8").read())
for case in record.get("cases", []):
    for attempt in case.get("attempts", []):
        if attempt.get("body") is not None:
            # Exactly the shape the endpoint returns when it is completely dead — the
            # answer that used to make metabase/poke/gm/hp report PASS.
            attempt["body"] = {"candidates": [], "careersUrl": None, "alreadyPublic": None,
                               "careersSearch": None, "query": case.get("input", ""),
                               "trace": []}
open(dst, "w", encoding="utf-8").write(json.dumps(record))
print(f"wrote dead-endpoint copy -> {dst}")
PYEOF
  if [ ! -f "$DEAD" ]; then
    echo "name_search.sh: could not build the dead-endpoint copy" >&2
    exit 1
  fi
  "$PY" "$SECTION/intent_test.py" --replay "$DEAD"
  RC=$?
  rm -f "$DEAD"
  if [ "$RC" = "0" ]; then
    echo >&2
    echo "name_search.sh: FAIL-FIRST BROKEN — a DEAD endpoint just passed this suite." >&2
    echo "name_search.sh: that is the exact false green this harness exists to prevent" >&2
    echo "                (see the 'vacuous' rule in cases.toml). Do not trust a green" >&2
    echo "                run until this goes red again." >&2
    exit 1
  fi
  echo
  echo "name_search.sh: PROVEN — the dead endpoint was rejected (replay exited $RC)."
  echo "name_search.sh: cost \$0.00, 0 searches."
  exit 0
fi

# ── the default, free rung ─────────────────────────────────────────────────
echo "=============================================================================="
echo "name_search.sh : COST \$0.00. No Browserbase call is made. The answers are"
echo "                 replayed from a recorded paid run and re-judged by the SAME"
echo "                 judge() a live run uses."
echo "                 Paid coverage lives behind: name_search.sh --live (~\$0.27)"
echo "=============================================================================="
FAILED=""

echo
echo "name_search.sh: === 1/4 cases.toml is valid (job-list shape on recorded truth) ==="
"$PY" "$SECTION/intent_test.py" --validate-only || FAILED="$FAILED validate"

echo
echo "name_search.sh: === 2/4 the judge still fails a dead endpoint (test_judge.py) ==="
# Standalone by design: no backend, no DB, no key. This is the one Python check in this
# feature that genuinely runs locally — the backend's own pytest suite does not (stale
# alembic stamp), and CI is the gate for that.
"$PY" -m pytest "$SECTION/test_judge.py" -q || FAILED="$FAILED test_judge"

echo
echo "name_search.sh: === 3/4 re-judge the recorded run (\$0, same judge) ==="
"$PY" "$SECTION/intent_test.py" --replay "$RECORDING" || FAILED="$FAILED replay"

echo
echo "name_search.sh: === 4/4 the browser sends the name verbatim (@name-search) ==="
if ! curl -fsS "http://127.0.0.1:3201/" >/dev/null 2>&1; then
  echo "name_search.sh: SKIPPED — no frontend on :3201. Run helpers/launch.sh first," \
       "then re-run; the drive needs the real page." >&2
  FAILED="$FAILED drive-not-run"
else
  (
    cd "$REPO_ROOT/e2e"
    NODE_PATH="$REPO_ROOT/e2e/node_modules" npx --no-install playwright test \
      --config="$SKILL_DIR/helpers/verify.playwright.config.ts" \
      --grep '@name-search'
  ) || FAILED="$FAILED drive"
fi

echo
if [ -n "$FAILED" ]; then
  echo "name_search.sh: FAILED —$FAILED"
  echo "name_search.sh: cost \$0.00, 0 searches."
  exit 1
fi
echo "name_search.sh: PASSED — validity, dead-endpoint pins, recorded re-judge, verbatim drive."
echo "name_search.sh: cost \$0.00, 0 searches. For live coverage: name_search.sh --live (~\$0.27)."
