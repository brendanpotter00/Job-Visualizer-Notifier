"""Metrics-push channel: payload assembly (pure), scorecard hash gating, and
the best-effort CLI contract (a metrics failure must never fail a tick)."""

import argparse
import json
import re

import httpx

from job_enricher import cli
from job_enricher.metrics import build_metrics_payload, drift_suspected
from job_enricher.taxonomy import taxonomy_version
from job_enricher.store import LAST_SCORECARD_HASH_KEY, TICK_COUNTER_COLS


def _run_tick(store, **counters):
    tid = store.start_tick()
    if counters:
        store.bump_tick_counters(**counters)
    store.record_stage_timing("classify", "t0", "t1", 1234, item_count=6, retry_count=1)
    store.end_tick(status="ok")
    return tid


def test_build_metrics_payload_shape(store):
    store.heartbeat()
    tid = _run_tick(store, claimed=6, classified=6, sent=6, nulled_facets=1)
    payload, scorecard_hash = build_metrics_payload(store)

    assert payload["tick_uuid"] == store.get_tick(tid)["uuid"]
    assert payload["status"] == "ok"
    assert payload["ended_at"] is not None
    assert payload["counters"] == {
        "claimed": 6, "cleaned": 0, "classified": 6, "judged": 0, "corrected": 0,
        "needs_human": 0, "sent": 6, "errors": 0, "nulled_facets": 1,
        "swe_classified": 0, "swe_subcat_evaluated": 0, "swe_subcategorized": 0,
    }
    assert payload["duration_s"] >= 0.0
    assert payload["stage_timings"] == [
        {"stage": "classify", "ms": 1234.0, "items": 6, "retries": 1}
    ]
    assert payload["heartbeat_age_s"] is not None and payload["heartbeat_age_s"] >= 0
    assert payload["knobs"]["judge_scope"] == "low_confidence"
    # The contract is "the payload carries the LIVE taxonomy version", not any
    # particular number — pinning the literal broke this test on every SKILL.md
    # bump. Assert the SHAPE too: comparing against taxonomy_version() alone would
    # still pass if both sides degraded together.
    assert re.fullmatch(r"v\d+\+[0-9a-f]{12}", payload["taxonomy_version"])
    assert payload["taxonomy_version"] == taxonomy_version()
    assert payload["enricher_version"]
    assert payload["drift_suspected"] is False
    assert payload["scorecard"] is None or scorecard_hash  # depends on repo scorecard state


def test_every_tick_counter_column_leaves_the_laptop(store):
    """⚠ THE DRIFT GUARD. The payload's counter set must BE `TICK_COUNTER_COLS` —
    not a second hand-written list beside it.

    That is exactly how the three v4 counters were lost: `bump_tick_counters`
    wrote `swe_classified` / `swe_subcat_evaluated` / `swe_subcategorized` to the
    ticks table correctly, and metrics-push silently dropped them, so JVN's
    `subcategory_empty_drift` breaker read nothing at all. A missing key is not an
    error on either side — nothing would ever have gone red."""
    store.heartbeat()
    _run_tick(store, classified=4, swe_classified=3,
              swe_subcat_evaluated=2, swe_subcategorized=1)
    payload, _ = build_metrics_payload(store)

    assert set(payload["counters"]) == set(TICK_COUNTER_COLS)
    assert payload["counters"]["swe_classified"] == 3
    assert payload["counters"]["swe_subcat_evaluated"] == 2
    assert payload["counters"]["swe_subcategorized"] == 1


def test_build_metrics_payload_running_tick_and_explicit_id(store):
    t1 = store.start_tick()
    store.end_tick(status="error", notes="boom")
    t2 = store.start_tick()  # still running
    payload, _ = build_metrics_payload(store)  # latest = running tick
    assert payload["status"] == "running" and payload["ended_at"] is None
    assert payload["tick_uuid"] == store.get_tick(t2)["uuid"]
    payload1, _ = build_metrics_payload(store, tick_id=t1)
    assert payload1["status"] == "error" and payload1["notes"] == "boom"


def test_build_metrics_payload_no_ticks(store):
    payload, scorecard_hash = build_metrics_payload(store)
    assert payload is None and scorecard_hash is None


