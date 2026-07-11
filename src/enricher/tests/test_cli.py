"""CLI orchestration seams: pull heartbeat ordering (E6), taxonomy slug
validation at ingest (E4), empty-id skip (E10), the composite-identity guard
(skipped_unknown instead of FK IntegrityError), record-judge skip counting
(E13), the code-enforced judge level rails, judge-queue scoping, the
chunk-file queue handoff (manifest shape, round-trip, batch-size chunking,
stale-file hygiene), a mocked pull->clean->record->write-back pipeline smoke,
tick-end guards, and the run_eval gate return code."""

import argparse
import json
from pathlib import Path

import httpx
import pytest

from job_enricher import cli
from job_enricher import enrich_config as ec
from job_enricher.clean import clean_description
from job_enricher.store import HEARTBEAT_KEY
from job_enricher.writeback import write_back


def _inbox_row(jid, source_id="greenhouse"):
    return {
        "job_listing_id": jid, "source_id": source_id, "title": "SWE",
        "company": "acme", "raw_location": "SF", "description_html": "<p>build systems</p>",
        "details_json": None, "content_hash": "h" + jid,
    }


def _enrichment(store, jid):
    """Fetch one enrichment row as a dict."""
    with store.connect() as c:
        row = c.execute("SELECT * FROM enrichments WHERE job_listing_id=?", (jid,)).fetchone()
    return dict(row) if row else None


# ---- E6: heartbeat only AFTER a successful pull ----------------------------
class _OkClient:
    def pull_pending(self, limit=None):
        return [_inbox_row("1")]


class _FailClient:
    def pull_pending(self, limit=None):
        raise httpx.ConnectError("jvn down")


def test_pull_stamps_heartbeat_after_success(store):
    assert store.get_meta(HEARTBEAT_KEY) is None
    inserted, skipped, received = cli._do_pull(store, _OkClient(), None)
    assert (inserted, received) == (1, 1)
    assert store.get_meta(HEARTBEAT_KEY) is not None


def test_failed_pull_does_not_stamp_heartbeat(store):
    with pytest.raises(httpx.ConnectError):
        cli._do_pull(store, _FailClient(), None)
    # a failed pull must NOT record a fresh "alive" heartbeat (E6)
    assert store.get_meta(HEARTBEAT_KEY) is None


# ---- E4: taxonomy slug validation at record-enrichment ---------------------
def test_bad_category_flagged_needs_human_not_shipped(store):
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "clean")
    res = cli.record_enrichment_items(
        store,
        [{"job_listing_id": "1", "source_id": "greenhouse",
          "category": "not_a_real_category", "level": "senior",
          "confidence": 0.9, "reasoning": "r"}],
        version="v1+abc",
    )
    assert (res["recorded"], res["needs_human"], res["skipped"]) == (1, 1, 0)
    assert res["nulled_facets"] == 1
    row = _enrichment(store, "1")
    assert row["category"] is None          # bad slug nulled — never shipped
    assert row["level"] == "senior"         # valid slug preserved
    assert row["needs_human"] == 1


def test_good_slugs_not_flagged(store):
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "clean")
    res = cli.record_enrichment_items(
        store,
        [{"job_listing_id": "1", "source_id": "greenhouse",
          "category": "software_engineering", "level": "mid"}],
        version="v1",
    )
    assert (res["recorded"], res["needs_human"], res["nulled_facets"]) == (1, 0, 0)
    assert _enrichment(store, "1")["needs_human"] == 0


# ---- E10: empty job_listing_id / unresolvable source_id skipped ------------
def test_empty_ids_skipped_at_record_enrichment(store):
    res = cli.record_enrichment_items(
        store,
        [
            {"job_listing_id": "   ", "source_id": "greenhouse"},   # blank id
            {"job_listing_id": "2", "source_id": "   "},            # blank source, no inbox row
        ],
        version="v1",
    )
    assert res["recorded"] == 0
    assert res["skipped"] == 1          # blank id
    assert res["skipped_unknown"] == 1  # unresolvable identity


