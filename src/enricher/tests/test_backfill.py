"""BF-6 / BF-9 / BF-12b / BF-10 / BF-16 — the backfill lane."""

import json

import pytest

from job_enricher import backfill as bf


# ---------------------------------------------------------------------------
# BF-6 — the trusted-row projection
# ---------------------------------------------------------------------------
class _Row(dict):
    """A stand-in for sqlite3.Row: dict access plus .keys()."""


def _row(**kw):
    base = {
        "job_listing_id": "1", "source_id": "gh", "title": "Backend Engineer",
        "company": "Acme", "tags": '["python", "postgres"]',
    }
    base.update(kw)
    return _Row(base)


def test_chunk_rows_emits_exactly_the_five_trusted_keys():
    out = bf.chunk_rows([_row()])
    assert list(out[0].keys()) == list(bf.CHUNK_ROW_KEYS)
    assert out[0]["tags"] == ["python", "postgres"]


def test_chunk_rows_raises_on_a_row_carrying_clean_description():
    """⚠ THE INJECTION BOUNDARY, MADE STRUCTURAL. The row handed to the prompt
    builder must have nowhere to put a description."""
    with pytest.raises(ValueError) as exc:
        bf.chunk_rows([_row(clean_description="untrusted scraped text")])
    assert "clean_description" in str(exc.value)


def test_chunk_rows_raises_on_a_row_carrying_description_html():
    with pytest.raises(ValueError):
        bf.chunk_rows([_row(description_html="<p>untrusted</p>")])


def test_chunk_rows_output_carries_no_description_substring():
    """The acceptance shape: serialise the projection and prove none of the
    source descriptions survive it."""
    rows = [_row(job_listing_id=str(i)) for i in range(10)]
    out = bf.chunk_rows(rows)
    blob = json.dumps(out)
    assert "SECRET" not in blob
    assert all(set(o) == set(bf.CHUNK_ROW_KEYS) for o in out)


def test_chunk_rows_tolerates_malformed_tags():
    assert bf.chunk_rows([_row(tags="not json")])[0]["tags"] == []
    assert bf.chunk_rows([_row(tags=None)])[0]["tags"] == []
    assert bf.chunk_rows([_row(tags='{"a": 1}')])[0]["tags"] == []
    assert bf.chunk_rows([_row(tags=["a", "b"])])[0]["tags"] == ["a", "b"]


# ---------------------------------------------------------------------------
# BF-6 — echoed-pair matching (the replacement for positional repair)
# ---------------------------------------------------------------------------
def _chunk(n=4):
    return bf.chunk_rows([_row(job_listing_id=str(i)) for i in range(n)])


def _res(jid, sid="gh", slugs=("backend",)):
    return {"job_listing_id": jid, "source_id": sid, "subcategories": list(slugs)}


def test_reversed_order_with_correct_echoes_writes_to_the_right_rows():
    """⚠ The proof that matching is by PAIR and not by position: the same
    reversal a positional implementation would mis-stamp lands correctly here."""
    chunk = _chunk(4)
    results = [_res(str(i), slugs=(f"slug{i}",)) for i in reversed(range(4))]
    matched, stats = bf.match_results_to_chunk(chunk, results)
    assert stats.echo_mismatch == 0
    assert stats.unanswered == 0
    assert len(matched) == 4
    for row, result in matched:
        assert result["subcategories"] == [f"slug{row['job_listing_id']}"]


def test_reversed_batch_without_echoes_matches_nothing():
    """⚠ THE REQUIRED REGRESSION, at the matching layer. Four results in REVERSE
    order with source_id/job_listing_id OMITTED — exactly the shape a
    positional-repair implementation would happily stamp. Nothing matches and
    every result is counted."""
    chunk = _chunk(4)
    results = [{"subcategories": [f"slug{i}"]} for i in reversed(range(4))]
    matched, stats = bf.match_results_to_chunk(chunk, results)
    assert matched == []
    assert stats.echo_mismatch == 4
    assert stats.unanswered == 4


def test_duplicate_echoed_pair_drops_both():
    """⚠ A collapsed pair is not evidence for either row."""
    chunk = _chunk(2)
    results = [_res("0", slugs=("a",)), _res("0", slugs=("b",))]
    matched, stats = bf.match_results_to_chunk(chunk, results)
    assert matched == []
    assert stats.echo_mismatch == 2
    assert stats.unanswered == 2


def test_a_third_repeat_of_a_collapsed_pair_is_also_dropped():
    chunk = _chunk(2)
    results = [_res("0"), _res("0"), _res("0")]
    matched, stats = bf.match_results_to_chunk(chunk, results)
    assert matched == []
    assert stats.echo_mismatch == 3


def test_echo_naming_a_row_outside_the_chunk_is_dropped_and_counted():
    chunk = _chunk(2)
    results = [_res("0"), _res("999")]
    matched, stats = bf.match_results_to_chunk(chunk, results)
    assert [r["job_listing_id"] for r, _ in matched] == ["0"]
    assert stats.echo_mismatch == 1
    assert stats.unanswered == 1


def test_a_right_id_on_the_wrong_source_is_dropped():
    """The composite key is the identity — a bare id match is not enough."""
    chunk = _chunk(2)
    matched, stats = bf.match_results_to_chunk(chunk, [_res("0", sid="lever")])
    assert matched == []
    assert stats.echo_mismatch == 1


@pytest.mark.parametrize("bad", [
    {"job_listing_id": "0", "source_id": "", "subcategories": []},
    {"job_listing_id": "", "source_id": "gh", "subcategories": []},
    {"job_listing_id": "0", "subcategories": []},
    {"source_id": "gh", "subcategories": []},
    {"job_listing_id": 0, "source_id": "gh"},
    "not a dict",
])
def test_a_result_without_two_non_empty_string_ids_is_dropped(bad):
    chunk = _chunk(1)
    matched, stats = bf.match_results_to_chunk(chunk, [bad])
    assert matched == []
    assert stats.echo_mismatch == 1


def test_partial_response_counts_unanswered():
    chunk = _chunk(4)
    matched, stats = bf.match_results_to_chunk(chunk, [_res("0"), _res("2")])
    assert len(matched) == 2
    assert stats.echo_mismatch == 0
    assert stats.unanswered == 2


# ---------------------------------------------------------------------------
# BF-9 — the run loop
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta, timezone  # noqa: E402

from job_enricher import enrich_config as ec  # noqa: E402
from job_enricher.engines.base import EngineError  # noqa: E402
from job_enricher.store import now_iso  # noqa: E402


class _FakeEngine:
    """Returns a scripted result list per call. An Exception item is raised."""

    name = "fake"

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def subcategory(self, rows):
        self.calls.append(rows)
        item = self._script.pop(0) if self._script else []
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(rows)
        return item


def _echo(rows, slugs=("backend",), conf=0.8):
    return [
        {
            "source_id": r["source_id"], "job_listing_id": r["job_listing_id"],
            "subcategories": list(slugs), "subcategory_confidence": conf,
        }
        for r in rows
    ]


