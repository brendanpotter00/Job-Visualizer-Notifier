"""On-demand, read-only production-health monitor for location normalization.

Answers "is the live two-tier location-normalization pipeline working?" for the
deterministic, SQL-derivable signal groups **A–D** (deployment/liveness, backlog/
throughput, integrity invariants, normalize-queue health). The log-stream (E) and
quality (F) arms need Railway logs + the Anthropic key and live in the runbook,
not here: ``src/backend/docs/location-normalization-monitoring.md``.

STRICTLY READ-ONLY. It opens an autocommit session pinned
``default_transaction_read_only = on`` and contains zero write SQL — every query
is a ``SELECT`` / ``information_schema`` read. It never INSERT/UPDATE/DELETEs,
never re-normalizes, never writes prod. (Remediation is a separate, human action.)

Canonical invocation (from the repo ROOT):

    MONITOR_DATABASE_URL='postgresql://readonly:...@host:port/db' \
        PYTHONPATH=. python -m src.backend.api.eval.monitor_prod --verbose

Get the DSN from Railway -> onesecondswe -> Postgres -> Connect (use the
read-only/public URL; never a write role). It is a DISTINCT env var from
``DATABASE_URL`` on purpose so this can never accidentally hit local dev.

Exit codes:
    0  healthy   — schema present, no warn/crit
    1  degraded  — schema present, >=1 warn or crit (the table shows which)
    2  setup     — MONITOR_DATABASE_URL unset/unreachable, OR the A1 schema gate
                   failed (feature not deployed). Never a misleading "0% healthy".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import psycopg2

from scripts.shared import database as db

# Status vocabulary, ordered by severity. "info" is contextual and never fails
# the run; "warn"/"crit" => degraded (exit 1). A missing schema => setup (exit 2).
_STATUSES = ("ok", "info", "warn", "crit")

# Mirrors CONFIDENCE_FLOOR in api/tasks/normalize_location.py:43 — cited, not a
# second source of truth. Low-confidence results are marked 'failed' and never
# cached, so any cached LLM alias below this floor (C7) is a leak.
_CONFIDENCE_FLOOR = 0.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #

@dataclass
class Context:
    """Cross-check state the evaluate() fns read."""
    baseline: Optional[dict]
    window_hours: int
    dormant: bool


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    category: str  # "A" | "B" | "C" | "D"
    sql: str
    threshold: str  # human-readable, for the table
    # (rows, ctx) -> (status, value, detail); status in _STATUSES.
    evaluate: Callable[[list[dict], Context], tuple]
    optional: bool = False  # a SQL error => info "unavailable", not crit


@dataclass
class CheckResult:
    id: str
    category: str
    title: str
    status: str
    value: object
    detail: str
    threshold: str


@dataclass
class Report:
    timestamp: str
    schema_present: bool
    dormant: bool
    window_hours: int
    results: list  # list[CheckResult]
    summary: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #

def _first_value(rows: list[dict]) -> int:
    """The single scalar a ``SELECT count(*) AS x`` returns (0 if no rows)."""
    if not rows:
        return 0
    v = next(iter(rows[0].values()))
    return int(v) if v is not None else 0


def _baseline_value(ctx: Context, check_id: str):
    """The ``value`` a prior run recorded for ``check_id`` (or None)."""
    if not ctx.baseline:
        return None
    for r in ctx.baseline.get("results", []):
        if r.get("id") == check_id:
            return r.get("value")
    return None


def _compute_dormant(b1_row: dict, b2_row: dict) -> bool:
    """True when the pipeline looks intentionally idle (no Anthropic key yet):
    a NULL backlog exists but nothing has been normalized AND no non-blank
    failures. A giant NULL backlog is a failure only once the key is set; the
    runbook's group-E log probe is the authoritative key-state confirmation."""
    null_backlog = int(b1_row.get("null_backlog") or 0)
    done = int(b1_row.get("done") or 0)
    failed_nonblank = int(b2_row.get("failed_nonblank") or 0)
    return null_backlog > 0 and done == 0 and failed_nonblank == 0


def _eval_heartbeat(rows: list[dict], ctx: Context) -> tuple:
    """A2 — worker liveness. Heartbeat fires every 5 min."""
    if not rows or rows[0].get("minutes_since_heartbeat") is None:
        return ("crit", None, "no heartbeat rows — worker never started?")
    mins = float(rows[0]["minutes_since_heartbeat"])
    if mins > 30:
        status = "crit"
    elif mins > 10:
        status = "warn"
    else:
        status = "ok"
    return (status, round(mins, 1), f"{mins:.1f} min since last heartbeat")