# ---- composite guard: hallucinated ids never raise (the E10 'never raises') -
def test_hallucinated_id_with_echoed_source_is_skipped_not_raised(store):
    """A hallucinated job_listing_id + echoed source_id used to hit the FK
    IntegrityError and abort the whole wave; now it is skipped + counted."""
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "clean")
    res = cli.record_enrichment_items(
        store,
        [
            {"job_listing_id": "1", "source_id": "greenhouse",
             "category": "software_engineering", "level": "mid"},
            {"job_listing_id": "GHOST", "source_id": "greenhouse",   # hallucinated
             "category": "software_engineering", "level": "mid"},
            {"job_listing_id": "1", "source_id": "wrong-source",     # wrong pair
             "category": "software_engineering", "level": "mid"},
        ],
        version="v1",
    )
    assert res["recorded"] == 1
    assert res["skipped_unknown"] == 2
    assert _enrichment(store, "1") is not None  # the good row still landed


def test_missing_source_resolved_only_when_unambiguous(store):
    store.enqueue_inbox([
        _inbox_row("X", source_id="src-a"),
        _inbox_row("X", source_id="src-b"),
        _inbox_row("1", source_id="greenhouse"),
    ])
    for src, jid in (("src-a", "X"), ("src-b", "X"), ("greenhouse", "1")):
        store.record_clean(src, jid, "clean")
    res = cli.record_enrichment_items(
        store,
        [
            {"job_listing_id": "1", "category": "software_engineering", "level": "mid"},
            {"job_listing_id": "X", "category": "software_engineering", "level": "mid"},  # ambiguous
        ],
        version="v1",
    )
    assert res["recorded"] == 1          # '1' resolved to its single source
    assert res["skipped_unknown"] == 1   # 'X' ambiguous across src-a/src-b
    assert _enrichment(store, "1")["source_id"] == "greenhouse"


# ---- E4 (judge half): bad correction slug nulled + flagged -----------------
def test_merge_judge_nulls_invalid_correction_slug(store):
    base = {
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": "senior",
        "level_includes": json.dumps(["senior"]), "tags": json.dumps([]),
        "locations": json.dumps([]),
    }
    merged = cli._merge_judge(
        base, {"passed": False, "confidence": 0.9, "corrections": {"category": "bogus"}}, floor=0.6
    )
    assert merged["category"] is None
    assert merged["needs_human"] is True


# ---- E16: judge must not clear a classify-time needs_human flag ------------
def test_merge_judge_preserves_base_needs_human(store):
    """E16: a base row classify flagged needs_human stays flagged even when a
    confident judge verdict says needs_human=False (never silently cleared)."""
    base = {
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": "senior",
        "level_includes": json.dumps(["senior"]), "tags": json.dumps([]),
        "locations": json.dumps([]), "needs_human": 1,
    }
    merged = cli._merge_judge(
        base, {"passed": True, "confidence": 0.95, "needs_human": False}, floor=0.6
    )
    assert merged["needs_human"] is True


# ---- code-enforced judge level rails ----------------------------------------
def _rail_base(level="new_grad"):
    return {
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": "software_engineering", "level": level,
        "level_includes": json.dumps([level]), "tags": json.dumps([]),
        "locations": json.dumps([]),
    }


def test_merge_judge_rejects_level_change_within_equivalence(store):
    """new_grad<->entry churn is rejected in CODE: label kept, needs_human set,
    rejection recorded in judge_notes + counted."""
    merged = cli._merge_judge(
        _rail_base("new_grad"),
        {"passed": False, "confidence": 0.95, "corrections": {"level": "entry"}},
        floor=0.6,
    )
    assert merged["level"] == "new_grad"            # correction NOT applied
    assert merged["needs_human"] is True
    assert merged["rejected_corrections"] == 1
    assert "equivalence" in merged["judge_notes"]
    assert merged["judge_pass"] is False            # proposed correction != clean pass


def test_merge_judge_rejects_low_confidence_level_change(store):
    """A level change outside the equivalence needs judge confidence >= 0.8;
    below that the level is kept while OTHER corrections still apply."""
    merged = cli._merge_judge(
        _rail_base("mid"),
        {"passed": False, "confidence": 0.5,
         "corrections": {"level": "senior", "category": "business_ops"}},
        floor=0.4,
    )
    assert merged["level"] == "mid"                  # level correction rejected
    assert merged["category"] == "business_ops"      # other correction kept
    assert merged["rejected_corrections"] == 1
    assert "confidence" in merged["judge_notes"]


