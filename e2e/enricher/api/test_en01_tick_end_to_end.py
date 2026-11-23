"""EN-01 — one real wrapper fire enriches the seeded OPEN jobs end to end.

The whole prod path, unmodified: launchd-style exec of
``scripts/enrich_tick_wrapper.sh`` -> ``tick-acquire`` -> ``pull`` (the REAL
``GET /api/internal/enrichment/pending``, which CLAIMS the rows) -> ``clean`` ->
``classify-queue`` -> ``classify-run`` (the REAL ollama engine, talking to the
stub) -> ``metrics-push`` -> ``judge-queue``/``judge-run`` -> ``write-back`` (the
REAL ``POST /results``) -> ``tick-end`` -> ``metrics-push``.

Every expected value comes from ``fixtures.py`` — the answer the stub was told
to give — never from the enricher.

Where the provenance lives (a correction to PLAN.md §3.2): JVN's
``job_enrichment`` stores taxonomy_version / classify confidence + reasoning /
judge fields, NOT the model or the tick. ``classify_model`` and ``tick_id`` are
LOCAL provenance in the enricher's own ``enrichments`` table, and the model
reaches JVN only inside the tick's ``knobs`` snapshot on ``/metrics``. Each is
asserted where it actually lives.
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import dump_json, seed, wrapper_int

GROUP = fixtures.EN01
IDS = {j.job_id for j in GROUP}


@pytest.mark.fast
def test_en01_one_fire_delivers_every_seeded_row(sandbox, stub, http, db_conn, step, case_dir):
    step("seeding the EN-01 rows into JVN as OPEN, described, never enriched")
    seed.reseed(GROUP)

    step("firing the real wrapper once, the way launchd does")
    run = sandbox.fire()
    assert run.rc == 0, f"wrapper exited {run.rc} — see {run.log_path}"
    run.expect("in-process engine (classify=ollama judge=ollama)",
               "the wrapper did not take the in-process ollama path — it may have reached `claude -p`")
    run.refute("judge engine", "the wrapper skipped the in-process judge")

    step("reading JVN's job_listings: every row left `claimed` and carries the stub's facets")
    rows = seed.listings(db_conn)
    dump_json(case_dir / "jvn-listings.json", rows)
    assert set(rows) == IDS
    for job in GROUP:
        row = rows[job.job_id]
        assert row["enrichment_status"] == "done", f"{job.job_id}: status {row['enrichment_status']!r}"
        assert row["enrichment_claimed_at"] is None, f"{job.job_id}: claim not cleared"
        assert (row["enrichment_category"], row["enrichment_level"]) == (job.category, job.level), job.job_id

    step("reading JVN's job_enrichment audit rows")
    enr = seed.enrichments(db_conn)
    dump_json(case_dir / "jvn-job-enrichment.json", enr)
    assert set(enr) == IDS
    taxonomy_version = sandbox.info["taxonomy_version"]
    for job in GROUP:
        e = enr[job.job_id]
        assert e["taxonomy_version"] == taxonomy_version, job.job_id
        assert e["classify_confidence"] == pytest.approx(job.confidence), job.job_id
        assert "e2e stub classify" in (e["classify_reasoning"] or ""), job.job_id
        assert e["judged"] is False, f"{job.job_id} was judged at confidence {job.confidence}"
        assert e["needs_human"] is False, job.job_id
        clean = e["clean_description"] or ""
        assert "We build" in clean and "<" not in clean, (
            f"{job.job_id}: clean_description is not the cleaned text: {clean[:120]!r}"
        )

    step("reading JVN's job_tags")
    assert seed.tags(db_conn) == {j.job_id: sorted(j.tags) for j in GROUP}

    step("reading the sandbox's own DB: one tick, closed ok, claimed == classified == sent")
    ticks = sandbox.ticks()
    dump_json(case_dir / "sandbox-ticks.json", ticks)
    assert len(ticks) == 1, f"expected exactly one tick, found {len(ticks)}"
    tick = ticks[0]
    assert tick["status"] == "ok", tick
    assert tick["ended_at"]
    n = len(GROUP)
    assert (tick["claimed"], tick["cleaned"], tick["classified"], tick["sent"]) == (n, n, n, n), tick
    assert tick["errors"] == 0 and tick["judged"] == 0, tick
    assert wrapper_int(run.output, "pull:", "claimed") == n

    step("reading the sandbox's local provenance (model + tick live HERE, not in JVN)")
    local = sandbox.enrichments()
    assert set(local) == IDS
    for jid, e in local.items():
        assert e["classify_model"] == fixtures.MODEL, (jid, e["classify_model"])
        assert e["tick_id"] == tick["id"], (jid, e["tick_id"])
        assert e["sent_at"], f"{jid} not marked sent locally"

    step("reading the stub's request log: only /api/chat, the prod model, temperature 0")
    log = stub.log()
    assert log["count"] == log["chat_count"], f"stub saw non-chat requests: {log['requests']}"
    chats = stub.chats()
    assert {r["stage"] for r in chats} == {"classify"}
    assert sorted(jid for r in chats for jid in r["job_ids"]) == sorted(IDS), "one classify call per row"
    for r in chats:
        assert r["model"] == fixtures.MODEL, r
        assert r["temperature"] == 0 and r["stream"] is False, r
        assert r["format_type"] == "array", r
        assert len(r["job_ids"]) == 1, f"in-process batch must be 1, got {r['job_ids']}"

    step("asking JVN's /enrichment/health whether it saw the enrichment land")
    health = http.get("/api/internal/enrichment/health").json()
    assert health["enabled"] is True
    assert health["last_enriched_at"] is not None
    assert health["open_by_status"].get("done") == n, health
