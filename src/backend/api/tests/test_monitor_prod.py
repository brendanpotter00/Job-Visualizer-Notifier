"""Unit tests for the PURE parts of the prod monitor (api/eval/monitor_prod.py).

Runs in the normal backend suite: no DB, no network, no anthropic. Feeds canned
dict rows (RealDictCursor shape) to the evaluate() fns and asserts status/exit/
dormancy logic, plus the read-only-SQL guard.
"""

from __future__ import annotations

import re

from api.eval.monitor_prod import (
    CHECKS,
    CheckResult,
    Context,
    Report,
    _PARENT_INDEX,
    _SIDECAR_INDEX,
    _bytes_per_row,
    _compute_dormant,
    _eval_backlog,
    _eval_failed_ratio,
    _eval_heartbeat,
    _eval_hot_churn,
    _eval_index_bloat,
    _eval_queue,
    _fmt_bytes,
    _fmt_index_size,
    _hot_pct,
    _index_bloat_verdict,
    _worst,
    _zero_count,
    all_sql_statements,
    main,
    overall_exit,
    render_table,
)


def _ctx(baseline=None, window_hours=1, dormant=False) -> Context:
    return Context(baseline=baseline, window_hours=window_hours, dormant=dormant)


def _result(status, cid="X", category="C") -> CheckResult:
    return CheckResult(id=cid, category=category, title="t", status=status,
                       value=0, detail="", threshold="")


# ---- overall_exit -----------------------------------------------------------

def test_overall_exit_schema_absent_is_2():
    rep = Report(timestamp="t", schema_present=False, dormant=False,
                 window_hours=1, results=[_result("crit", "A1_schema_gate", "A")])
    assert overall_exit(rep) == 2


def test_overall_exit_all_ok_is_0():
    rep = Report(timestamp="t", schema_present=True, dormant=False,
                 window_hours=1, results=[_result("ok"), _result("info")])
    assert overall_exit(rep) == 0


def test_overall_exit_any_warn_is_1():
    rep = Report(timestamp="t", schema_present=True, dormant=False,
                 window_hours=1, results=[_result("ok"), _result("warn")])
    assert overall_exit(rep) == 1


def test_overall_exit_crit_is_1():
    rep = Report(timestamp="t", schema_present=True, dormant=False,
                 window_hours=1, results=[_result("ok"), _result("warn"), _result("crit")])
    assert overall_exit(rep) == 1


# ---- A2 heartbeat -----------------------------------------------------------

def test_heartbeat_fresh_ok():
    assert _eval_heartbeat([{"minutes_since_heartbeat": 3.4}], _ctx())[0] == "ok"


def test_heartbeat_stale_warn():
    assert _eval_heartbeat([{"minutes_since_heartbeat": 12}], _ctx())[0] == "warn"


def test_heartbeat_dead_crit():
    assert _eval_heartbeat([{"minutes_since_heartbeat": 45}], _ctx())[0] == "crit"


def test_heartbeat_empty_or_null_crit():
    assert _eval_heartbeat([], _ctx())[0] == "crit"
    assert _eval_heartbeat([{"minutes_since_heartbeat": None}], _ctx())[0] == "crit"


# ---- B1 backlog + dormancy --------------------------------------------------

def _b1(null_backlog=0, null_aged=0, done=0, failed=0, total=0):
    return [{"null_backlog": null_backlog, "null_aged": null_aged,
             "done": done, "failed": failed, "total": total}]


def test_backlog_dormant_is_info_not_crit():
    # large NULL backlog but nothing produced -> dormant info, never crit.
    ctx = _ctx(dormant=True)
    status, _, detail = _eval_backlog(_b1(null_backlog=48000, null_aged=48000), ctx)
    assert status == "info"
    assert "DORMANT" in detail


def test_backlog_key_set_ok_below_threshold():
    assert _eval_backlog(_b1(null_aged=300, done=1000), _ctx())[0] == "ok"