def test_merge_judge_applies_confident_level_change_outside_equivalence(store):
    merged = cli._merge_judge(
        _rail_base("mid"),
        {"passed": False, "confidence": 0.9, "corrections": {"level": "senior"}},
        floor=0.6,
    )
    assert merged["level"] == "senior"
    assert merged["rejected_corrections"] == 0


def test_merge_judge_applies_new_grad_to_intern_correction(store):
    """intern is a standalone tier OUTSIDE the new_grad/entry equivalence, so a
    confident new_grad->intern fix (an internship previously folded into
    new_grad) must be APPLIED, not rejected as filter-equivalent churn."""
    merged = cli._merge_judge(
        _rail_base("new_grad"),
        {"passed": False, "confidence": 0.9,
         "corrections": {"level": "intern", "level_includes": ["intern"]}},
        floor=0.6,
    )
    assert merged["level"] == "intern"
    assert merged["rejected_corrections"] == 0


# ---- E13: record-judge counts skipped verdicts for unknown ids -------------
def test_record_judge_counts_skipped_unknown_ids(store):
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_enrichment({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "business_ops",
        "level": "mid", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "classify_confidence": 0.9, "classify_reasoning": "r", "taxonomy_version": "v1",
    })
    res = cli.apply_judge_verdicts(
        store,
        [
            {"job_listing_id": "1", "passed": True, "confidence": 0.9},
            {"job_listing_id": "ghost", "passed": True, "confidence": 0.9},
        ],
        floor=0.6,
    )
    assert res["judged"] == 1
    assert res["skipped"] == 1


def test_apply_judge_verdicts_matches_composite_pair(store):
    """Verdicts carrying source_id land on the right row when the same bare id
    exists under two sources; a source-less verdict for that id is ambiguous
    and skipped."""
    for src in ("src-a", "src-b"):
        store.enqueue_inbox([_inbox_row("X", source_id=src)])
        store.record_clean(src, "X", "clean")
        store.record_enrichment({
            "job_listing_id": "X", "source_id": src, "category": "software_engineering",
            "level": "mid", "level_includes": "[]", "tags": "[]", "locations": "[]",
            "classify_confidence": 0.9, "classify_reasoning": "r", "taxonomy_version": "v1",
        })
    res = cli.apply_judge_verdicts(
        store,
        [
            {"job_listing_id": "X", "source_id": "src-b", "passed": False,
             "confidence": 0.9, "corrections": {"category": "business_ops"}},
            {"job_listing_id": "X", "passed": True, "confidence": 0.9},  # ambiguous
        ],
        floor=0.6,
        judge_model="opus",
    )
    assert res["judged"] == 1 and res["skipped"] == 1
    with store.connect() as c:
        rows = {
            r["source_id"]: r["category"]
            for r in c.execute("SELECT source_id, category FROM enrichments").fetchall()
        }
    assert rows == {"src-a": "software_engineering", "src-b": "business_ops"}


# ---- judge-queue scoping ----------------------------------------------------
def _seed_enriched(store, jid, conf, needs_human=False, category="software_engineering"):
    store.enqueue_inbox([_inbox_row(jid)])
    store.record_clean("greenhouse", jid, "clean " + jid)
    store.record_enrichment({
        "job_listing_id": jid, "source_id": "greenhouse", "category": category,
        "level": "mid", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "classify_confidence": conf, "classify_reasoning": "r", "taxonomy_version": "v1",
        "needs_human": needs_human,
    })


def _manifest_items(capsys):
    """Parse a queue command's stdout manifest and flatten the chunk files'
    contents back into one items list (the round-trip the sub-agents do)."""
    manifest = json.loads(capsys.readouterr().out)
    items = []
    for entry in manifest:
        items.extend(json.loads(Path(entry["chunk_file"]).read_text(encoding="utf-8")))
    return manifest, items


