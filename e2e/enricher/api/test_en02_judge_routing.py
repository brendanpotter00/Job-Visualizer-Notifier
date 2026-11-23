"""EN-02 — judge routing: only the unsure rows reach the judge, and what it says
lands in JVN.

``judge:scope`` defaults to ``low_confidence`` with ``judge:confidence_ceiling``
0.85, so a row classified at 0.96 must ship untouched and a row at 0.55 must be
judged. The expected judged set is computed from the FIXTURE confidences
(``fixtures.expected_judged``), not read back from the enricher.

Three verdicts, three outcomes:

* ``EN02-REVISED``  the judge corrects category AND level at its own 0.90 —
  clearing the code-enforced 0.8 level-change rail — so JVN shows the
  correction, and the local row keeps the one-shot pre-judge snapshot.
* ``EN02-HUMAN``    the judge answers at 0.40, below ``judge:human_floor`` 0.60.
  It did NOT ask for a human; the floor forces ``needs_human`` anyway. With
  JVN's ``ENRICHMENT_REQUIRE_JUDGE_PASS`` off (the default) the row still
  publishes ``done``, and ``job_enrichment.needs_human`` carries the flag to
  the admin triage queue.
* ``EN02-CONFIRMED`` judged, passed, nothing changed.
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import dump_json, seed

GROUP = fixtures.EN02


def test_en02_only_unsure_rows_are_judged_and_verdicts_land(sandbox, stub, db_conn, step, case_dir):
    step("seeding the EN-02 rows")
    seed.reseed(GROUP)

    step("firing one tick")
    run = sandbox.fire()
    assert run.rc == 0, f"wrapper exited {run.rc} — see {run.log_path}"

    expected = fixtures.expected_judged(GROUP)
    assert expected == {"EN02-REVISED", "EN02-HUMAN", "EN02-CONFIRMED"}, "fixture drifted"

    step("checking which rows the stub was asked to judge")
    assert stub.ids_seen("judge") == expected, (
        f"judged {sorted(stub.ids_seen('judge'))}, expected {sorted(expected)} — judge:scope "
        f"routing is wrong"
    )

    step("checking JVN's job_enrichment.judged matches the routing")
    enr = seed.enrichments(db_conn)
    dump_json(case_dir / "jvn-job-enrichment.json", enr)
    for job in GROUP:
        assert enr[job.job_id]["judged"] is (job.job_id in expected), job.job_id

    rows = seed.listings(db_conn)

    step("EN02-REVISED: the judge's category + level correction is what JVN shows")
    assert (rows["EN02-REVISED"]["enrichment_category"], rows["EN02-REVISED"]["enrichment_level"]) == (
        "software_engineering", "senior",
    )
    revised = enr["EN02-REVISED"]
    assert revised["judge_passed"] is False
    assert revised["judge_confidence"] == pytest.approx(0.9)
    assert revised["needs_human"] is False

    step("EN02-HUMAN: a verdict below the human floor arrives as needs_human")
    human = enr["EN02-HUMAN"]
    assert human["needs_human"] is True, "judge confidence 0.40 < floor 0.60 must flag needs_human"
    assert human["judge_confidence"] == pytest.approx(0.4)
    assert rows["EN02-HUMAN"]["enrichment_status"] == "done", (
        "with ENRICHMENT_REQUIRE_JUDGE_PASS off the row publishes; the flag rides on job_enrichment"
    )
    assert rows["EN02-HUMAN"]["enrichment_category"] == "business_ops"

    step("EN02-CONFIRMED: judged, passed, unchanged")
    assert enr["EN02-CONFIRMED"]["judge_passed"] is True
    assert rows["EN02-CONFIRMED"]["enrichment_category"] == "growth"

    step("EN02-CONFIDENT: never judged, shipped as classified")
    assert enr["EN02-CONFIDENT"]["judge_passed"] is None
    assert rows["EN02-CONFIDENT"]["enrichment_level"] == "senior_plus"

    step("checking the local tick counters and the pre-judge snapshot")
    (tick,) = sandbox.ticks()
    assert tick["status"] == "ok"
    assert (tick["judged"], tick["corrected"], tick["needs_human"], tick["sent"]) == (3, 2, 1, 4), tick
    local = sandbox.enrichments()
    assert local["EN02-REVISED"]["pre_judge_category"] == "data_scientist"
    assert local["EN02-REVISED"]["pre_judge_level"] == "mid"
    assert local["EN02-REVISED"]["judge_model"] == fixtures.MODEL
