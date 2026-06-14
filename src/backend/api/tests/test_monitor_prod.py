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
    _compute_dormant,
    _eval_backlog,
    _eval_failed_ratio,
    _eval_heartbeat,
    _eval_queue,
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
