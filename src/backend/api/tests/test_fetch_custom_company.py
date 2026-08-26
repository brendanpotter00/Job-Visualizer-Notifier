"""E7 Phase 2 leaf-task behavior — the graduated verdicts + shared test helpers.

Phase 1 landed every custom harvest UNVERIFIED (no oracle). Phase 2 wires the
provider-derived oracle (DECISION D2): a Greenhouse company is ``declared_probed``
even though its ``company_scripts.oracle_kind`` was seeded ``'none'`` in Phase 1 —
so it graduates with no backfill. This module keeps the small seeding/monkeypatch
helpers the broader close-path suite (``test_fetch_custom_company_close.py``)
imports, and pins two leaf-task behaviors directly:

* a Greenhouse board that VERIFIES but whose dropped job does NOT close within the
  miss threshold + 36h floor, and
* a Greenhouse board that goes to a *declared* zero — VERIFIED ``zero_proven``,
  yet the ``empty_scrape`` safety guard still blocks any close (belt-and-braces).

The task is called directly (``await fetch_custom_company(...)``) so it opens its
OWN connection from ``settings.database_url``, which the test points at the
per-worker test schema.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from psycopg2 import sql

import api.services.discovery.progress as dp
import api.tasks.fetch_custom_company as task_mod
from api.config import settings
from api.services import greenhouse_client
from api.services.harvest_meta import HarvestEvidence
from api.tasks.fetch_custom_company import fetch_custom_company
from scripts.shared.constants import custom

pytestmark = pytest.mark.asyncio


def _seed_custom_company(
    db_conn, company_id: str, token: str, *, ats: str = "greenhouse",
    provider_config: dict | None = None, oracle_kind: str = "none",
) -> None:
    """Seed a custom company + its Phase-1 script row.

    ``oracle_kind`` defaults to ``'none'`` on PURPOSE — Phase-1 rows carry that,
    and DECISION D2 says the gate derives the real oracle from the ATS provider
    anyway, so seeding 'none' proves a Phase-1 row graduates without a backfill.
    """
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state) "
            "VALUES (%s, %s, %s, %s, TRUE, %s::jsonb, 'user', 24, now(), 'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, ats, token, json.dumps(provider_config or {})),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, oracle_kind) "
            "VALUES (%s, %s::jsonb, 1, 'ats_client', %s)"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps({"kind": "ats_client", "provider": ats, "token": token}),
         oracle_kind),
    )
    db_conn.commit()


def _raw_job(i: int) -> dict:
    return {
        "id": i, "title": "Engineer", "absolute_url": f"https://x/{i}",
        "location": {"name": "Remote"}, "offices": [{"name": "Remote"}],
        "departments": [{"name": "Eng"}], "metadata": [],
        "first_published": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z", "content": "<p>d</p>",
    }


def patch_greenhouse_meta(monkeypatch, raw_jobs: list[dict], declared_total: int | None):
    """Monkeypatch ``greenhouse_client.fetch_jobs_with_meta`` (the Phase-2 entry
    the leaf task now calls) to return controlled rows + single-shot evidence."""
    async def _fetch(board_token, http):
        return list(raw_jobs), HarvestEvidence.single_shot(declared_total=declared_total)
    monkeypatch.setattr(greenhouse_client, "fetch_jobs_with_meta", _fetch)


def _patch_env(monkeypatch):
    """Point the task's own connection at the active test schema + silence the
    normalize_location defer (no Procrastinate connector is open here)."""
    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])

    configured = MagicMock()
    configured.defer_async = AsyncMock(return_value=None)
    monkeypatch.setattr(
        task_mod.normalize_location, "configure", lambda *a, **k: configured
    )


def _rows(db_conn, table: str, company_id: str) -> list[dict]:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT * FROM {} WHERE company_id = %s ORDER BY started_at").format(
            sql.Identifier(table)
        ),
        (company_id,),
    )
    return list(cur.fetchall())


def _company_row(db_conn, company_id: str) -> dict:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT last_success_at, health_state, tracking_started_at "
            "FROM {} WHERE id = %s"
        ).format(sql.Identifier("companies")),
        (company_id,),
    )
    return cur.fetchone()


def _scrape_runs(db_conn, company_id: str) -> list[dict]:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT * FROM {} WHERE company = %s ORDER BY started_at").format(
            sql.Identifier("scrape_runs")
        ),
        (company_id,),
    )
    return list(cur.fetchall())


def _job_status(db_conn, company_id: str) -> dict[str, dict]:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT j.id, j.status, f.consecutive_misses "
            "FROM {} j JOIN job_freshness f ON f.source_id = j.source_id AND f.id = j.id "
            "WHERE j.company = %s AND j.source_id = %s"
        ).format(sql.Identifier("job_listings")),
        (company_id, custom(company_id)),
    )
    return {r["id"]: r for r in cur.fetchall()}


def backdate_last_seen(db_conn, company_id: str, job_id: str, hours: float) -> None:
    """Push a job's ``job_freshness.last_seen_at`` back by ``hours`` so the 36h
    close floor can be satisfied in a test without waiting."""
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE job_freshness SET last_seen_at = now() - (%s * interval '1 hour') "
        "WHERE source_id = %s AND id = %s",
        (hours, custom(company_id), job_id),
    )
    db_conn.commit()


async def test_two_runs_dropping_a_job_verifies_but_does_not_close_early(db_conn, monkeypatch):
    """A Greenhouse custom company graduates to VERIFIED (D2 — derived from the
    provider even though ``oracle_kind='none'`` was seeded), but a job dropped on
    the 2nd run does NOT close: the first run closes nothing, and one miss is
    below the threshold + 36h floor."""
    company_id = "u-ghverify01"
    _seed_custom_company(db_conn, company_id, "duolingo")
    _patch_env(monkeypatch)

    # --- Run 1: three jobs, declared total matches → VERIFIED (declared_exact) ---
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2), _raw_job(3)], 3)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    jobs = _job_status(db_conn, company_id)
    assert set(jobs) == {"1", "2", "3"}
    assert all(j["status"] == "OPEN" for j in jobs.values())
    assert max(j["consecutive_misses"] for j in jobs.values()) == 0

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "VERIFIED"
    assert harvests[0]["verdict_reason"] == "declared_exact"
    # D2: recorded oracle is the provider-derived one, NOT the seeded 'none'.
    assert harvests[0]["oracle_kind"] == "declared_probed"
    assert harvests[0]["declared_total"] == 3
    assert harvests[0]["oracle_total"] == 3

    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == 1
    assert runs[0]["closed_jobs"] == 0
    assert runs[0]["success"] is True
    # First VERIFIED run closes nothing and stamps tracking + healthy.
    assert runs[0]["guard_reason"] == "first_verified_run"
    company = _company_row(db_conn, company_id)
    assert company["last_success_at"] is not None
    assert company["health_state"] == "healthy"
    assert company["tracking_started_at"] is not None

    # --- Run 2: the board drops job "3" (declared total drops to 2 → VERIFIED) ---
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    jobs = _job_status(db_conn, company_id)
    # Job 3 is missing this run → one miss, but NOT closed (threshold 2 + 36h).
    assert jobs["3"]["status"] == "OPEN"
    assert jobs["3"]["consecutive_misses"] == 1
    assert all(j["status"] == "OPEN" for j in jobs.values())

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 2
    assert all(h["verdict"] == "VERIFIED" for h in harvests)

    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == 2
    assert all(r["closed_jobs"] == 0 for r in runs)
    # Run 2 is a clean close-eligible VERIFIED run (no block) → guard_reason NULL.
    assert runs[1]["guard_reason"] is None


async def test_greenhouse_zero_board_verifies_but_guard_blocks_close(db_conn, monkeypatch):
    """A Greenhouse board that goes to a DECLARED zero (meta.total=0) is VERIFIED
    ``zero_proven`` — yet the ``empty_scrape`` safety guard still blocks the close,
    so pre-existing jobs stay OPEN (the 2026-03-29 belt-and-braces: a board→0 on a
    single run is indistinguishable from a scraper outage)."""
    company_id = "u-ghzero0001"
    _seed_custom_company(db_conn, company_id, "duolingo")
    _patch_env(monkeypatch)

    # Run 1 seeds three OPEN jobs (VERIFIED).
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2), _raw_job(3)], 3)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    assert set(_job_status(db_conn, company_id)) == {"1", "2", "3"}

    # Run 2: the board returns [] with a trusted declared total of 0.
    patch_greenhouse_meta(monkeypatch, [], 0)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    jobs = _job_status(db_conn, company_id)
    assert all(j["status"] == "OPEN" for j in jobs.values())  # nothing closed

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[1]["verdict"] == "VERIFIED"
    assert harvests[1]["verdict_reason"] == "zero_proven"

    runs = _scrape_runs(db_conn, company_id)
    # The empty_scrape safety guard wins the close-precedence and blocks any close.
    assert runs[1]["guard_reason"] == "empty_scrape"
    assert runs[1]["closed_jobs"] == 0
    assert runs[1]["success"] is True


# --- E7 Phase 3b: discovered (http_json) transport ---------------------------

import httpx  # noqa: E402  (test-local; the leaf task's replay uses a sync client)


def _seed_discovered_company(
    db_conn, company_id: str, *, script: dict, transport: str = "http_json",
    oracle_kind: str = "facet_sum",
) -> None:
    """Seed a DISCOVERED (non-ATS) custom company + its multi-primitive script."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state) "
            "VALUES (%s, %s, 'discovered', %s, TRUE, '{{}}'::jsonb, 'user', 24, now(), 'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, "https://careers.acme.example/jobs"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, oracle_kind) "
            "VALUES (%s, %s::jsonb, 1, %s, %s)"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps(script), transport, oracle_kind),
    )
    db_conn.commit()