def _seed(store, n, *, title="Staff Engineer", tags="[]", prefix="j"):
    """SWE rows the title/tag rule pass CANNOT type, so they reach the model."""
    with store.connect() as c:
        for i in range(n):
            jid = f"{prefix}{i}"
            c.execute(
                "INSERT INTO inbox (job_listing_id, source_id, title, company, "
                "raw_location, content_hash, claimed_at, status, first_seen_at) "
                "VALUES (?, 'gh', ?, 'Acme', 'SF', ?, ?, 'sent', ?)",
                (jid, title, f"h-{jid}", now_iso(), f"2026-08-{(i % 28) + 1:02d}"),
            )
            c.execute(
                "INSERT INTO enrichments (job_listing_id, source_id, category, "
                "tags, enriched_at, sent_at) VALUES (?, 'gh', "
                "'software_engineering', ?, ?, ?)",
                (jid, tags, now_iso(), now_iso()),
            )


def _armed(store):
    ec.set_backfill_enabled(store, True)
    return store


def _sub(store, jid):
    with store.connect() as c:
        return dict(
            c.execute(
                "SELECT * FROM enrichments WHERE job_listing_id = ?", (jid,)
            ).fetchone()
        )


def test_bf9_never_calls_bump_tick_counters_or_writes_chunk_files(store, monkeypatch, tmp_path):
    """⚠ THE LANE-SEPARATION ASSERTION. bump_tick_counters resolves
    current_tick_id() from meta and the live worker restarts 62 s after each tick
    ends, so a tick is almost always OPEN — every counter the backfill bumped
    would be attributed to the LIVE tick and could force a healthy tick to close
    status=error."""
    _armed(store)
    _seed(store, 3)

    def _boom(*a, **kw):
        raise AssertionError("the backfill must NEVER bump tick counters")

    monkeypatch.setattr(type(store), "bump_tick_counters", _boom)
    monkeypatch.setattr(type(store), "start_tick", _boom)
    out = bf.run_backfill(store, _FakeEngine([_echo]), batch=3)
    assert out.status == "ok"
    assert out.counters["model_labelled"] == 3
    assert not (store.db_path.parent / "chunks").exists()


def test_bf9_writes_labels_confidence_source_and_run_id(store):
    _armed(store)
    _seed(store, 2)
    out = bf.run_backfill(store, _FakeEngine([_echo]), batch=2)
    row = _sub(store, "j0")
    assert json.loads(row["subcategories"]) == ["backend"]
    assert row["subcategory_source"] == "backfill"
    assert row["subcategory_confidence"] == 0.8
    assert row["subcategory_run_id"] == out.run_id
    assert store.get_backfill_run(out.run_id)["status"] == "ok"


def test_bf9_the_rule_pass_never_reaches_the_model(store):
    """⚠ Rows the deterministic regex resolves are written at ZERO model cost."""
    _armed(store)
    _seed(store, 2, title="Senior Frontend Engineer", prefix="r")
    engine = _FakeEngine([])
    out = bf.run_backfill(store, engine, batch=5)
    assert engine.calls == []          # the model was never called
    assert out.counters["rule_labelled"] == 2
    assert out.counters["model_calls"] == 0
    assert _sub(store, "r0")["subcategory_source"] == "rule"


def test_bf9_a_deadline_already_past_stops_before_any_model_call(store):
    _armed(store)
    _seed(store, 3)
    engine = _FakeEngine([_echo])
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    out = bf.run_backfill(store, engine, batch=3, deadline=past)
    assert engine.calls == []
    assert out.notes == "deadline"
    assert _sub(store, "j0")["subcategories"] is None
    assert _sub(store, "j0")["subcategory_attempts"] == 0


def test_bf9_enabled_knob_off_stops_at_the_next_chunk_boundary(store):
    ec.set_backfill_enabled(store, False)
    _seed(store, 3)
    engine = _FakeEngine([_echo])
    out = bf.run_backfill(store, engine, batch=3)
    assert engine.calls == []
    assert "backfill:enabled is off" in out.notes


def test_bf9_the_stop_sentinel_stops_at_the_next_chunk_boundary(store, tmp_path):
    _armed(store)
    _seed(store, 3)
    sentinel = tmp_path / "stop"
    sentinel.touch()
    engine = _FakeEngine([_echo])
    out = bf.run_backfill(store, engine, batch=3, stop_path=sentinel)
    assert engine.calls == []
    assert "sentinel" in out.notes


def test_bf9_an_all_empty_run_trips_the_empty_rate_breaker(store):
    """⚠ '[]' is TERMINAL: without this breaker a systematically broken run does
    not error, it quietly removes thousands of rows from the queue permanently."""
    _armed(store)
    _seed(store, 60)
    engine = _FakeEngine([lambda rows: _echo(rows, slugs=(), conf=None)] * 20)
    out = bf.run_backfill(store, engine, batch=10)
    assert out.status == "aborted"
    assert out.aborted_reason == "empty_rate"
    assert out.exit_code != 0
    assert store.get_backfill_run(out.run_id)["aborted_reason"] == "empty_rate"


def test_bf9_five_consecutive_transport_errors_abort_without_bumping_attempts(store):
    """⚠ A rate-limit storm at 02:00 must not retire thousands of good rows at
    the 3-attempt cap."""
    _armed(store)
    _seed(store, 10)
    engine = _FakeEngine([EngineError("claude exited 1")] * 8)
    out = bf.run_backfill(store, engine, batch=2)
    assert out.status == "aborted"
    assert out.aborted_reason == "transport"
    assert out.counters["transport_errors"] == bf.BACKFILL_TRANSPORT_ABORT
    with store.connect() as c:
        assert c.execute(
            "SELECT SUM(subcategory_attempts) AS n FROM enrichments"
        ).fetchone()["n"] == 0


def test_bf9_a_transport_error_streak_resets_on_a_good_chunk(store):
    _armed(store)
    _seed(store, 10)
    engine = _FakeEngine(
        [EngineError("x")] * 4 + [_echo] + [EngineError("x")] * 4 + [_echo] * 5
    )
    out = bf.run_backfill(store, engine, batch=2)
    assert out.status == "ok"


def test_bf9_a_parse_failure_bumps_attempts_and_leaves_the_row_null(store):
    _armed(store)
    _seed(store, 2)
    # results with NO echoed ids — the shape positional repair would mis-stamp
    engine = _FakeEngine([lambda rows: [{"subcategories": ["backend"]}] * len(rows)])
    out = bf.run_backfill(store, engine, batch=2, limit=2)
    assert out.counters["echo_mismatch"] == 2
    assert out.counters["parse_errors"] == 2
    for jid in ("j0", "j1"):
        row = _sub(store, jid)
        assert row["subcategories"] is None
        assert row["subcategory_attempts"] == 1


def test_bf9_reversed_batch_without_echoes_writes_nothing(store, monkeypatch):
    """⚠ THE REQUIRED REGRESSION, end to end. Four rows, four results in REVERSE
    order with the ids OMITTED — exactly what a positional-repair implementation
    would happily stamp. record_subcategories is monkeypatched to RAISE, so any
    write at all fails the test."""
    _armed(store)
    _seed(store, 4)

    def _boom(*a, **kw):
        raise AssertionError("nothing may be written from an unechoed batch")

    monkeypatch.setattr(type(store), "record_subcategories", _boom)
    engine = _FakeEngine(
        [lambda rows: [{"subcategories": [f"s{i}"]} for i in reversed(range(len(rows)))]]
    )
    out = bf.run_backfill(store, engine, batch=4, limit=4)
    assert out.counters["echo_mismatch"] == 4
    for jid in ("j0", "j1", "j2", "j3"):
        row = _sub(store, jid)
        assert row["subcategories"] is None
        assert row["subcategory_attempts"] == 1