def test_judge_queue_low_confidence_scope(store, monkeypatch, capsys):
    """Default scope=low_confidence emits only rows below the ceiling, with a
    nulled facet, or already flagged needs_human — and the chunk files carry
    company + raw_location + source_id for HQ verification."""
    _seed_enriched(store, "1", conf=0.95)                      # confident -> excluded
    _seed_enriched(store, "2", conf=0.5)                       # low conf -> included
    _seed_enriched(store, "3", conf=0.99, needs_human=True)    # flagged -> included
    _seed_enriched(store, "4", conf=0.99, category=None)       # nulled facet -> included
    monkeypatch.setattr(cli, "Store", lambda: store)

    rc = cli._cmd_judge_queue(argparse.Namespace(limit=None))
    assert rc == 0
    _, items = _manifest_items(capsys)
    assert sorted(i["job_listing_id"] for i in items) == ["2", "3", "4"]
    for i in items:
        assert i["source_id"] == "greenhouse"
        assert i["company"] == "acme"
        assert i["raw_location"] == "SF"


def test_judge_queue_scope_all_emits_everything(store, monkeypatch, capsys):
    from job_enricher import enrich_config as ec

    _seed_enriched(store, "1", conf=0.95)
    _seed_enriched(store, "2", conf=0.5)
    ec.set_judge_scope(store, "all")
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_judge_queue(argparse.Namespace(limit=None))
    _, items = _manifest_items(capsys)
    assert sorted(i["job_listing_id"] for i in items) == ["1", "2"]


# ---- chunk-file handoff (queue -> sub-agents) --------------------------------
def _seed_cleaned(store, jid):
    store.enqueue_inbox([_inbox_row(jid)])
    store.record_clean("greenhouse", jid, "clean text " + jid)


def test_classify_queue_manifest_shape_and_roundtrip(store, monkeypatch, capsys):
    """classify-queue writes chunk files and prints ONLY a [{chunk_file, count}]
    manifest — no job text/ids in the orchestrator's stdout. The chunk files
    round-trip the exact per-row fields the agents need."""
    for jid in ("1", "2", "3", "4"):
        _seed_cleaned(store, jid)
    monkeypatch.setattr(cli, "Store", lambda: store)

    rc = cli._cmd_classify_queue(argparse.Namespace(limit=None))
    assert rc == 0
    manifest, items = _manifest_items(capsys)
    # manifest is small: exactly chunk_file + count per entry, nothing else
    assert all(set(e) == {"chunk_file", "count"} for e in manifest)
    # default batch_size=3 -> chunks of 3 + 1
    assert [e["count"] for e in manifest] == [3, 1]
    for e in manifest:
        p = Path(e["chunk_file"])
        assert p.is_absolute()
        assert p.parent == (store.db_path.parent / "chunks").resolve()
        assert p.name.startswith("classify-") and p.suffix == ".json"
    # round-trip: full job objects, exactly the fields agents get today
    assert sorted(i["job_listing_id"] for i in items) == ["1", "2", "3", "4"]
    for i in items:
        assert set(i) == {
            "job_listing_id", "source_id", "title", "company",
            "raw_location", "clean_description",
        }
        assert i["clean_description"] == "clean text " + i["job_listing_id"]


def test_classify_queue_respects_batch_size_knob(store, monkeypatch, capsys):
    from job_enricher import enrich_config as ec

    for jid in ("1", "2", "3", "4", "5", "6", "7"):
        _seed_cleaned(store, jid)
    ec.set_classify_batch_size(store, 5)  # knob read fresh from meta
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=None))
    manifest, items = _manifest_items(capsys)
    assert [e["count"] for e in manifest] == [5, 2]
    assert len(items) == 7


def test_classify_queue_names_chunks_after_current_tick(store, monkeypatch, capsys):
    tid = store.start_tick()
    _seed_cleaned(store, "1")
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=None))
    manifest, _ = _manifest_items(capsys)
    assert Path(manifest[0]["chunk_file"]).name == f"classify-t{tid}-01.json"


def test_queue_commands_clear_only_their_own_stale_chunks(store, monkeypatch, capsys):
    """Each queue command deletes its OWN previous chunk files before writing
    (classify-*.json vs judge-*.json) and leaves the other's alone."""
    chunks = store.db_path.parent / "chunks"
    chunks.mkdir()
    stale_classify = chunks / "classify-t1-01.json"
    stale_judge = chunks / "judge-t1-01.json"
    stale_classify.write_text("[]")
    stale_judge.write_text("[]")
    _seed_cleaned(store, "1")
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=None))
    manifest, _ = _manifest_items(capsys)
    assert not stale_classify.exists()          # own stale file removed
    assert stale_judge.exists()                 # other queue's file untouched
    assert len(manifest) == 1