def _eval_backlog(rows: list[dict], ctx: Context) -> tuple:
    """B1 — status distribution + aged NULL backlog. Headline value = null_aged."""
    r = rows[0]
    null_backlog = int(r.get("null_backlog") or 0)
    null_aged = int(r.get("null_aged") or 0)
    done = int(r.get("done") or 0)
    if ctx.dormant:
        return (
            "info", null_aged,
            f"looks DORMANT (null_backlog={null_backlog}, done=0) — is "
            "ANTHROPIC_API_KEY set on Railway? (confirm via group-E logs)",
        )
    status = "ok"
    if null_aged > 2000:
        status = "crit"
    elif null_aged > 500:
        status = "warn"
    detail = f"null_aged={null_aged} (>{ctx.window_hours}h old), null_backlog={null_backlog}, done={done}"
    prev = _baseline_value(ctx, "B1_backlog")
    if prev is not None:
        prev = int(prev)
        if null_aged > 0 and null_aged >= prev:
            if status == "ok":
                status = "warn"
            detail += f"; NOT decreasing vs baseline ({prev})"
        else:
            detail += f"; draining ({prev} -> {null_aged})"
    return (status, null_aged, detail)


def _eval_failed_ratio(rows: list[dict], ctx: Context) -> tuple:
    """B2 — LLM-side failure ratio, blank-location failures excluded."""
    r = rows[0]
    failed_blank = int(r.get("failed_blank") or 0)
    failed_nonblank = int(r.get("failed_nonblank") or 0)
    done = int(r.get("done") or 0)
    denom = done + failed_nonblank
    if denom == 0:
        return ("info", "n/a", f"no normalized rows yet (failed_blank={failed_blank})")
    ratio = failed_nonblank / denom
    if ratio > 0.05:
        status = "crit"
    elif ratio > 0.02:
        status = "warn"
    else:
        status = "ok"
    pct = round(ratio * 100, 2)
    return (status, pct, f"{pct}% non-blank failures (failed_nonblank={failed_nonblank}, done={done}, blank={failed_blank})")


def _zero_count(severity: str) -> Callable[[list[dict], Context], tuple]:
    """Factory for the C-checks: expected value is 0; >0 => ``severity``."""
    def _eval(rows: list[dict], ctx: Context) -> tuple:
        v = _first_value(rows)
        if v > 0:
            return (severity, v, f"{v} (expected 0)")
        return ("ok", 0, "0")
    return _eval


def _eval_queue(rows: list[dict], ctx: Context) -> tuple:
    """D — normalize-queue health. Counts are info; rising failures / big
    backlog (while the worker is alive, per A2) => warn."""
    counts = {row["status"]: int(row["n"]) for row in rows}
    todo = counts.get("todo", 0) + counts.get("doing", 0)
    failed = counts.get("failed", 0)
    status = "ok"
    detail_bits = [f"{k}={v}" for k, v in sorted(counts.items())] or ["(no normalize-queue rows yet)"]
    detail = " ".join(detail_bits)
    if todo > 1000:
        status = "warn"
        detail += f"; large todo/doing backlog ({todo})"
    prev = _baseline_value(ctx, "D_normalize_queue")
    prev_failed = prev.get("failed") if isinstance(prev, dict) else None
    if prev_failed is not None and failed > int(prev_failed):
        status = "warn"
        detail += f"; failed rising vs baseline ({prev_failed} -> {failed})"
    return (status, counts, detail)


def _eval_throughput(rows: list[dict], ctx: Context) -> tuple:
    """D-optional — normalize successes in the window. Info only."""
    n = _first_value(rows)
    return ("info", n, f"{n} normalize successes in the last {ctx.window_hours}h")


# --------------------------------------------------------------------------- #
# The checks — exactly the §4-A..D queries, verified against db_models.py.
# --------------------------------------------------------------------------- #

_SCHEMA_GATE_SQL = """
SELECT
  (SELECT count(*) FROM information_schema.columns
     WHERE table_schema='public' AND table_name='job_listings'
       AND column_name='normalization_status') AS has_status_col,
  (SELECT count(*) FROM information_schema.tables
     WHERE table_schema='public'
       AND table_name IN ('locations','location_aliases','alias_locations','job_locations')) AS n_loc_tables
""".strip()