def test_drift_suspected_thresholds():
    assert drift_suspected({"classified": 10, "nulled_facets": 6}) is True
    assert drift_suspected({"classified": 10, "nulled_facets": 5}) is False   # exactly 50% is fine
    assert drift_suspected({"classified": 9, "nulled_facets": 9}) is False    # below min classified
    assert drift_suspected({"classified": 0, "nulled_facets": 0}) is False


def test_drift_suspected_rides_metrics_payload(store):
    _run_tick(store, classified=10, nulled_facets=6)
    payload, _ = build_metrics_payload(store)
    assert payload["drift_suspected"] is True


def test_scorecard_sent_only_when_hash_new(store, monkeypatch, tmp_path):
    import job_enricher.metrics as metrics_mod

    scorecards = tmp_path / "scorecards"
    scorecards.mkdir()
    (scorecards / "scorecard.json").write_text(json.dumps({"category_accuracy": 0.9}))
    import job_enricher.eval.golden as golden
    monkeypatch.setattr(golden, "SCORECARD_DIR", scorecards)

    _run_tick(store)
    payload, digest = build_metrics_payload(store)
    assert payload["scorecard"] == {"category_accuracy": 0.9}
    assert digest

    # after a successful push the CLI stores the hash -> next payload omits it
    store.set_meta(LAST_SCORECARD_HASH_KEY, digest)
    payload2, digest2 = build_metrics_payload(store)
    assert payload2["scorecard"] is None and digest2 is None

    # a changed scorecard is sent again
    (scorecards / "scorecard.json").write_text(json.dumps({"category_accuracy": 0.95}))
    payload3, digest3 = build_metrics_payload(store)
    assert payload3["scorecard"] == {"category_accuracy": 0.95}
    assert digest3 and digest3 != digest


# ---- CLI best-effort contract -----------------------------------------------
class _OkMetricsClient:
    def __init__(self):
        self.payloads = []

    def post_metrics(self, payload):
        self.payloads.append(payload)
        return {"ok": True}


class _DownMetricsClient:
    def post_metrics(self, payload):
        raise httpx.ConnectError("jvn down")


def test_cmd_metrics_push_ok(store, monkeypatch, capsys):
    _run_tick(store, sent=3)
    monkeypatch.setattr(cli, "Store", lambda: store)
    import job_enricher.jvn_client as jc
    client = _OkMetricsClient()
    monkeypatch.setattr(jc, "JVNClient", lambda: client)

    rc = cli._cmd_metrics_push(argparse.Namespace(tick_id=None, strict=False))
    assert rc == 0
    assert len(client.payloads) == 1
    assert "metrics-push: ok" in capsys.readouterr().out


def test_cmd_metrics_push_failure_is_best_effort_exit_zero(store, monkeypatch):
    """NEVER let a metrics failure fail the tick: log + exit 0."""
    _run_tick(store)
    monkeypatch.setattr(cli, "Store", lambda: store)
    import job_enricher.jvn_client as jc
    monkeypatch.setattr(jc, "JVNClient", lambda: _DownMetricsClient())

    rc = cli._cmd_metrics_push(argparse.Namespace(tick_id=None, strict=False))
    assert rc == 0


def test_cmd_metrics_push_strict_exits_two_on_failure(store, monkeypatch):
    _run_tick(store)
    monkeypatch.setattr(cli, "Store", lambda: store)
    import job_enricher.jvn_client as jc
    monkeypatch.setattr(jc, "JVNClient", lambda: _DownMetricsClient())

    rc = cli._cmd_metrics_push(argparse.Namespace(tick_id=None, strict=True))
    assert rc == 2


