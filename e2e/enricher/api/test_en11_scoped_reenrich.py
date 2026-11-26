"""EN-11 — the scoped re-enrich (the Forward Deployed Engineer backfill).

`docs/RUNBOOK-forward-deployed-reenrich.md` corrects rows the OLD rubric put in
`business_ops`, using `reenrich --title-regex RE --title-exclude RE --category
business_ops`. This case runs that runbook against a real JVN and the real CLI:

* the dry run lists exactly the rows the selector matches and changes nothing;
* the reset re-queues only those rows. A look-alike title (`--title-exclude`)
  and an FDE row already in SWE (`--category`) are not re-classified;
* the next tick's new answer REPLACES JVN's category on a row it already
  enriched, a CLOSED one included (the runbook's "history is corrected too");
* with `writeback:send_subcategories` OFF (prod's state on 2026-11-26) the
  `forward_deployed` subcategory stays local and JVN's stays NULL (runbook
  step 3b). Turning the knob on and draining with `subcategory-push` ships it.

The stub answers the old rubric on tick 1 and each row's `Job.relabel` (the new
rubric) once it is in `relabel` mode.
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import dump_json, seed

GROUP = fixtures.EN11
RESET = {"EN11-FDE-OPEN", "EN11-FDE-CLOSED"}
LEFT_ALONE = {"EN11-STRATEGIST", "EN11-SWE"}
SELECTOR = (
    "--title-regex", fixtures.EN11_FDE_RE,
    "--title-exclude", fixtures.EN11_EXCLUDE_RE,
    "--category", "business_ops",
)


def _listed_ids(stdout: str) -> set[str]:
    """The job ids `reenrich`'s row listing prints (`  source\\tid\\tcategory\\ttitle`)."""
    return {
        parts[1] for line in stdout.splitlines()
        if line.startswith("  ") and len(parts := line.strip().split("\t")) == 4
    }


@pytest.mark.v7
@pytest.mark.scoped_reenrich
def test_en11_scoped_reenrich_corrects_only_the_selected_rows(sandbox, stub, db_conn, step, case_dir):
    step("seeding EN-11 and enriching it under the OLD rubric (FDEs -> business_ops)")
    seed.reseed(GROUP)
    run = sandbox.fire(label="tick-1-old-rubric")
    assert run.rc == 0, f"see {run.log_path}"
    rows = seed.listings(db_conn)
    assert {k: r["enrichment_category"] for k, r in rows.items()} == {
        "EN11-FDE-OPEN": "business_ops", "EN11-FDE-CLOSED": "business_ops",
        "EN11-STRATEGIST": "business_ops", "EN11-SWE": "software_engineering",
    }
    before_local = sandbox.enrichments()

    step("the posting closes after it was enriched")
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE job_listings SET status = 'CLOSED' WHERE source_id = %s AND id = %s",
            (fixtures.SOURCE_ID, "EN11-FDE-CLOSED"),
        )

    step("dry run: lists exactly the two FDE engineers, modifies nothing")
    proc = sandbox.cli("reenrich", *SELECTOR, "--dry-run")
    assert "reenrich: 2 rows match" in proc.stdout, proc.stdout
    assert _listed_ids(proc.stdout) == RESET, proc.stdout
    assert "nothing was modified" in proc.stdout
    assert sandbox.enrichments() == before_local, "a dry run changed the local DB"

    step("reset: only the selected rows go back to `cleaned`")
    proc = sandbox.cli("reenrich", *SELECTOR)
    assert "reenrich: reset 2 rows" in proc.stdout, proc.stdout
    inbox = sandbox.inbox()
    assert {k for k, r in inbox.items() if r["status"] == "cleaned"} == RESET
    assert set(sandbox.enrichments()) == LEFT_ALONE

    step("tick 2 under the NEW rubric (stub relabel mode), knob OFF")
    stub.reset()
    stub.mode("relabel", stage="classify")
    run = sandbox.fire(label="tick-2-new-rubric")
    assert run.rc == 0, f"see {run.log_path}"
    assert stub.ids_seen("classify") == RESET, "only the reset rows may be re-classified"
    rows = seed.listings(db_conn)
    dump_json(case_dir / "jvn-listings-after-reenrich.json", rows)

    step("JVN took the new category, on the CLOSED row too")
    for jid in RESET:
        assert rows[jid]["enrichment_category"] == "software_engineering", (jid, rows[jid])
        assert rows[jid]["enrichment_status"] == "done", (jid, rows[jid])
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM job_listings WHERE source_id = %s AND id = %s",
            (fixtures.SOURCE_ID, "EN11-FDE-CLOSED"),
        )
        assert cur.fetchone()["status"] == "CLOSED", "write-back must not reopen a closed row"
    assert rows["EN11-STRATEGIST"]["enrichment_category"] == "business_ops"
    assert rows["EN11-SWE"]["enrichment_category"] == "software_engineering"

    step("knob OFF: forward_deployed is recorded locally, JVN's subcategory stays NULL")
    local = sandbox.enrichments()
    for jid in RESET:
        assert local[jid]["subcategories"] == '["forward_deployed"]', (jid, local[jid])
        assert rows[jid]["enrichment_subcategories"] is None, (jid, rows[jid])

    step("knob ON + the drain ships forward_deployed for the reset rows")
    sandbox.cli("writeback-send-subcategories", "on")
    proc = sandbox.cli("subcategory-push", "--slot-hold", "0.01", "--duty", "100")
    assert "subcategory-push: status=ok" in proc.stdout, proc.stdout
    rows = seed.listings(db_conn)
    dump_json(case_dir / "jvn-listings-after-push.json", rows)
    for jid in RESET:
        assert rows[jid]["enrichment_subcategories"] == ["forward_deployed"], (jid, rows[jid])
        assert rows[jid]["enrichment_subcategory_source"] == "classify", (jid, rows[jid])
    assert rows["EN11-STRATEGIST"]["enrichment_subcategories"] is None
    # The drain is not scoped: it also ships the label tick 1 recorded for the
    # row that was already SWE while the knob was off (the runbook's warning).
    assert rows["EN11-SWE"]["enrichment_subcategories"] == ["forward_deployed"]
