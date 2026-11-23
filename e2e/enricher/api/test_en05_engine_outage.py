"""EN-05 — delivery-first under an engine outage.

The stub answers every model call with HTTP 500 (an ollama that is down, OOM or
mid-restart). The wrapper's contract is that a failing LLM stage can never stop
the tick from reaching ``write-back`` and ``tick-end``: the tick still closes,
nothing half-done is sent, the claimed rows stay claimed in JVN (not
re-handed-out, not lost) and stay ``cleaned`` locally. The NEXT tick, with the
model back, delivers them — once each.

Per chunk the engine makes TWO calls (the first attempt, then one retry with
the stricter nudge) before giving the chunk up.
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import dump_json, seed, wrapper_int

GROUP = fixtures.EN05
IDS = {j.job_id for j in GROUP}


@pytest.mark.slow
def test_en05_outage_tick_sends_nothing_and_the_next_tick_delivers_once(sandbox, stub, db_conn, step, case_dir):
    step("seeding EN-05 and putting the stub in http500 mode")
    seed.reseed(GROUP)
    stub.mode("http500")

    step("tick 1, model down")
    run1 = sandbox.fire(label="tick-1-outage")
    assert run1.rc == 0, f"see {run1.log_path}"
    run1.expect("write-back:", "the outage tick never reached write-back")
    run1.expect("tick-end: closed tick_id=1", "the outage tick never closed")
    assert wrapper_int(run1.output, "classify-run:", "recorded") == 0

    (t1,) = sandbox.ticks()
    assert t1["status"] == "ok" and t1["ended_at"], t1
    assert (t1["claimed"], t1["classified"], t1["sent"]) == (2, 0, 0), t1

    step("tick 1: the stub saw two attempts per chunk, all answered 500")
    chats = stub.chats("classify")
    assert len(chats) == 2 * len(GROUP), [c["job_ids"] for c in chats]
    assert {c["status"] for c in chats} == {500}
    assert sum(1 for c in chats if c["retry_nudge"]) == len(GROUP), "one nudged retry per chunk"

    step("tick 1: JVN still has both rows CLAIMED and nothing written")
    rows = seed.listings(db_conn)
    assert {r["enrichment_status"] for r in rows.values()} == {"claimed"}, rows
    assert seed.enrichments(db_conn) == {}
    assert {r["status"] for r in sandbox.inbox().values()} == {"cleaned"}

    step("tick 2, model back")
    stub.reset()
    run2 = sandbox.fire(label="tick-2-recovered")
    assert run2.rc == 0, f"see {run2.log_path}"
    t2 = sandbox.ticks()[1]
    dump_json(case_dir / "sandbox-ticks.json", sandbox.ticks())
    assert t2["status"] == "ok"
    assert (t2["claimed"], t2["classified"], t2["sent"]) == (0, 2, 2), (
        f"tick 2 must claim nothing new (JVN still holds the claim) and deliver both: {t2}"
    )

    step("tick 2: JVN has both rows done, exactly once each")
    rows = seed.listings(db_conn)
    assert {k: r["enrichment_status"] for k, r in rows.items()} == {k: "done" for k in IDS}
    enr = seed.enrichments(db_conn)
    assert set(enr) == IDS
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT job_listing_id, count(*) AS n FROM job_enrichment WHERE source_id = %s "
            "GROUP BY job_listing_id",
            (fixtures.SOURCE_ID,),
        )
        assert {r["job_listing_id"]: r["n"] for r in cur.fetchall()} == {k: 1 for k in IDS}
    assert seed.tags(db_conn) == {j.job_id: sorted(j.tags) for j in GROUP}


@pytest.mark.slow
@pytest.mark.v7
def test_en05_an_abandoned_chunk_is_counted_not_silent(sandbox, stub, step):
    """P0-3 (shipped with the v7 epic): before it, an abandoned chunk left
    ``errors`` at 0 and ``inbox.attempts`` untouched, so an outage tick closed
    ``ok errors=0`` and the same rows were re-abandoned forever, invisibly."""
    step("seeding EN-05, http500, one tick")
    seed.reseed(GROUP)
    stub.mode("http500")
    run = sandbox.fire()
    assert run.rc == 0
    assert wrapper_int(run.output, "classify-run:", "abandoned") == len(GROUP)
    (tick,) = sandbox.ticks()
    assert tick["errors"] == len(GROUP), tick
    assert {r["attempts"] for r in sandbox.inbox().values()} == {1}
