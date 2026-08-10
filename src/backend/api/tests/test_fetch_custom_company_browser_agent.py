"""E7 Stagehand pivot — the leaf task's 3rd (browser_agent) transport branch.

$0: the browser-agent runner (which would spawn the paid Stagehand subprocess) is
monkeypatched. Proves the load-bearing safety of the browser-agent replay through the
UNCHANGED gate/verdict/upsert tail:

* an UNVERIFIED run (not terminated cleanly) upserts but closes NOTHING and is not a miss;
* a VERIFIED self_consistent run with streak < 3 closes NOTHING (first-run, then
  streak_too_short) — a browser-agent board never closes until it earns the 3-run streak;
* a runner RAISE (a row-index id / subprocess failure) → FAILED: writes nothing
  destructive, re-raises for Procrastinate, and is explicitly NOT a miss.
"""

from __future__ import annotations

import json
import os

import pytest
from psycopg2 import sql

import api.services.browser_agent.runner as ba_runner
from api.services.harvest_meta import HarvestEvidence
from api.services.recipe_runner import RecipeExecutionError
from api.tasks.fetch_custom_company import fetch_custom_company

from api.tests.test_fetch_custom_company import (
    _company_row,
    _patch_env,
    _rows,
    _scrape_runs,
)
from api.tests.test_fetch_custom_company_close import (
    _max_misses,
    _open_count,
    _seed_open_jobs,
    _set_tracking,
)

pytestmark = pytest.mark.asyncio


_ARTIFACT = {
    "script_version": 2,
    "transport": "browser_agent",
    "entry_url": "https://board.example/jobs",
    "extract": {
        "instruction": "extract jobs",
        "schema": {"type": "object", "properties": {"jobs": {"type": "array"}}},
    },
    "pagination": {"next_action": "click next", "max_pages": 3},
    "id_field": "url",
    "expected_min_jobs": 1,
    "oracle": {"kind": "self_consistent"},
}


def _seed_browser_agent_company(db_conn, company_id: str) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state) "
            "VALUES (%s, %s, 'discovered', %s, TRUE, '{{}}'::jsonb, 'user', 24, now(), "
            "'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, "https://board.example/jobs"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, oracle_kind) "
            "VALUES (%s, %s::jsonb, 2, 'browser_agent', 'self_consistent')"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps(_ARTIFACT)),
    )
    db_conn.commit()


def _patch_runner(monkeypatch, *, rows=None, evidence=None, raises=None) -> None:
    """Patch the browser-agent runner (imported lazily by the leaf task's branch)."""
    async def _fake(script, *, transport=None, oracle_kind=None):
        if raises is not None:
            raise raises
        return list(rows or []), evidence
    monkeypatch.setattr(ba_runner, "run_browser_agent", _fake)


def _agent_rows(ids):
    return [
        {"id": str(i), "title": f"J{i}", "url": f"/jobs/{i}", "location": "Remote"}
        for i in ids
    ]


def _job_status(db_conn, company_id, job_id):
    cur = db_conn.cursor()
    cur.execute(
        "SELECT status FROM job_listings WHERE source_id = %s AND id = %s",
        (f"custom:{company_id}", str(job_id)),
    )
    row = cur.fetchone()
    return row["status"] if row else None


# --- UNVERIFIED (not terminated cleanly) closes nothing ----------------------

async def test_unverified_browser_agent_run_closes_nothing(db_conn, monkeypatch):
    company_id = "u-baunverif1"
    _seed_browser_agent_company(db_conn, company_id)
    _seed_open_jobs(db_conn, company_id, 1, 3, last_seen_hours_ago=48)
    _patch_env(monkeypatch)

    # terminated_cleanly=False → self_consistent verdict is UNVERIFIED.
    evidence = HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=False,
        page_advance_ok=None, pages_fetched=1,
    )
    _patch_runner(monkeypatch, rows=_agent_rows([1, 2]), evidence=evidence)

    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "UNVERIFIED"
    assert harvests[0]["verdict_reason"] == "not_terminated_cleanly"
    assert harvests[0]["oracle_kind"] == "self_consistent"

    runs = _scrape_runs(db_conn, company_id)
    assert runs[0]["guard_reason"] == "unverified_harvest"
    assert runs[0]["closed_jobs"] == 0
    # Nothing closed; no miss accrued; the missing job 3 stays OPEN.
    assert _open_count(db_conn, company_id) == 3
    assert _job_status(db_conn, company_id, 3) == "OPEN"
    assert _max_misses(db_conn, company_id) == 0