def _http_json_script() -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "steps": [
            {"op": "fetch", "method": "GET",
             "url": "https://careers.acme.example/api/jobs", "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "facet_sum", "facet_path": "facets.dept",
                   "single_valued": True, "total_path": "hits", "window_cap": 100000},
    }


# 3 jobs; the single-valued dept facet sums to 3 == hits, so declared_total=3 and
# a 3-row harvest VERIFIES exactly (tolerance 0).
_HTTP_JSON_PAYLOAD = {
    "jobs": [
        {"id": "1", "title": "Staff Engineer", "url": "https://careers.acme.example/j/1"},
        {"id": "2", "title": "Designer", "url": "https://careers.acme.example/j/2"},
        {"id": "3", "title": "PM", "url": "https://careers.acme.example/j/3"},
    ],
    "facets": {"dept": [{"eng": 2}, {"design": 1}]},
    "hits": 3,
}


def _patch_recipe_http(monkeypatch, payload: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    def factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(task_mod, "_recipe_http_client", factory)


async def test_http_json_transport_replays_through_gate_and_verifies(db_conn, monkeypatch) -> None:
    """A stored http_json script replays via recipe_runner through the SAME gate;
    the oracle comes from the STORED column (facet_sum), not the ATS provider
    (a discovered company's provider 'discovered' would derive 'none')."""
    _patch_env(monkeypatch)
    _patch_recipe_http(monkeypatch, _HTTP_JSON_PAYLOAD)
    company_id = "u-httpjson01"
    _seed_discovered_company(db_conn, company_id, script=_http_json_script())

    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "VERIFIED"
    assert harvests[0]["oracle_kind"] == "facet_sum"    # STORED, not provider-derived
    assert harvests[0]["records_harvested"] == 3
    assert harvests[0]["oracle_total"] == 3

    # First VERIFIED run graduates the company but closes nothing.
    company = _company_row(db_conn, company_id)
    assert company["health_state"] == "healthy"
    assert company["tracking_started_at"] is not None


async def test_http_json_transport_replay_failure_is_failed_not_a_miss(db_conn, monkeypatch) -> None:
    """A replay that RAISES (records_path that doesn't resolve) is a recorded
    FAILED run — nothing destructive, not a miss."""
    _patch_env(monkeypatch)
    _patch_recipe_http(monkeypatch, {"unexpected": "shape"})
    company_id = "u-httpjson02"
    _seed_discovered_company(db_conn, company_id, script=_http_json_script())

    with pytest.raises(Exception):
        await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[0]["verdict"] == "FAILED"
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT success FROM {} WHERE company = %s").format(sql.Identifier("scrape_runs")),
        (company_id,),
    )
    assert cur.fetchone()["success"] is False


