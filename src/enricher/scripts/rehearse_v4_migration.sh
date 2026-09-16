#!/usr/bin/env bash
# P0-7 — rehearse the SQLite v3->v4 migration on a CONSISTENT copy of the prod DB.
#
# ⚠ THIS IS THE ONE REHEARSAL STEP, and ENR-ST-1's migration may not reach
# /Users/bpotter/developer/personal/app until it has recorded
# MIGRATION_V3_V4_SECONDS.
#
# ⚠ COPY WITH `sqlite3 ".backup"`, NEVER `cp`: the prod DB is WAL-mode, so a plain
# file copy silently drops the -wal sibling and is racy against a running tick —
# the copy you rehearse on would not be the database you have.
#
# ⚠ v3->v4 IS A ONE-WAY DOOR. `init_schema` has no downgrade and `user_version`
# only moves forward, so THE .backup COPY IS THE ROLLBACK ARTIFACT. Its path is
# printed below; record it (and the ticks lost by restoring it) in
# docs/RUNBOOK-subcategory-backfill.md.
#
# Usage:
#   scripts/rehearse_v4_migration.sh [/path/to/live/enricher.db] [/path/to/copy.db]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LIVE="${1:-/Users/bpotter/developer/personal/app/data/enricher.db}"
COPY="${2:-/tmp/enricher-v4-rehearsal-$(date +%Y%m%d-%H%M%S).db}"

if [[ ! -f "$LIVE" ]]; then
  echo "rehearse: no such DB $LIVE" >&2
  exit 2
fi

echo "rehearse: .backup $LIVE -> $COPY   (NOT cp — the DB is WAL-mode)"
sqlite3 "$LIVE" ".backup '$COPY'"
echo "rehearse: ROLLBACK ARTIFACT = $COPY   <-- record this path in the runbook"

BEFORE_INBOX=$(sqlite3 "$COPY" "SELECT COUNT(*) FROM inbox")
BEFORE_ENR=$(sqlite3 "$COPY" "SELECT COUNT(*) FROM enrichments")
BEFORE_TICKS=$(sqlite3 "$COPY" "SELECT COUNT(*) FROM ticks")
BEFORE_VERSION=$(sqlite3 "$COPY" "PRAGMA user_version")
echo "rehearse: before  user_version=$BEFORE_VERSION inbox=$BEFORE_INBOX enrichments=$BEFORE_ENR ticks=$BEFORE_TICKS"

# time.time(), not time.monotonic(): monotonic's epoch is not guaranteed to be
# comparable across two separate python processes.
START=$(python3 -c 'import time; print(time.time())')
uv run python -c "
from job_enricher.store import Store
Store(db_path='$COPY').init_schema()
"
END=$(python3 -c 'import time; print(time.time())')
SECONDS_TAKEN=$(python3 -c "print(round($END - $START, 2))")

echo
echo "MIGRATION_V3_V4_SECONDS = $SECONDS_TAKEN"

uv run python - "$COPY" "$BEFORE_INBOX" "$BEFORE_ENR" "$BEFORE_TICKS" <<'PY'
import sqlite3
import sys

path, before_inbox, before_enr, before_ticks = sys.argv[1:5]
conn = sqlite3.connect(path)
conn.row_factory = sqlite3.Row
fail = []

def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label} {detail}")
    if not ok:
        fail.append(label)

version = conn.execute("PRAGMA user_version").fetchone()[0]
check("user_version == 4", version == 4, f"(got {version})")

enr_cols = {r["name"] for r in conn.execute("PRAGMA table_info(enrichments)")}
for name in ("subcategories", "subcategory_confidence", "subcategory_source",
             "subcategory_attempts", "pre_judge_subcategories",
             "subcategory_run_id", "subcategory_sent_at"):
    check(f"enrichments.{name}", name in enr_cols)

tick_cols = {r["name"] for r in conn.execute("PRAGMA table_info(ticks)")}
for name in ("swe_classified", "swe_subcat_evaluated", "swe_subcategorized"):
    check(f"ticks.{name}", name in tick_cols)

tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check("table backfill_runs", "backfill_runs" in tables)
check("table backfill_scope", "backfill_scope" in tables)
check("backfill_roster absent", "backfill_roster" not in tables)

for label, before in (("inbox", before_inbox), ("enrichments", before_enr), ("ticks", before_ticks)):
    now = conn.execute(f"SELECT COUNT(*) FROM {label}").fetchone()[0]
    check(f"{label} row count unchanged", now == int(before), f"({before} -> {now})")

integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
check("integrity_check == ok", integrity == "ok", f"(got {integrity!r})")

not_null = conn.execute(
    "SELECT COUNT(*) FROM enrichments WHERE subcategories IS NOT NULL"
).fetchone()[0]
check(
    "every pre-existing enrichment at subcategories IS NULL",
    not_null == 0,
    f"({not_null} rows are non-NULL)",
)
conn.close()

if fail:
    print(f"\nrehearse: {len(fail)} CHECK(S) FAILED — do NOT deploy")
    raise SystemExit(1)
print("\nrehearse: all checks passed")
PY

echo
echo "rehearse: re-running init_schema (idempotence)"
uv run python -c "
from job_enricher.store import Store
Store(db_path='$COPY').init_schema()
import sqlite3
print('  user_version after re-run:', sqlite3.connect('$COPY').execute('PRAGMA user_version').fetchone()[0])
"

echo
echo "⚠ DECISION RULE: MIGRATION_V3_V4_SECONDS = $SECONDS_TAKEN"
python3 - "$SECONDS_TAKEN" <<'PY'
import sys
secs = float(sys.argv[1])
if secs > 30:
    print(f"   {secs}s > 30s -> SPLIT THE MIGRATION. deploy.sh runs it at step 6 "
          f"with the worker parked.")
else:
    print(f"   {secs}s <= 30s -> inline in deploy.sh step 6 is acceptable.")
print("   Record this number, integrity_check=ok, the row counts and the "
      ".backup path in docs/RUNBOOK-subcategory-backfill.md.")
PY