CHECKS: list = [
    Check(
        id="A2_worker_liveness", title="Worker liveness", category="A",
        threshold=">10m warn, >30m crit",
        sql="SELECT extract(epoch FROM (now() - max(at)))/60.0 AS minutes_since_heartbeat FROM worker_heartbeats",
        evaluate=_eval_heartbeat,
    ),
    Check(
        id="B1_backlog", title="Status distribution + aged backlog", category="B",
        threshold="null_aged >500 warn, >2000 crit; must drain",
        sql="""
SELECT
  count(*) FILTER (WHERE normalization_status IS NULL) AS null_backlog,
  count(*) FILTER (WHERE normalization_status IS NULL
                   AND first_seen_at < now() - make_interval(hours => %(window_hours)s)) AS null_aged,
  count(*) FILTER (WHERE normalization_status='done') AS done,
  count(*) FILTER (WHERE normalization_status='failed') AS failed,
  count(*) AS total
FROM job_listings
""".strip(),
        evaluate=_eval_backlog,
    ),
    Check(
        id="B2_failed_breakdown", title="Failed: legitimate vs LLM-side", category="B",
        threshold="non-blank ratio >2% warn, >5% crit",
        sql="""
SELECT
  count(*) FILTER (WHERE normalization_status='failed'
                   AND (location IS NULL OR btrim(location)='')) AS failed_blank,
  count(*) FILTER (WHERE normalization_status='failed'
                   AND location IS NOT NULL AND btrim(location)<>'') AS failed_nonblank,
  count(*) FILTER (WHERE normalization_status='done') AS done
FROM job_listings
""".strip(),
        evaluate=_eval_failed_ratio,
    ),
    Check(
        id="C1_done_without_locations", title="'done' job with no job_locations", category="C",
        threshold="0 (crit if >0)",
        sql="""
SELECT count(*) AS done_without_locations
FROM job_listings jl
WHERE jl.normalization_status='done'
  AND NOT EXISTS (SELECT 1 FROM job_locations l WHERE l.job_listing_id = jl.id)
""".strip(),
        evaluate=_zero_count("crit"),
    ),
    Check(
        id="C2_alias_without_children", title="alias_locations zero-children bug", category="C",
        threshold="0 (warn if >0)",
        sql="""
SELECT count(*) AS aliases_without_children
FROM location_aliases a
WHERE NOT EXISTS (SELECT 1 FROM alias_locations al WHERE al.raw_text = a.raw_text)
""".strip(),
        evaluate=_zero_count("warn"),
    ),
    Check(
        id="C3_id_collisions", title="job_listings.id collisions", category="C",
        threshold="0 (crit if >0)",
        sql="SELECT count(*) AS colliding_ids FROM (SELECT id FROM job_listings GROUP BY id HAVING count(*) > 1) t",
        evaluate=_zero_count("crit"),
    ),
    Check(
        id="C4_orphan_job_locations", title="orphan job_locations rows", category="C",
        threshold="0 (warn if >0)",
        sql="""
SELECT count(*) AS orphan_job_locations
FROM job_locations l
WHERE NOT EXISTS (SELECT 1 FROM job_listings jl WHERE jl.id = l.job_listing_id)
""".strip(),
        evaluate=_zero_count("warn"),
    ),
    Check(
        id="C5_remote_with_city", title="kind='remote' carrying a city", category="C",
        threshold="0 (warn if >0)",
        sql="SELECT count(*) AS remote_with_city FROM locations WHERE kind='remote' AND city IS NOT NULL",
        evaluate=_zero_count("warn"),
    ),
    Check(
        id="C6_city_kind_null_city", title="kind='city' missing a city", category="C",
        threshold="0 (warn if >0)",
        sql="SELECT count(*) AS city_kind_null_city FROM locations WHERE kind='city' AND city IS NULL",
        evaluate=_zero_count("warn"),
    ),
    Check(
        id="C7_lowconf_llm_alias", title="low-confidence cached LLM alias", category="C",
        threshold="0 (warn if >0)",
        sql=(
            "SELECT count(*) AS lowconf_llm_aliases FROM location_aliases "
            "WHERE source='llm' AND confidence IS NOT NULL AND confidence < 0.5"
        ),
        evaluate=_zero_count("warn"),
    ),
    Check(
        id="C8_geo_populated", title="geo populated in v1 (should be NULL)", category="C",
        threshold="0 (warn if >0)",
        sql="SELECT count(*) AS geo_populated FROM locations WHERE lat IS NOT NULL OR lng IS NOT NULL",
        evaluate=_zero_count("warn"),
    ),
    Check(
        id="C9_multi_primary", title="multiple primaries on one job", category="C",
        threshold="0 (warn if >0)",
        sql="""
SELECT count(*) AS jobs_multi_primary
FROM (SELECT job_listing_id FROM job_locations WHERE is_primary
      GROUP BY job_listing_id HAVING count(*) > 1) t
""".strip(),
        evaluate=_zero_count("warn"),
    ),
    Check(
        id="D_normalize_queue", title="normalize queue status distribution", category="D",
        threshold="failed flat vs baseline; todo/doing small",
        sql="""
SELECT status, count(*) AS n
FROM procrastinate_jobs
WHERE queue_name='normalize'
GROUP BY status ORDER BY status
""".strip(),
        evaluate=_eval_queue,
    ),
    Check(
        id="D_throughput", title="normalize successes in window", category="D",
        threshold="info only",
        sql="""
SELECT count(*) AS normalize_succeeded_in_window
FROM procrastinate_events e
JOIN procrastinate_jobs j ON j.id = e.job_id
WHERE j.queue_name='normalize' AND e.type='succeeded'
  AND e.at > now() - make_interval(hours => %(window_hours)s)
""".strip(),
        evaluate=_eval_throughput,
        optional=True,
    ),
]


