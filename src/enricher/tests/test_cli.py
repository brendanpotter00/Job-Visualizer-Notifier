"""CLI orchestration seams: pull heartbeat ordering (E6), taxonomy slug
validation at ingest (E4), empty-id skip (E10), the composite-identity guard
(skipped_unknown instead of FK IntegrityError), record-judge skip counting
(E13), the code-enforced judge level rails, judge-queue scoping, the
chunk-file queue handoff (manifest shape, round-trip, batch-size chunking,
stale-file hygiene), a mocked pull->clean->record->write-back pipeline smoke,
tick-end guards, and the run_eval gate return code."""

import argparse
from zoneinfo import ZoneInfo
import json
from pathlib import Path

import httpx
import pytest

from job_enricher import cli
from job_enricher import enrich_config as ec
from job_enricher import taxonomy as tax
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


def _install_capture_client(monkeypatch, store):
    """Patch cli.Store + JVNClient so _cmd_pull runs against `store` and records
    the limit it claims with. Returns the mutable capture dict."""
    import job_enricher.jvn_client as jc

    captured: dict = {}

    class _CapClient:
        def pull_pending(self, limit=None):
            captured["limit"] = limit
            return []

    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(jc, "JVNClient", _CapClient)
    return captured


def test_pull_caps_to_per_tick_limit_for_in_process_engine(store, monkeypatch):
    """A serial in-process engine must not over-claim: _cmd_pull caps the claim to
    enrich:per_tick_limit so inflow can't outrun classify throughput and grow the
    local backlog (which would also bury freshly-posted jobs)."""
    captured = _install_capture_client(monkeypatch, store)
    ec.set_classify_engine(store, "ollama")
    ec.set_enrich_per_tick_limit(store, 25)
    cli._cmd_pull(argparse.Namespace(limit=None))
    assert captured["limit"] == 25


def test_pull_unbounded_for_claude_code(store, monkeypatch):
    """claude-code fan-out clears a batch fast, so the per-tick cap does NOT apply
    to pull — the limit stays None (JVNClient falls back to settings.pull_limit)."""
    captured = _install_capture_client(monkeypatch, store)
    ec.set_classify_engine(store, "claude-code")
    ec.set_enrich_per_tick_limit(store, 25)  # ignored for claude-code
    cli._cmd_pull(argparse.Namespace(limit=None))
    assert captured["limit"] is None


def test_pull_explicit_limit_overrides_cap(store, monkeypatch):
    """An explicit --limit wins over the per-tick cap (operator override)."""
    captured = _install_capture_client(monkeypatch, store)
    ec.set_classify_engine(store, "ollama")
    ec.set_enrich_per_tick_limit(store, 25)
    cli._cmd_pull(argparse.Namespace(limit=100))
    assert captured["limit"] == 100


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


# ---- title-only stopgap: empty description -> low-confidence, marked ---------
def test_title_only_marks_and_clamps_empty_description(store):
    """A row whose source captured no description (empty clean_description) is
    marked title_only and its confidence clamped below the judge ceiling, whatever
    the agent claimed — a code-level guarantee that routes it through the judge."""
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "")   # no description captured
    res = cli.record_enrichment_items(
        store,
        [{"job_listing_id": "1", "source_id": "greenhouse",
          "category": "software_engineering", "level": "senior",
          "confidence": 0.95, "reasoning": "from title"}],
        version="v1",
    )
    assert res["recorded"] == 1 and res["title_only"] == 1
    row = _enrichment(store, "1")
    assert row["title_only"] == 1
    assert row["classify_confidence"] == cli.TITLE_ONLY_MAX_CONFIDENCE  # clamped from 0.95
    assert row["needs_human"] == 0  # NOT flagged to the human queue, only low-confidence


def test_title_only_tolerates_non_numeric_confidence(store):
    """A local model can emit a non-numeric confidence ("medium"/"0.5"); the
    title-only clamp must coerce it to the cap, not raise (the record loop's
    'never raises on bad data' contract). Regression for the min(str, float)
    TypeError on the title-only path."""
    store.enqueue_inbox([_inbox_row("1"), _inbox_row("2")])
    store.record_clean("greenhouse", "1", "")
    store.record_clean("greenhouse", "2", "")
    res = cli.record_enrichment_items(
        store,
        [
            {"job_listing_id": "1", "source_id": "greenhouse",
             "category": "software_engineering", "level": "mid", "confidence": "medium"},
            {"job_listing_id": "2", "source_id": "greenhouse",
             "category": "software_engineering", "level": "mid", "confidence": "0.5"},
        ],
        version="v1",
    )
    assert res["recorded"] == 2 and res["title_only"] == 2  # neither raised
    assert _enrichment(store, "1")["classify_confidence"] == cli.TITLE_ONLY_MAX_CONFIDENCE
    assert _enrichment(store, "2")["classify_confidence"] == cli.TITLE_ONLY_MAX_CONFIDENCE


def test_non_empty_description_is_not_title_only(store):
    """A normal row (real description) keeps its confidence and title_only=0."""
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "real cleaned description text")
    res = cli.record_enrichment_items(
        store,
        [{"job_listing_id": "1", "source_id": "greenhouse",
          "category": "software_engineering", "level": "mid", "confidence": 0.9}],
        version="v1",
    )
    assert res["title_only"] == 0
    row = _enrichment(store, "1")
    assert row["title_only"] == 0 and row["classify_confidence"] == 0.9


def test_normal_path_tolerates_structured_scalar_fields(store):
    """Prod regression 2026-08-07: the local model returned a dict where
    confidence belongs, the raw dict reached the sqlite bind ("Error binding
    parameter 8: type 'dict' is not supported"), and the whole classify-run
    died — stalling classify on every tick that re-claimed the same batch.
    Non-numeric confidence -> None (judge-routed), structured reasoning ->
    JSON text, junk latency -> None; the item records instead of raising."""
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "real cleaned description text")
    res = cli.record_enrichment_items(
        store,
        [{"job_listing_id": "1", "source_id": "greenhouse",
          "category": "software_engineering", "level": "mid",
          "confidence": {"category": 0.9, "level": 0.7},
          "reasoning": {"why": ["structured", "junk"]},
          "classify_latency_ms": "fast"}],
        version="v1",
    )
    assert res["recorded"] == 1 and res["skipped"] == 0
    row = _enrichment(store, "1")
    assert row["classify_confidence"] is None
    assert json.loads(row["classify_reasoning"]) == {"why": ["structured", "junk"]}
    assert row["classify_latency_ms"] is None
    assert cli._needs_judge(row, 0.85) is True  # unknown confidence -> judged


def test_normal_path_coerces_numeric_string_confidence(store):
    """"0.9" (a string) is a usable confidence on the normal path too — stored
    as the float, not bound as text."""
    store.enqueue_inbox([_inbox_row("1")])
    store.record_clean("greenhouse", "1", "real cleaned description text")
    res = cli.record_enrichment_items(
        store,
        [{"job_listing_id": "1", "source_id": "greenhouse",
          "category": "software_engineering", "level": "mid",
          "confidence": "0.9"}],
        version="v1",
    )
    assert res["recorded"] == 1
    assert _enrichment(store, "1")["classify_confidence"] == 0.9


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


def test_merge_judge_tolerates_structured_scalar_fields(store):
    """Judge half of the 2026-08-07 prod regression: a dict judge-confidence
    used to raise at the `conf < floor` comparison before even reaching the
    sqlite bind, and structured notes/reasoning crash the bind itself. A
    non-dict corrections payload is dropped (with a warning), scalars are
    coerced, and the verdict merges instead of raising."""
    merged = cli._merge_judge(
        _rail_base("mid"),
        {"passed": True,
         "confidence": {"overall": 0.9},
         "notes": {"nested": True},
         "reasoning": ["step 1", "step 2"],
         "judge_latency_ms": "slow",
         "corrections": ["not", "a", "dict"]},
        floor=0.6,
    )
    assert merged["judge_confidence"] is None
    assert json.loads(merged["judge_notes"]) == {"nested": True}
    assert json.loads(merged["judge_reasoning"]) == ["step 1", "step 2"]
    assert merged["judge_latency_ms"] is None
    assert merged["judge_pass"] is True   # junk corrections dropped, not proposed
    assert merged["level"] == "mid"       # base facets untouched


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
def _seed_enriched(store, jid, conf, needs_human=False, category="software_engineering",
                   **extra):
    store.enqueue_inbox([_inbox_row(jid)])
    store.record_clean("greenhouse", jid, "clean " + jid)
    e = {
        "job_listing_id": jid, "source_id": "greenhouse", "category": category,
        "level": "mid", "level_includes": "[]", "tags": "[]", "locations": "[]",
        "classify_confidence": conf, "classify_reasoning": "r", "taxonomy_version": "v1",
        "needs_human": needs_human,
    }
    e.update(extra)
    store.record_enrichment(e)


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
    ec.set_classify_engine(store, "claude-code")  # batch_size chunking is the claude path
    monkeypatch.setattr(cli, "Store", lambda: store)

    rc = cli._cmd_classify_queue(argparse.Namespace(limit=None))
    assert rc == 0
    manifest, items = _manifest_items(capsys)
    # manifest is small: exactly chunk_file + count per entry, nothing else
    assert all(set(e) == {"chunk_file", "count"} for e in manifest)
    # claude-code batch_size=3 -> chunks of 3 + 1
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
    ec.set_classify_engine(store, "claude-code")  # batch_size only applies to claude-code
    ec.set_classify_batch_size(store, 5)  # knob read fresh from meta
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=None))
    manifest, items = _manifest_items(capsys)
    assert [e["count"] for e in manifest] == [5, 2]
    assert len(items) == 7


# ---- per-tick queue cap for the serial in-process engines --------------------
def test_classify_queue_bounds_in_process_engine(store, monkeypatch, capsys):
    """A serial in-process engine (ollama) must NOT queue the whole cleaned
    backlog in one tick — classify-queue caps it at enrich:per_tick_limit so
    classify-run finishes inside the wrapper watchdog and the tick still reaches
    write-back. Regression guard for the 'ticks never deliver' cutover bug."""
    for jid in ("1", "2", "3", "4", "5"):
        _seed_cleaned(store, jid)
    ec.set_classify_engine(store, "ollama")
    ec.set_enrich_per_tick_limit(store, 2)
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=None))
    _, items = _manifest_items(capsys)
    assert len(items) == 2  # a bounded slice, not all 5