def test_classify_queue_empty_queue_empty_manifest_no_files(store, monkeypatch, capsys):
    chunks = store.db_path.parent / "chunks"
    chunks.mkdir()
    (chunks / "classify-t1-01.json").write_text("[]")  # stale from a prior run
    monkeypatch.setattr(cli, "Store", lambda: store)

    rc = cli._cmd_classify_queue(argparse.Namespace(limit=None))
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []
    assert list(chunks.glob("classify-*.json")) == []  # nothing left behind


def test_judge_queue_empty_and_disabled_leave_no_files(store, monkeypatch, capsys):
    from job_enricher import enrich_config as ec

    chunks = store.db_path.parent / "chunks"
    chunks.mkdir()
    monkeypatch.setattr(cli, "Store", lambda: store)

    # empty queue -> [] and stale judge chunks removed
    (chunks / "judge-t1-01.json").write_text("[]")
    rc = cli._cmd_judge_queue(argparse.Namespace(limit=None))
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []
    assert list(chunks.glob("judge-*.json")) == []

    # judge disabled -> same contract
    (chunks / "judge-t2-01.json").write_text("[]")
    ec.set_judge_enabled(store, False)
    rc = cli._cmd_judge_queue(argparse.Namespace(limit=None))
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []
    assert list(chunks.glob("judge-*.json")) == []


def test_judge_queue_chunk_files_carry_current_classification(store, monkeypatch, capsys):
    """Judge chunk files preserve the per-row fields including the nested
    `current` classification exactly as the inline queue emitted them."""
    _seed_enriched(store, "1", conf=0.5)
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_judge_queue(argparse.Namespace(limit=None))
    manifest, items = _manifest_items(capsys)
    assert all(set(e) == {"chunk_file", "count"} for e in manifest)
    assert Path(manifest[0]["chunk_file"]).name.startswith("judge-")
    (item,) = items
    assert set(item) == {
        "job_listing_id", "source_id", "title", "company",
        "raw_location", "clean_description", "current",
    }
    assert item["current"] == {
        "category": "software_engineering", "level": "mid",
        "level_includes": [], "tags": [], "locations": [], "confidence": 0.5,
    }


# ---- tick-end guards ---------------------------------------------------------
def test_tick_end_refuses_mismatched_tick_id(store, monkeypatch, capsys):
    """Stray tick-end guard: a tick-end naming a tick that is not the current
    one must refuse (exit 1) and leave the tick open."""
    tid = store.start_tick()
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=tid + 99))
    assert rc == 1
    assert "REFUSED" in capsys.readouterr().out
    assert store.current_tick_id() == tid  # still open

    rc = cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=tid))
    assert rc == 0
    assert store.current_tick_id() is None


def test_tick_end_reads_expected_tick_from_env(store, monkeypatch):
    tid = store.start_tick()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setenv("ENRICH_TICK_ID", str(tid + 1))
    rc = cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=None))
    assert rc == 1
    monkeypatch.setenv("ENRICH_TICK_ID", str(tid))
    rc = cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=None))
    assert rc == 0


def test_tick_end_mass_nulling_circuit_breaker(store, monkeypatch):
    """>50% nulled facets with >=10 classified closes the tick status=error
    with a drift note, even when 'ok' was requested."""
    tid = store.start_tick()
    store.bump_tick_counters(classified=10, nulled_facets=6)
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=tid))
    assert rc == 0
    tick = store.get_tick(tid)
    assert tick["status"] == "error"
    assert "circuit breaker" in tick["notes"]


def test_tick_end_no_breaker_below_thresholds(store, monkeypatch):
    tid = store.start_tick()
    store.bump_tick_counters(classified=9, nulled_facets=9)  # classified < 10
    monkeypatch.setattr(cli, "Store", lambda: store)
    cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=tid))
    assert store.get_tick(tid)["status"] == "ok"