def test_cmd_metrics_push_no_tick_is_noop(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_metrics_push(argparse.Namespace(tick_id=None, strict=False))
    assert rc == 0
    assert "no tick" in capsys.readouterr().out


def test_cmd_metrics_push_updates_scorecard_hash_only_on_success(store, monkeypatch, tmp_path):
    scorecards = tmp_path / "scorecards"
    scorecards.mkdir()
    (scorecards / "scorecard.json").write_text(json.dumps({"n": 252}))
    import job_enricher.eval.golden as golden
    monkeypatch.setattr(golden, "SCORECARD_DIR", scorecards)
    _run_tick(store)
    monkeypatch.setattr(cli, "Store", lambda: store)
    import job_enricher.jvn_client as jc

    # failed push: hash NOT stored -> the scorecard re-sends next time
    monkeypatch.setattr(jc, "JVNClient", lambda: _DownMetricsClient())
    cli._cmd_metrics_push(argparse.Namespace(tick_id=None, strict=False))
    assert store.get_meta(LAST_SCORECARD_HASH_KEY) is None

    # successful push stores it
    ok = _OkMetricsClient()
    monkeypatch.setattr(jc, "JVNClient", lambda: ok)
    cli._cmd_metrics_push(argparse.Namespace(tick_id=None, strict=False))
    assert store.get_meta(LAST_SCORECARD_HASH_KEY) is not None
    assert ok.payloads[0]["scorecard"] == {"n": 252}


# ---------------------------------------------------------------------------
# BF-11 — the two subcategory drift breakers
# ---------------------------------------------------------------------------
from job_enricher.metrics import (  # noqa: E402
    SUBCAT_DRIFT_MIN_SWE,
    subcategory_absent_drift,
    subcategory_empty_drift,
    window_counters,
)


def test_absent_drift_at_the_boundary():
    assert subcategory_absent_drift({"swe_classified": 10, "swe_subcat_evaluated": 0})
    # ⚠ FALSE one below the threshold ...
    assert not subcategory_absent_drift({"swe_classified": 9, "swe_subcat_evaluated": 0})
    # ... and FALSE the moment a single row was evaluated
    assert not subcategory_absent_drift({"swe_classified": 10, "swe_subcat_evaluated": 1})


def test_empty_drift_at_the_boundary():
    assert subcategory_empty_drift(
        {"swe_subcat_evaluated": 10, "swe_subcategorized": 0}
    )
    assert not subcategory_empty_drift(
        {"swe_subcat_evaluated": 9, "swe_subcategorized": 0}
    )
    assert not subcategory_empty_drift(
        {"swe_subcat_evaluated": 10, "swe_subcategorized": 1}
    )


def test_the_two_detectors_are_not_the_same_detector(store):
    """⚠ COVERAGE vs YIELD. A wave that evaluated every SWE row and answered []
    for all of them is INVISIBLE to the absent detector and caught by the empty
    one — the exact blindness the draft's single breaker had."""
    window = {
        "swe_classified": 12, "swe_subcat_evaluated": 12, "swe_subcategorized": 0
    }
    assert subcategory_absent_drift(window) is False
    assert subcategory_empty_drift(window) is True


def test_window_spans_three_ticks(store):
    """⚠ THE COVERAGE-GAP REGRESSION. 4/5/6 SWE rows across three ticks arms the
    breaker where any single one of them would not."""
    for n in (4, 5, 6):
        store.start_tick()
        store.bump_tick_counters(swe_classified=n)
        store.end_tick(status="ok")
    window = window_counters(store)
    assert window["swe_classified"] == 15 >= SUBCAT_DRIFT_MIN_SWE
    assert subcategory_absent_drift(window) is True
    # a one-tick window would be silent on every one of them
    assert subcategory_absent_drift(window_counters(store, n=1)) is False


def test_window_counters_only_looks_back_n_ticks(store):
    for n in (100, 1, 1, 1):
        store.start_tick()
        store.bump_tick_counters(swe_classified=n)
        store.end_tick(status="ok")
    assert window_counters(store, n=3)["swe_classified"] == 3


def test_counters_are_not_silently_dropped(store):
    """⚠ This is what catches a column missing from store._TICK_COUNTER_COLS:
    all three appear in the payload AND reflect real increments asserted on the
    ticks ROW."""
    tid = store.start_tick()
    store.bump_tick_counters(
        classified=12, swe_classified=12, swe_subcat_evaluated=12,
        swe_subcategorized=0,
    )
    store.end_tick(status="ok")
    row = store.get_tick(tid)
    assert (row["swe_classified"], row["swe_subcat_evaluated"]) == (12, 12)
    payload, _ = build_metrics_payload(store)
    for c in ("swe_classified", "swe_subcat_evaluated", "swe_subcategorized"):
        assert c in payload["counters"]
    assert payload["subcategory_empty_drift"] is True
    assert payload["subcategory_absent_drift"] is False
    assert payload["subcategory_window"]["swe_subcat_evaluated"] == 12