def test_classify_queue_unbounded_for_claude_code(store, monkeypatch, capsys):
    """The claude-code parallel fan-out clears a whole batch fast, so the per-tick
    cap does NOT apply — every cleaned row is still queued."""
    for jid in ("1", "2", "3", "4", "5"):
        _seed_cleaned(store, jid)
    ec.set_classify_engine(store, "claude-code")
    ec.set_enrich_per_tick_limit(store, 2)  # ignored for claude-code
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=None))
    _, items = _manifest_items(capsys)
    assert len(items) == 5


def test_classify_queue_explicit_limit_overrides_per_tick_cap(store, monkeypatch, capsys):
    """An explicit --limit always wins over the knob (eval / manual runs)."""
    for jid in ("1", "2", "3", "4", "5"):
        _seed_cleaned(store, jid)
    ec.set_classify_engine(store, "ollama")
    ec.set_enrich_per_tick_limit(store, 2)
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=4))
    _, items = _manifest_items(capsys)
    assert len(items) == 4


def test_judge_queue_bounds_in_process_engine(store, monkeypatch, capsys):
    """judge-queue applies the same per-tick cap for in-process engines so the
    serial judge-run also stays inside the watchdog (scope=all here → all seeded
    rows are judge-eligible, isolating the cap)."""
    for jid in ("1", "2", "3", "4", "5"):
        _seed_enriched(store, jid, conf=0.5)
    ec.set_judge_engine(store, "ollama")
    ec.set_judge_scope(store, "all")
    ec.set_enrich_per_tick_limit(store, 2)
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_judge_queue(argparse.Namespace(limit=None))
    _, items = _manifest_items(capsys)
    assert len(items) == 2


def test_judge_queue_cap_is_post_scope_not_starved(store, monkeypatch, capsys):
    """The per-tick cap is applied AFTER the scope filter. Under scope=low_confidence
    the confident rows (which the judge never touches) sit at the FRONT of the
    unjudged queue; they must not consume the cap and starve the low-confidence rows
    that DO need judging — a naive pre-filter SQL LIMIT would emit zero here."""
    for jid in ("h1", "h2", "h3"):        # confident, enriched first -> scope skips
        _seed_enriched(store, jid, conf=0.95)
    for jid in ("l1", "l2", "l3"):        # low confidence -> these need judging
        _seed_enriched(store, jid, conf=0.5)
    ec.set_judge_engine(store, "ollama")
    ec.set_enrich_per_tick_limit(store, 2)   # scope stays low_confidence (default)
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_judge_queue(argparse.Namespace(limit=None))
    _, items = _manifest_items(capsys)
    assert len(items) == 2                                          # capped, not starved to 0
    assert all(i["job_listing_id"].startswith("l") for i in items)  # only the low-conf rows


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
        # ⚠ Present-and-None, not absent: the judge must see the facet it is
        # invited to correct, and None is the "never evaluated, leave it alone"
        # state the prompt names.
        "subcategories": None,
        "level_includes": [], "tags": [], "locations": [], "confidence": 0.5,
    }


def test_judge_queue_current_carries_subcategories_matching_the_eval_queue(
    store, monkeypatch, capsys
):
    """⚠ PROD/EVAL PARITY. `_cmd_eval_run` puts `subcategories` in `current` and
    build_judge_prompt invites a correction on it, so omitting it in prod would
    have the judge RE-DERIVE the facet from the description here while VERIFYING
    it in eval — _merge_judge's rails would be gating a blind guess, and the
    judge-correction rate measured in eval would not be the one prod produces.
    All three states have to survive the queue."""
    _seed_enriched(store, "1", conf=0.5, subcategories='["backend"]')
    _seed_enriched(store, "2", conf=0.5, subcategories="[]")
    _seed_enriched(store, "3", conf=0.5)                       # never evaluated
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_judge_queue(argparse.Namespace(limit=None))
    _, items = _manifest_items(capsys)
    by_id = {i["job_listing_id"]: i["current"] for i in items}
    assert by_id["1"]["subcategories"] == ["backend"]
    assert by_id["2"]["subcategories"] == []          # evaluated, none apply
    assert by_id["3"]["subcategories"] is None        # NOT [] — never evaluated
    # the key exists on every row, whatever the state
    assert all("subcategories" in c for c in by_id.values())


def test_judge_queue_current_keys_match_the_eval_queue_exactly():
    """The two `current` builders are hand-written dicts in different functions;
    this pins them to the same key set so they cannot drift apart again."""
    import inspect
    prod = inspect.getsource(cli._cmd_judge_queue)
    ev = inspect.getsource(cli._cmd_eval_run)
    for key in ("category", "level", "subcategories", "level_includes",
                "tags", "locations", "confidence"):
        assert f'"{key}"' in prod, key
        assert f'"{key}"' in ev, key


# ---- batch=1 forced for local (non claude-code) engines at queue time --------
def test_classify_queue_forces_batch1_for_local_engine(store, monkeypatch, capsys):
    """A non-claude-code classify engine writes ONE job per chunk file so the
    engine's positional id-recovery can engage; Claude keeps its fan-out batch."""
    for jid in ("1", "2", "3", "4"):
        _seed_cleaned(store, jid)
    ec.set_classify_engine(store, "ollama")
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=None))
    manifest, items = _manifest_items(capsys)
    assert [e["count"] for e in manifest] == [1, 1, 1, 1]   # one job per chunk
    assert len(items) == 4


def test_classify_queue_keeps_batch_size_for_claude_engine(store, monkeypatch, capsys):
    for jid in ("1", "2", "3", "4"):
        _seed_cleaned(store, jid)
    ec.set_classify_engine(store, "claude-code")   # explicit default engine
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_classify_queue(argparse.Namespace(limit=None))
    manifest, _ = _manifest_items(capsys)
    assert [e["count"] for e in manifest] == [3, 1]   # classify:batch_size=3


def test_judge_queue_forces_batch1_for_local_engine(store, monkeypatch, capsys):
    for jid in ("1", "2", "3", "4"):
        _seed_enriched(store, jid, conf=0.5)   # low conf -> in default judge scope
    ec.set_judge_engine(store, "ollama")
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_judge_queue(argparse.Namespace(limit=None))
    manifest, items = _manifest_items(capsys)
    assert [e["count"] for e in manifest] == [1, 1, 1, 1]
    assert len(items) == 4


def test_judge_queue_keeps_batch_size_for_claude_engine(store, monkeypatch, capsys):
    for jid in ("1", "2", "3", "4"):
        _seed_enriched(store, jid, conf=0.5)
    ec.set_judge_engine(store, "claude-code")
    monkeypatch.setattr(cli, "Store", lambda: store)

    cli._cmd_judge_queue(argparse.Namespace(limit=None))
    manifest, _ = _manifest_items(capsys)
    assert [e["count"] for e in manifest] == [3, 1]


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


# ---- P0-3: an abandoned classify chunk is no longer silent --------------------
def _write_chunk(store, jids):
    import json as _json

    chunk_dir = store.db_path.parent / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    path = chunk_dir / "classify-000.json"
    path.write_text(_json.dumps([
        {"job_listing_id": j, "source_id": "greenhouse", "title": "SWE",
         "company": "acme", "raw_location": "SF", "clean_description": "x"}
        for j in jids
    ]))
    return path


class _ExplodingEngine:
    name = "boom"

    def classify(self, jobs):
        from job_enricher.engines import EngineError

        raise EngineError("timed out")


def test_engine_error_bumps_errors_by_the_chunk_size_and_attempts_per_row(
    store, monkeypatch, capsys
):
    """BEFORE P0-3 this path was a SILENT capacity leak: `except EngineError:
    continue` left `errors` at 0 and `inbox.attempts` untouched, so the tick
    closed status=ok having lost the whole chunk, and the same rows were
    re-claimed and re-abandoned every tick forever."""
    for jid in ("1", "2", "3"):
        _seed_cleaned(store, jid)
    chunk = _write_chunk(store, ["1", "2", "3"])
    store.start_tick()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.engines.build_engine", lambda *a, **kw: _ExplodingEngine()
    )
    rc = cli._cmd_classify_run(
        argparse.Namespace(engine=None, chunk_file=str(chunk))
    )
    assert rc == 0
    assert "abandoned=3" in capsys.readouterr().out
    with store.connect() as c:
        attempts = {
            r["job_listing_id"]: r["attempts"]
            for r in c.execute("SELECT job_listing_id, attempts FROM inbox")
        }
        errors = c.execute("SELECT errors FROM ticks ORDER BY id DESC").fetchone()["errors"]
    assert attempts == {"1": 1, "2": 1, "3": 1}
    assert errors == 3


def test_repeated_abandonment_flips_a_row_terminal(store, monkeypatch, capsys):
    _seed_cleaned(store, "1")
    chunk = _write_chunk(store, ["1"])
    store.start_tick()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.engines.build_engine", lambda *a, **kw: _ExplodingEngine()
    )
    for _ in range(5):
        cli._cmd_classify_run(argparse.Namespace(engine=None, chunk_file=str(chunk)))
    with store.connect() as c:
        assert c.execute("SELECT status FROM inbox").fetchone()["status"] == "failed"
    assert store.jobs_needing_classify() == []
    # ...and `unfail` brings it back
    assert cli._cmd_unfail(argparse.Namespace(limit=None)) == 0
    assert len(store.jobs_needing_classify()) == 1


def _tick_errors(store):
    with store.connect() as c:
        return c.execute(
            "SELECT errors FROM ticks ORDER BY id DESC"
        ).fetchone()["errors"]