def test_backlog_key_set_warn_and_crit_thresholds():
    assert _eval_backlog(_b1(null_aged=800, done=1000), _ctx())[0] == "warn"
    assert _eval_backlog(_b1(null_aged=2500, done=1000), _ctx())[0] == "crit"


def test_backlog_not_decreasing_vs_baseline_warns():
    baseline = {"results": [{"id": "B1_backlog", "value": 400}]}
    # same aged count as last run during drain (and key set) -> warn even though < 500.
    status, _, detail = _eval_backlog(_b1(null_aged=400, done=10), _ctx(baseline=baseline))
    assert status == "warn"
    assert "NOT decreasing" in detail


def test_backlog_decreasing_vs_baseline_ok():
    baseline = {"results": [{"id": "B1_backlog", "value": 900}]}
    status, _, detail = _eval_backlog(_b1(null_aged=300, done=10), _ctx(baseline=baseline))
    assert status == "ok"
    assert "draining" in detail


def test_compute_dormant_boundary():
    assert _compute_dormant({"null_backlog": 100, "done": 0}, {"failed_nonblank": 0}) is True
    # done > 0 -> not dormant
    assert _compute_dormant({"null_backlog": 100, "done": 5}, {"failed_nonblank": 0}) is False
    # a real non-blank failure -> not dormant
    assert _compute_dormant({"null_backlog": 100, "done": 0}, {"failed_nonblank": 3}) is False
    # nothing pending -> not dormant
    assert _compute_dormant({"null_backlog": 0, "done": 0}, {"failed_nonblank": 0}) is False


# ---- B2 failed ratio --------------------------------------------------------

def _b2(failed_blank=0, failed_nonblank=0, done=0):
    return [{"failed_blank": failed_blank, "failed_nonblank": failed_nonblank, "done": done}]


def test_failed_ratio_no_normalized_rows_is_info():
    status, value, _ = _eval_failed_ratio(_b2(failed_blank=4418), _ctx())
    assert status == "info"
    assert value == "n/a"


def test_failed_ratio_thresholds():
    assert _eval_failed_ratio(_b2(failed_nonblank=1, done=99), _ctx())[0] == "ok"     # 1%
    assert _eval_failed_ratio(_b2(failed_nonblank=3, done=97), _ctx())[0] == "warn"   # 3%
    assert _eval_failed_ratio(_b2(failed_nonblank=7, done=93), _ctx())[0] == "crit"   # 7%


def test_failed_ratio_excludes_blank():
    # 9999 blank failures must not move the needle when non-blank ratio is tiny.
    assert _eval_failed_ratio(_b2(failed_blank=9999, failed_nonblank=1, done=99), _ctx())[0] == "ok"


# ---- C-checks (zero-count) --------------------------------------------------

def test_zero_count_ok_when_zero():
    assert _zero_count("crit")([{"n": 0}], _ctx())[0] == "ok"


def test_zero_count_uses_given_severity():
    assert _zero_count("crit")([{"n": 1}], _ctx())[0] == "crit"
    assert _zero_count("warn")([{"n": 5}], _ctx())[0] == "warn"


def test_zero_count_empty_rows_is_ok():
    assert _zero_count("warn")([], _ctx())[0] == "ok"


# ---- D queue ----------------------------------------------------------------

def test_queue_stable_failed_ok():
    rows = [{"status": "succeeded", "n": 100}, {"status": "failed", "n": 2}]
    baseline = {"results": [{"id": "D_normalize_queue", "value": {"succeeded": 90, "failed": 2}}]}
    assert _eval_queue(rows, _ctx(baseline=baseline))[0] == "ok"


