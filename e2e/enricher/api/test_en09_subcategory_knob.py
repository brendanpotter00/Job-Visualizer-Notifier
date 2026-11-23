"""EN-09 (v7) — the subcategory dark knob.

``writeback:send_subcategories`` ships OFF. Off, ``/results`` items OMIT the
three subcategory keys entirely, and JVN reads an absent key as "leave the
column alone" — so an SWE row it has never labelled stays ``NULL`` ("never
evaluated", the backfill queue), NOT ``'{}'`` ("evaluated, none apply",
terminal). Getting that wrong would drain the backfill queue on the first
ordinary tick.

On, the NEXT write-back carries them: SWE rows get their ordered array and
``subcategory_source='classify'``; non-SWE rows stay NULL (JVN's parent rule
runs first and unconditionally). Rows already sent are NOT re-sent by flipping
the knob — that is the backfill drain's job, not the tick's.
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import dump_json, seed


@pytest.mark.v7
def test_en09_knob_off_leaves_null_and_knob_on_populates_swe_rows_only(sandbox, db_conn, step, case_dir):
    step("seeding group A, knob at its default (off), one tick")
    seed.reseed(fixtures.EN09_A)
    run = sandbox.fire(label="tick-1-knob-off")
    assert run.rc == 0, f"see {run.log_path}"
    rows = seed.listings(db_conn)
    assert rows["EN09-A-SWE"]["enrichment_status"] == "done"
    assert rows["EN09-A-SWE"]["enrichment_subcategories"] is None, (
        f"knob off must leave NULL, got {rows['EN09-A-SWE']['enrichment_subcategories']!r}"
    )
    assert rows["EN09-A-PM"]["enrichment_subcategories"] is None
    local = sandbox.enrichments()
    assert local["EN09-A-SWE"]["subcategories"] == '["backend"]', (
        "classify recorded the label locally; only the SHIPPING is dark"
    )

    step("turning the knob on")
    sandbox.cli("writeback-send-subcategories", "on")

    step("adding group B and running the next tick")
    seed.add_jobs(fixtures.EN09_B)
    run = sandbox.fire(label="tick-2-knob-on")
    assert run.rc == 0, f"see {run.log_path}"
    rows = seed.listings(db_conn)
    enr = seed.enrichments(db_conn)
    dump_json(case_dir / "jvn-listings.json", rows)

    step("group B: the SWE row carries its array + provenance, the PM row stays NULL")
    assert rows["EN09-B-SWE"]["enrichment_subcategories"] == ["mobile"]
    assert rows["EN09-B-SWE"]["enrichment_subcategory_source"] == "classify"
    assert enr["EN09-B-SWE"]["subcategory_confidence"] == pytest.approx(0.9)
    assert rows["EN09-B-PM"]["enrichment_subcategories"] is None
    assert rows["EN09-B-PM"]["enrichment_subcategory_source"] is None

    step("group A was not re-sent by the knob flip")
    assert rows["EN09-A-SWE"]["enrichment_subcategories"] is None