def test_an_unreadable_classify_chunk_is_counted_not_silently_skipped(
    store, monkeypatch, capsys, tmp_path
):
    """⚠ THE SECOND LOCUS of the P0-3 failure mode. A corrupt chunk `continue`d
    with NO `errors` bump, so a whole lost chunk closed the tick
    `status=ok errors=0` — indistinguishable from "there was nothing to do".
    This is verbatim what the engine handler below it exists to kill."""
    _seed_cleaned(store, "1")
    chunk = tmp_path / "classify-000.json"
    chunk.write_text("{not json at all", encoding="utf-8")
    store.start_tick()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.engines.build_engine", lambda *a, **kw: _ExplodingEngine()
    )
    rc = cli._cmd_classify_run(argparse.Namespace(engine=None, chunk_file=str(chunk)))
    assert rc == 0
    assert "unreadable_chunks=1" in capsys.readouterr().out
    assert _tick_errors(store) == 1


def test_a_missing_classify_chunk_file_is_counted_too(store, monkeypatch, capsys, tmp_path):
    """OSError, not just a JSON decode error — the same `except`, the same
    previously-silent `continue`."""
    _seed_cleaned(store, "1")
    store.start_tick()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.engines.build_engine", lambda *a, **kw: _ExplodingEngine()
    )
    rc = cli._cmd_classify_run(
        argparse.Namespace(engine=None, chunk_file=str(tmp_path / "gone.json"))
    )
    assert rc == 0
    assert _tick_errors(store) == 1


def test_a_lost_judge_chunk_is_counted_not_silently_skipped(
    store, monkeypatch, capsys, tmp_path
):
    """Same shape in judge-run, both `continue`s. There is no un-fail path to run
    here — the rows keep their classify verdict and stay unjudged — so making the
    loss VISIBLE is the entire fix. `errors=0` said the chunk was never there."""
    _seed_enriched(store, "1", conf=0.5)
    chunk = tmp_path / "judge-000.json"
    chunk.write_text("[[[", encoding="utf-8")
    store.start_tick()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.engines.build_engine", lambda *a, **kw: _ExplodingEngine()
    )
    rc = cli._cmd_judge_run(argparse.Namespace(engine=None, chunk_file=str(chunk)))
    assert rc == 0
    assert "lost_chunks=1" in capsys.readouterr().out
    assert _tick_errors(store) == 1


def test_a_judge_engine_failure_is_counted_too(store, monkeypatch, capsys, tmp_path):
    """The other `continue` in the same loop: a READABLE chunk the engine then
    fails on. Counting one and not the other would just move the blind spot."""
    _seed_enriched(store, "1", conf=0.5)
    chunk = tmp_path / "judge-000.json"
    chunk.write_text(json.dumps([{"job_listing_id": "1", "source_id": "greenhouse"}]),
                     encoding="utf-8")
    store.start_tick()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.engines.build_engine", lambda *a, **kw: _ExplodingJudgeEngine()
    )
    rc = cli._cmd_judge_run(argparse.Namespace(engine=None, chunk_file=str(chunk)))
    assert rc == 0
    assert "lost_chunks=1" in capsys.readouterr().out
    assert _tick_errors(store) == 1


class _ExplodingJudgeEngine:
    name = "boom"

    def judge(self, items):
        from job_enricher.engines import EngineError

        raise EngineError("timed out")


def test_starved_null_recency_appears_in_collect_health(store):
    from job_enricher.health import collect_health

    _seed_cleaned(store, "1")
    assert collect_health(store)["starved_null_recency"] == 1


# ---- ENR-REN-1: reenrich is now guarded ---------------------------------------
# WHY: at v7, `reenrich --taxonomy-below v7+<hash>` matches EVERY v6 row — the
# whole corpus — and the command DELETEs each enrichment with no undo.


