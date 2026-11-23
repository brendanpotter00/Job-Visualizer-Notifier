"""EN-07 — idempotent re-delivery.

The enricher marks a row sent ONLY on a 2xx, so any time JVN commits a
``/results`` batch but the response is lost (a Railway redeploy mid-request, a
laptop that sleeps between send and ack), the next write-back sends the SAME
rows again. JVN's ``/results`` must therefore be an idempotent upsert: the
second delivery may refresh ``enriched_at`` and nothing else.

The lost ack is modelled exactly: after a normal tick, the sandbox's rows are
flipped back to unsent (``Sandbox.mark_all_unsent`` — the one raw write this
section makes to the enricher's own DB) and the REAL ``cli write-back`` runs
again. Then a full wrapper fire proves a quiet tick touches nothing.
"""

from __future__ import annotations

import json

import fixtures
from conftest import dump_json, seed

GROUP = fixtures.EN07

_ENRICHMENT_FIELDS = (
    "clean_description", "classify_confidence", "classify_reasoning", "taxonomy_version",
    "judged", "judge_passed", "judge_confidence", "judge_notes", "needs_human",
)


def _snapshot(db_conn) -> dict:
    listings = {
        k: {f: v for f, v in r.items() if f != "enrichment_claimed_at"}
        for k, r in seed.listings(db_conn).items()
    }
    enr = {k: {f: r[f] for f in _ENRICHMENT_FIELDS} for k, r in seed.enrichments(db_conn).items()}
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM job_enrichment WHERE source_id = %s", (fixtures.SOURCE_ID,))
        n_enr = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM job_tags WHERE source_id = %s", (fixtures.SOURCE_ID,))
        n_tags = cur.fetchone()["n"]
        cur.execute(
            "SELECT job_listing_id, normalized_location_id FROM job_locations "
            "WHERE job_listing_id = ANY(%s) "
            "ORDER BY 1, 2",
            ([j.job_id for j in GROUP],),
        )
        locations = [tuple(r.values()) for r in cur.fetchall()]
    return {"listings": listings, "job_enrichment": enr, "tags": seed.tags(db_conn),
            "counts": {"job_enrichment": n_enr, "job_tags": n_tags}, "job_locations": locations}


def _enriched_at(db_conn) -> dict:
    return {k: r["enriched_at"] for k, r in seed.enrichments(db_conn).items()}


def test_en07_redelivering_the_same_results_changes_nothing(sandbox, db_conn, step, case_dir):
    step("seeding EN-07 and delivering it with one normal tick")
    seed.reseed(GROUP)
    run = sandbox.fire(label="tick-1")
    assert run.rc == 0, f"see {run.log_path}"
    first = _snapshot(db_conn)
    first_at = _enriched_at(db_conn)
    dump_json(case_dir / "snapshot-1.json", first)
    assert first["counts"] == {"job_enrichment": 3, "job_tags": sum(len(j.tags) for j in GROUP)}
    assert {r["enrichment_status"] for r in first["listings"].values()} == {"done"}
    assert len(first["job_locations"]) == len(GROUP), "the location write path did not run"

    step("modelling a lost ack: the sandbox's rows flip back to unsent")
    assert sandbox.mark_all_unsent() == len(GROUP)

    step("re-delivering through the real `cli write-back`")
    proc = sandbox.cli("write-back")
    result = json.loads(proc.stdout.strip().splitlines()[-1].split("write-back:", 1)[-1])
    assert result["sent"] == len(GROUP) and result["failed"] == 0, result

    step("comparing JVN before/after the duplicate delivery")
    second = _snapshot(db_conn)
    dump_json(case_dir / "snapshot-2.json", second)
    assert second == first, "a re-delivered /results batch changed JVN"
    second_at = _enriched_at(db_conn)
    assert all(second_at[k] >= first_at[k] for k in first_at), "enriched_at went backwards"

    step("a quiet tick (nothing to claim, nothing unsent) touches nothing")
    run = sandbox.fire(label="tick-2-quiet")
    assert run.rc == 0
    tick = sandbox.ticks()[-1]
    assert (tick["claimed"], tick["classified"], tick["sent"]) == (0, 0, 0), tick
    assert _snapshot(db_conn) == first