def test_queue_rising_failed_warns():
    rows = [{"status": "succeeded", "n": 100}, {"status": "failed", "n": 10}]
    baseline = {"results": [{"id": "D_normalize_queue", "value": {"succeeded": 90, "failed": 2}}]}
    status, value, detail = _eval_queue(rows, _ctx(baseline=baseline))
    assert status == "warn"
    assert "rising" in detail
    assert value == {"succeeded": 100, "failed": 10}


def test_queue_large_backlog_warns():
    rows = [{"status": "todo", "n": 5000}]
    assert _eval_queue(rows, _ctx())[0] == "warn"


def test_queue_empty_is_ok():
    assert _eval_queue([], _ctx())[0] == "ok"


# ---- S1 index bloat: pure threshold / formatting / absent-index logic --------

_MIB = 1024 * 1024

# The real index names, so the per-relation thresholds are pinned to the
# relations they govern rather than to hardcoded strings.
_PARENT = _PARENT_INDEX
_SIDECAR = _SIDECAR_INDEX

# Measured against prod 2026-08-05 05:17 UTC (67,648 rows in both tables) — the
# numbers the runbook and db_models.py comment quote. Kept here so a threshold
# edit that stops flagging the real, known-bloated parent index fails a test.
_PROD_PARENT_BYTES = 46_800_896   # 691.8 B/row
_PROD_SIDECAR_BYTES = 1_851_392   # 27.4 B/row
_PROD_ROWS = 67_648


def _bloat_rows(parent_bytes=_PROD_PARENT_BYTES, sidecar_bytes=_PROD_SIDECAR_BYTES,
                parent_rows=_PROD_ROWS, sidecar_rows=_PROD_ROWS):
    return [{"parent_bytes": parent_bytes, "sidecar_bytes": sidecar_bytes,
             "parent_rows": parent_rows, "sidecar_rows": sidecar_rows}]


def test_bytes_per_row_math_and_guards():
    assert _bytes_per_row(_PROD_PARENT_BYTES, _PROD_ROWS) == 691.8
    assert _bytes_per_row(_PROD_SIDECAR_BYTES, _PROD_ROWS) == 27.4
    assert _bytes_per_row(None, _PROD_ROWS) is None    # absent index
    assert _bytes_per_row(1234, 0) is None             # empty table, no div-by-zero
    assert _bytes_per_row(1234, None) is None


def test_fmt_bytes_is_binary_and_labelled_mib():
    assert _fmt_bytes(None) == "absent"
    # 1 MiB = 1024^2 B — the label must not imply 10^6.
    assert _fmt_bytes(1024 * 1024) == "1.0MiB"
    assert _fmt_bytes(_PROD_PARENT_BYTES) == "44.6MiB"
    assert _fmt_bytes(4096) == "4096B"                 # sub-0.1MiB stays exact
    assert _fmt_index_size(_PROD_SIDECAR_BYTES, _PROD_ROWS) == "1.8MiB@27.4B/row"
    assert _fmt_index_size(None, _PROD_ROWS) == "absent"
    assert _fmt_index_size(4096, 0) == "4096B@?B/row"


def test_parent_index_today_is_flagged_bloated():
    status, value, detail = _eval_index_bloat(_bloat_rows(), _ctx())
    assert status == "warn"
    assert "BLOATED" in detail
    assert ">150.0B/row" in detail and ">10.0MiB" in detail
    assert value == {"parent": "44.6MiB@691.8B/row", "sidecar": "1.8MiB@27.4B/row"}


def test_healthy_sidecar_alone_is_ok():
    # both relations inside budget -> ok (the post-Unit-4 steady state, modulo
    # the parent index which is gone by then).
    status, _, detail = _eval_index_bloat(
        _bloat_rows(parent_bytes=2 * _MIB, sidecar_bytes=_PROD_SIDECAR_BYTES), _ctx())
    assert status == "ok"
    assert "BLOATED" not in detail


