"""EN-03 — the metrics channel: a ``running`` snapshot mid-tick, then the final
``ok`` push upserting the SAME ``tick_uuid``.

A local tick runs 1-3 hours in prod. The wrapper pushes ``/metrics`` after
classify-run and after judge-run (status ``running``) precisely so JVN's
"last tick" age (``verdict.ts`` ``DARK_TICK_AGE_S``) does not flag a live laptop
as dark mid-tick, and ``/metrics`` is idempotent on ``tick_uuid`` so the closing
push UPDATES that row instead of adding a second one. The stub's ``slow`` mode
on the judge stage holds the tick open long enough to watch the ``running`` row
exist in JVN's ``enrichment_ticks``.
"""

from __future__ import annotations

import time

import fixtures
from conftest import dump_json, seed

GROUP = fixtures.EN03


def test_en03_running_snapshot_then_the_same_tick_closes_ok(sandbox, stub, http, db_conn, step, case_dir):
    step("seeding EN-03 and slowing the stub's JUDGE answers to 4 s")
    seed.reseed(GROUP)
    stub.mode("slow", stage="judge", slow_s=4.0)

    step("firing the wrapper in the background and watching JVN's tick table")
    seen_running: dict | None = None
    with sandbox.background() as (proc, log_path):
        deadline = time.monotonic() + 120
        while proc.poll() is None and time.monotonic() < deadline:
            for row in seed.ticks(db_conn):
                if row["status"] == "running" and seen_running is None:
                    seen_running = dict(row)
            time.sleep(0.2)
        rc = proc.wait(timeout=120)
    assert rc == 0, f"wrapper exited {rc} — see {log_path}"
    assert seen_running is not None, (
        "no `running` tick ever appeared in JVN's enrichment_ticks while the tick ran — "
        "the mid-tick metrics push is not reaching JVN"
    )
    dump_json(case_dir / "jvn-running-snapshot.json", seen_running)
    assert seen_running["classified"] == len(GROUP), "the running push came after classify-run"

    step("reading JVN's tick table after the wrapper exited")
    rows = seed.ticks(db_conn)
    dump_json(case_dir / "jvn-ticks.json", rows)
    assert len(rows) == 1, f"the closing push must UPSERT, not add a row: {len(rows)} rows"
    final = rows[0]
    assert final["tick_uuid"] == seen_running["tick_uuid"]
    assert final["status"] == "ok" and final["ended_at"] is not None
    assert (final["claimed"], final["classified"], final["judged"], final["sent"]) == (2, 2, 1, 2), final
    assert final["taxonomy_version"] == sandbox.info["taxonomy_version"]

    step("matching the JVN tick to the sandbox's own tick")
    (local,) = sandbox.ticks()
    assert local["uuid"] == final["tick_uuid"]

    step("checking the knobs + stage timings that rode along")
    knobs = final["knobs"] or {}
    assert knobs.get("opencode_model") == fixtures.MODEL, knobs
    assert knobs.get("classify_engine") == "ollama" and knobs.get("judge_engine") == "ollama", knobs
    stages = {s.get("stage") for s in (final["stage_timings"] or [])}
    assert {"clean", "classify", "judge", "writeback"} <= stages, stages

    step("checking /enrichment/health reflects the enrichment")
    health = http.get("/api/internal/enrichment/health").json()
    assert health["last_enriched_at"] is not None
    assert health["last_enriched_age_s"] is not None and health["last_enriched_age_s"] < 600
    assert health["open_by_status"].get("done") == len(GROUP), health