# --- the FIRST-SCAN rung: the checklist stops lying about "0 open jobs" --------
#
# Discovery accepts a board, ticks its four steps and enqueues this task. Until this
# task lands the company genuinely holds zero jobs, and a complete green checklist over
# that read as "we looked and found nothing". So the run that reads the board settles
# the fifth rung itself — with the count, or with why it could not.


def _seed_discovery_blob(db_conn, company_id: str) -> None:
    """The blob discovery leaves behind: four ticks and an OPEN first-scan rung."""
    ledger = dp.ProgressLedger()
    ledger.finish(dp.STEP_OPEN_PAGE, "opened careers.acme.example")
    ledger.finish(dp.STEP_FIND_FEED, "found 1 candidate feed(s)")
    ledger.finish(dp.STEP_VERIFY_READ, "read 3 job(s)")
    ledger.finish(dp.STEP_READY, "reading the board's own feed directly")
    ledger.start(dp.STEP_FIRST_SCAN)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "UPDATE {} SET provider_config = jsonb_set(provider_config, "
            "'{{discovery}}', %s::jsonb, true) WHERE id = %s"
        ).format(sql.Identifier("companies")),
        (json.dumps(ledger.snapshot(outcome=dp.OUTCOME_TRACKING)), company_id),
    )
    db_conn.commit()