# ---- E14: pull -> clean -> record -> write-back pipeline smoke --------------
class _PipeClient:
    def __init__(self):
        self.posted = []

    def pull_pending(self, limit=None):
        return [_inbox_row("1"), _inbox_row("2")]

    def post_results(self, payload):
        self.posted.append(payload)
        return {"written": len(payload), "failed": []}


def test_pipeline_smoke(store):
    client = _PipeClient()
    # pull
    cli._do_pull(store, client, None)
    # clean
    for r in store.jobs_needing_clean():
        store.record_clean(r["source_id"], r["job_listing_id"], clean_description(r["description_html"]))
    # record classify results
    res = cli.record_enrichment_items(
        store,
        [
            {"job_listing_id": "1", "source_id": "greenhouse",
             "category": "software_engineering", "level": "senior", "confidence": 0.9},
            {"job_listing_id": "2", "source_id": "greenhouse",
             "category": "business_ops", "level": "mid", "confidence": 0.8},
        ],
        version="v1",
    )
    assert res["recorded"] == 2
    # write-back
    wb = write_back(store, client=client, batch_size=10)
    assert wb["sent"] == 2
    assert wb["unsent"] == 0
    assert store.enriched_unsent() == []
    assert len(client.posted) == 1 and len(client.posted[0]) == 2


# ---- LLM stage timings recorded at record time -------------------------------
def test_record_enrichment_cmd_records_classify_stage_timing(store, monkeypatch):
    store.start_tick()
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "clean")
    monkeypatch.setattr(cli, "Store", lambda: store)
    items = json.dumps([{"job_listing_id": "1", "source_id": "greenhouse",
                         "category": "software_engineering", "level": "mid"}])
    rc = cli._cmd_record_enrichment(argparse.Namespace(json=items, json_file=None))
    assert rc == 0
    with store.connect() as c:
        rows = c.execute("SELECT stage, item_count FROM stage_timings").fetchall()
    assert [(r["stage"], r["item_count"]) for r in rows] == [("classify", 1)]
    # classify_model provenance stamped from the active knob
    assert _enrichment(store, "1")["classify_model"] == "haiku"


def test_record_judge_cmd_records_judge_stage_timing(store, monkeypatch):
    store.start_tick()
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "clean")
    store.record_enrichment({
        "job_listing_id": "1", "source_id": "greenhouse", "category": "software_engineering",
        "level": "mid", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "classify_confidence": 0.5, "classify_reasoning": "r", "taxonomy_version": "v1",
    })
    monkeypatch.setattr(cli, "Store", lambda: store)
    verdicts = json.dumps([{"job_listing_id": "1", "source_id": "greenhouse",
                            "passed": True, "confidence": 0.9}])
    rc = cli._cmd_record_judge(argparse.Namespace(json=verdicts, json_file=None))
    assert rc == 0
    with store.connect() as c:
        stages = [r["stage"] for r in c.execute("SELECT stage FROM stage_timings").fetchall()]
    assert stages == ["judge"]
    assert _enrichment(store, "1")["judge_model"] == "sonnet"


# ---- reenrich: true 'below' semantics ----------------------------------------
def test_version_below_orders_by_declared_version():
    assert cli._version_below("v1+aaa", "v2+bbb") is True         # smaller N -> below
    assert cli._version_below("v2+aaa", "v2+bbb") is False        # same N, diff hash -> NOT below
    assert cli._version_below("v2+bbb", "v2+bbb") is False        # identical
    assert cli._version_below("v3+ccc", "v2+bbb") is False        # newer
    assert cli._version_below(None, "v2+bbb") is True             # unversioned -> below
    assert cli._version_below("garbage", "v2+bbb") is True        # unparseable -> below
    with pytest.raises(ValueError):
        cli._version_below("v1+aaa", "not-a-version")