def all_sql_statements() -> list[str]:
    """Every SQL string the monitor can issue — for the read-only guard test."""
    return [_SCHEMA_GATE_SQL] + [c.sql for c in CHECKS]


# --------------------------------------------------------------------------- #
# DB access (read-only) + run
# --------------------------------------------------------------------------- #

def connect_readonly(dsn: str):
    """Open a connection pinned read-only. Belt-and-suspenders on top of the
    fact that every query here is already a SELECT."""
    conn = db.get_connection(dsn, application_name="monitor_prod", statement_timeout_ms=30_000)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute("SET default_transaction_read_only = on")
    finally:
        cur.close()
    return conn


def _run_sql(conn, sql: str, params: dict) -> list[dict]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def schema_gate(conn) -> tuple:
    """A1 — returns (present: bool, row: dict)."""
    row = _run_sql(conn, _SCHEMA_GATE_SQL, {})[0]
    present = int(row["has_status_col"]) >= 1 and int(row["n_loc_tables"]) >= 4
    return present, row


def _summarize(results: list) -> dict:
    out = {s: 0 for s in _STATUSES}
    for r in results:
        out[r.status] = out.get(r.status, 0) + 1
    return out


def run(dsn: str, baseline: Optional[dict], window_hours: int) -> Report:
    conn = connect_readonly(dsn)
    try:
        present, gate_row = schema_gate(conn)
        gate = CheckResult(
            id="A1_schema_gate", category="A", title="Schema-presence gate",
            status="ok" if present else "crit",
            value=f"col={gate_row['has_status_col']}, tables={gate_row['n_loc_tables']}",
            detail=("4 location tables + normalization_status present" if present
                    else "FEATURE NOT DEPLOYED — expected col=1 and 4 location tables"),
            threshold="col=1 & tables=4",
        )
        if not present:
            return Report(
                timestamp=_now_iso(), schema_present=False, dormant=False,
                window_hours=window_hours, results=[gate], summary=_summarize([gate]),
            )

        params = {"window_hours": window_hours}
        raw: dict = {}
        for chk in CHECKS:
            try:
                raw[chk.id] = _run_sql(conn, chk.sql, params)
            except psycopg2.Error as exc:
                raw[chk.id] = exc

        b1, b2 = raw.get("B1_backlog"), raw.get("B2_failed_breakdown")
        dormant = (
            isinstance(b1, list) and b1 and isinstance(b2, list) and b2
            and _compute_dormant(b1[0], b2[0])
        )
        ctx = Context(baseline=baseline, window_hours=window_hours, dormant=bool(dormant))

        results = [gate]
        for chk in CHECKS:
            r = raw[chk.id]
            if isinstance(r, Exception):
                if chk.optional:
                    status, value, detail = "info", None, f"unavailable: {r}"
                else:
                    status, value, detail = "crit", None, f"query error: {r}"
            else:
                status, value, detail = chk.evaluate(r, ctx)
            results.append(CheckResult(
                id=chk.id, category=chk.category, title=chk.title,
                status=status, value=value, detail=detail, threshold=chk.threshold,
            ))
        return Report(
            timestamp=_now_iso(), schema_present=True, dormant=bool(dormant),
            window_hours=window_hours, results=results, summary=_summarize(results),
        )
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def _fmt_value(v) -> str:
    if isinstance(v, dict):
        return " ".join(f"{k}={x}" for k, x in sorted(v.items())) or "-"
    return "-" if v is None else str(v)