def _reenrich_args(**kw):
    base = dict(
        taxonomy_below="v2+cur", dry_run=False, yes_i_mean_all=False, limit=None
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _seed_two_old_rows(store):
    _seed_enriched(store, "1", conf=0.9)
    _seed_enriched(store, "2", conf=0.9)
    with store.connect() as c:
        c.execute("UPDATE enrichments SET taxonomy_version='v1+old'")


def test_reenrich_dry_run_prints_the_count_and_mutates_nothing(store, monkeypatch, capsys):
    _seed_two_old_rows(store)
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_reenrich(_reenrich_args(dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 rows match" in out and "nothing was modified" in out
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 2


def test_reenrich_refuses_above_the_threshold_without_the_flag(store, monkeypatch, capsys):
    _seed_two_old_rows(store)
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(cli, "REENRICH_CONFIRM_THRESHOLD", 1)
    rc = cli._cmd_reenrich(_reenrich_args())
    assert rc == 2
    assert "REFUSING" in capsys.readouterr().err
    with store.connect() as c:  # NOTHING was modified
        assert c.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 2


def test_reenrich_proceeds_above_the_threshold_with_the_flag(store, monkeypatch):
    _seed_two_old_rows(store)
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(cli, "REENRICH_CONFIRM_THRESHOLD", 1)
    assert cli._cmd_reenrich(_reenrich_args(yes_i_mean_all=True)) == 0
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 0


def test_reenrich_below_the_threshold_proceeds(store, monkeypatch):
    _seed_two_old_rows(store)
    monkeypatch.setattr(cli, "Store", lambda: store)
    assert cli._cmd_reenrich(_reenrich_args()) == 0
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 0


def test_reenrich_limit_bounds_the_reset(store, monkeypatch):
    _seed_two_old_rows(store)
    monkeypatch.setattr(cli, "Store", lambda: store)
    assert cli._cmd_reenrich(_reenrich_args(limit=1)) == 0
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 1


def test_reenrich_leaves_same_n_different_hash_alone_and_warns(store, monkeypatch, caplog):
    """Rubric-only edits move the hash and NOT the declared N — same-N-different-
    hash is NOT below, so those rows are warned about and left alone."""
    import logging

    _seed_enriched(store, "1", conf=0.9)
    with store.connect() as c:
        c.execute("UPDATE enrichments SET taxonomy_version='v2+other'")
    monkeypatch.setattr(cli, "Store", lambda: store)
    with caplog.at_level(logging.WARNING):
        assert cli._cmd_reenrich(_reenrich_args()) == 0
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM enrichments").fetchone()[0] == 1
    assert "different" in caplog.text


# ---- subcategory-weak-baseline (EV-11) ----------------------------------------
def _weak_baseline_env(tmp_path, monkeypatch, rows):
    import job_enricher.eval.golden as golden

    seed = tmp_path / "golden.json"
    seed.write_text(json.dumps(rows))
    monkeypatch.setattr(golden, "SEED_FILE", seed)
    monkeypatch.setattr(golden, "SCORECARD_DIR", tmp_path / "scorecards")
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    return tmp_path / "scorecards" / "baseline.weak_rule.json"


_WEAK_SWE_ROW = {
    "job_listing_id": "1", "source_id": "greenhouse", "title": "Backend Engineer",
    "category": "software_engineering", "level": "mid", "tags": [],
    "label_source": "draft", "subcategories": None,
    "gold_subcategory_provenance": None,
}


def test_weak_baseline_refuses_when_the_subcategory_pool_is_empty(
    store, monkeypatch, capsys, tmp_path
):
    """⚠ NOT A DAY-ONE GATE. The rule labeler needs no human labels but SCORING
    it does: with `load_truth(facet='subcategory')` empty, every metric is 0.0
    and "beat 0.0 by 0.10" is a free pass. The card is stamped gate_ready=false
    and the command fails closed."""
    card_path = _weak_baseline_env(tmp_path, monkeypatch, [dict(_WEAK_SWE_ROW)])
    rc = cli._cmd_subcategory_weak_baseline(argparse.Namespace())
    assert rc == 2
    assert "gate_ready=false" in capsys.readouterr().err
    card = json.loads(card_path.read_text())
    assert card["gate_ready"] is False
    assert card["subcategory_n"] == 0
    assert "EMPTY" in card["gate_blocked_reason"]


def test_weak_baseline_allow_empty_pool_still_writes_the_durable_artifact(
    store, monkeypatch, capsys, tmp_path
):
    card_path = _weak_baseline_env(tmp_path, monkeypatch, [dict(_WEAK_SWE_ROW)])
    rc = cli._cmd_subcategory_weak_baseline(
        argparse.Namespace(allow_empty_pool=True)
    )
    assert rc == 0
    assert json.loads(card_path.read_text())["gate_ready"] is False
    art = json.loads(
        (tmp_path / "golden" / "baselines" / "weak_rule"
         / "predictions.weak_rule.json").read_text()
    )
    assert art["predictions"][0]["subcategories"] == ["backend"]


def test_weak_baseline_is_gate_ready_once_the_pool_exists(
    store, monkeypatch, capsys, tmp_path
):
    card_path = _weak_baseline_env(tmp_path, monkeypatch, [dict(
        _WEAK_SWE_ROW, subcategories=["backend"],
        gold_subcategory_provenance="human",
    )])
    assert cli._cmd_subcategory_weak_baseline(argparse.Namespace()) == 0
    card = json.loads(card_path.read_text())
    assert card["gate_ready"] is True
    assert card["gate_blocked_reason"] is None
    assert card["subcategory_n"] == 1
    assert card["subcategory_set_f1"] == 1.0     # the regex types this title


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
    monkeypatch.setattr(golden, "UNMATCHED_WORKLIST", tmp_path / "unmatched.json")

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
    # ⚠ EXIT 2: this stubbed feed is PRE-v7 (no subcategories/taxonomy_version),
    # so the run cannot have written subcategory gold. The category half still
    # merged — the counts below are asserted on the same run.
    assert rc == 2
    captured = capsys.readouterr()
    out = captured.out
    assert "matched=1" in out and "upgraded=1" in out and "unmatched=1" in out
    assert "subcategory_upgraded=0" in out
    assert "v7 CONTRACT VIOLATION" in captured.err
    # EV-16: the printed line NAMES the parked worklist and says the seed does
    # not grow from this feed.
    assert "golden/review/unmatched-corrections.json" in out
    assert "the seed does NOT grow from this feed" in out
    assert len(json.loads(seed.read_text())) == 2   # the unmatched row is NOT appended
    assert json.loads((tmp_path / "unmatched.json").read_text())[0]["job_listing_id"] == "missing"

    rows = json.loads(seed.read_text())
    row1 = next(r for r in rows if r["job_listing_id"] == "1")
    assert row1["category"] == "software_engineering"
    assert row1["level"] == "new_grad"
    assert row1["level_includes"] == ["new_grad", "entry"]
    assert row1["tags"] == ["python"]
    assert row1["label_source"] == "human"
    # untouched row stays draft
    assert next(r for r in rows if r["job_listing_id"] == "2")["label_source"] == "draft"


def _merge_seed(tmp_path, monkeypatch, rows):
    import job_enricher.eval.golden as golden

    seed = tmp_path / "golden.json"
    seed.write_text(json.dumps(rows))
    monkeypatch.setattr(golden, "SEED_FILE", seed)
    monkeypatch.setattr(golden, "UNMATCHED_WORKLIST", tmp_path / "unmatched.json")
    return seed


def _stub_corrections(monkeypatch, corrections):
    class _CorrClient:
        def get_corrections(self, since=None, limit=None):
            return corrections

    import job_enricher.jvn_client as jc
    monkeypatch.setattr(jc, "JVNClient", lambda: _CorrClient())


_SWE_SEED_ROW = {
    "job_listing_id": "1", "source_id": "greenhouse", "title": "SWE",
    "category": "software_engineering", "level": "mid", "level_includes": ["mid"],
    "tags": [], "label_source": "draft", "subcategories": None,
    "gold_subcategory_provenance": None,
}


def test_golden_merge_refuses_a_pre_v7_feed_instead_of_a_green_no_op(
    store, monkeypatch, capsys, tmp_path
):
    """⚠ THE CONTRACT RAIL, ON THE PRODUCTION PATH. `missing_v7_correction_keys`
    used to have no caller outside a unit test over literal dicts, so a
    /corrections feed shipped without `subcategories`/`taxonomy_version` (ADM-5
    slipping) made golden-merge print matched=N upgraded=N, exit 0, and write
    ZERO subcategory gold. It must exit 2 and name the missing keys."""
    seed = _merge_seed(tmp_path, monkeypatch, [dict(_SWE_SEED_ROW)])
    _stub_corrections(monkeypatch, [
        {"job_listing_id": "1", "source_id": "greenhouse",
         "category": "software_engineering", "level": "mid", "tags": ["python"],
         "corrected_at": "t"},
    ])
    rc = cli._cmd_golden_merge(argparse.Namespace(since=None, limit=None))
    assert rc == 2
    cap = capsys.readouterr()
    assert "subcategory_upgraded=0" in cap.out
    assert "v7 CONTRACT VIOLATION" in cap.err
    assert "'subcategories'" in cap.err and "'taxonomy_version'" in cap.err
    assert "greenhouse/1" in cap.err
    # the category half is still real work and still landed
    assert json.loads(seed.read_text())[0]["label_source"] == "human"


def test_golden_merge_refuses_a_half_v7_feed(store, monkeypatch, capsys, tmp_path):
    """One key present is not the contract — `taxonomy_version` alone missing
    means the gold row could not be stamped with the taxonomy it was labelled
    under."""
    _merge_seed(tmp_path, monkeypatch, [dict(_SWE_SEED_ROW)])
    _stub_corrections(monkeypatch, [
        {"job_listing_id": "1", "source_id": "greenhouse",
         "category": "software_engineering", "level": "mid", "tags": [],
         "subcategories": ["backend"]},
    ])
    assert cli._cmd_golden_merge(argparse.Namespace(since=None, limit=None)) == 2
    assert "'taxonomy_version'" in capsys.readouterr().err


def test_golden_merge_is_green_and_counts_subcategory_gold_on_a_v7_feed(
    store, monkeypatch, capsys, tmp_path
):
    seed = _merge_seed(tmp_path, monkeypatch, [dict(_SWE_SEED_ROW)])
    _stub_corrections(monkeypatch, [
        {"job_listing_id": "1", "source_id": "greenhouse",
         "category": "software_engineering", "level": "mid", "tags": [],
         "subcategories": ["backend"], "taxonomy_version": "v7+abc123def456"},
    ])
    assert cli._cmd_golden_merge(argparse.Namespace(since=None, limit=None)) == 0
    cap = capsys.readouterr()
    assert "subcategory_upgraded=1" in cap.out
    assert "CONTRACT VIOLATION" not in cap.err
    row = json.loads(seed.read_text())[0]
    assert row["subcategories"] == ["backend"]
    assert row["gold_subcategory_provenance"] == "human"


def test_golden_merge_allow_pre_v7_still_prints_the_violation(
    store, monkeypatch, capsys, tmp_path
):
    """The escape hatch downgrades the exit code and NOTHING else — a
    category-only merge before ADM-5 stays possible, and stays loud."""
    _merge_seed(tmp_path, monkeypatch, [dict(_SWE_SEED_ROW)])
    _stub_corrections(monkeypatch, [
        {"job_listing_id": "1", "source_id": "greenhouse",
         "category": "software_engineering", "level": "mid", "tags": []},
    ])
    rc = cli._cmd_golden_merge(
        argparse.Namespace(since=None, limit=None, allow_pre_v7=True)
    )
    assert rc == 0
    assert "v7 CONTRACT VIOLATION" in capsys.readouterr().err


def test_golden_merge_on_an_empty_feed_is_green(store, monkeypatch, capsys, tmp_path):
    """No corrections is not a contract violation — there is nothing to violate."""
    _merge_seed(tmp_path, monkeypatch, [dict(_SWE_SEED_ROW)])
    _stub_corrections(monkeypatch, [])
    assert cli._cmd_golden_merge(argparse.Namespace(since=None, limit=None)) == 0
    assert "CONTRACT VIOLATION" not in capsys.readouterr().err


def test_golden_merge_nulls_subcategories_when_the_category_leaves_swe(
    store, monkeypatch, capsys, tmp_path
):
    """⚠ The arrow never runs backwards: a correction moving a row off
    software_engineering must clear its subcategories in the SAME write, or the
    stale list scores as gold on a row that cannot have one."""
    import job_enricher.eval.golden as golden

    seed = tmp_path / "golden.json"
    seed.write_text(json.dumps([
        {"job_listing_id": "1", "source_id": "greenhouse", "title": "SWE",
         "category": "software_engineering", "level": "mid", "tags": [],
         "label_source": "draft", "subcategories": ["backend"],
         "gold_subcategory_provenance": "human"},
    ]))
    monkeypatch.setattr(golden, "SEED_FILE", seed)
    monkeypatch.setattr(golden, "UNMATCHED_WORKLIST", tmp_path / "unmatched.json")

    class _CorrClient:
        def get_corrections(self, since=None, limit=None):
            return [{"job_listing_id": "1", "source_id": "greenhouse",
                     "category": "data_scientist", "level": "mid", "tags": [],
                     "subcategories": None, "taxonomy_version": "v7+abc123def456"}]

    import job_enricher.jvn_client as jc
    monkeypatch.setattr(jc, "JVNClient", lambda: _CorrClient())
    assert cli._cmd_golden_merge(argparse.Namespace(since=None, limit=None)) == 0
    row = json.loads(seed.read_text())[0]
    assert row["category"] == "data_scientist"
    assert row["subcategories"] == []
    assert row["gold_subcategory_provenance"] == "contract"


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
    # ...and the engine, which is authoritative — the Claude-tier model fields
    # above are inert unless the matching engine is claude-code
    assert health["classify_engine"] == "ollama"
    assert health["judge_engine"] == "ollama"
    assert health["opencode_model"] == "qwen3:32b"


def test_health_exits_2_when_a_taxonomy_file_is_missing(store, monkeypatch, tmp_path, capsys):
    """⚠ THE DEPLOY SANITY CHECK, and until now only its happy path was tested.
    `deploy.sh` step 6 runs `cli health`; if `SUBCATEGORIES.md` is absent the
    backfill lane would label every row from an empty rubric and still report
    success. This branch is the one guard against that."""
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(tax, "subcategory_rubric_path",
                        lambda: tmp_path / "nope" / "SUBCATEGORIES.md")
    rc = cli._cmd_health(argparse.Namespace())
    out, err = capsys.readouterr()
    assert rc == 2
    assert "MISSING taxonomy file(s)" in err
    assert "SUBCATEGORIES.md" in err
    assert out == ""      # and NO health JSON: a caller must not read this as ok


def test_health_reports_every_missing_file_not_just_the_first(store, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(tax, "skill_path", lambda: tmp_path / "nope" / "SKILL.md")
    monkeypatch.setattr(tax, "subcategory_rubric_path",
                        lambda: tmp_path / "nope" / "SUBCATEGORIES.md")
    assert cli._cmd_health(argparse.Namespace()) == 2
    err = capsys.readouterr().err
    assert "SKILL.md" in err and "SUBCATEGORIES.md" in err


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


# ---- eval-run classify coverage/drops counter ------------------------------
# _cmd_eval_run prints "eval-run: classify coverage N/total (drops=D)" where N is
# the number of golden rows whose OWN (source_id, job_listing_id) landed in
# classify_by_key — deliberately a MEMBERSHIP count, not len(classify_by_key),
# so at batch>1 a hallucinated/mis-echoed key can't misreport the drop count.
# This is the exact number the docs cite as proof the row-drop fix works.
class _FakeEvalEngine:
    """Deterministic stand-in for build_engine(...) inside _cmd_eval_run, giving
    full control over which input keys end up in classify_by_key:
      - "all"     every row echoed under its own key       -> full coverage
      - "misecho" `target` echoed under a WRONG source_id  -> its input key is
                  absent, yet classify_by_key still holds `total` entries, so a
                  len()-based counter would wrongly report drops=0 (the case that
                  proves the counter counts membership, not raw returned length)
      - "drop"    `target` omitted from the returned list   -> input key absent
    """

    def __init__(self, mode, target_key):
        self.name = "fake"
        self._mode = mode
        self._target = target_key

    @staticmethod
    def _pred(source_id, job_listing_id):
        return {
            "job_listing_id": job_listing_id, "source_id": source_id,
            "category": "software_engineering", "level": "mid",
            "level_includes": ["mid"], "tags": ["backend"], "locations": [],
            "confidence": 0.8, "reasoning": "fake", "classify_latency_ms": 1,
        }

    def classify(self, jobs):
        out = []
        for j in jobs:
            key = (j["source_id"], j["job_listing_id"])
            if key == self._target:
                if self._mode == "drop":
                    continue  # row vanishes -> its input key never recorded
                if self._mode == "misecho":
                    out.append(self._pred("WRONG", j["job_listing_id"]))
                    continue
            out.append(self._pred(j["source_id"], j["job_listing_id"]))
        return out

    def judge(self, items):  # unused with --judge off; present for contract parity
        return [{"job_listing_id": it["job_listing_id"], "source_id": it["source_id"],
                 "passed": True, "confidence": 0.9, "corrections": {}} for it in items]


_EVAL_GOLDEN_ROWS = [
    {"source_id": "gh", "job_listing_id": "1", "clean_description": "desc one",
     "title": "SWE", "company": "Acme", "raw_location": "SF", "label_source": "human"},
    {"source_id": "gh", "job_listing_id": "2", "clean_description": "desc two",
     "title": "SWE", "company": "Acme", "raw_location": "SF", "label_source": "human"},
    # same job_listing_id "1" as the first row but a different source -> forces the
    # counter to key on the composite (source_id, job_listing_id) pair, not the bare id.
    {"source_id": "lever", "job_listing_id": "1", "clean_description": "desc three",
     "title": "SWE", "company": "Beta", "raw_location": "NY", "label_source": "human"},
]


@pytest.mark.parametrize("mode,expected_covered,expected_drops", [
    ("all", 3, 0),
    ("misecho", 2, 1),
    ("drop", 2, 1),
])
def test_eval_run_classify_coverage_counts_input_key_membership(
    store, monkeypatch, capsys, tmp_path, mode, expected_covered, expected_drops
):
    """The 'classify coverage N/total (drops=D)' line counts golden rows whose own
    input key made it into classify_by_key. `all` -> 3/3 drops=0; `drop`/`misecho`
    -> 2/3 drops=1. `misecho` is the discriminator: the engine returns 3 dicts (one
    keyed under a bogus source_id), so a len(classify_by_key) counter would say
    drops=0 — membership correctly reports drops=1."""
    target = ("lever", "1")
    # build_engine is imported inside _cmd_eval_run from job_enricher.engines, so
    # patch it at that module; load_seed / _predictions_path are likewise re-imported
    # in-function, so patch them at their source modules too.
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.eval.golden.load_seed", lambda: [dict(r) for r in _EVAL_GOLDEN_ROWS]
    )
    monkeypatch.setattr(
        "job_enricher.engines.build_engine",
        lambda kind, model=None: _FakeEvalEngine(mode, target),
    )
    monkeypatch.setattr(
        "job_enricher.eval.report._predictions_path",
        lambda judge, engine=None, tag=None: tmp_path
        / (
            ".".join(
                ["predictions"]
                + ([tag] if tag else [])
                + ([engine] if engine else [])
                + (["judge_off"] if judge == "off" else [])
            )
            + ".json"
        ),
    )

    args = argparse.Namespace(
        engine="ollama", set="golden", judge="off", batch=2, limit=None,
        human_only=False, classify_model="fake-model", judge_model="fake-model",
        tag=None,
    )
    rc = cli._cmd_eval_run(args)

    assert rc == 0
    err = capsys.readouterr().err
    assert (
        f"eval-run: classify coverage {expected_covered}/3 (drops={expected_drops})" in err
    )


# ---- dashboard: refuses to serve from a scratch git worktree ----------------
def test_dashboard_refuses_worktree_checkout(monkeypatch, caplog):
    monkeypatch.setattr(
        cli, "REPO_ROOT", Path("/Users/x/job-enricher/.claude/worktrees/scratch")
    )
    args = argparse.Namespace(host="127.0.0.1", port=None, allow_remote=False, api_only=False)
    rc = cli._cmd_dashboard(args)
    assert rc == 2
    assert "worktree" in caplog.text


def test_dashboard_warns_off_main_but_still_serves(monkeypatch, caplog):
    monkeypatch.setattr(cli, "REPO_ROOT", Path("/Users/x/job-enricher"))
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: argparse.Namespace(stdout="feature/foo\n"),
    )
    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: calls.setdefault("ran", True))
    args = argparse.Namespace(host="127.0.0.1", port=8788, allow_remote=False, api_only=False)
    rc = cli._cmd_dashboard(args)
    assert rc == 0
    assert calls.get("ran") is True
    assert "not main" in caplog.text


# ---- P0-4: the scope importer -------------------------------------------------
def test_scope_import_is_idempotent_and_prints_the_three_numbers(
    store, monkeypatch, capsys, tmp_path
):
    _seed_enriched(store, "1", conf=0.9)
    ndjson = tmp_path / "scope.ndjson"
    ndjson.write_text(
        '{"source_id":"greenhouse","job_listing_id":"1"}\n'
        '{"source_id":"greenhouse","job_listing_id":"999"}\n'
    )
    monkeypatch.setattr(cli, "Store", lambda: store)
    assert cli._cmd_subcategory_scope_import(argparse.Namespace(json_file=str(ndjson))) == 0
    out = capsys.readouterr().out
    assert "imported=2 matched_local=1 missing_local=1" in out
    assert "PARAM_BACKFILL_DENOMINATOR" in out
    # idempotent
    assert cli._cmd_subcategory_scope_import(argparse.Namespace(json_file=str(ndjson))) == 0
    assert "imported=2 matched_local=1" in capsys.readouterr().out


def test_scope_import_refuses_an_empty_file(store, monkeypatch, capsys, tmp_path):
    """⚠ A silently-empty scope makes --open-only a no-op that reports success."""
    empty = tmp_path / "empty.ndjson"
    empty.write_text("")
    monkeypatch.setattr(cli, "Store", lambda: store)
    assert cli._cmd_subcategory_scope_import(argparse.Namespace(json_file=str(empty))) == 2
    assert "REFUSING" in capsys.readouterr().err


def test_scope_import_refuses_a_missing_file(store, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "Store", lambda: store)
    assert cli._cmd_subcategory_scope_import(
        argparse.Namespace(json_file=str(tmp_path / "nope.ndjson"))
    ) == 2


def test_scope_freshness_check_refuses_empty_and_stale(store):
    assert "EMPTY" in cli.check_backfill_scope_freshness(store)
    store.import_backfill_scope([("greenhouse", "1")])
    assert cli.check_backfill_scope_freshness(store) is None
    with store.connect() as c:  # backdate it
        c.execute("UPDATE backfill_scope SET imported_at='2020-01-01T00:00:00+00:00'")
    assert "old" in cli.check_backfill_scope_freshness(store)


# ---- ENR-CLS-1: the absent-vs-empty sentinel + the tick counters ---------------
def _swe_item(jid, **extra):
    item = {
        "job_listing_id": jid, "source_id": "greenhouse",
        "category": "software_engineering", "level": "mid",
        "level_includes": ["mid"], "tags": ["backend"], "locations": [],
        "confidence": 0.9, "reasoning": "r",
    }
    item.update(extra)
    return item


def _record(store, items):
    return cli.record_enrichment_items(store, items, "v7+abc", classify_model="haiku")


def test_swe_row_with_a_list_records_it_with_source_classify(store):
    _seed_cleaned(store, "1")
    res = _record(store, [_swe_item("1", subcategories=["backend"])])
    row = _enrichment(store, "1")
    assert row["subcategories"] == '["backend"]'
    assert row["subcategory_source"] == "classify"
    assert res["subcategory_recorded"] == 1


def test_non_swe_row_carrying_subcategories_is_nulled_and_flagged(store):
    _seed_cleaned(store, "1")
    res = _record(
        store,
        [_swe_item("1", category="business_ops", subcategories=["backend"])],
    )
    row = _enrichment(store, "1")
    assert row["subcategories"] is None
    assert row["needs_human"] == 1
    assert res["nulled_facets"] == 1


def test_ABSENT_key_on_an_swe_row_stays_NULL_with_no_source(store):
    """⚠ THE TRI-STATE, HALF ONE. The model omitted the field, so the row must
    stay in the backfill queue — NULL, and stamped with no provenance it never had."""
    _seed_cleaned(store, "1")
    res = _record(store, [_swe_item("1")])          # no `subcategories` key at all
    row = _enrichment(store, "1")
    assert row["subcategories"] is None
    assert row["subcategory_source"] is None
    assert res["subcategory_missing"] == 1
    assert res["subcategory_recorded"] == 0


def test_EXPLICIT_empty_list_on_an_swe_row_stores_the_string_bracket_bracket(store):
    """⚠ THE TRI-STATE, HALF TWO — asserted ON THE DB, not on the counters. `[]`
    is TERMINAL: the row leaves the backfill queue forever."""
    _seed_cleaned(store, "1")
    res = _record(store, [_swe_item("1", subcategories=[])])
    row = _enrichment(store, "1")
    assert row["subcategories"] == "[]"       # NOT None
    assert row["subcategory_source"] == "classify"
    assert res["subcategory_empty"] == 1


@pytest.mark.parametrize("junk", [{"a": 1}, 7, True])
def test_junk_subcategories_never_raises_and_nulls_the_field(store, junk):
    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", subcategories=junk)])
    assert _enrichment(store, "1")["subcategories"] is None


def test_dict_subcategory_confidence_coerces_to_none(store):
    """The class of bug commit bf3be25 fixed: a dict confidence crashed the
    sqlite bind and silently stalled classify."""
    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", subcategories=["backend"],
                              subcategory_confidence={"backend": 0.9})])
    assert _enrichment(store, "1")["subcategory_confidence"] is None