def _checklist(db_conn, company_id: str) -> dict:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT provider_config FROM {} WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (company_id,),
    )
    progress = dp.read_progress(cur.fetchone()["provider_config"])
    assert progress is not None
    return {step["key"]: step for step in progress["steps"]}


async def test_the_first_harvest_ticks_the_first_scan_rung_with_its_count(
    db_conn, monkeypatch
) -> None:
    """The rung the user is actually waiting on. It carries the number of jobs we read,
    because "done" with no number is the generic tick this whole checklist replaced."""
    _patch_env(monkeypatch)
    _patch_recipe_http(monkeypatch, _HTTP_JSON_PAYLOAD)
    company_id = "u-firstscan01"
    _seed_discovered_company(db_conn, company_id, script=_http_json_script())
    _seed_discovery_blob(db_conn, company_id)

    await fetch_custom_company(company_id=company_id)

    rung = _checklist(db_conn, company_id)["first_scan"]
    assert rung["status"] == "done"
    assert "3" in rung["result"]
    # The four discovery rungs are untouched — the harvest owns exactly one rung.
    assert _checklist(db_conn, company_id)["verify_read"]["status"] == "done"


async def test_a_failed_first_harvest_marks_the_rung_and_refuses_nothing(
    db_conn, monkeypatch
) -> None:
    """A first scan that fails must not make a good board look REFUSED: the row stays
    tracked and enabled, its discovery outcome stays 'tracking', and the ✕ lands only on
    the rung the harvest owns — carrying the reason, which is the one thing that tells
    the user whether to wait for tonight or do something."""
    _patch_env(monkeypatch)
    _patch_recipe_http(monkeypatch, {"unexpected": "shape"})
    company_id = "u-firstscan02"
    _seed_discovered_company(db_conn, company_id, script=_http_json_script())
    _seed_discovery_blob(db_conn, company_id)

    with pytest.raises(Exception):
        await fetch_custom_company(company_id=company_id)

    rung = _checklist(db_conn, company_id)["first_scan"]
    assert rung["status"] == "failed"
    assert rung["result"]

    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT health_state, enabled, provider_config -> 'discovery' ->> 'outcome' "
            "AS outcome FROM {} WHERE id = %s"
        ).format(sql.Identifier("companies")),
        (company_id,),
    )
    row = cur.fetchone()
    assert row["health_state"] != "refused"
    assert row["enabled"] is True
    assert row["outcome"] == "tracking"
    # And a FAILED run is still not a miss and closes nothing (invariant #2).
    assert _rows(db_conn, "company_harvests", company_id)[0]["verdict"] == "FAILED"
    assert _job_status(db_conn, company_id) == {}