def overall_exit(report: Report) -> int:
    if not report.schema_present:
        return 2
    if any(r.status in ("warn", "crit") for r in report.results):
        return 1
    return 0


def _verdict(report: Report) -> str:
    if not report.schema_present:
        return "SETUP"
    return "DEGRADED" if overall_exit(report) == 1 else "HEALTHY"


def render_table(report: Report, verbose: bool = False) -> str:
    lines: list[str] = []
    lines.append(f"Location-Normalization Prod Monitor — {report.timestamp}")
    if not report.schema_present:
        lines.append("\n  *** FEATURE NOT DEPLOYED *** (A1 schema gate failed)")
    shown = [r for r in report.results if verbose or r.status != "ok"]
    if not shown:
        lines.append("\n  all checks OK")
    for r in shown:
        lines.append(
            f"\n  [{r.status.upper():<4}] {r.id}  ({r.category})"
            f"\n         value: {_fmt_value(r.value)}"
            f"\n         {r.detail}"
            f"\n         threshold: {r.threshold}"
        )
    s = report.summary
    lines.append(
        f"\nSummary: ok={s.get('ok', 0)} info={s.get('info', 0)} "
        f"warn={s.get('warn', 0)} crit={s.get('crit', 0)}"
    )
    if report.dormant:
        lines.append("Note: pipeline looks DORMANT — confirm ANTHROPIC_API_KEY state via group-E logs (runbook).")
    lines.append(f"Verdict: {_verdict(report)} (exit {overall_exit(report)})")
    return "\n".join(lines)


def _report_to_dict(report: Report) -> dict:
    return {
        "timestamp": report.timestamp,
        "schema_present": report.schema_present,
        "dormant": report.dormant,
        "window_hours": report.window_hours,
        "summary": report.summary,
        "verdict": _verdict(report),
        "exit_code": overall_exit(report),
        "results": [asdict(r) for r in report.results],
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

_NO_DSN_MSG = (
    "ERROR: MONITOR_DATABASE_URL is not set.\n"
    "  Get the prod connection string from Railway -> onesecondswe -> Postgres ->\n"
    "  Connect (use the read-only/public URL; never a write role). Then:\n"
    "    MONITOR_DATABASE_URL='postgresql://...' PYTHONPATH=. \\\n"
    "      python -m src.backend.api.eval.monitor_prod\n"
    "  Do NOT reuse the local dev DATABASE_URL (that's localhost)."
)


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Read-only location-normalization prod-health monitor (groups A-D).")
    p.add_argument("--json", metavar="PATH", help="write the full structured report to JSON (also the next run's --baseline)")
    p.add_argument("--baseline", metavar="PATH", help="load a prior run's JSON to enable run-over-run deltas (B1 must drain, D failed must not rise)")
    p.add_argument("--window-hours", type=int, default=1, help="window for the aged-backlog / throughput slices (default 1)")
    p.add_argument("--verbose", action="store_true", help="print every check, not just non-ok ones")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    dsn = os.environ.get("MONITOR_DATABASE_URL")
    if not dsn:
        print(_NO_DSN_MSG, file=sys.stderr)
        return 2

    baseline = None
    if args.baseline:
        with open(args.baseline) as f:
            baseline = json.load(f)

    try:
        report = run(dsn, baseline, args.window_hours)
    except psycopg2.Error as exc:
        print(f"ERROR: could not query MONITOR_DATABASE_URL (read-only prod): {exc}", file=sys.stderr)
        return 2

    if args.json:
        with open(args.json, "w") as f:
            json.dump(_report_to_dict(report), f, indent=2, default=str)
        print(f"wrote report -> {args.json}")

    print(render_table(report, verbose=args.verbose))
    return overall_exit(report)


if __name__ == "__main__":
    sys.exit(main())