# --- VERIFIED first run (streak 0 < 3) closes nothing ------------------------

async def test_verified_first_run_closes_nothing_and_marks_healthy(db_conn, monkeypatch):
    company_id = "u-bafirst001"
    _seed_browser_agent_company(db_conn, company_id)
    _seed_open_jobs(db_conn, company_id, 1, 3, last_seen_hours_ago=48)
    _patch_env(monkeypatch)

    evidence = HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=None, pages_fetched=1,
    )
    _patch_runner(monkeypatch, rows=_agent_rows([1, 2]), evidence=evidence)

    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[0]["verdict"] == "VERIFIED"
    assert harvests[0]["verdict_reason"] == "self_consistent_ok"

    runs = _scrape_runs(db_conn, company_id)
    assert runs[0]["guard_reason"] == "first_verified_run"   # streak 0 < 3
    assert runs[0]["closed_jobs"] == 0
    assert _job_status(db_conn, company_id, 3) == "OPEN"

    company = _company_row(db_conn, company_id)
    assert company["health_state"] == "healthy"
    assert company["tracking_started_at"] is not None


# --- VERIFIED but streak_too_short (past first run) still closes nothing ------

async def test_verified_streak_too_short_closes_nothing(db_conn, monkeypatch):
    company_id = "u-bastreak01"
    _seed_browser_agent_company(db_conn, company_id)
    _set_tracking(db_conn, company_id)   # isolate the streak gate (not first run)
    _seed_open_jobs(db_conn, company_id, 1, 3, last_seen_hours_ago=48)
    _patch_env(monkeypatch)

    evidence = HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=None, pages_fetched=1,
    )

    # Runs 1 & 2: VERIFIED but streak < 3 → misses accrue on job 3, no close.
    for run in range(2):
        _patch_runner(monkeypatch, rows=_agent_rows([1, 2]), evidence=evidence)
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()
        assert _job_status(db_conn, company_id, 3) == "OPEN"
        assert _scrape_runs(db_conn, company_id)[run]["guard_reason"] == "streak_too_short"
        assert _scrape_runs(db_conn, company_id)[run]["closed_jobs"] == 0

    assert _open_count(db_conn, company_id) == 3
    assert _max_misses(db_conn, company_id) == 2   # accrued, but never closed


# --- runner RAISE → FAILED writes nothing ------------------------------------

async def test_runner_raise_is_failed_and_writes_nothing(db_conn, monkeypatch):
    company_id = "u-bafailed01"
    _seed_browser_agent_company(db_conn, company_id)
    _seed_open_jobs(db_conn, company_id, 1, 3, last_seen_hours_ago=48)
    _patch_env(monkeypatch)

    _patch_runner(
        monkeypatch,
        raises=RecipeExecutionError("browser-agent id '0-650' is a DOM row-index"),
    )

    # A FAILED run re-raises so Procrastinate retries.
    with pytest.raises(RecipeExecutionError, match="row-index"):
        await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "FAILED"

    runs = _scrape_runs(db_conn, company_id)
    assert runs[0]["success"] is False
    assert runs[0]["error_count"] == 1
    assert runs[0]["closed_jobs"] == 0
    # Nothing written: no browser-agent job rows created; the pre-existing 3 untouched.
    assert _open_count(db_conn, company_id) == 3
    assert _job_status(db_conn, company_id, 1) == "OPEN"
    assert _max_misses(db_conn, company_id) == 0