def test_three_slugs_truncate_to_two_WITHOUT_needs_human(store):
    _seed_cleaned(store, "1")
    res = _record(
        store,
        [_swe_item("1", subcategories=["backend", "frontend", "security"])],
    )
    row = _enrichment(store, "1")
    assert json.loads(row["subcategories"]) == ["backend", "frontend"]
    assert row["needs_human"] == 0          # truncation is a rule, not a hallucination
    assert res["subcategory_truncated"] == 1


def test_full_stack_suppresses_backend(store):
    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", subcategories=["full_stack", "backend"])])
    assert _enrichment(store, "1")["subcategories"] == '["full_stack"]'


def test_needs_judge_does_NOT_fire_on_null_subcategories_alone(store):
    """⚠ STANDING REGRESSION. Roughly half the corpus is software_engineering, so
    a `SWE and subcategories IS NULL` clause in _needs_judge would route half of
    it to the judge and blow up judge volume on a lane already at capacity."""
    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", confidence=0.99)])   # confident, no subcategories
    row = _enrichment(store, "1")
    assert row["subcategories"] is None
    assert cli._needs_judge(row, ceiling=0.85) is False


def test_a_three_row_batch_bumps_all_three_tick_counters(store):
    """⚠ ASSERTED ON THE TICKS ROW. bump_tick_counters silently drops any key
    absent from TICK_COUNTER_COLS, so the return value proves nothing."""
    for jid in ("1", "2", "3"):
        _seed_cleaned(store, jid)
    store.start_tick()
    _record(store, [
        _swe_item("1", subcategories=["backend"]),   # labelled
        _swe_item("2", subcategories=[]),            # evaluated, none apply
        _swe_item("3"),                              # absent -> never evaluated
    ])
    with store.connect() as c:
        row = c.execute("SELECT * FROM ticks ORDER BY id DESC").fetchone()
    assert row["swe_classified"] == 3
    assert row["swe_subcat_evaluated"] == 2
    assert row["swe_subcategorized"] == 1


