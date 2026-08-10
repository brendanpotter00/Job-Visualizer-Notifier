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
