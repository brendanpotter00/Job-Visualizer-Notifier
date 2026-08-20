"""E7 Phase 3c — the leaf task's ``browser_fetch`` transport branch.

$0: the browser_fetch runner (which would launch a real Chromium subprocess) is
monkeypatched. Proves the tier reaches the UNCHANGED gate/verdict/upsert tail and,
above all, invariant #2 — **never wrong-close**:

* a VERIFIED declared_probed harvest upserts its rows, marks the company healthy and
  still closes nothing on the first run (``first_verified_run``);
* a runner RAISE (a bot wall, an SSRF rejection, a dead Chromium) is a recorded FAILED
  run that writes NOTHING destructive: zero closes AND zero miss increments, asserted
  directly against the DB;
* the kill-switch OFF is a no-op skip that spawns nothing, closes nothing and accrues
  no miss;
* the STORED ``oracle_kind`` drives the verdict (a discovered company has no ATS
  provider, so the provider-derived oracle does not apply).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from psycopg2 import sql

import api.services.browser_fetch.runner as bf_runner
from api.config import settings
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
)

pytestmark = pytest.mark.asyncio

_RECIPE = json.loads(
    (Path(__file__).parent / "fixtures" / "recipes" / "tiktok_browser_fetch.json").read_text()
)


def _bf_env(monkeypatch) -> None:
    """Point the task at the test schema AND turn the browser_fetch kill-switch on.

    ``custom_company_discovery_enabled`` is that switch, and since the capture pivot it is
    the ONLY discovery flag: discovery is the only thing that ever creates a
    browser_fetch company, so with it off the tier is dormant end-to-end.
    """
    _patch_env(monkeypatch)
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)


def _seed_browser_fetch_company(db_conn, company_id: str) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state) "
            "VALUES (%s, %s, 'discovered', %s, TRUE, '{{}}'::jsonb, 'user', 24, now(), "
            "'unverified')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, "https://lifeattiktok.com/"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, script, script_version, transport, oracle_kind) "
            "VALUES (%s, %s::jsonb, 1, 'browser_fetch', 'declared_probed')"
        ).format(sql.Identifier("company_scripts")),
        (company_id, json.dumps(_RECIPE)),
    )
    db_conn.commit()


def _patch_runner(monkeypatch, *, rows=None, evidence=None, raises=None) -> None:
    """Patch the browser_fetch runner (imported lazily by the leaf task's branch)."""
    async def _fake(script, *, transport=None, oracle_kind=None):
        if raises is not None:
            raise raises
        return list(rows or []), evidence
    monkeypatch.setattr(bf_runner, "run_browser_fetch", _fake)


def _recipe_rows(ids):
    return [
        {"id": str(i), "title": f"Software Engineer {i}",
         "url": f"https://lifeattiktok.com/search/{i}", "location": "San Jose"}
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


# --- VERIFIED harvest → upserts, healthy, still closes nothing ----------------

async def test_browser_fetch_harvest_verifies_and_upserts(db_conn, monkeypatch):
    """A stored browser_fetch company replays through the SAME gate; the oracle is
    the STORED declared_probed column (a discovered company's ats is 'discovered',
    which the provider-derived path would map to 'none' and never verify)."""
    company_id = "u-bfverif001"
    _seed_browser_fetch_company(db_conn, company_id)
    _bf_env(monkeypatch)

    evidence = HarvestEvidence(
        declared_total=3, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=True, pages_fetched=2,
    )
    _patch_runner(monkeypatch, rows=_recipe_rows([1, 2, 3]), evidence=evidence)

    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "VERIFIED"
    assert harvests[0]["verdict_reason"] == "declared_exact"
    assert harvests[0]["oracle_kind"] == "declared_probed"   # STORED, not provider-derived
    assert harvests[0]["records_harvested"] == 3
    assert harvests[0]["declared_total"] == 3
    assert harvests[0]["page_advance_ok"] is True

    runs = _scrape_runs(db_conn, company_id)
    assert runs[0]["success"] is True
    assert runs[0]["jobs_seen"] == 3
    assert runs[0]["new_jobs"] == 3
    assert runs[0]["closed_jobs"] == 0
    assert runs[0]["guard_reason"] == "first_verified_run"

    # The rows really landed, scoped to this custom company.
    assert _open_count(db_conn, company_id) == 3
    assert _job_status(db_conn, company_id, 1) == "OPEN"

    company = _company_row(db_conn, company_id)
    assert company["health_state"] == "healthy"
    assert company["tracking_started_at"] is not None
    assert company["last_success_at"] is not None


# --- INVARIANT #2: a runner RAISE closes nothing and increments no miss -------

async def test_runner_raise_is_failed_with_zero_closes_and_zero_misses(db_conn, monkeypatch):
    """The load-bearing one. Three jobs are seeded 48h stale — old enough that a
    close-eligible run WOULD close them — and the runner raises the way a bot wall,
    an SSRF rejection or a dead Chromium raises. The run must be FAILED, write
    nothing destructive, and NOT count as a miss."""
    company_id = "u-bffailed01"
    _seed_browser_fetch_company(db_conn, company_id)
    _seed_open_jobs(db_conn, company_id, 1, 3, last_seen_hours_ago=48)
    _bf_env(monkeypatch)

    _patch_runner(
        monkeypatch,
        raises=RecipeExecutionError(
            "HTTP 403 from the in-browser fetch on page 0 (body starts: 'bot wall')"
        ),
    )

    # A FAILED run re-raises so the failure is visible to Procrastinate.
    with pytest.raises(RecipeExecutionError, match="in-browser fetch"):
        await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "FAILED"
    assert harvests[0]["records_harvested"] == 0

    runs = _scrape_runs(db_conn, company_id)
    assert runs[0]["success"] is False
    assert runs[0]["error_count"] == 1
    assert runs[0]["closed_jobs"] == 0

    # THE assertions: nothing closed, nothing missed, nothing added.
    assert _open_count(db_conn, company_id) == 3
    assert _job_status(db_conn, company_id, 1) == "OPEN"
    assert _job_status(db_conn, company_id, 3) == "OPEN"
    assert _max_misses(db_conn, company_id) == 0

    company = _company_row(db_conn, company_id)
    assert company["last_success_at"] is None


# --- MIGRATION: a company left on the RETIRED browser_agent transport ----------

async def test_a_retired_browser_agent_company_fails_loudly_and_closes_nothing(
    db_conn, monkeypatch
):
    """The Stagehand tier is deleted, but a company discovered under it may still carry
    ``transport='browser_agent'`` in ``company_scripts``. Two things must hold, and only
    an explicit branch gives both: the run FAILS with a message an operator can act on
    (falling through to the ATS ``else`` would try to fetch an ATS provider literally
    named 'discovered' and fail with something meaningless), and — invariant #2 — it
    closes ZERO jobs and increments ZERO misses, so the board goes stale in the UI
    rather than losing its history.

    An operator (or the user) recovers by Removing the board and re-adding the same
    careers URL, which runs capture discovery and rewrites the script."""
    company_id = "u-retiredba1"
    _seed_browser_fetch_company(db_conn, company_id)
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE company_scripts SET transport = 'browser_agent' WHERE company_id = %s",
        (company_id,),
    )
    db_conn.commit()
    _seed_open_jobs(db_conn, company_id, 1, 3, last_seen_hours_ago=48)
    _bf_env(monkeypatch)

    with pytest.raises(RecipeExecutionError, match="must be re-discovered"):
        await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[0]["verdict"] == "FAILED"
    assert "browser_agent" in (harvests[0]["verdict_reason"] or "")
    assert _open_count(db_conn, company_id) == 3
    assert _max_misses(db_conn, company_id) == 0
    assert _scrape_runs(db_conn, company_id)[0]["closed_jobs"] == 0


# --- kill-switch OFF → no-op, no subprocess ----------------------------------

async def test_flag_off_replay_is_noop_and_never_reaches_the_runner(db_conn, monkeypatch):
    company_id = "u-bfflagoff1"
    _seed_browser_fetch_company(db_conn, company_id)
    _seed_open_jobs(db_conn, company_id, 1, 3, last_seen_hours_ago=48)
    _patch_env(monkeypatch)
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)

    # If the runner were reached it would launch Chromium; make that a loud failure.
    async def _boom(script, *, transport=None, oracle_kind=None):
        raise AssertionError("the browser_fetch runner must NOT run when the flag is off")

    monkeypatch.setattr(bf_runner, "run_browser_fetch", _boom)

    # No exception propagates → the runner was never called (AssertionError is not in
    # the leaf task's narrow except, so a call would escape and fail this test).
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[0]["verdict_reason"] == "browser_fetch_disabled"
    runs = _scrape_runs(db_conn, company_id)
    assert runs[0]["closed_jobs"] == 0
    assert _open_count(db_conn, company_id) == 3
    assert _max_misses(db_conn, company_id) == 0