def test_coerce_subcategories_field_preserves_none(store):
    """⚠ The regression guard on the ONE line that would destroy the tri-state:
    _coerce_json_field turns None into '[]'; _coerce_subcategories_field must not."""
    assert cli._coerce_subcategories_field(None) is None
    assert cli._coerce_json_field(None) == "[]"
    assert cli._coerce_subcategories_field([]) == "[]"
    assert cli._coerce_subcategories_field(["backend"]) == '["backend"]'


# ---- ENR-CLS-2: the four subcategory rails in _merge_judge --------------------
def _judge_base(subcategories=None, category="software_engineering"):
    return {
        "job_listing_id": "1", "source_id": "greenhouse",
        "category": category, "level": "mid",
        "level_includes": '["mid"]', "tags": "[]", "locations": "[]",
        "subcategories": subcategories, "needs_human": False,
    }


def _verdict(conf, **corrections):
    return {"passed": False, "confidence": conf, "corrections": corrections}


def test_a_valid_subcategory_correction_at_0_9_applies():
    merged = cli._merge_judge(
        _judge_base('["backend"]'), _verdict(0.9, subcategories=["frontend"]), 0.6
    )
    assert merged["subcategories"] == '["frontend"]'
    assert merged["rejected_corrections"] == 0


def test_rail_B_a_correction_at_0_7_is_rejected_counted_and_NOT_needs_human():
    """⚠ needs_human is reserved for the new_grad/entry equivalence — forcing it
    here would flood the triage queue."""
    merged = cli._merge_judge(
        _judge_base('["backend"]'), _verdict(0.7, subcategories=["frontend"]), 0.6
    )
    assert merged["subcategories"] == '["backend"]'      # unchanged
    assert merged["rejected_corrections"] == 1
    assert merged["needs_human"] is False
    assert "subcategories correction" in merged["judge_notes"]


def test_rail_B_confidence_none_rejects():
    merged = cli._merge_judge(
        _judge_base('["backend"]'), _verdict(None, subcategories=["frontend"]), 0.6
    )
    assert merged["subcategories"] == '["backend"]'
    assert merged["rejected_corrections"] == 1


def test_rail_A_the_knob_off_drops_the_correction_at_any_confidence():
    merged = cli._merge_judge(
        _judge_base('["backend"]'), _verdict(0.99, subcategories=["frontend"]), 0.6,
        subcategory_corrections=False,
    )
    assert merged["subcategories"] == '["backend"]'
    assert "judge:subcategory_corrections is off" in merged["judge_notes"]


def test_rail_D_a_category_off_swe_forces_empty_list_not_null():
    """⚠ `[]`, NOT NULL — the row WAS evaluated and the answer is 'not
    applicable', so it must LEAVE the backfill queue rather than sit in it."""
    merged = cli._merge_judge(
        _judge_base('["backend"]'),
        _verdict(0.95, category="business_ops", subcategories=["backend"]),
        0.6,
    )
    assert merged["category"] == "business_ops"
    assert merged["subcategories"] == "[]"


def test_rail_C_a_judge_pass_on_a_NULL_row_leaves_it_NULL():
    """⚠ THE RAIL C REGRESSION. `is None`, not `== '[]'`. Turning 'never
    evaluated' into 'evaluated, none apply' silently drains the backfill queue and
    makes the coverage number that gates the 90% reveal a lie."""
    merged = cli._merge_judge(
        _judge_base(None), {"passed": True, "confidence": 0.9, "corrections": {}}, 0.6
    )
    assert merged["subcategories"] is None
    assert merged["subcategories"] != "[]"


def test_a_hallucinated_slug_from_the_judge_is_nulled_and_flags_needs_human():
    merged = cli._merge_judge(
        _judge_base('["backend"]'), _verdict(0.95, subcategories=["ai_ml"]), 0.6
    )
    assert merged["subcategories"] == "[]"   # the bad slug dropped, list emptied
    assert merged["needs_human"] is True


# ---- the judge's subcategory CONFIDENCE + SOURCE travel with the array -------
# ⚠ `writeback._row_to_result` re-applies contract 1.2 A on the wire, so a stale
# confidence is invisible in the payload. The STORED column is the corrupted one,
# and `job_detail`, the eval artifacts and BF-12b's D2 drain all read THAT.
# Every assertion below is therefore on the merge result or on a READ-BACK.

def _judge_base_with_provenance(subcategories, conf, source,
                                category="software_engineering"):
    base = _judge_base(subcategories, category=category)
    base["subcategory_confidence"] = conf
    base["subcategory_source"] = source
    return base


def test_rail_D_forcing_empty_also_clears_the_stale_confidence_and_restamps_source():
    """THE LIVE REPRO. classify stores (["backend"], 0.91, 'classify'); the judge
    moves the category to business_ops; RAIL D forces `[]`. The row must NOT keep
    ('[]', 0.91, 'classify') — contract 1.2 A requires a null confidence whenever
    the array is `[]`, and the lane that wrote the row is now the judge."""
    merged = cli._merge_judge(
        _judge_base_with_provenance('["backend"]', 0.91, "classify"),
        _verdict(0.95, category="business_ops", subcategories=["backend"]),
        0.6,
    )
    assert merged["subcategories"] == "[]"
    assert merged["subcategory_confidence"] is None
    assert merged["subcategory_source"] == "judge"


def test_a_label_change_clears_the_confidence_that_belonged_to_the_old_label():
    """0.91 was measured against `backend`. After the judge moves the row to
    `frontend` that number describes a label the row no longer carries."""
    merged = cli._merge_judge(
        _judge_base_with_provenance('["backend"]', 0.91, "classify"),
        _verdict(0.9, subcategories=["frontend"]),
        0.6,
    )
    assert merged["subcategories"] == '["frontend"]'
    assert merged["subcategory_confidence"] is None
    assert merged["subcategory_source"] == "judge"


def test_an_unchanged_subcategory_keeps_classifys_confidence_AND_source():
    """The other half of the rule: stamping every judged row 'judge' would break
    a scoped rollback just as badly in the other direction — a row the judge
    merely AGREED with was still written by classify."""
    merged = cli._merge_judge(
        _judge_base_with_provenance('["backend"]', 0.91, "classify"),
        {"passed": True, "confidence": 0.95, "corrections": {}},
        0.6,
    )
    assert merged["subcategories"] == '["backend"]'
    assert merged["subcategory_confidence"] == 0.91
    assert merged["subcategory_source"] == "classify"


def test_a_rejected_correction_leaves_the_confidence_and_source_alone():
    """RAIL B rejected the correction, so the array never moved — neither may
    its provenance."""
    merged = cli._merge_judge(
        _judge_base_with_provenance('["backend"]', 0.91, "classify"),
        _verdict(0.7, subcategories=["frontend"]),
        0.6,
    )
    assert merged["subcategories"] == '["backend"]'
    assert merged["subcategory_confidence"] == 0.91
    assert merged["subcategory_source"] == "classify"


def test_a_never_evaluated_row_the_judge_leaves_alone_carries_no_source():
    """§1.2 A: source is absent/null when the array is null. A NULL row must not
    pick up a provenance it never had, or the backfill lane cannot find it."""
    merged = cli._merge_judge(
        _judge_base_with_provenance(None, None, None),
        {"passed": True, "confidence": 0.9, "corrections": {}}, 0.6,
    )
    assert merged["subcategories"] is None
    assert merged["subcategory_confidence"] is None
    assert merged["subcategory_source"] is None


def test_record_judge_PERSISTS_the_cleared_confidence_and_the_judge_source(store):
    """READ-BACK through the real UPDATE. `_merge_judge` computing the right
    values is worth nothing if `record_judge`'s statement does not write them —
    that was the second locus of the same bug."""
    _seed_enriched(store, "1", conf=0.5, subcategories='["backend"]',
                   subcategory_confidence=0.91, subcategory_source="classify")
    assert _enrichment(store, "1")["subcategory_source"] == "classify"

    cli.apply_judge_verdicts(
        store,
        [{"job_listing_id": "1", "source_id": "greenhouse", "passed": False,
          "confidence": 0.95, "corrections": {"category": "business_ops"}}],
        floor=0.6,
    )
    row = _enrichment(store, "1")
    assert row["category"] == "business_ops"
    assert row["subcategories"] == "[]"          # RAIL D: evaluated, none apply
    assert row["subcategory_confidence"] is None  # NOT the stale 0.91
    assert row["subcategory_source"] == "judge"   # NOT the stale 'classify'


def test_record_judge_does_not_disturb_provenance_when_the_judge_agrees(store):
    _seed_enriched(store, "1", conf=0.5, subcategories='["backend"]',
                   subcategory_confidence=0.91, subcategory_source="classify")
    cli.apply_judge_verdicts(
        store,
        [{"job_listing_id": "1", "source_id": "greenhouse", "passed": True,
          "confidence": 0.95, "corrections": {}}],
        floor=0.6,
    )
    row = _enrichment(store, "1")
    assert row["subcategories"] == '["backend"]'
    assert row["subcategory_confidence"] == 0.91
    assert row["subcategory_source"] == "classify"