async def test_a_later_success_heals_a_failed_first_scan_rung(db_conn, monkeypatch) -> None:
    """A permanent ✕ describing a problem that has since gone away is worse than no
    rung at all — the next successful harvest overwrites it."""
    _patch_env(monkeypatch)
    company_id = "u-firstscan03"
    _seed_discovered_company(db_conn, company_id, script=_http_json_script())
    _seed_discovery_blob(db_conn, company_id)

    _patch_recipe_http(monkeypatch, {"unexpected": "shape"})
    with pytest.raises(Exception):
        await fetch_custom_company(company_id=company_id)
    assert _checklist(db_conn, company_id)["first_scan"]["status"] == "failed"

    _patch_recipe_http(monkeypatch, _HTTP_JSON_PAYLOAD)
    await fetch_custom_company(company_id=company_id)
    assert _checklist(db_conn, company_id)["first_scan"]["status"] == "done"


async def test_a_company_with_no_checklist_gets_no_blob_written(db_conn, monkeypatch) -> None:
    """The rung is display-only and belongs to discovered boards. An ATS custom company
    has a provider_config the leaf task READS for its provider settings; inventing a
    'discovery' key on it would put a setup checklist on a row that never had one."""
    _patch_env(monkeypatch)
    patch_greenhouse_meta(monkeypatch, [_raw_job(1)], declared_total=1)
    company_id = "u-firstscan04"
    _seed_custom_company(db_conn, company_id, "tok-fs04")

    await fetch_custom_company(company_id=company_id)

    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT provider_config FROM {} WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (company_id,),
    )
    assert "discovery" not in (cur.fetchone()["provider_config"] or {})


# --- unit 6: ``_cap_details`` learns about ``description`` --------------------
#
# The blob cap was written when ``details`` held short scalars, so its last-resort
# branch kept a fixed set of structured keys and dropped everything else. A recipe
# board's ``description`` is 2.7-5.8 KB of a stranger's HTML, and dropping it is not
# "a smaller blob": ``enrichment_monitor.DESCRIPTION_SQL`` reads
# ``details->>'description'`` and the enrichment claim excludes every row where it is
# NULL, so a dropped description is a job the enricher can never see.
#
# These touch neither the database nor the network — they are ``async`` only because
# the module carries a blanket ``pytest.mark.asyncio``, and a sync test under it is a
# pytest warning per test.

# What the BOARD publishes — raw page markup, entities and all.
_PUBLISHED_DESCRIPTION = (
    "<p><strong>Working at Atlassian</strong></p>"
    "<p>Atlassians can choose where they work &mdash; in an office, from home, "
    "or a combination of the two.</p>"
    "<ul><li><p>Own the P99 &lt; 100ms latency budget</p></li>"
    "<li><p>Partner with Design &amp; Research</p></li></ul>"
)


def _as_mapped(published: str) -> str:
    """``published`` after ``render_row_field`` — the shape ``_cap_details`` really gets.

    Goes through the real seam rather than passing the string straight in, so this test
    keeps testing the real composition if the seam ever changes what it hands over. Today
    it is a PASS-THROUGH: ``description`` is in ``_DEFERRED_UNESCAPE_FIELDS``, because it
    is the one mapped field that is tag-stripped and decoding before stripping makes an
    escaped tag indistinguishable from a real one. So the board's raw markup — entities
    and all — is exactly what arrives here, and ``_plain_text`` does the single decode
    after it strips. See ``recipe_runner.render_row_field`` for the rule.
    """
    from api.services.recipe_runner import render_row_field

    return render_row_field({"d": published}, "description", "d")


async def test_a_description_is_stored_as_plain_text_not_markup() -> None:
    """The mapped value is UNTRUSTED and arrives as markup. Storing it raw spends the
    blob budget on angle brackets, hands the classifier tags instead of prose, and
    passes a stranger's HTML on to everything that renders a job."""
    out = task_mod._cap_details({"description": _as_mapped(_PUBLISHED_DESCRIPTION)})
    text = out["description"]
    assert "<p>" not in text and "<strong>" not in text
    # Decoded exactly once, by the runner — and NOT again here.
    assert "&mdash;" not in text and "&amp;" not in text
    assert "Working at Atlassian" in text
    # The literal "<" in prose survives: the loose ``<[^>]+>`` pattern used elsewhere
    # in this repo eats from it to the ">" of the next real tag.
    assert "P99 < 100ms" in text
    assert "Partner with Design & Research" in text
    assert "_details_truncated" not in out