def test_either_threshold_alone_trips_the_warn():
    # big but well-packed (a much larger corpus): bytes over, B/row fine.
    assert _index_bloat_verdict("idx_job_listings_last_seen", 11 * _MIB, 1_000_000)[0] == "warn"
    # small but badly packed (a tiny corpus that churned): B/row over, bytes fine.
    assert _index_bloat_verdict("idx_job_listings_last_seen", 2 * _MIB, 5_000)[0] == "warn"


def test_sidecar_thresholds_are_pinned():
    # The sidecar constants (8 MiB / 80.0 B-row) are separate from the parent's
    # and would otherwise be asserted nowhere — loosening them must fail here.
    # bytes over, B/row fine:
    assert _index_bloat_verdict(_SIDECAR, 9 * _MIB, 1_000_000)[0] == "warn"
    # B/row over (81), bytes fine:
    assert _index_bloat_verdict(_SIDECAR, 81 * 1_000, 1_000)[0] == "warn"
    # and the parent's looser 150 B/row line must NOT be what governs the sidecar
    assert _index_bloat_verdict(_SIDECAR, 100 * 1_000, 1_000)[0] == "warn"
    assert _index_bloat_verdict(_PARENT, 100 * 1_000, 1_000)[0] == "ok"


def test_exactly_at_threshold_does_not_trip():
    # the comparison is strict >, so the threshold value itself is still ok.
    assert _index_bloat_verdict(_PARENT, 10 * _MIB, 10 * _MIB // 150)[0] == "ok"
    assert _index_bloat_verdict(_PARENT, 150 * 1_000, 1_000)[0] == "ok"   # exactly 150.0 B/row
    assert _index_bloat_verdict(_SIDECAR, 8 * _MIB, 8 * _MIB // 80)[0] == "ok"
    assert _index_bloat_verdict(_SIDECAR, 80 * 1_000, 1_000)[0] == "ok"   # exactly 80.0 B/row
    # one byte past each line does trip.
    assert _index_bloat_verdict(_PARENT, 10 * _MIB + 1, 10)[0] == "warn"
    assert _index_bloat_verdict(_SIDECAR, 8 * _MIB + 1, 10)[0] == "warn"


def test_absent_parent_index_is_info_not_error():
    # post-Unit-4: the index is gone on purpose. Must not raise, must not warn.
    status, value, detail = _eval_index_bloat(_bloat_rows(parent_bytes=None), _ctx())
    assert status == "info"
    assert "absent (dropped by Unit 4 contract)" in detail
    assert value["parent"] == "absent"


def test_absent_sidecar_index_warns():
    # the index the read path now depends on is missing — different meaning.
    status, _, detail = _eval_index_bloat(
        _bloat_rows(parent_bytes=None, sidecar_bytes=None), _ctx())
    assert status == "warn"
    assert "sidecar read path has no index" in detail


def test_both_indexes_absent_does_not_raise():
    # nothing hardcodes that either index exists.
    status, value, _ = _eval_index_bloat(
        _bloat_rows(parent_bytes=None, sidecar_bytes=None), _ctx())
    assert status == "warn"
    assert value == {"parent": "absent", "sidecar": "absent"}


def test_index_bloat_no_rows_does_not_raise():
    assert _eval_index_bloat([], _ctx())[0] == "warn"  # both read as absent


def test_worst_status_ordering():
    assert _worst("ok", "info") == "info"
    assert _worst("info", "warn") == "warn"
    assert _worst("warn", "crit") == "crit"
    assert _worst("ok", "ok") == "ok"


# ---- S2 HOT churn -----------------------------------------------------------

def test_hot_pct_math_and_zero_update_guard():
    assert _hot_pct(182_158_867, 209_910) == 0.115   # job_listings, 2026-08-05
    assert _hot_pct(88_350, 22) == 0.025             # job_freshness, same day
    assert _hot_pct(0, 0) is None                    # never updated, not "0% HOT"
    assert _hot_pct(None, None) is None


def test_hot_churn_reports_both_tables_and_never_fails():
    rows = [
        {"relname": "job_freshness", "n_tup_upd": 88_350, "n_tup_hot_upd": 22,
         "n_dead_tup": 0, "autovacuum_count": 5},
        {"relname": "job_listings", "n_tup_upd": 182_158_867, "n_tup_hot_upd": 209_910,
         "n_dead_tup": 7163, "autovacuum_count": 9181},
    ]
    status, value, detail = _eval_hot_churn(rows, _ctx())
    # info only: no assertion on the trend, by design.
    assert status == "info"
    assert value == {"job_freshness": 0.025, "job_listings": 0.115}
    assert "job_listings: upd=182158867" in detail
    assert "autovac=9181" in detail


def test_hot_churn_empty_rows_is_info():
    assert _eval_hot_churn([], _ctx())[0] == "info"


# ---- S3/S4 anti-join invariants ---------------------------------------------

def test_anti_join_checks_are_registered_and_critical():
    by_id = {c.id: c for c in CHECKS}
    for cid in ("S3_listings_without_freshness", "S4_freshness_without_listing"):
        assert by_id[cid].category == "S"
        # a non-zero count is a FAILING check — the listing vanishes from /api/jobs.
        assert by_id[cid].evaluate([{"n": 1}], _ctx())[0] == "crit"
        assert by_id[cid].evaluate([{"n": 0}], _ctx())[0] == "ok"


def test_s_checks_do_not_assume_both_indexes_exist():
    # the SQL must resolve the index names dynamically, never hardcode presence.
    sql = {c.id: c.sql for c in CHECKS}["S1_index_bloat"]
    assert sql.count("to_regclass(") == 2


# ---- read-only guard --------------------------------------------------------

def test_no_write_sql_anywhere():
    forbidden = re.compile(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE|CREATE|GRANT)\b", re.IGNORECASE)
    for sql in all_sql_statements():
        assert not forbidden.search(sql), f"write keyword found in: {sql[:80]!r}"


def test_every_check_sql_is_a_select():
    for sql in all_sql_statements():
        assert sql.lstrip().upper().startswith("SELECT")


# ---- render smoke -----------------------------------------------------------

def test_render_table_contains_verdict_and_shown_checks():
    rep = Report(
        timestamp="2026-06-14T00:00:00+00:00", schema_present=True, dormant=False,
        window_hours=1,
        results=[_result("ok", "A2_worker_liveness", "A"), _result("crit", "C1_done_without_locations", "C")],
        summary={"ok": 1, "info": 0, "warn": 0, "crit": 1},
    )
    out = render_table(rep, verbose=False)
    assert "Verdict: DEGRADED (exit 1)" in out
    assert "C1_done_without_locations" in out
    # non-verbose hides the ok check
    assert "A2_worker_liveness" not in out
    # verbose shows it
    assert "A2_worker_liveness" in render_table(rep, verbose=True)


def test_render_table_not_deployed_banner():
    rep = Report(timestamp="t", schema_present=False, dormant=False, window_hours=1,
                 results=[_result("crit", "A1_schema_gate", "A")],
                 summary={"ok": 0, "info": 0, "warn": 0, "crit": 1})
    out = render_table(rep)
    assert "FEATURE NOT DEPLOYED" in out
    assert "Verdict: SETUP (exit 2)" in out


# ---- read-only guard: refuse PYTEST_SCHEMA ----------------------------------

def test_main_refuses_to_run_under_pytest_schema(monkeypatch, capsys):
    # Even with a DSN present, main() must bail with exit 2 BEFORE connecting:
    # get_connection's PYTEST_SCHEMA branch would otherwise CREATE SCHEMA +
    # commit (a write) before the read-only pin. No DB is touched here.
    monkeypatch.setenv("MONITOR_DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("PYTEST_SCHEMA", "test_deadbeef")
    assert main([]) == 2
    assert "PYTEST_SCHEMA" in capsys.readouterr().err