def test_the_judge_source_is_one_of_the_five_declared_values():
    """`taxonomy.SUBCATEGORY_SOURCES` is asserted cross-repo (SCHEMA-15 /
    ENR-PAR-2); a source string this repo invents would pass every local test and
    fail on the far side."""
    merged = cli._merge_judge(
        _judge_base_with_provenance('["backend"]', 0.91, "classify"),
        _verdict(0.9, subcategories=["frontend"]), 0.6,
    )
    assert merged["subcategory_source"] in tax.SUBCATEGORY_SOURCES


def test_the_knob_defaults_true_and_rides_config_snapshot(store):
    assert ec.get_judge_subcategory_corrections(store) is True
    assert ec.config_snapshot(store)["judge_subcategory_corrections"] is True
    ec.set_judge_subcategory_corrections(store, False)
    assert ec.get_judge_subcategory_corrections(store) is False
    assert ec.config_snapshot(store)["judge_subcategory_corrections"] is False


# ---- ENR-CLS-3: subcategories on BOTH eval artifacts --------------------------
# ⚠ `_eval_classify_pred` and `_eval_post_judge_pred` are HAND-WRITTEN KEY LISTS.
# A field absent from them is silently absent from every eval artifact, and every
# subcategory metric reads 0.0 with no error anywhere. Under D3 this is the ONLY
# channel that can tell you whether the compact section 1b is good enough.

def test_classify_prediction_carries_both_subcategory_keys():
    cp = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering",
         "level": "mid", "subcategories": ["backend"], "subcategory_confidence": 0.8},
        "desc",
    )
    assert cp["subcategories"] == ["backend"]
    assert cp["subcategory_confidence"] == 0.8


def test_None_survives_as_None_through_BOTH_functions():
    """⚠ NOT coerced to []. The eval must distinguish 'the model omitted it' from
    'the model said none apply' — that distinction IS a metric."""
    cp = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh",
         "category": "software_engineering", "level": "mid"},
        "desc",
    )
    assert cp["subcategories"] is None
    assert cp["subcategories"] != []

    pj = cli._eval_post_judge_pred(
        cp, {"passed": True, "confidence": 0.9, "corrections": {}}, 0.6
    )
    assert pj["subcategories"] is None
    assert pj["subcategories"] != []


def test_the_eval_artifact_mirrors_the_column_production_stores():
    """⚠ EVAL/PROD PARITY ON THE CONFIDENCE. `_eval_post_judge_pred` runs the
    SAME `_merge_judge` rails, so it must take the merge's own answer: a judge
    that MOVES the label invalidates the classify confidence, and an artifact
    that kept 0.8 would calibrate against a label the row no longer carries —
    on exactly the corrected rows the artifact exists to measure."""
    cp = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering",
         "level": "mid", "subcategories": ["backend"], "subcategory_confidence": 0.8},
        "desc",
    )
    # judge leaves the label alone -> classify's confidence stands
    kept = cli._eval_post_judge_pred(
        cp, {"passed": True, "confidence": 0.95, "corrections": {}}, 0.6
    )
    assert kept["subcategories"] == ["backend"]
    assert kept["subcategory_confidence"] == 0.8

    # judge moves the label -> the old confidence goes with it
    moved = cli._eval_post_judge_pred(
        cp,
        {"passed": False, "confidence": 0.95, "corrections": {"subcategories": ["frontend"]}},
        0.6,
    )
    assert moved["subcategories"] == ["frontend"]
    assert moved["subcategory_confidence"] is None


def test_post_judge_prediction_reflects_a_correction_that_passed_the_rail():
    cp = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering",
         "level": "mid", "subcategories": ["backend"]},
        "desc",
    )
    pj = cli._eval_post_judge_pred(
        cp,
        {"passed": False, "confidence": 0.95,
         "corrections": {"subcategories": ["full_stack"]}},
        0.6,
    )
    assert pj["subcategories"] == ["full_stack"]


def test_post_judge_prediction_is_empty_when_the_judge_moved_the_category_off_swe():
    cp = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering",
         "level": "mid", "subcategories": ["backend"]},
        "desc",
    )
    pj = cli._eval_post_judge_pred(
        cp,
        {"passed": False, "confidence": 0.95, "corrections": {"category": "growth"}},
        0.6,
    )
    assert pj["category"] == "growth"
    assert pj["subcategories"] == []


def test_both_artifacts_have_the_key_even_when_the_model_said_nothing():
    """The `jq '.[0] | has("subcategories")'` acceptance, in code."""
    cp = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh",
         "category": "business_ops", "level": "mid"},
        "desc",
    )
    pj = cli._eval_post_judge_pred(
        cp, {"passed": True, "confidence": 0.9, "corrections": {}}, 0.6
    )
    assert "subcategories" in cp and "subcategory_confidence" in cp
    assert "subcategories" in pj and "subcategory_confidence" in pj


# ---- SHARED CONTRACT 1.2 A: no confidence without a label ---------------------
# "`subcategory_confidence` MUST be null when the array is `[]` or null."
# ⚠ These are SILENT-failure tests: the contradictory row persists fine, ships
# fine and counts as `written`; the damage only shows up as subcategory-
# confidence calibration measured over rows that carry no subcategory at all.

def test_confidence_is_nulled_when_the_model_omitted_the_array(store):
    """⚠ The observed model shape: no `subcategories` key, but a confidence
    anyway. NULL array + 0.7 would be a confidence with nothing behind it."""
    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", subcategory_confidence=0.7)])
    row = _enrichment(store, "1")
    assert row["subcategories"] is None
    assert row["subcategory_confidence"] is None


def test_confidence_is_nulled_when_the_array_is_explicitly_empty(store):
    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", subcategories=[], subcategory_confidence=0.7)])
    row = _enrichment(store, "1")
    assert row["subcategories"] == "[]"          # the tri-state is untouched
    assert row["subcategory_confidence"] is None


def test_confidence_is_nulled_when_validation_empties_the_array(store):
    """A non-SWE row carrying slugs is forced to NULL by validate_subcategories;
    the confidence must follow the RESOLVED value, not the raw item."""
    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", category="business_ops",
                              subcategories=["backend"], subcategory_confidence=0.7)])
    row = _enrichment(store, "1")
    assert row["subcategories"] is None
    assert row["subcategory_confidence"] is None


def test_confidence_survives_on_a_genuinely_labelled_row(store):
    """The rule only nulls the contradiction — it must not eat a real value."""
    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", subcategories=["backend"],
                              subcategory_confidence=0.82)])
    row = _enrichment(store, "1")
    assert row["subcategory_confidence"] == 0.82


def test_eval_classify_prediction_obeys_the_same_rule():
    absent = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering",
         "level": "mid", "subcategory_confidence": 0.7},
        "desc",
    )
    assert absent["subcategories"] is None
    assert absent["subcategory_confidence"] is None

    empty = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering",
         "level": "mid", "subcategories": [], "subcategory_confidence": 0.7},
        "desc",
    )
    assert empty["subcategories"] == []
    assert empty["subcategory_confidence"] is None


def test_eval_post_judge_confidence_clears_when_the_judge_clears_the_array():
    """The judge moves the category off SWE, so the merged array becomes [] —
    the confidence carried over from classify has to clear with it."""
    cp = cli._eval_classify_pred(
        {"job_listing_id": "1", "source_id": "gh", "category": "software_engineering",
         "level": "mid", "subcategories": ["backend"], "subcategory_confidence": 0.9},
        "desc",
    )
    assert cp["subcategory_confidence"] == 0.9
    pj = cli._eval_post_judge_pred(
        cp,
        {"passed": False, "confidence": 0.95, "corrections": {"category": "growth"}},
        0.6,
    )
    assert pj["subcategories"] == []
    assert pj["subcategory_confidence"] is None


# ---- EV-13: the BACKFILL lane's eval ------------------------------------------
class _FakeBackfillEngine:
    """Captures the prompt `ChunkEngine.subcategory` would build, then replies."""

    captured_prompts: list[str] = []

    subcategory_schema = None

    def subcategory(self, rows):
        from job_enricher.engines.prompts import build_subcategory_prompt

        _FakeBackfillEngine.captured_prompts.append(build_subcategory_prompt(rows))
        return [
            {"job_listing_id": r["job_listing_id"], "source_id": r["source_id"],
             "subcategories": ["backend"], "subcategory_confidence": 0.7,
             "subcategory_latency_ms": 11}
            for r in rows
        ]


_BACKFILL_ROWS = [
    {"source_id": "greenhouse", "job_listing_id": "1", "title": "Backend Engineer",
     "company": "Acme", "raw_location": "SF", "label_source": "human",
     "category": "software_engineering", "tags": ["THE-GOLD-TAG"],
     "clean_description": "SECRET DESCRIPTION TEXT",
     "description_html": "<p>SECRET DESCRIPTION TEXT</p>"},
]


def test_eval_run_backfill_lane_uses_the_production_builder_and_no_description(
    store, monkeypatch, capsys, tmp_path
):
    """⚠ TWO ASSERTIONS IN ONE, both structural:

    1. the lane calls ENR-PB-1's `build_subcategory_prompt`, not an eval-local
       reimplementation — otherwise the eval measures a prompt production never
       runs; and
    2. the built prompt contains NO description text, which is the
       prompt-injection boundary asserted in code rather than in a docstring.
    """
    _FakeBackfillEngine.captured_prompts.clear()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.eval.golden.load_seed", lambda: [dict(r) for r in _BACKFILL_ROWS]
    )
    monkeypatch.setattr(
        "job_enricher.engines.build_engine",
        lambda kind, model=None, lane="classify": _FakeBackfillEngine(),
    )
    monkeypatch.setattr(
        "job_enricher.eval.report._predictions_path",
        lambda judge, engine=None, tag=None: tmp_path / f"predictions.{tag}.json",
    )
    args = argparse.Namespace(
        engine="ollama", set="golden", judge="off", batch=1, limit=None,
        human_only=False, classify_model="fake", judge_model="fake",
        tag="v7-backfill", prompt="backfill",
    )
    assert cli._cmd_eval_run(args) == 0

    prompt = _FakeBackfillEngine.captured_prompts[0]
    assert "SECRET DESCRIPTION TEXT" not in prompt
    assert "THE-GOLD-TAG" not in prompt          # the gold label never reaches it
    assert "Backend Engineer" in prompt
    assert "<subcategory_rubric>" in prompt      # the production builder's shape

    preds = json.loads((tmp_path / "predictions.v7-backfill.json").read_text())
    assert preds[0]["subcategories"] == ["backend"]
    assert preds[0]["clean_description"] == ""   # empty BY CONSTRUCTION
    assert preds[0]["category"] == "software_engineering"