async def test_a_small_plain_description_is_stored_untouched() -> None:
    """Well under every budget and carrying no markup, so nothing may touch it — a
    normalization that rewrote short plain descriptions would churn every row of every
    board on every nightly harvest."""
    description = "Build and run the payments platform." * 13      # 468 B
    assert 400 < len(description) < 600
    out = task_mod._cap_details({"description": description, "category": "Eng"})
    assert out == {"description": description, "category": "Eng"}


async def test_a_huge_description_is_truncated_and_flagged_never_dropped() -> None:
    """THE unit. A 10 KB HTML description used to fall through to the last-resort
    branch, whose fixed key set did not include it — so the first descriptions we ever
    mapped would have been eaten silently. It must come back as non-empty plain text
    (the exact predicate ``DESCRIPTION_SQL`` reads) with the loss flagged."""
    out = task_mod._cap_details({"description": "<p>Ship it.</p>" * 800})   # ~11 KB
    assert isinstance(out["description"], str) and out["description"]
    assert out["_details_truncated"] is True
    assert len(out["description"].encode("utf-8")) <= task_mod._DESCRIPTION_MAX_BYTES
    assert len(json.dumps(out).encode("utf-8")) <= task_mod._DETAILS_MAX_BYTES


async def test_a_huge_description_beside_a_huge_content_still_fits_the_blob() -> None:
    """Both over cap at once. The free-text body still goes (nothing claims it), the
    description stays, and the whole blob fits."""
    out = task_mod._cap_details({
        "description": "<p>Ship it.</p>" * 800,
        "content": "<p>x</p>" * 4000,
        "department": "Engineering",
    })
    assert out["content"] is None
    assert out["department"] == "Engineering"
    assert isinstance(out["description"], str) and out["description"]
    assert out["_details_truncated"] is True
    assert len(json.dumps(out).encode("utf-8")) <= task_mod._DETAILS_MAX_BYTES


async def test_the_last_resort_branch_keeps_both_description_and_department() -> None:
    """The rung reached when dropping ``content`` is not enough — here a custom Ashby
    company whose ``description_html`` is 30 KB, which this ladder has never known how
    to drop. ``department`` stays on that rung, and now for two reasons rather than one:
    a custom company on the ``ats_client`` transport is harvested by the same
    Greenhouse/Ashby/Lever/Gem/Eightfold clients as a public one and those populate it,
    AND a recipe-harvested board maps it directly again — it is what the UI's Department
    filter reads, through the denormalized ``job_listings.department`` column."""
    out = task_mod._cap_details({
        "description": "<p>Ship it.</p>" * 800,
        "description_html": "<p>y</p>" * 4000,
        "department": "Engineering",
        "experience_level": "senior",
        "is_remote_eligible": True,
        "team": "Platform",                      # not an essential — expected to go
    })
    assert "team" not in out and "description_html" not in out
    assert out["department"] == "Engineering"
    assert out["experience_level"] == "senior"
    assert out["is_remote_eligible"] is True
    assert isinstance(out["description"], str) and out["description"]
    assert len(json.dumps(out).encode("utf-8")) <= task_mod._DETAILS_MAX_BYTES


async def test_the_description_budget_is_bytes_not_characters() -> None:
    """A CJK board is where a character budget breaks: 6,000 characters of Chinese is
    18 KB, which alone blows the 8 KB blob cap the description budget exists to fit
    inside. The clip must also never split a codepoint."""
    out = task_mod._cap_details({"description": "工程师招聘" * 2000})    # 30 KB of UTF-8
    text = out["description"]
    assert len(text.encode("utf-8")) <= task_mod._DESCRIPTION_MAX_BYTES
    assert text.encode("utf-8").decode("utf-8") == text        # no split codepoint
    assert len(json.dumps(out).encode("utf-8")) <= task_mod._DETAILS_MAX_BYTES


async def test_a_description_of_only_markup_becomes_absent_not_an_empty_string() -> None:
    """An empty string would satisfy ``DESCRIPTION_SQL IS NOT NULL`` and hand the
    enricher a claimed row with nothing to classify. Absent is the honest answer."""
    out = task_mod._cap_details({"description": "<div></div><br/>", "category": "Eng"})
    assert out["description"] is None