def test_bf9_an_echo_mismatch_storm_trips_its_own_breaker(store):
    _armed(store)
    _seed(store, 60)
    engine = _FakeEngine([lambda rows: [{"subcategories": ["backend"]}] * len(rows)] * 20)
    out = bf.run_backfill(store, engine, batch=10)
    assert out.status == "aborted"
    assert out.aborted_reason == "echo_mismatch"
    assert "LOWER" in out.notes


def test_bf9_a_hallucinated_slug_is_dropped_and_the_survivor_recorded(store):
    _armed(store)
    _seed(store, 1)
    engine = _FakeEngine([lambda rows: _echo(rows, slugs=("backend", "ai_ml"))])
    out = bf.run_backfill(store, engine, batch=1, limit=1)
    assert json.loads(_sub(store, "j0")["subcategories"]) == ["backend"]
    assert out.counters["nulled_slugs"] == 1


def test_bf9_an_all_invalid_row_stays_null(store):
    """⚠ NEVER []. An all-invalid row is a FAILURE, and [] is a terminal answer."""
    _armed(store)
    _seed(store, 1)
    engine = _FakeEngine([lambda rows: _echo(rows, slugs=("ai_ml", "nonsense"))])
    out = bf.run_backfill(store, engine, batch=1, limit=1)
    row = _sub(store, "j0")
    assert row["subcategories"] is None
    assert row["subcategory_attempts"] == 1
    assert out.counters["parse_errors"] == 1


def test_bf9_an_explicit_empty_array_is_written_and_counted(store):
    _armed(store)
    _seed(store, 1)
    engine = _FakeEngine([lambda rows: _echo(rows, slugs=(), conf=0.4)])
    out = bf.run_backfill(store, engine, batch=1, limit=1)
    row = _sub(store, "j0")
    assert row["subcategories"] == "[]"
    assert row["subcategory_confidence"] is None
    assert out.counters["empty_labelled"] == 1


def test_bf9_dry_run_writes_zero_rows_zero_ledger_rows_and_a_full_probe(store, tmp_path):
    _seed(store, 4)
    probe = tmp_path / "probe.json"
    out = bf.run_backfill(
        store, _FakeEngine([_echo] * 4), batch=2, limit=4, dry_run=True,
        probe_path=probe,
    )
    assert out.run_id is None
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM backfill_runs").fetchone()["n"] == 0
        assert c.execute(
            "SELECT COUNT(*) AS n FROM enrichments WHERE subcategories IS NOT NULL"
        ).fetchone()["n"] == 0
        assert c.execute(
            "SELECT SUM(subcategory_attempts) AS n FROM enrichments"
        ).fetchone()["n"] == 0
    payload = json.loads(probe.read_text())
    for key in (
        "chunk_latency_s", "seconds_per_row", "rule_pass", "empty_array_rate",
        "invalid_slug_rate", "echo_mismatch_rate", "model_calls", "counters",
        "wall_seconds",
    ):
        assert key in payload, key
    for p in ("p50", "p95", "max"):
        assert p in payload["chunk_latency_s"]
    assert set(payload["rule_pass"]) == {"title_layer", "tag_layer", "total", "yield"}


def test_bf9_dry_run_covers_the_WHOLE_limit_not_just_the_first_chunk(store, tmp_path):
    """⚠ THE SILENT ONE-CHUNK DRY RUN. A dry run writes nothing, so the selector
    keeps handing back the same head of the queue; the run-local `seen` set has to
    make the loop PAGE PAST those rows, not filter them out of the result. Filter
    them and pass 2 comes back empty, the run exits `ok` with "queue exhausted
    (dry-run)" after ONE chunk, and everything downstream reports success on a
    fraction of the work: BF-9's "--dry-run runs the FULL pipeline" (one latency
    sample, so p50 == p95 == max), P0-5's sweep (`batch` rows per cell, not
    `--n`), and the runbook's `--dry-run --limit 20` smoke test."""
    _seed(store, 20)
    probe = tmp_path / "probe.json"
    out = bf.run_backfill(
        store, _FakeEngine([_echo] * 8), batch=5, limit=20, dry_run=True,
        probe_path=probe,
    )
    assert out.counters["selected"] == 20
    assert out.counters["model_labelled"] == 20
    assert out.counters["model_calls"] == 4
    assert out.notes == "limit reached"
    # ⚠ FOUR chunk-latency samples reach the probe, so p50/p95/max are a real
    # distribution and not one sample printed three times.
    assert out.probe["counters"]["selected"] == 20
    assert out.probe["seconds_per_row"] is not None
    # still a dry run: nothing written, no ledger row
    assert out.run_id is None
    with store.connect() as c:
        assert c.execute(
            "SELECT COUNT(*) AS n FROM enrichments WHERE subcategories IS NOT NULL"
        ).fetchone()["n"] == 0


def test_bf9_dry_run_visits_each_row_exactly_once_then_stops(store, tmp_path):
    """The other half: with no --limit the dry run must page to the END of the
    queue and stop there, having handed each row to the model exactly once."""
    _seed(store, 7)
    engine = _FakeEngine([_echo] * 5)
    out = bf.run_backfill(
        store, engine, batch=3, dry_run=True, probe_path=tmp_path / "p.json",
    )
    assert out.counters["selected"] == 7
    assert out.notes == "queue exhausted (dry-run)"
    handed = [
        (r["source_id"], r["job_listing_id"]) for call in engine.calls for r in call
    ]
    assert len(handed) == 7
    assert len(set(handed)) == 7


def test_bf9_dry_run_ignores_the_enabled_knob(store, tmp_path):
    """The runbook's pre-flight smoke test runs BEFORE the knob is armed."""
    ec.set_backfill_enabled(store, False)
    _seed(store, 2)
    out = bf.run_backfill(
        store, _FakeEngine([_echo]), batch=2, dry_run=True,
        probe_path=tmp_path / "p.json",
    )
    assert out.counters["model_calls"] == 1


def test_bf9_open_only_refuses_rather_than_silently_labelling_nothing(store):
    _armed(store)
    _seed(store, 2)
    from job_enricher.store import ScopeUnavailableError
    with pytest.raises(ScopeUnavailableError):
        bf.run_backfill(store, _FakeEngine([_echo]), batch=2, open_only=True)


def test_bf9_resumes_exactly_where_it_stopped(store):
    """⚠ RESUMABILITY IS NOTHING TO IMPLEMENT: unreached rows are still NULL with
    attempts unchanged, so there is no checkpoint and no double-labelling."""
    _armed(store)
    _seed(store, 6)
    bf.run_backfill(store, _FakeEngine([_echo] * 3), batch=2, limit=2)
    with store.connect() as c:
        first = c.execute(
            "SELECT COUNT(*) AS n FROM enrichments WHERE subcategories IS NOT NULL"
        ).fetchone()["n"]
    assert first == 2
    bf.run_backfill(store, _FakeEngine([_echo] * 3), batch=2)
    with store.connect() as c:
        assert c.execute(
            "SELECT COUNT(*) AS n FROM enrichments WHERE subcategories IS NOT NULL"
        ).fetchone()["n"] == 6
        # every row written exactly ONCE
        assert c.execute(
            "SELECT MAX(subcategory_attempts) AS n FROM enrichments"
        ).fetchone()["n"] == 1


# ---------------------------------------------------------------------------
# BF-14 — the reset command's guard
# ---------------------------------------------------------------------------
import argparse  # noqa: E402

