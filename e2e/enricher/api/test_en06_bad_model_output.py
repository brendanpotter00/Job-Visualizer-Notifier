"""EN-06 — bad model output never kills a wave.

One tick, six rows, five of them misbehaving in a different way on the
classify call (``fixtures.py`` ``behaviour``). The good rows must still land,
and each bad row must fail in its own documented way — never by taking the
tick, the chunk loop or a neighbour down:

| row            | stub answer                         | contract                                           |
|----------------|-------------------------------------|----------------------------------------------------|
| EN06-OK        | normal                              | done                                               |
| EN06-GHOST     | its answer + one for an unclaimed id| its own answer recorded; the ghost skipped+counted |
| EN06-BADSLUG   | category ``astronaut_engineering``  | nulled LOCALLY, needs_human, judged, ships NULL    |
| EN06-GARBLED   | valid envelope, prose content       | nothing recorded; stays cleaned/claimed for retry  |
| EN06-HTTPJUNK  | HTTP 200, HTML body                 | engine error for that chunk only                   |
| EN06-LONGTAG   | a 78-char tag                       | JVN drops the tag and says so in ``warnings[]``,   |
|                |                                     | which the enricher logs                            |

A correction to PLAN.md §3.2's wording: an invalid slug does NOT reach JVN as
a slug JVN nulls — the enricher's ``validate_facets`` nulls it before
write-back (and flags the row), so JVN receives ``category: null`` and has
nothing to warn about. JVN's ``warnings[]`` channel is exercised by the long
tag instead.
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import dump_json, seed, wrapper_int

GROUP = fixtures.EN06


def test_en06_each_bad_row_fails_alone_and_the_good_rows_land(sandbox, stub, db_conn, step, case_dir):
    step("seeding EN-06 and firing one tick")
    seed.reseed(GROUP)
    run = sandbox.fire()
    assert run.rc == 0, f"see {run.log_path}"
    (tick,) = sandbox.ticks()
    assert tick["status"] == "ok", f"one bad row must not fail the tick: {tick}"
    rows = seed.listings(db_conn)
    enr = seed.enrichments(db_conn)
    dump_json(case_dir / "jvn-listings.json", rows)
    dump_json(case_dir / "jvn-job-enrichment.json", enr)
    local = sandbox.enrichments()
    inbox = sandbox.inbox()

    step("EN06-OK landed")
    assert rows["EN06-OK"]["enrichment_status"] == "done"
    assert rows["EN06-OK"]["enrichment_category"] == "software_engineering"

    step("EN06-GHOST: its own answer landed, the hallucinated id was skipped and counted")
    assert rows["EN06-GHOST"]["enrichment_status"] == "done"
    assert wrapper_int(run.output, "classify-run:", "skipped_unknown") == 1
    ghost = fixtures.GHOST_PREFIX + "EN06-GHOST"
    assert ghost not in local and ghost not in enr and ghost not in rows

    step("EN06-BADSLUG: nulled locally, flagged, judged, shipped as NULL")
    assert local["EN06-BADSLUG"]["category"] is None
    assert local["EN06-BADSLUG"]["needs_human"] == 1
    assert tick["nulled_facets"] >= 1, tick
    assert "EN06-BADSLUG" in stub.ids_seen("judge"), "a nulled facet must route to the judge"
    assert rows["EN06-BADSLUG"]["enrichment_status"] == "done"
    assert rows["EN06-BADSLUG"]["enrichment_category"] is None
    assert enr["EN06-BADSLUG"]["needs_human"] is True
    run.expect("has invalid category='astronaut_engineering'", "the local null was not logged")

    step("EN06-GARBLED and EN06-HTTPJUNK: nothing recorded, both still pending everywhere")
    for jid in ("EN06-GARBLED", "EN06-HTTPJUNK"):
        assert jid not in local, f"{jid} recorded something"
        assert inbox[jid]["status"] == "cleaned", inbox[jid]
        assert rows[jid]["enrichment_status"] == "claimed", rows[jid]
        assert jid not in enr
        calls = [c for c in stub.chats("classify") if c["job_ids"] == [jid]]
        assert len(calls) == 2 and calls[1]["retry_nudge"], f"{jid}: expected one nudged retry: {calls}"

    step("EN06-LONGTAG: JVN dropped the tag and the enricher logged JVN's warning")
    assert rows["EN06-LONGTAG"]["enrichment_status"] == "done"
    assert seed.tags(db_conn)["EN06-LONGTAG"] == ["figma"]
    run.expect(f"JVN warning for (source_id={fixtures.SOURCE_ID}, job_listing_id=EN06-LONGTAG)",
               "the /results warnings[] entry never reached the enricher's log")

    step("the tick still delivered every row it could")
    assert tick["sent"] == 4, tick  # OK, GHOST, BADSLUG, LONGTAG


@pytest.mark.v7
def test_en06_a_non_json_http_body_is_an_engine_error_but_prose_content_is_not(sandbox, stub, step):
    """The two "garbage" shapes are NOT the same failure, and the difference is
    observable: an HTTP body that is not JSON raises EngineError (the chunk is
    abandoned, counted in ``errors`` and bumps ``inbox.attempts`` — P0-3), while
    a valid envelope whose content is prose parses to ``[]`` and records
    NOTHING, silently: the row is simply re-queued next tick, with no error and
    no attempt counted. Pinned here as observed (see CASES.md)."""
    step("seeding EN-06, one tick")
    seed.reseed(GROUP)
    run = sandbox.fire()
    assert run.rc == 0
    inbox = sandbox.inbox()
    assert inbox["EN06-HTTPJUNK"]["attempts"] == 1, inbox["EN06-HTTPJUNK"]
    assert inbox["EN06-GARBLED"]["attempts"] == 0, inbox["EN06-GARBLED"]
    assert wrapper_int(run.output, "classify-run:", "abandoned") == 1
    (tick,) = sandbox.ticks()
    assert tick["errors"] == 1, tick