async def test_details_with_no_description_are_untouched() -> None:
    """Every custom company on the ATS transport is this case; a change of shape here
    would rewrite blobs on boards that never mapped a description."""
    details = {"department": "Eng", "experience_level": "senior", "content": "<p>d</p>"}
    assert task_mod._cap_details(dict(details)) == details


# --- the department is back in the capture schema, and it is the CHEAP field ---

async def test_a_real_department_is_stored_untouched() -> None:
    """The longest department in the dev DB is 122 characters; the mean is 22.3. The
    budget below exists for a board that is not like that, and must stay invisible to
    every board that is — a clipped facet label is a second, wrong option in a filter
    dropdown."""
    department = "Trading, Research, and Machine Learning"       # Jane Street's own
    out = task_mod._cap_details({"description": "Short.", "department": department})
    assert out == {"description": "Short.", "department": department}


async def test_a_pathological_department_never_shrinks_the_description() -> None:
    """THE precedence rule, stated as a test: when the two mapped fields cannot both
    fit, the DESCRIPTION wins.

    A dropped description is a row ``enrichment_monitor.DESCRIPTION_SQL`` can never
    claim — invisible to the enricher forever. A clipped department is a filter label
    with a shorter tail. So the cheap field is the one that gets bounded, and it is
    bounded BEFORE the description is measured, which is what keeps the last-resort
    rung's ``_fit_description`` from ever being reached because of a department.

    Without the bound this is not hypothetical: that rung keeps ``department`` whole and
    shrinks ``description`` against whatever room is left, so a 4 KB department would
    silently eat 4 KB of prose."""
    out = task_mod._cap_details({
        "description": "Ship it. " * 1200,                        # ~10.8 KB
        "department": "Platform " * 2000,                         # ~18 KB of label
    })

    # The description still gets its WHOLE budget — the department cost it nothing.
    assert len(out["description"].encode("utf-8")) == task_mod._DESCRIPTION_MAX_BYTES
    assert len(out["department"].encode("utf-8")) <= task_mod._DEPARTMENT_MAX_BYTES
    assert out["_details_truncated"] is True
    assert len(json.dumps(out).encode("utf-8")) <= task_mod._DETAILS_MAX_BYTES


async def test_the_two_budgets_cannot_be_set_so_they_collide() -> None:
    """An arithmetic guard on the constants themselves, because the property above holds
    only while they add up. Both budgets plus the structured scalars, the keys and JSON
    escaping have to fit the blob cap with room to spare; if a later edit raises either
    one past that, the description starts paying for the department again."""
    assert (
        task_mod._DESCRIPTION_MAX_BYTES + task_mod._DEPARTMENT_MAX_BYTES
        <= task_mod._DETAILS_MAX_BYTES - 1024
    )


async def test_a_captured_row_lands_with_both_a_description_and_a_department() -> None:
    """End to end over the real seams, on an Atlassian-shaped record that publishes
    both: the runner's field map → ``recipe_rows`` → ``_cap_details`` → the tuple the
    single job-write path binds. This is the regression the re-capture was needed for —
    a recipe with no ``department`` mapping writes NULL into the denormalized column on
    every upsert (``_UPSERT_ON_CONFLICT``: ``department = EXCLUDED.department``), which
    is how Microsoft went from 2,217 rows carrying a department to 139."""
    from api.services.recipe_rows import recipe_rows_to_job_listings
    from api.services.recipe_runner import map_records
    from scripts.shared import database as db

    record = {
        "id": "25020",
        "title": "Senior Account Executive",
        "portalJobPost": {"portalUrl": "https://www.atlassian.com/jobs/25020"},
        "category": "Sales",
        "responsibilities": "<p>Own the pipeline.</p>",
    }
    (row,) = map_records([record], {
        "id": "id",
        "title": "title",
        "url": "portalJobPost.portalUrl",
        "department": "category",
        "description": "responsibilities",
    })
    (job,) = recipe_rows_to_job_listings("u-6in22gc9yf", [row])
    details = task_mod._cap_details(job.details)

    assert details["description"] == "Own the pipeline."
    assert details["department"] == "Sales"

    # The column the filter actually reads, from the one write path every scraper and
    # every fetch task funnels through.
    columns = [c.strip() for c in db._JOB_COLUMNS.split(",")]
    values = db._build_job_values(job.model_copy(update={"details": details}))
    assert values[columns.index("department")] == "Sales"