from job_enricher import cli  # noqa: E402


def _reset_args(**kw):
    base = dict(run_id=None, source=None, category=None, dry_run=False,
                yes_i_mean_all=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_bf14_cli_prints_the_count_first_and_names_the_pushed_rows(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Store", lambda: store)
    _armed(store)
    _seed(store, 3)
    out = bf.run_backfill(store, _FakeEngine([_echo]), batch=3)
    with store.connect() as c:
        c.execute("UPDATE enrichments SET subcategory_sent_at='2026-08-20T00:00:00' "
                  "WHERE job_listing_id='j0'")
    rc = cli._cmd_subcategory_reset(_reset_args(run_id=out.run_id, dry_run=True))
    printed = capsys.readouterr().out
    assert rc == 0
    assert "3 rows match" in printed
    assert "1 of them were ALREADY PUSHED" in printed
    assert "ADM-15" in printed
    # dry run mutated nothing
    assert _sub(store, "j0")["subcategories"] is not None


def test_bf14_cli_refuses_above_the_threshold_without_the_flag(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(cli, "RESET_CONFIRM_THRESHOLD", 2)
    _armed(store)
    _seed(store, 3)
    bf.run_backfill(store, _FakeEngine([_echo]), batch=3)
    assert cli._cmd_subcategory_reset(_reset_args()) == 2
    assert "REFUSING" in capsys.readouterr().err
    assert _sub(store, "j0")["subcategories"] is not None
    assert cli._cmd_subcategory_reset(_reset_args(yes_i_mean_all=True)) == 0
    assert _sub(store, "j0")["subcategories"] is None


def test_bf14_default_source_covers_the_runs_RULE_PASS_rows_too(store, monkeypatch, capsys):
    """⚠ ONE RUN WRITES TWO SOURCES. The free title/tag pass writes
    `source='rule'` and the model pass writes `source='backfill'`, both stamped
    with the SAME run_id. A `--source` default of 'backfill' alone would make the
    runbook's `subcategory-reset --run-id <N>` report success while leaving every
    rule-pass row of that run labelled — non-NULL, `attempts` un-zeroed, and
    permanently out of `rows_needing_subcategory`."""
    monkeypatch.setattr(cli, "Store", lambda: store)
    _armed(store)
    _seed(store, 3, title="Backend Engineer", prefix="r")   # the rule pass types these
    _seed(store, 2, title="Staff Engineer", prefix="m")     # these reach the model
    out = bf.run_backfill(store, _FakeEngine([_echo]), batch=5)
    assert out.counters["rule_labelled"] == 3
    assert out.counters["model_labelled"] == 2
    assert _sub(store, "r0")["subcategory_source"] == "rule"

    assert cli._cmd_subcategory_reset(_reset_args(run_id=out.run_id, dry_run=True)) == 0
    assert "5 rows match" in capsys.readouterr().out

    assert cli._cmd_subcategory_reset(_reset_args(run_id=out.run_id)) == 0
    for jid in ("r0", "r1", "r2", "m0", "m1"):
        row = _sub(store, jid)
        assert row["subcategories"] is None, jid
        assert row["subcategory_attempts"] == 0, jid
    # and they are genuinely back in the queue
    assert len(store.rows_needing_subcategory()) == 5


def test_bf14_naming_the_source_still_scopes_to_exactly_that_lane(store, monkeypatch, capsys):
    """The narrow form stays available — it is only the DEFAULT that widens."""
    monkeypatch.setattr(cli, "Store", lambda: store)
    _armed(store)
    _seed(store, 3, title="Backend Engineer", prefix="r")
    _seed(store, 2, title="Staff Engineer", prefix="m")
    out = bf.run_backfill(store, _FakeEngine([_echo]), batch=5)
    rc = cli._cmd_subcategory_reset(
        _reset_args(run_id=out.run_id, source="backfill", dry_run=True)
    )
    assert rc == 0
    assert "2 rows match" in capsys.readouterr().out


def test_bf14_cli_source_all_never_reaches_human_or_judge():
    assert "human" not in cli.RESET_SOURCE_CHOICES
    assert "judge" not in cli.RESET_SOURCE_CHOICES
    assert set(cli._RESET_ALL_SOURCES) == {"rule", "backfill", "classify"}


# ---------------------------------------------------------------------------
# BF-16 — the write-back cost probe
# ---------------------------------------------------------------------------
class _ProbeClient:
    """Records every call with a monotonic (start, end) so the test can assert
    the requests never overlap."""

    def __init__(self, ping_s=0.1, req_s=1.0):
        self.ping_s, self.req_s = ping_s, req_s
        self.posts, self.pings, self.spans = [], 0, []
        self._t = 0.0

    def clock(self):
        return self._t

    def get_health(self):
        self.pings += 1
        start = self._t
        self._t += self.ping_s
        self.spans.append((start, self._t))
        return {"ok": True}

    def post_subcategories(self, items):
        self.posts.append(list(items))
        start = self._t
        self._t += self.req_s
        self.spans.append((start, self._t))
        return {"written": len(items), "skipped": [], "failed": [], "warnings": []}


def _pushable(store, n):
    _seed(store, n, prefix="p")
    run = store.start_backfill_run(kind="label", taxonomy_version="v7+deadbeef1234")
    for i in range(n):
        store.record_subcategories("gh", f"p{i}", ["backend"], 0.8, "backfill",
                                   run_id=run)
    return run


def test_bf16_probe_issues_exactly_the_expected_calls_and_never_overlaps(store):
    _pushable(store, 60)
    client = _ProbeClient()
    report = bf.push_probe(
        store, client, batches=2, sizes=(50,), timer=client.clock
    )
    assert client.pings == 2
    assert len(client.posts) == 2 * 1
    # ⚠ strictly sequential: no span starts before the previous one ended
    for (s0, e0), (s1, _e1) in zip(client.spans, client.spans[1:]):
        assert s1 >= e0
    assert report["cells"]["50"]["n"] == 50
    assert report["cells"]["50"]["bytes"] > 0


def test_bf16_slot_hold_is_t_req_p95_minus_t_ping_p50(store):
    _pushable(store, 10)
    client = _ProbeClient(ping_s=0.25, req_s=2.0)
    report = bf.push_probe(store, client, batches=3, sizes=(10,), timer=client.clock)
    assert report["t_ping_p50"] == pytest.approx(0.25)
    assert report["cells"]["10"]["t_req_p95"] == pytest.approx(2.0)
    assert report["cells"]["10"]["slot_hold_p95"] == pytest.approx(1.75)


def test_bf16_derived_pace_matches_the_formula():
    d = bf.derive_pace(slot_hold_p95=2.0, batch=250, duty_pct=25, pending_push=9000)
    # sleep = S_p95 * (100/duty - 1)
    assert d["sleep_between_batches"] == pytest.approx(6.0)
    # rows_per_hour = 3600 * B * (duty/100) / S_p95
    assert d["rows_per_hour"] == pytest.approx(112500.0)
    assert d["eta_hours"] == pytest.approx(round(9000 / 112500.0, 2))


def test_bf16_chooses_the_largest_batch_under_the_slot_hold_ceiling():
    cells = {
        "50": {"slot_hold_p95": 0.4}, "100": {"slot_hold_p95": 1.2},
        "250": {"slot_hold_p95": 4.9}, "500": {"slot_hold_p95": 7.1},
    }
    assert bf.choose_push_batch(cells) == 250
    assert bf.choose_push_batch({"500": {"slot_hold_p95": 9.9}}) is None


def test_bf16_push_http_timeout_is_three_x_p95_with_a_30s_floor():
    assert bf.push_http_timeout_s(None) == 30.0
    assert bf.push_http_timeout_s(2.0) == 30.0          # floor wins
    assert bf.push_http_timeout_s(20.0) == 60.0


def test_bf16_a_probe_run_stamps_nothing_locally(store):
    """⚠ It is a MEASUREMENT, not a push — subcategory_sent_at is untouched."""
    _pushable(store, 10)
    client = _ProbeClient()
    bf.push_probe(store, client, batches=1, sizes=(10,), timer=client.clock)
    with store.connect() as c:
        assert c.execute(
            "SELECT COUNT(*) AS n FROM enrichments WHERE subcategory_sent_at IS NOT NULL"
        ).fetchone()["n"] == 0


def test_bf16_push_item_is_exactly_the_six_slim_keys(store):
    """⚠ SCHEMA-14 is extra='forbid' — a seventh key 422s the whole batch."""
    _pushable(store, 1)
    row = store.rows_needing_subcategory_push()[0]
    item = bf.push_item(row)
    assert set(item) == bf.PUSH_ITEM_KEYS
    assert item["subcategories"] == ["backend"]
    # the RUN's taxonomy_version, not the row's classify-time one
    assert item["taxonomy_version"] == "v7+deadbeef1234"


def test_bf16_the_probe_cell_is_marked_when_no_local_rows_exist(store):
    client = _ProbeClient()
    report = bf.push_probe(store, client, batches=1, sizes=(50,), timer=client.clock)
    assert report["cells"]["50"]["n"] == 0
    assert client.posts == []


# ---------------------------------------------------------------------------
# BF-12b — the throttled drain
# ---------------------------------------------------------------------------
import httpx  # noqa: E402


class _PushClient:
    """Scripted responses. An Exception item is raised; a dict is returned."""

    def __init__(self, script=None):
        self._script = list(script or [])
        self.payloads = []
        self.spans = []
        self._t = 0.0

    def clock(self):
        return self._t

    def post_subcategories(self, items):
        self.payloads.append(list(items))
        start = self._t
        self._t += 1.0
        self.spans.append((start, self._t))
        item = self._script.pop(0) if self._script else None
        if isinstance(item, Exception):
            raise item
        return item or {"written": len(items), "skipped": [], "failed": [],
                        "warnings": []}


def _sleeper():
    slept = []
    def _s(seconds):
        slept.append(seconds)
    return slept, _s


def _http_error(status, body=""):
    request = httpx.Request("POST", "http://x/api/internal/enrichment/subcategories")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def _drain_ready(store, n, *, knob=True):
    if knob:
        ec.set_writeback_send_subcategories(store, True)
    return _pushable(store, n)


def test_bf12b_refuses_with_exit_2_when_the_knob_is_off(store):
    """⚠ Draining while JVN is not accepting the facet would stamp the cursor on
    rows nothing received."""
    _drain_ready(store, 5, knob=False)
    client = _PushClient()
    out = bf.push_subcategories(store, client, printer=lambda *_: None)
    assert out.exit_code == 2
    assert out.status == "refused"
    assert client.payloads == []


def test_bf12b_the_payload_is_exactly_the_six_slim_keys(store):
    _drain_ready(store, 3)
    client = _PushClient()
    _, s = _sleeper()
    bf.push_subcategories(store, client, batch=3, limit=3, sleep=s,
                          timer=client.clock, printer=lambda *_: None)
    assert len(client.payloads) == 1
    for item in client.payloads[0]:
        # ⚠ a seventh key would 422 the whole batch against extra='forbid'
        assert set(item) == bf.PUSH_ITEM_KEYS


def test_bf12b_stamps_the_cursor_and_never_sent_at_or_inbox_status(store):
    _drain_ready(store, 3)
    with store.connect() as c:
        before = {
            r["job_listing_id"]: (r["sent_at"], r["status"]) for r in c.execute(
                "SELECT e.job_listing_id, e.sent_at, i.status FROM enrichments e "
                "JOIN inbox i ON i.job_listing_id = e.job_listing_id"
            ).fetchall()
        }
    _, s = _sleeper()
    out = bf.push_subcategories(store, _PushClient(), batch=3, limit=3, sleep=s,
                                printer=lambda *_: None)
    assert out.counters["pushed"] == 3
    with store.connect() as c:
        for r in c.execute(
            "SELECT e.job_listing_id, e.sent_at, e.subcategory_sent_at, i.status "
            "FROM enrichments e JOIN inbox i "
            "ON i.job_listing_id = e.job_listing_id"
        ).fetchall():
            assert r["subcategory_sent_at"] is not None
            assert (r["sent_at"], r["status"]) == before[r["job_listing_id"]]


def test_bf12b_the_two_lanes_are_disjoint_by_construction(store):
    """⚠ For a fixture covering every combination, NO row is returned by BOTH
    enriched_unsent() and rows_needing_subcategory_push()."""
    ec.set_writeback_send_subcategories(store, True)
    _seed(store, 4, prefix="d")
    run = store.start_backfill_run(kind="label")
    # d0: labelled + sent            -> the drain's lane
    store.record_subcategories("gh", "d0", ["backend"], 0.8, "backfill", run_id=run)
    # d1: labelled + NOT sent        -> the live write-back's lane
    store.record_subcategories("gh", "d1", ["backend"], 0.8, "backfill", run_id=run)
    with store.connect() as c:
        c.execute("UPDATE enrichments SET sent_at = NULL WHERE job_listing_id='d1'")
        # d2: labelled + sent + already drained -> neither
        c.execute("UPDATE enrichments SET subcategory_sent_at='2026-08-20T00:00:00' "
                  "WHERE job_listing_id='d2'")
    store.record_subcategories("gh", "d2", ["backend"], 0.8, "backfill", run_id=run)
    with store.connect() as c:
        c.execute("UPDATE enrichments SET subcategory_sent_at='2026-08-20T00:00:00' "
                  "WHERE job_listing_id='d2'")
    # d3: never labelled + sent      -> neither
    live = {(r["source_id"], r["job_listing_id"]) for r in store.enriched_unsent()}
    drain = {
        (r["source_id"], r["job_listing_id"])
        for r in store.rows_needing_subcategory_push()
    }
    assert live & drain == set()
    assert ("gh", "d0") in drain and ("gh", "d1") in live
    assert ("gh", "d2") not in drain and ("gh", "d2") not in live


def test_bf12b_a_stamped_row_is_never_reselected(store):
    _drain_ready(store, 4)
    _, s = _sleeper()
    bf.push_subcategories(store, _PushClient(), batch=2, limit=2, sleep=s,
                          printer=lambda *_: None)
    remaining = {r["job_listing_id"] for r in store.rows_needing_subcategory_push()}
    assert len(remaining) == 2
    bf.push_subcategories(store, _PushClient(), batch=2, sleep=s,
                          printer=lambda *_: None)
    assert store.rows_needing_subcategory_push() == []


def test_bf12b_requests_are_strictly_sequential(store):
    _drain_ready(store, 6)
    _, s = _sleeper()
    client = _PushClient()
    bf.push_subcategories(store, client, batch=2, sleep=s, timer=client.clock,
                          printer=lambda *_: None)
    for (s0, e0), (s1, _e1) in zip(client.spans, client.spans[1:]):
        assert s1 >= e0


def test_bf12b_a_429_doubles_the_sleep_and_it_decays_after_clean_batches(store):
    _drain_ready(store, 8)
    slept, s = _sleeper()
    client = _PushClient([_http_error(429), None, None, None, None])
    out = bf.push_subcategories(
        store, client, batch=2, duty_pct=50, slot_hold_p95=2.0, sleep=s,
        printer=lambda *_: None,
    )
    assert out.status == "ok"
    # base sleep = 2.0 * (100/50 - 1) = 2.0; the 429 doubled it above base ...
    assert max(slept) > 2.0
    # ... and it decayed back toward base by the end
    assert out.effective_sleep == pytest.approx(2.0)


def test_bf12b_the_sleep_never_exceeds_the_cap(store):
    _drain_ready(store, 4)
    slept, s = _sleeper()
    client = _PushClient([_http_error(503)] * 12)
    bf.push_subcategories(store, client, batch=2, slot_hold_p95=40.0, duty_pct=1,
                          sleep=s, printer=lambda *_: None)
    assert all(x <= max(bf.PUSH_MAX_SLEEP, 40.0 * 99) for x in slept)


def test_bf12b_three_pool_pressure_responses_abort(store):
    """⚠ THE NAMED HONOURING of docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md."""
    _drain_ready(store, 20)
    _, s = _sleeper()
    body = f"500: RuntimeError('{bf.PUSH_POOL_PRESSURE_STRING}')"
    client = _PushClient([_http_error(503, body)] * 9)
    out = bf.push_subcategories(store, client, batch=2, sleep=s,
                                printer=lambda *_: None)
    assert out.status == "aborted"
    assert out.aborted_reason == "pool_pressure"
    assert out.exit_code != 0
    assert out.counters["pool_pressure_events"] == bf.PUSH_POOL_ABORT
    assert "Do NOT raise duty_pct" in out.notes


def test_bf12b_a_413_aborts_immediately_without_retrying(store):
    _drain_ready(store, 6)
    _, s = _sleeper()
    client = _PushClient([_http_error(413)])
    out = bf.push_subcategories(store, client, batch=2, sleep=s,
                                printer=lambda *_: None)
    assert out.status == "aborted"
    assert out.aborted_reason == "http_error"
    assert len(client.payloads) == 1     # NOT retried


def test_bf12b_a_client_timeout_waits_the_cooldown(store):
    _drain_ready(store, 4)
    slept, s = _sleeper()
    client = _PushClient([httpx.TimeoutException("read timeout")])
    bf.push_subcategories(store, client, batch=2, limit=2, sleep=s,
                          printer=lambda *_: None)
    assert bf.PUSH_TIMEOUT_COOLDOWN in slept


def test_bf12b_a_failed_entry_leaves_that_row_unstamped(store):
    _drain_ready(store, 2)
    _, s = _sleeper()
    client = _PushClient([{
        "written": 1, "skipped": [], "warnings": [],
        "failed": [{"source_id": "gh", "job_listing_id": "p0", "error": "x"}],
    }])
    out = bf.push_subcategories(store, client, batch=2, limit=2, sleep=s,
                                printer=lambda *_: None)
    assert out.counters["push_rejected"] == 1
    with store.connect() as c:
        assert c.execute(
            "SELECT subcategory_sent_at FROM enrichments WHERE job_listing_id='p0'"
        ).fetchone()["subcategory_sent_at"] is None
        assert c.execute(
            "SELECT subcategory_sent_at FROM enrichments WHERE job_listing_id='p1'"
        ).fetchone()["subcategory_sent_at"] is not None


def test_bf12b_a_human_lock_skip_DOES_stamp_the_row(store):
    """⚠ The human lock is TERMINAL, not a retryable failure — an unstamped row
    would be re-pushed forever against a row JVN will never accept."""
    _drain_ready(store, 2)
    _, s = _sleeper()
    client = _PushClient([{
        "written": 2, "failed": [], "warnings": [],
        "skipped": [{"source_id": "gh", "job_listing_id": "p0",
                     "reason": "human-corrected"}],
    }])
    out = bf.push_subcategories(store, client, batch=2, limit=2, sleep=s,
                                printer=lambda *_: None)
    assert out.counters["push_skipped_human"] == 1
    assert out.counters["pushed"] == 1
    with store.connect() as c:
        assert c.execute(
            "SELECT subcategory_sent_at FROM enrichments WHERE job_listing_id='p0'"
        ).fetchone()["subcategory_sent_at"] is not None


def test_bf12b_a_nulled_warning_is_counted_as_a_parity_break(store):
    _drain_ready(store, 2)
    _, s = _sleeper()
    client = _PushClient([{
        "written": 2, "failed": [], "skipped": [],
        "warnings": [{"source_id": "gh", "job_listing_id": "p0",
                      "warnings": ["subcategories nulled: unknown slug"]}],
    }])
    out = bf.push_subcategories(store, client, batch=2, limit=2, sleep=s,
                                printer=lambda *_: None)
    assert out.counters["push_nulled_by_jvn"] == 1


def test_bf12b_prints_the_eta_before_the_first_post(store):
    _drain_ready(store, 4)
    lines = []
    _, s = _sleeper()
    client = _PushClient()

    def _printer(msg):
        # ⚠ the ETA must be printed BEFORE any request goes out
        assert client.payloads == []
        lines.append(msg)

    bf.push_subcategories(store, client, batch=4, limit=4, duty_pct=25,
                          slot_hold_p95=2.0, sleep=s, printer=_printer)
    assert any("ETA=" in line and "pending_push=" in line for line in lines)


def test_bf12b_the_stop_sentinel_stops_at_the_next_batch_boundary(store, tmp_path):
    _drain_ready(store, 6)
    sentinel = tmp_path / "stop"
    sentinel.touch()
    _, s = _sleeper()
    client = _PushClient()
    out = bf.push_subcategories(store, client, batch=2, sleep=s,
                                stop_path=sentinel, printer=lambda *_: None)
    assert client.payloads == []
    assert "sentinel" in out.notes


def test_bf12b_opens_a_push_kind_ledger_row(store):
    _drain_ready(store, 2)
    _, s = _sleeper()
    out = bf.push_subcategories(store, _PushClient(), batch=2, limit=2, sleep=s,
                                printer=lambda *_: None)
    row = store.get_backfill_run(out.run_id)
    assert row["kind"] == "push"
    assert row["pushed"] == 2
    assert store.latest_backfill_run(kind="push")["id"] == out.run_id


def test_bf12b_has_no_concurrency_flag_or_knob():
    parser = cli.build_parser()
    sub = parser._subparsers._group_actions[0].choices["subcategory-push"]
    assert "--concurrency" not in {o for a in sub._actions for o in a.option_strings}
    assert not any("concurrency" in k for k in ec.KNOB_META_KEYS)


def test_bf12b_second_invocation_exits_75(store, monkeypatch, capsys):
    import job_enricher.lock as lock_mod

    monkeypatch.setattr(cli, "Store", lambda: store)
    assert lock_mod.try_acquire(
        store.db_path.parent / bf.PUSH_LOCK_NAME, stale_after_hours=6
    )[0]
    rc = cli._cmd_subcategory_push(argparse.Namespace(
        limit=1, batch=1, duty=None, max_seconds=None, dry_run=False, notify=False,
        probe=None, slot_hold=None,
    ))
    assert rc == 75
    assert "skipped" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# BF-10 — the morning report
# ---------------------------------------------------------------------------
def test_bf10_renders_every_label_field_from_a_hand_built_ledger_row(store):
    run = store.start_backfill_run(kind="label", taxonomy_version="v7+aaa",
                                   rubric_version="rub")
    store.bump_backfill_counters(
        run, selected=100, rule_labelled=10, tag_labelled=5, model_labelled=60,
        empty_labelled=20, retired=3, transport_errors=1, parse_errors=2,
        echo_mismatch=4, unanswered=1, model_calls=9,
    )
    store.end_backfill_run(run, "ok")
    report = bf.build_report(store, kind="label")
    lab = report["label"]
    assert lab["labelled"] == {"rule_title": 10, "rule_tag": 5, "model": 60,
                               "empty": 20}
    assert lab["selected"] == 100
    assert lab["retired_at_cap"] == 3
    assert lab["errors"] == {"transport": 1, "parse": 2, "echo_mismatch": 4,
                             "unanswered": 1}
    assert lab["model_calls"] == 9
    assert lab["taxonomy_version"] == "v7+aaa"
    assert lab["rubric_version"] == "rub"


def test_bf10_an_aborted_run_surfaces_its_reason_in_the_FIRST_line(store):
    run = store.start_backfill_run(kind="label")
    store.end_backfill_run(run, "aborted", aborted_reason="empty_rate")
    text = bf.render_report(bf.build_report(store, kind="label"))
    assert text.splitlines()[0].startswith("⚠ LABEL RUN")
    assert "empty_rate" in text.splitlines()[0]


def test_bf10_echo_mismatch_gets_its_own_named_line_with_the_remedy(store):
    """⚠ It must not be buried inside 'errors': a non-zero echo-mismatch means
    the batch size is too high and the fix is a KNOB, not a rerun."""
    run = store.start_backfill_run(kind="label")
    store.bump_backfill_counters(run, echo_mismatch=7, parse_errors=1)
    store.end_backfill_run(run, "ok")
    text = bf.render_report(bf.build_report(store, kind="label"))
    line = next(line for line in text.splitlines() if "echo_mismatch=7" in line)
    assert "LOWER" in line and "--batch" in line


def test_bf10_renders_the_push_lane_and_the_effective_sleep(store):
    run = store.start_backfill_run(kind="push")
    store.bump_backfill_counters(
        run, pushed=180, push_batches=2, push_rejected=5, push_skipped_human=15,
        push_nulled_by_jvn=0, pool_pressure_events=1,
    )
    store.end_backfill_run(run, "ok", notes="effective_sleep=48.0s")
    text = bf.render_report(bf.build_report(store, kind="push"))
    assert "pushed=180" in text
    assert "skipped_human=15" in text
    assert "effective_sleep=48.0s" in text


def test_bf10_push_nulled_by_jvn_emits_the_parity_warning(store):
    run = store.start_backfill_run(kind="push")
    store.bump_backfill_counters(run, push_nulled_by_jvn=3)
    store.end_backfill_run(run, "ok")
    report = bf.build_report(store, kind="push")
    assert any("PARITY IS BROKEN" in w for w in report["warnings"])
    assert "parity-check" in bf.render_report(report)


def test_bf10_the_reconciliation_arithmetic_on_known_counts(store):
    _seed(store, 10, prefix="rc")
    run = store.start_backfill_run(kind="label")
    for i in range(4):
        store.record_subcategories("gh", f"rc{i}", ["backend"], 0.8, "backfill",
                                   run_id=run)
    for i in range(4, 6):
        store.record_subcategories("gh", f"rc{i}", [], None, "backfill", run_id=run)
    store.mark_subcategory_sent([("gh", "rc0"), ("gh", "rc1"), ("gh", "rc2")])
    store.end_backfill_run(run, "ok")
    rec = bf.build_report(store)["reconciliation"]
    # 4 labelled + 2 empty of 10 SWE rows
    assert rec["local_coverage_pct"] == 60.0
    # 3 of 10 have actually shipped
    assert rec["shipped_coverage_pct"] == 30.0
    assert rec["pending_push"] == 3
    assert "JVN is behind" in rec["which_side_is_behind"]


def test_bf10_collect_health_carries_the_block_on_a_db_with_no_run_at_all(store):
    from job_enricher.health import collect_health

    block = collect_health(store)["subcategory"]
    assert block["last_label_run"] is None and block["last_push_run"] is None
    assert block["total_swe"] == 0
    assert block["local_coverage_pct"] is None


def test_bf10_collect_health_matches_the_report(store):
    from job_enricher.health import collect_health

    _seed(store, 4, prefix="h")
    run = store.start_backfill_run(kind="label")
    store.record_subcategories("gh", "h0", ["backend"], 0.8, "backfill", run_id=run)
    store.mark_subcategory_sent([("gh", "h0")])
    store.end_backfill_run(run, "ok")
    block = collect_health(store)["subcategory"]
    rec = bf.build_report(store)["reconciliation"]
    assert block["shipped_coverage_pct"] == rec["shipped_coverage_pct"]
    assert block["local_coverage_pct"] == rec["local_coverage_pct"]
    assert block["last_label_run"]["id"] == run


def test_bf10_cli_writes_the_artifact_and_json_parses(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Store", lambda: store)
    run = store.start_backfill_run(kind="label")
    store.end_backfill_run(run, "ok")
    rc = cli._cmd_subcategory_report(argparse.Namespace(
        run_id=None, kind="label", json=True, notify=False))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.split("  (written to")[0])
    assert payload["label"]["run_id"] == run
    assert (store.db_path.parent / f"backfill-report-{run}.json").exists()


# ---------------------------------------------------------------------------
# BF-10 — `retired` comes from the PRODUCTION path, not a hand-written row
# ---------------------------------------------------------------------------
def _attempts(store, jid, n):
    with store.connect() as c:
        c.execute(
            "UPDATE enrichments SET subcategory_attempts = ? "
            "WHERE job_listing_id = ?", (n, jid),
        )


def test_bf10_a_run_that_spends_a_rows_last_attempt_increments_retired(store):
    """⚠ THE COUNTER MUST BE BUMPED BY `run_backfill`. Hand-writing `retired=3`
    into the ledger only proves the renderer can read a column; it never touches
    the production path, and with nothing in src/ bumping it the morning report
    printed `retired at the attempts cap: 0` forever."""
    _armed(store)
    _seed(store, 2)
    _attempts(store, "j0", 2)          # one attempt left, at max_attempts=3
    _attempts(store, "j1", 0)          # three left
    # the model answers NEITHER row: both take the PARSE-FAILURE disposition
    engine = _FakeEngine([lambda rows: []])
    out = bf.run_backfill(store, engine, batch=2, limit=2)
    assert out.counters["parse_errors"] == 2
    # ⚠ ONE, not two: only j0's bump reached the cap.
    assert out.counters["retired"] == 1
    assert store.get_backfill_run(out.run_id)["retired"] == 1
    report = bf.build_report(store, kind="label")
    assert report["label"]["retired_at_cap"] == 1
    assert "retired at the attempts cap: 1" in bf.render_report(report)


def test_bf10_the_all_invalid_slug_disposition_also_retires_at_the_cap(store):
    """The second failure site: every slug rejected is a FAILURE, not a `[]`."""
    _armed(store)
    _seed(store, 1)
    _attempts(store, "j0", 2)
    engine = _FakeEngine([lambda rows: _echo(rows, slugs=("not_a_real_slug",))])
    out = bf.run_backfill(store, engine, batch=1, limit=1)
    assert out.counters["parse_errors"] == 1
    assert out.counters["retired"] == 1


def test_bf10_a_row_with_attempts_to_spare_is_not_counted_retired(store):
    _armed(store)
    _seed(store, 3)
    engine = _FakeEngine([lambda rows: []])
    out = bf.run_backfill(store, engine, batch=3, limit=3)
    assert out.counters["parse_errors"] == 3
    assert out.counters["retired"] == 0


def test_bf10_a_transport_abort_retires_nothing(store):
    """⚠ Transport failures do NOT bump attempts, so they cannot retire a row —
    that is the whole reason for the error taxonomy."""
    _armed(store)
    _seed(store, 1)
    _attempts(store, "j0", 2)
    engine = _FakeEngine([EngineError("claude exited 1")] * 8)
    out = bf.run_backfill(store, engine, batch=1)
    assert out.aborted_reason == "transport"
    assert out.counters["retired"] == 0


# ---------------------------------------------------------------------------
# P0-5 — the probe carries the per-row labels the agreement half needs
# ---------------------------------------------------------------------------
def test_p05_the_dry_run_probe_emits_per_row_model_labels(store):
    _armed(store)
    _seed(store, 3)
    engine = _FakeEngine([lambda rows: _echo(rows, slugs=("backend",))])
    out = bf.run_backfill(store, engine, batch=3, limit=3, dry_run=True)
    labels = out.probe["row_labels"]
    # the selector orders newest-first, so this is j2, j1, j0 — the point is
    # that the order is DETERMINISTIC and identical across tiers.
    assert [e["job_listing_id"] for e in labels] == ["j2", "j1", "j0"]
    assert all(e["source"] == "model" and e["slugs"] == ["backend"] for e in labels)
    assert out.probe["row_labels_truncated"] is False


def test_p05_rule_labelled_rows_are_tagged_as_rule_not_model(store):
    """⚠ The rule pass is DETERMINISTIC and tier-independent. Mislabelling those
    rows `model` would inflate haiku-vs-sonnet agreement toward 100% on rows no
    model ever saw."""
    _armed(store)
    _seed(store, 1, title="Backend Engineer")
    out = bf.run_backfill(store, _FakeEngine([]), batch=1, limit=1, dry_run=True)
    assert [e["source"] for e in out.probe["row_labels"]] == ["rule"]


# ---------------------------------------------------------------------------
# BF-12b — the shipped CLI path reaches BF-16's measurement
# ---------------------------------------------------------------------------
def _probe_file(tmp_path, *, hold=0.4, batch=250, t_req=0.5):
    path = tmp_path / "subcategory-push-probe-2026-08-20T00-00-00.json"
    path.write_text(json.dumps({
        "measured_at": "2026-08-20T00:00:00+00:00",
        "chosen_batch": batch,
        "cells": {str(batch): {"slot_hold_p95": hold, "t_req_p95": t_req}},
    }), encoding="utf-8")
    return path


def _push_args(**kw):
    base = dict(limit=0, batch=250, duty=25, max_seconds=None, dry_run=True,
                notify=False, probe=None, slot_hold=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_bf12b_the_cli_derives_the_pace_from_the_probes_measured_s_p95(
    store, monkeypatch, tmp_path, capsys
):
    """⚠ THE SEAM THE RUNBOOK WALKS THROUGH. Run the probe, fill in the table,
    run the push — and before this flag the ETA came from the UNMEASURED 5.0 s
    placeholder regardless of what was measured."""
    monkeypatch.setattr(cli, "Store", lambda: store)
    ec.set_writeback_send_subcategories(store, True)
    rc = cli._cmd_subcategory_push(
        _push_args(probe=str(_probe_file(tmp_path, hold=0.4)))
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "measured S_p95=0.4s at B=250" in out
    # sleep = 0.4 * (100/25 - 1) = 1.2s, NOT 5.0 * 3 = 15.0s
    assert "sleep=1.2s" in out
    # 3600 * 250 * 0.25 / 0.4
    assert "rows_per_hour=562500.0" in out
    assert "UNMEASURED" not in out


def test_bf12b_slot_hold_flag_overrides_the_probe_cell(
    store, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(cli, "Store", lambda: store)
    ec.set_writeback_send_subcategories(store, True)
    cli._cmd_subcategory_push(
        _push_args(probe=str(_probe_file(tmp_path, hold=0.4)), slot_hold=2.0)
    )
    assert "sleep=6.0s" in capsys.readouterr().out


def test_bf12b_without_a_measurement_the_printed_eta_says_so_loudly(
    store, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "Store", lambda: store)
    ec.set_writeback_send_subcategories(store, True)
    cli._cmd_subcategory_push(_push_args())
    out = capsys.readouterr().out
    assert "UNMEASURED PUSH_SLOT_HOLD_CEILING_S=5.0s placeholder" in out
    assert "THE SLEEP, ROWS/HOUR AND ETA ABOVE ARE NOT MEASURED" in out


def test_bf12b_a_probe_without_a_usable_cell_refuses_instead_of_falling_back(
    store, monkeypatch, tmp_path, capsys
):
    """⚠ REFUSE, NEVER FALL BACK: a silent fallback to the placeholder is the
    defect `--probe` exists to close."""
    monkeypatch.setattr(cli, "Store", lambda: store)
    ec.set_writeback_send_subcategories(store, True)
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"chosen_batch": 250, "cells": {}}), encoding="utf-8")
    rc = cli._cmd_subcategory_push(_push_args(probe=str(path)))
    assert rc == 2
    assert "refused" in capsys.readouterr().out


def test_bf12b_slot_hold_from_probe_reads_the_cell_for_the_requested_batch():
    report = {
        "chosen_batch": 500,
        "cells": {
            "250": {"slot_hold_p95": 0.4, "t_req_p95": 0.5},
            "500": {"slot_hold_p95": 6.0, "t_req_p95": 6.2},
        },
    }
    assert bf.slot_hold_from_probe(report, 250)[0] == 0.4
    assert bf.slot_hold_from_probe(report)[0] == 6.0        # the chosen cell
    assert bf.slot_hold_from_probe(report, 100)[0] is None  # no cell -> refuse


def test_bf12b_the_measured_t_req_p95_sets_the_client_timeout(store, tmp_path):
    """⚠ At the 30 s default a slow batch times out CLIENT-side while the server
    still holds its pooled slot, and the retry stacks a second one."""
    _drain_ready(store, 1)
    _, s = _sleeper()
    out = bf.push_subcategories(
        store, _PushClient(), batch=1, limit=1, sleep=s, slot_hold_p95=0.4,
        t_req_p95=40.0, printer=lambda *_: None,
    )
    assert out.plan["http_timeout_s"] == 120.0
    assert out.plan["slot_hold_measured"] is True


def test_bf12b_the_push_parser_exposes_the_measurement_flags():
    parser = cli.build_parser()
    sub = parser._subparsers._group_actions[0].choices["subcategory-push"]
    flags = {o for a in sub._actions for o in a.option_strings}
    assert {"--probe", "--slot-hold"} <= flags