# --- an UNVERIFIED browser_fetch run is still harmless ------------------------

async def test_count_mismatch_is_unverified_and_closes_nothing(db_conn, monkeypatch):
    """A partial harvest (declared 5, got 3) must NOT be read as a shrunken board:
    UNVERIFIED, rows still upserted, nothing closed, no miss accrued."""
    company_id = "u-bfunverif1"
    _seed_browser_fetch_company(db_conn, company_id)
    _seed_open_jobs(db_conn, company_id, 90, 92, last_seen_hours_ago=48)
    _bf_env(monkeypatch)

    evidence = HarvestEvidence(
        declared_total=5, cap_hit=False, terminated_cleanly=False,
        page_advance_ok=True, pages_fetched=2,
    )
    _patch_runner(monkeypatch, rows=_recipe_rows([1, 2, 3]), evidence=evidence)

    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[0]["verdict"] == "UNVERIFIED"
    assert harvests[0]["verdict_reason"] == "count_mismatch"

    runs = _scrape_runs(db_conn, company_id)
    assert runs[0]["guard_reason"] == "unverified_harvest"
    assert runs[0]["closed_jobs"] == 0
    # The 3 harvested rows landed alongside the 3 untouched pre-existing ones.
    assert _open_count(db_conn, company_id) == 6
    assert _job_status(db_conn, company_id, 90) == "OPEN"
    assert _max_misses(db_conn, company_id) == 0
