#!/usr/bin/env python3
"""P0-1 / P0-2 — READ-ONLY diagnostic harness against a live enricher SQLite DB.

Run from the DEV worktree with `--db` pointing at the prod DB:

    uv run python scripts/diagnose_stuck_cohort.py \\
        --db /Users/bpotter/developer/personal/enricher-prod/src/enricher/data/enricher.db

CONNECTION RECIPE, and why it is not the obvious one:

* Plain ``sqlite3.connect(path)`` then ``PRAGMA query_only = ON``, ABORTING if a
  follow-up read of the pragma does not return 1. Read-only is enforced by the
  connection, not by hoping.
* NOT a ``file:...?mode=ro`` URI: a WAL database must attach its ``-shm``/``-wal``
  siblings, and a read-only URI raises ``SQLITE_CANTOPEN`` (err 14) trying to.
* NOT ``immutable=1`` either: that returns a stale main-file image, i.e. silently
  wrong numbers rather than an error.
* It MUST NOT construct ``Store()``. ``Store.init_schema()`` **WRITES** (the
  journal-mode pragma at store.py:219 and the ``PRAGMA user_version`` stamp at
  :232), so merely opening the prod DB through the normal class would mutate it.

Nothing here writes. Every statement is a SELECT.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# The classify lane's per-tick cap lives in enrich_config as `enrich:per_tick_limit`
# (enrich_config.py:93). Recent ticks record classified=38 against a limit of 40,
# which is the fingerprint of H1 below.
DEFAULT_PER_TICK_LIMIT = 40

# P0-2 decision rule: if NULL-recency rows exceed this share of the cleaned
# cohort, RECORD the count and both candidate remedies in the runbook and STOP.
# Both remedies change the live tick's claim order, and r11 declined that.
NULL_RECENCY_ESCALATION_RATIO = 0.10


def open_read_only(path: Path) -> sqlite3.Connection:
    """Open `path` and PROVE the connection is read-only, or abort."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    got = conn.execute("PRAGMA query_only").fetchone()[0]
    if int(got) != 1:
        conn.close()
        raise RuntimeError(
            f"refusing to continue: PRAGMA query_only read back {got!r}, not 1 — "
            f"this connection is NOT provably read-only"
        )
    return conn


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def collect_report(conn: sqlite3.Connection, per_tick_limit: int) -> dict:
    """Every section of the diagnosis, as one JSON-able dict."""
    report: dict = {}

    report["schema_version"] = _scalar(conn, "PRAGMA user_version")

    report["inbox_by_status"] = {
        r["status"]: r["n"]
        for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM inbox GROUP BY status ORDER BY status"
        )
    }

    cleaned = _scalar(conn, "SELECT COUNT(*) FROM inbox WHERE status='cleaned'")
    # H2 ORDER STARVATION (store.py:354-366, ORDER BY at :360): rows with a NULL
    # first_seen_at sort LAST forever, so a NULL-recency row at the back of a
    # queue longer than the per-tick limit is never reached.
    starved = _scalar(
        conn,
        "SELECT COUNT(*) FROM inbox WHERE status='cleaned' AND first_seen_at IS NULL",
    )
    report["cleaned_total"] = cleaned
    report["starved_null_recency"] = starved
    report["starved_null_recency_ratio"] = round(starved / cleaned, 4) if cleaned else 0.0
    # REPORTED, DELIBERATELY NOT REPAIRED. Overwriting first_seen_at with a local
    # claim timestamp would permanently corrupt a provenance column (documented at
    # store.py:68-71 as "the job's posting-recency signal from JVN") to fix a sort
    # symptom, AND it would change the live tick's claim order — which r11
    # declined. See P0-3 and the runbook.
    report["starved_null_recency_action"] = "REPORT ONLY — see the runbook, needs an explicit yes"

    report["enrichments_total"] = _scalar(conn, "SELECT COUNT(*) FROM enrichments")
    report["enrichments_by_category"] = {
        (r["category"] or "<null>"): r["n"]
        for r in conn.execute(
            "SELECT category, COUNT(*) AS n FROM enrichments GROUP BY category "
            "ORDER BY n DESC"
        )
    }

    # H1 ENGINE-TIMEOUT ABANDONMENT (cli.py:707-711): `except EngineError: continue`
    # skips the chunk — `errors` is never bumped, `inbox.attempts` is never touched,
    # and the tick still closes status=ok/errors=0. The fingerprint is a tick whose
    # `classified` sits just BELOW the per-tick limit with errors=0.
    ticks = [
        dict(r)
        for r in conn.execute(
            "SELECT id, started_at, ended_at, status, claimed, cleaned, classified, "
            "judged, errors FROM ticks ORDER BY id DESC LIMIT 20"
        )
    ]
    report["recent_ticks"] = ticks
    silent = [
        t for t in ticks
        if t["errors"] == 0 and 0 < t["classified"] < per_tick_limit
    ]
    report["h1_silent_abandonment_ticks"] = len(silent)
    report["h1_rows_lost_estimate"] = sum(per_tick_limit - t["classified"] for t in silent)
    report["per_tick_limit_assumed"] = per_tick_limit

    report["failed_rows"] = _scalar(conn, "SELECT COUNT(*) FROM inbox WHERE status='failed'")
    report["attempts_histogram"] = {
        str(r["attempts"]): r["n"]
        for r in conn.execute(
            "SELECT attempts, COUNT(*) AS n FROM inbox GROUP BY attempts ORDER BY attempts"
        )
    }

    # Subcategory backlog — meaningful only once the v4 migration has run. This
    # script must still work against a v3 DB, so the column is probed first.
    enr_cols = {r["name"] for r in conn.execute("PRAGMA table_info(enrichments)")}
    if "subcategories" in enr_cols:
        report["subcategory_backlog"] = {
            "swe_total": _scalar(
                conn,
                "SELECT COUNT(*) FROM enrichments WHERE category='software_engineering'",
            ),
            "swe_null": _scalar(
                conn,
                "SELECT COUNT(*) FROM enrichments WHERE category='software_engineering' "
                "AND subcategories IS NULL",
            ),
            "swe_empty": _scalar(
                conn,
                "SELECT COUNT(*) FROM enrichments WHERE category='software_engineering' "
                "AND subcategories = '[]'",
            ),
        }
    else:
        report["subcategory_backlog"] = "n/a (schema is pre-v4)"

    return report


def _print_report(report: dict) -> None:
    print(json.dumps(report, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--per-tick-limit", type=int, default=DEFAULT_PER_TICK_LIMIT)
    args = ap.parse_args(argv)

    if not args.db.exists():
        print(f"diagnose: no such DB {args.db}", file=sys.stderr)
        return 2
    try:
        conn = open_read_only(args.db)
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"diagnose: {exc}", file=sys.stderr)
        return 2
    try:
        report = collect_report(conn, args.per_tick_limit)
    finally:
        conn.close()

    _print_report(report)
    ratio = report["starved_null_recency_ratio"]
    if ratio > NULL_RECENCY_ESCALATION_RATIO:
        print(
            f"\ndiagnose: NULL-recency rows are {ratio:.1%} of the cleaned cohort "
            f"(> {NULL_RECENCY_ESCALATION_RATIO:.0%}). RECORD the count and BOTH "
            f"candidate remedies in docs/RUNBOOK-subcategory-backfill.md and STOP — "
            f"both change the live tick's claim order, which r11 declined.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
