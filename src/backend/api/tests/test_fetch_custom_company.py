"""E7 Phase 1 never-close regression — fetch_custom_company runs UNVERIFIED.

The whole safety property of Phase 1 in one test: run the custom leaf task twice
against a fake ATS client; on the second run the board drops a job. Because no
oracle exists (``oracle_kind='none'``) every harvest is UNVERIFIED, so NOTHING
is ever closed and NO miss is ever counted — the dropped job stays OPEN with
zero misses. Each run writes one ``company_harvests`` row and one ``scrape_runs``
row (``source_id=custom:<id>``, ``guard_reason='unverified_harvest'``).

The task is called directly (``await fetch_custom_company(...)``) rather than
through the Procrastinate worker, so it does not depend on the worker's
event loop / connector — it opens its OWN connection from
``settings.database_url``, which the test points at the per-worker test schema.
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
from api.tasks.fetch_custom_company import fetch_custom_company
from scripts.shared.constants import custom

pytestmark = pytest.mark.asyncio


def _seed_custom_company(db_conn, company_id: str, token: str) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state) "
            "VALUES (%s, %s, 'greenhouse', %s, TRUE, '{{}}'::jsonb, 'user', 24, now(), 'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, token),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, oracle_kind) "
            "VALUES (%s, %s::jsonb, 1, 'ats_client', 'none')"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps({"kind": "ats_client", "provider": "greenhouse", "token": token})),
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
        sql.SQL("SELECT * FROM {} WHERE company_id = %s").format(sql.Identifier(table)),
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


def _job_status(db_conn, company_id: str) -> dict[str, str]:
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


async def test_two_runs_dropping_a_job_never_closes(db_conn, monkeypatch):
    company_id = "u-nevrclose1"
    _seed_custom_company(db_conn, company_id, "duolingo")
    _patch_env(monkeypatch)

    # --- Run 1: three jobs on the board ---
    async def fetch_three(board_token, http):
        return [_raw_job(1), _raw_job(2), _raw_job(3)]

    monkeypatch.setattr(greenhouse_client, "fetch_jobs", fetch_three)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()  # fresh snapshot — the task committed on its own conn

    jobs = _job_status(db_conn, company_id)
    assert set(jobs) == {"1", "2", "3"}
    assert all(j["status"] == "OPEN" for j in jobs.values())
    assert max(j["consecutive_misses"] for j in jobs.values()) == 0

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "UNVERIFIED"
    assert harvests[0]["oracle_kind"] == "none"
    assert harvests[0]["records_harvested"] == 3

    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == 1
    assert runs[0]["source_id"] == custom(company_id)
    assert runs[0]["guard_reason"] == "unverified_harvest"
    assert runs[0]["closed_jobs"] == 0
    assert runs[0]["success"] is True

    # A successful (UNVERIFIED, executed) run stamps last_success_at so the UI
    # stops reading "Not yet checked". health_state stays 'unverified' (no oracle
    # in Phase 1) and tracking_started_at stays NULL (first VERIFIED harvest only).
    company = _company_row(db_conn, company_id)
    assert company["last_success_at"] is not None
    assert company["health_state"] == "unverified"
    assert company["tracking_started_at"] is None

    # --- Run 2: the board drops job "3" ---
    async def fetch_two(board_token, http):
        return [_raw_job(1), _raw_job(2)]

    monkeypatch.setattr(greenhouse_client, "fetch_jobs", fetch_two)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    jobs = _job_status(db_conn, company_id)
    # The dropped job "3" is STILL OPEN — UNVERIFIED never closes.
    assert jobs["3"]["status"] == "OPEN"
    assert all(j["status"] == "OPEN" for j in jobs.values())
    # No miss was ever counted against anything.
    assert max(j["consecutive_misses"] for j in jobs.values()) == 0

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 2
    assert all(h["verdict"] == "UNVERIFIED" for h in harvests)

    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == 2
    assert all(r["closed_jobs"] == 0 for r in runs)
    assert all(r["guard_reason"] == "unverified_harvest" for r in runs)
    assert all(r["source_id"] == custom(company_id) for r in runs)


async def test_empty_harvest_raises_and_closes_nothing(db_conn, monkeypatch):
    """An empty harvest is a FAILED run (check 2 raises) — it writes no jobs and
    is not a miss. It still records a harvest + scrape_runs row for evidence."""
    company_id = "u-emptybrd01"
    _seed_custom_company(db_conn, company_id, "emptyco")
    _patch_env(monkeypatch)

    async def fetch_none(board_token, http):
        return []

    monkeypatch.setattr(greenhouse_client, "fetch_jobs", fetch_none)
    with pytest.raises(Exception):
        # The gate raises HarvestGateError; the task records the run then
        # re-raises so Procrastinate retries.
        await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    assert _job_status(db_conn, company_id) == {}
    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "FAILED"
    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == 1
    assert runs[0]["closed_jobs"] == 0
    assert runs[0]["success"] is False

    # A FAILED run must NOT stamp last_success_at — it stays NULL.
    assert _company_row(db_conn, company_id)["last_success_at"] is None