def test_reenrich_rejects_malformed_threshold(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_reenrich(argparse.Namespace(taxonomy_below="typo"))
    assert rc == 2


def test_reenrich_resets_only_older_versions(store, monkeypatch):
    _seed_enriched(store, "1", conf=0.9)
    _seed_enriched(store, "2", conf=0.9)
    with store.connect() as c:
        c.execute("UPDATE enrichments SET taxonomy_version='v1+old' WHERE job_listing_id='1'")
        c.execute("UPDATE enrichments SET taxonomy_version='v2+cur' WHERE job_listing_id='2'")
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_reenrich(argparse.Namespace(taxonomy_below="v2+cur"))
    assert rc == 0
    with store.connect() as c:
        left = [r["job_listing_id"] for r in c.execute("SELECT job_listing_id FROM enrichments").fetchall()]
        status1 = c.execute("SELECT status FROM inbox WHERE job_listing_id='1'").fetchone()["status"]
    assert left == ["2"]          # only the v1 row was reset
    assert status1 == "cleaned"   # re-queued for classify


# ---- golden-merge -------------------------------------------------------------
def test_cmd_golden_merge_reports_counts(store, monkeypatch, capsys, tmp_path):
    import job_enricher.eval.golden as golden

    seed = tmp_path / "golden.json"
    seed.write_text(json.dumps([
        {"job_listing_id": "1", "source_id": "greenhouse", "title": "SWE",
         "category": "business_ops", "level": "mid", "level_includes": ["mid"],
         "tags": ["ops"], "label_source": "draft"},
        {"job_listing_id": "2", "source_id": "greenhouse", "title": "PM",
         "category": "product_manager", "level": "senior", "level_includes": ["senior"],
         "tags": [], "label_source": "draft"},
    ]))
    monkeypatch.setattr(golden, "SEED_FILE", seed)

    class _CorrClient:
        def get_corrections(self, since=None, limit=None):
            return [
                {"job_listing_id": "1", "source_id": "greenhouse", "title": "SWE",
                 "company": "acme", "category": "software_engineering",
                 "level": "new_grad", "tags": ["python"], "corrected_at": "t"},
                {"job_listing_id": "missing", "source_id": "greenhouse", "title": "X",
                 "company": "acme", "category": "growth", "level": "mid",
                 "tags": [], "corrected_at": "t"},
            ]

    import job_enricher.jvn_client as jc
    monkeypatch.setattr(jc, "JVNClient", lambda: _CorrClient())

    rc = cli._cmd_golden_merge(argparse.Namespace(since=None, limit=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert "matched=1" in out and "upgraded=1" in out and "unmatched=1" in out

    rows = json.loads(seed.read_text())
    row1 = next(r for r in rows if r["job_listing_id"] == "1")
    assert row1["category"] == "software_engineering"
    assert row1["level"] == "new_grad"
    assert row1["level_includes"] == ["new_grad", "entry"]
    assert row1["tags"] == ["python"]
    assert row1["label_source"] == "human"
    # untouched row stays draft
    assert next(r for r in rows if r["job_listing_id"] == "2")["label_source"] == "draft"


# ---- health: failed rows visible, excluded from unsent ----------------------
def test_health_reports_failed_rows_and_excludes_them_from_unsent(store, monkeypatch, capsys):
    _seed_enriched(store, "1", conf=0.9)
    _seed_enriched(store, "2", conf=0.9)
    for _ in range(5):
        store.record_writeback_failure("greenhouse", "2")  # poison -> terminal failed
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_health(argparse.Namespace())
    assert rc == 0
    health = json.loads(capsys.readouterr().out)
    assert health["unsent"] == 1                 # only the live row
    assert health["failed_rows"] == 1
    assert health["inbox"].get("failed") == 1
    # health surfaces the live models so the deploy sanity check reveals them
    assert health["classify_model"] == "haiku"
    assert health["judge_model"] == "sonnet"


# ---- reset-knob clears an override back to the committed default ------------
def test_reset_knob_clears_override(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Store", lambda: store)
    cli._cmd_set_knob(
        argparse.Namespace(knob="classify:model", setter=ec.set_classify_model, value="sonnet")
    )
    assert ec.get_classify_model(store) == "sonnet"
    rc = cli._cmd_reset_knob(argparse.Namespace(knob="classify:model"))
    assert rc == 0
    assert ec.get_classify_model(store) == "haiku"  # back to committed default
    assert "reset to committed default" in capsys.readouterr().out


# ---- run_eval gate return code (no network) --------------------------------
def test_run_eval_returns_one_without_human_truth():
    from job_enricher.eval.report import run_eval

    # The seeded golden set has no human-labeled rows, so the gate cannot run
    # and run_eval returns a non-zero code without touching the network.
    assert run_eval(gate=True) == 1