def test_eval_run_backfill_lane_writes_a_separately_tagged_artifact(
    store, monkeypatch, capsys, tmp_path
):
    """⚠ The two lanes must produce DIFFERENT scorecards, or one gate is
    silently governing a prompt it never saw."""
    _FakeBackfillEngine.captured_prompts.clear()
    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr(
        "job_enricher.eval.golden.load_seed", lambda: [dict(r) for r in _BACKFILL_ROWS]
    )
    monkeypatch.setattr(
        "job_enricher.engines.build_engine",
        lambda kind, model=None, lane="classify": _FakeBackfillEngine(),
    )
    from job_enricher.eval.report import _predictions_path

    monkeypatch.setattr(
        "job_enricher.eval.report._predictions_path",
        lambda judge, engine=None, tag=None: tmp_path / _predictions_path(
            judge, engine, tag
        ).name,
    )
    args = argparse.Namespace(
        engine="ollama", set="golden", judge="off", batch=1, limit=None,
        human_only=False, classify_model="fake", judge_model="fake",
        tag="v7-backfill", prompt="backfill",
    )
    assert cli._cmd_eval_run(args) == 0
    assert (tmp_path / "predictions.v7-backfill.ollama.judge_off.json").exists()
    assert not (tmp_path / "predictions.v7.ollama.judge_off.json").exists()


def test_needs_judge_ignores_subcategories_entirely(store):
    """⚠ EV-14: THE DECISION THAT STAYS CLOSED, pinned in code.

    A `category == 'software_engineering' AND subcategories IS NULL` clause in
    the OR-chain would route roughly half the corpus (126 of 273 golden rows are
    SWE) to a judge measured NET-NEGATIVE on category accuracy (-5.3 pts,
    macro-F1 0.73 -> 0.55). And `[]` is a legal EVALUATED answer that must never
    be read as a nulled facet."""
    import inspect

    src = inspect.getsource(cli._needs_judge)
    body = src.split('"""')[-1]
    assert "subcategor" not in body, "a subcategory clause crept into _needs_judge"

    _seed_cleaned(store, "1")
    _record(store, [_swe_item("1", confidence=0.99, subcategories=[])])
    row = _enrichment(store, "1")
    assert row["subcategories"] == "[]"          # EVALUATED, none apply
    assert cli._needs_judge(row, ceiling=0.85) is False


# ---- BF-11: the subcategory breakers are WIRED to the tick's status ---------
def test_all_empty_run_trips_the_breaker(store, monkeypatch):
    """⚠ THE CERTIFIED ASSERTION. Bump the counters THROUGH
    store.bump_tick_counters (never by hand-writing the ticks row) across three
    ticks, run tick-end, and assert on the PERSISTED tick's STATUS. "Adds the
    flag" is not enough — the flag riding in the /metrics payload while the tick
    still closes ok is exactly the silent failure this exists to catch."""
    monkeypatch.setattr(cli, "Store", lambda: store)
    tid = None
    for _ in range(3):
        tid = store.start_tick()
        store.bump_tick_counters(
            swe_classified=12, swe_subcat_evaluated=12, swe_subcategorized=0
        )
        rc = cli._cmd_tick_end(
            argparse.Namespace(status="ok", notes=None, tick_id=tid)
        )
        assert rc == 0
    tick = store.get_tick(tid)
    assert tick["status"] == "error"
    assert "subcategory_empty_drift" in tick["notes"]


def test_one_labelled_row_closes_ok(store, monkeypatch):
    """The paired NEGATIVE — what proves the breaker is not just always-on."""
    monkeypatch.setattr(cli, "Store", lambda: store)
    tid = None
    for _ in range(3):
        tid = store.start_tick()
        store.bump_tick_counters(
            swe_classified=12, swe_subcat_evaluated=12, swe_subcategorized=1
        )
        cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=tid))
    assert store.get_tick(tid)["status"] == "ok"
    assert not store.get_tick(tid)["notes"]


def test_absent_drift_trips_the_breaker_and_names_itself(store, monkeypatch):
    monkeypatch.setattr(cli, "Store", lambda: store)
    tid = store.start_tick()
    store.bump_tick_counters(swe_classified=12, swe_subcat_evaluated=0)
    cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=tid))
    tick = store.get_tick(tid)
    assert tick["status"] == "error"
    assert "subcategory_absent_drift" in tick["notes"]
    assert "subcategory_empty_drift" not in tick["notes"]


def test_neither_subcategory_breaker_fires_on_a_healthy_window(store, monkeypatch):
    monkeypatch.setattr(cli, "Store", lambda: store)
    tid = store.start_tick()
    store.bump_tick_counters(
        swe_classified=12, swe_subcat_evaluated=12, swe_subcategorized=7
    )
    cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=tid))
    assert store.get_tick(tid)["status"] == "ok"


def test_the_mass_nulling_breaker_still_fires_unchanged(store, monkeypatch):
    """The existing breaker must be untouched by the second block."""
    monkeypatch.setattr(cli, "Store", lambda: store)
    tid = store.start_tick()
    store.bump_tick_counters(classified=10, nulled_facets=6, swe_subcat_evaluated=5)
    cli._cmd_tick_end(argparse.Namespace(status="ok", notes=None, tick_id=tid))
    tick = store.get_tick(tid)
    assert tick["status"] == "error"
    assert "circuit breaker" in tick["notes"]


# ---- BF-9: the night's run, at the CLI seam --------------------------------
def test_subcategory_backfill_has_no_concurrency_flag():
    """⚠ ARGPARSE ASSERTION, so the DELETED option cannot creep back.
    _call_with_repair is strictly sequential, ChunkEngine has no parallel path,
    and a threadpool would multiply SQLite write contention against the live
    tick. The levers for wall time are --batch and the model tier."""
    parser = cli.build_parser()
    sub = parser._subparsers._group_actions[0].choices["subcategory-backfill"]
    flags = {o for a in sub._actions for o in a.option_strings}
    assert "--concurrency" not in flags
    assert "--batch" in flags and "--until" in flags and "--dry-run" in flags


def test_backfill_concurrency_is_not_a_knob_either():
    assert not any("concurrency" in k for k in ec.KNOB_META_KEYS)


def test_resolve_deadline_takes_the_next_occurrence_and_the_minimum():
    from datetime import datetime, timedelta, timezone

    # 03:00 UTC == 21:00 previous day in Chicago (CDT), so 09:00 local is ahead
    now = datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc)
    dl = cli.resolve_deadline("09:00", "America/Chicago", None, now=now)
    assert dl is not None and now < dl <= now + timedelta(hours=24)
    assert dl.astimezone(ZoneInfo("America/Chicago")).hour == 9

    # --max-seconds wins when it is sooner
    both = cli.resolve_deadline("09:00", "America/Chicago", 60, now=now)
    assert both == now + timedelta(seconds=60)
    assert cli.resolve_deadline(None, "America/Chicago", None, now=now) is None


def test_subcategory_backfill_second_invocation_exits_75(store, monkeypatch, capsys):
    import job_enricher.lock as lock_mod

    monkeypatch.setattr(cli, "Store", lambda: store)
    lock_path = store.db_path.parent / ".backfill.lock"
    assert lock_mod.try_acquire(lock_path, stale_after_hours=12)[0]
    rc = cli._cmd_subcategory_backfill(argparse.Namespace(
        until=None, tz="America/Chicago", max_seconds=None, limit=1, batch=1,
        model=None, open_only=False, dry_run=False, probe_json=None, notify=False,
    ))
    assert rc == 75
    assert "skipped" in capsys.readouterr().out


@pytest.mark.parametrize("model, expected", [
    ("sonnet", ("claude-code", "sonnet")),
    (None, ("ollama", "qwen3:32b")),
])
def test_subcategory_backfill_model_picks_the_claude_engine(store, monkeypatch, model, expected):
    """A Claude tier must run on claude-code even when the classify knob is
    ollama (prod). Before the fix "sonnet" was sent to ollama and 404'd."""
    seen = []

    class _Stop(Exception):
        pass

    def _fake_build(kind, model=None):
        seen.append((kind, model))
        raise _Stop

    monkeypatch.setattr(cli, "Store", lambda: store)
    monkeypatch.setattr("job_enricher.engines.build_engine", _fake_build)
    with pytest.raises(_Stop):
        cli._cmd_subcategory_backfill(argparse.Namespace(
            until=None, tz="America/Chicago", max_seconds=None, limit=1, batch=1,
            model=model, open_only=False, dry_run=True, probe_json=None, notify=False,
        ))
    assert seen == [expected]


def test_health_migrates_an_old_db_before_reading_it(store, monkeypatch, capsys):
    """deploy.sh step 6 runs `cli health` with the worker parked and relies on
    it to migrate. A v3 DB used to fail with "no such column: e.subcategories"."""
    with store.connect() as conn:
        conn.execute("DROP INDEX IF EXISTS idx_enrichments_subcat_push")
        conn.execute("ALTER TABLE enrichments DROP COLUMN subcategory_sent_at")
        conn.execute("PRAGMA user_version = 3")
    monkeypatch.setattr(cli, "Store", lambda: store)
    assert cli._cmd_health(argparse.Namespace()) == 0
    json.loads(capsys.readouterr().out)
    with store.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 4
        cols = {r[1] for r in conn.execute("PRAGMA table_info(enrichments)")}
    assert "subcategory_sent_at" in cols


def test_subcategory_backfill_open_only_refuses_on_an_empty_scope(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Store", lambda: store)
    rc = cli._cmd_subcategory_backfill(argparse.Namespace(
        until=None, tz="America/Chicago", max_seconds=None, limit=1, batch=1,
        model=None, open_only=True, dry_run=False, probe_json=None, notify=False,
    ))
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err
