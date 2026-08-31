"""E7 Phase 2 §8 — the destructive-tail regression + integration suite.

Drives ``fetch_custom_company`` directly against controlled harvests and asserts
the load-bearing safety properties: only a VERIFIED run may close; a capped
Workday board is UNVERIFIED (never silently-partial); the 36h floor and the
consecutive-VERIFIED streak; the fleet breaker; and that a non-executed / zero /
UNVERIFIED run is never a miss.

Reuses the small seeding/monkeypatch helpers from ``test_fetch_custom_company``.
"""

from __future__ import annotations

import httpx
import pytest
from psycopg2 import sql

import api.tasks.fetch_custom_company as task_mod
from api.services import greenhouse_client, lever_client, workday_client
from api.services.harvest_meta import HarvestEvidence
from api.tasks.fetch_custom_company import fetch_custom_company
from scripts.shared.constants import custom
from scripts.shared.utils import get_iso_timestamp

from api.tests.test_fetch_custom_company import (
    _company_row,
    _job_status,
    _patch_env,
    _raw_job,
    _rows,
    _scrape_runs,
    _seed_custom_company,
    backdate_last_seen,
    patch_greenhouse_meta,
)

pytestmark = pytest.mark.asyncio

_WD_CFG = {"base_url": "https://x.wd5.myworkdayjobs.com",
           "tenant_slug": "t", "career_site_slug": "s"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _seed_open_jobs(db_conn, company_id, lo, hi, *, last_seen_hours_ago=0.0):
    """Seed OPEN job_listings [lo, hi] under custom:<id>; the AFTER INSERT
    trigger materializes their job_freshness rows. Optionally backdate every
    freshness row's last_seen_at (to satisfy the 36h close floor in a test)."""
    source_id = custom(company_id)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO job_listings
          (id, title, company, location, url, source_id, details, created_at,
           posted_on, closed_on, status, has_matched, ai_metadata, first_seen_at,
           details_scraped, experience_level, is_remote_eligible)
        SELECT g::text, 'J'||g, %s, 'Remote', 'https://x/'||g, %s, '{}'::jsonb,
           now(), NULL, NULL, 'OPEN', false, '{}'::jsonb, now(), true, NULL, false
        FROM generate_series(%s, %s) g
        """,
        (company_id, source_id, lo, hi),
    )
    if last_seen_hours_ago:
        cur.execute(
            "UPDATE job_freshness SET last_seen_at = now() - (%s * interval '1 hour') "
            "WHERE source_id = %s",
            (last_seen_hours_ago, source_id),
        )
    db_conn.commit()


def _open_count(db_conn, company_id) -> int:
    cur = db_conn.cursor()
    cur.execute(
        "SELECT count(*) AS n FROM job_listings WHERE source_id = %s AND status = 'OPEN'",
        (custom(company_id),),
    )
    return int(cur.fetchone()["n"])


def _max_misses(db_conn, company_id) -> int:
    cur = db_conn.cursor()
    cur.execute(
        "SELECT COALESCE(max(consecutive_misses), 0) AS m FROM job_freshness WHERE source_id = %s",
        (custom(company_id),),
    )
    return int(cur.fetchone()["m"])


def _set_tracking(db_conn, company_id):
    """Mark a company as already past day-0 (tracking set, healthy) so
    first_verified_run does not fire — used to isolate the streak gate."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "UPDATE {} SET tracking_started_at = now() - interval '10 days', "
            "health_state = 'healthy' WHERE id = %s"
        ).format(sql.Identifier("companies")),
        (company_id,),
    )
    db_conn.commit()


def _insert_custom_run(db_conn, run_company, *, success):
    """Insert one scrape_runs row under a custom:<id> source (for the fleet
    breaker's night-scoped aggregate)."""
    cur = db_conn.cursor()
    ts = get_iso_timestamp()
    cur.execute(
        """
        INSERT INTO scrape_runs
          (run_id, company, started_at, completed_at, mode, jobs_seen, new_jobs,
           closed_jobs, details_fetched, error_count, source_id, success)
        VALUES (%s, %s, %s, %s, 'full', 0, 0, 0, 0, 0, %s, %s)
        """,
        (f"run-{run_company}-{ts}", run_company, ts, ts, custom(run_company), success),
    )
    db_conn.commit()


def _patch_workday_meta(monkeypatch, raw_jobs, evidence):
    async def _fake(provider_config, http):
        return list(raw_jobs), evidence
    monkeypatch.setattr(workday_client, "fetch_jobs_with_meta", _fake)


def _patch_lever(monkeypatch, raw_jobs):
    async def _fake(board_token, http):
        return list(raw_jobs)
    monkeypatch.setattr(lever_client, "fetch_jobs", _fake)


def _lever_raw(ids):
    return [{"id": str(i), "text": "Eng", "hostedUrl": f"https://x/{i}"} for i in ids]


def _wd_raw(ids):
    return [{"title": f"J{i}", "externalPath": f"/job/{i}", "bulletFields": [str(i)]}
            for i in ids]


# --------------------------------------------------------------------------- #
# F.1 — Target 11,960-vs-2,000 regression
# --------------------------------------------------------------------------- #

async def test_target_workday_cap_regression(db_conn, monkeypatch):
    company_id = "u-target0001"
    _seed_custom_company(db_conn, company_id, "wd", ats="workday", provider_config=_WD_CFG)
    _seed_open_jobs(db_conn, company_id, 1, 11960)
    _patch_env(monkeypatch)

    evidence = HarvestEvidence(
        declared_total=11960, cap_hit=True, terminated_cleanly=False,
        page_advance_ok=True, pages_fetched=100,
    )
    _patch_workday_meta(monkeypatch, _wd_raw(range(1, 2001)), evidence)

    for _ in range(2):  # run twice — a repeated cap must never accumulate to a close
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()

    assert _open_count(db_conn, company_id) == 11960
    assert _max_misses(db_conn, company_id) == 0

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 2
    assert all(h["verdict"] == "UNVERIFIED" for h in harvests)
    assert all(h["verdict_reason"] == "cap_hit" for h in harvests)
    assert all(h["cap_hit"] is True for h in harvests)
    assert all(h["declared_total"] == 11960 for h in harvests)
    assert all(h["records_harvested"] == 2000 for h in harvests)

    runs = _scrape_runs(db_conn, company_id)
    assert len(runs) == 2
    assert all(r["guard_reason"] == "unverified_harvest" for r in runs)
    assert all(r["closed_jobs"] == 0 for r in runs)


# --------------------------------------------------------------------------- #
# F.2 — capped Workday is UNVERIFIED, not silently partial (real client loop)
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeWdHttp:
    """Async-context httpx stand-in whose .post always returns a full page with
    an unreachable total, so the REAL client loop hits WORKDAY_MAX_PAGES."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        offset = json["offset"]
        postings = [
            {"title": f"J{offset+k}", "externalPath": f"/job/{offset+k}",
             "bulletFields": [str(offset + k)]}
            for k in range(20)
        ]
        return _Resp({"jobPostings": postings, "total": 11960})


async def test_capped_workday_is_unverified_not_silently_partial(db_conn, monkeypatch):
    company_id = "u-wdcap0001"
    _seed_custom_company(db_conn, company_id, "wd", ats="workday", provider_config=_WD_CFG)
    _patch_env(monkeypatch)
    # Drive the REAL client loop (not a mocked verdict) so the end-to-end path
    # proves the client surfaces cap_hit rather than a silent partial.
    monkeypatch.setattr(task_mod.httpx, "AsyncClient", lambda *a, **k: _FakeWdHttp())

    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert len(harvests) == 1
    assert harvests[0]["verdict"] == "UNVERIFIED"  # never VERIFIED
    assert harvests[0]["verdict_reason"] == "cap_hit"
    assert harvests[0]["cap_hit"] is True
    assert harvests[0]["records_harvested"] == 2000
    assert _scrape_runs(db_conn, company_id)[0]["closed_jobs"] == 0


# --------------------------------------------------------------------------- #
# F.3 — Greenhouse graduates + closes a genuinely-removed job (2 runs + 36h)
# --------------------------------------------------------------------------- #

async def test_greenhouse_declared_total_verifies_and_closes_removed_job(db_conn, monkeypatch):
    company_id = "u-ghclose001"
    _seed_custom_company(db_conn, company_id, "gh")
    _patch_env(monkeypatch)

    # Run 1: {1,2,3} → VERIFIED, first_verified_run (closes nothing, tracking set).
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2), _raw_job(3)], 3)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    assert _company_row(db_conn, company_id)["health_state"] == "healthy"

    # Run 2: {1,2} → VERIFIED; job 3 → miss 1 (threshold not reached).
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    assert _job_status(db_conn, company_id)["3"]["consecutive_misses"] == 1

    # Backdate job 3 past the 36h floor, then Run 3: miss 2 + aged → CLOSE.
    backdate_last_seen(db_conn, company_id, "3", 37)
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    jobs = _job_status(db_conn, company_id)
    assert jobs["3"]["status"] == "CLOSED"
    assert jobs["1"]["status"] == "OPEN" and jobs["2"]["status"] == "OPEN"
    runs = _scrape_runs(db_conn, company_id)
    assert runs[-1]["closed_jobs"] == 1


# --------------------------------------------------------------------------- #
# F.4 — a manual rerun cannot accelerate closure past the 36h floor
# --------------------------------------------------------------------------- #

async def test_manual_rerun_cannot_accelerate_closure(db_conn, monkeypatch):
    company_id = "u-ghfloor001"
    _seed_custom_company(db_conn, company_id, "gh")
    _patch_env(monkeypatch)

    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2), _raw_job(3)], 3)
    await fetch_custom_company(company_id=company_id)   # run 1: first_verified
    db_conn.rollback()

    # Runs 2 & 3 within 36h — job 3 reaches misses>=2 but last_seen is recent.
    for _ in range(2):
        patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()

    jobs = _job_status(db_conn, company_id)
    assert jobs["3"]["status"] == "OPEN"          # floor blocked the close
    assert jobs["3"]["consecutive_misses"] >= 2

    # Now age it past 36h and rerun → it closes. The wall clock, not the counter,
    # is what a scheduler double-fire cannot shortcut.
    backdate_last_seen(db_conn, company_id, "3", 37)
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    assert _job_status(db_conn, company_id)["3"]["status"] == "CLOSED"


# --------------------------------------------------------------------------- #
# F.5 — a non-executed (FAILED) run — and an UNVERIFIED run — is not a miss
# --------------------------------------------------------------------------- #

async def test_non_executed_run_is_not_a_miss(db_conn, monkeypatch):
    company_id = "u-ghfail0001"
    _seed_custom_company(db_conn, company_id, "gh")
    _patch_env(monkeypatch)

    # Run 1 seeds {1,2,3} VERIFIED.
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2), _raw_job(3)], 3)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    # Run 2: the client raises → FAILED. Nothing destructive, not a miss.
    async def _boom(board_token, http):
        raise httpx.HTTPError("boom")
    monkeypatch.setattr(greenhouse_client, "fetch_jobs_with_meta", _boom)
    with pytest.raises(Exception):
        await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    assert _max_misses(db_conn, company_id) == 0
    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[-1]["verdict"] == "FAILED"
    runs = _scrape_runs(db_conn, company_id)
    assert runs[-1]["success"] is False
    assert runs[-1]["closed_jobs"] == 0

    # Run 3: an UNVERIFIED (count_mismatch) run also never increments a miss,
    # even though job 3 is absent from the harvest.
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 5)  # declared 5 vs 2
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[-1]["verdict"] == "UNVERIFIED"
    assert harvests[-1]["verdict_reason"] == "count_mismatch"
    assert _max_misses(db_conn, company_id) == 0


# --------------------------------------------------------------------------- #
# F.6 — abandoned board fails the zero-chain (Marcus & Millichap, Lever 200 [])
# --------------------------------------------------------------------------- #

async def test_abandoned_board_fails_zero_chain(db_conn, monkeypatch):
    company_id = "u-mm00000001"
    _seed_custom_company(db_conn, company_id, "mmboard", ats="lever")
    _seed_open_jobs(db_conn, company_id, 1, 5)  # 5 real jobs already live
    _patch_env(monkeypatch)

    _patch_lever(monkeypatch, [])  # a polished empty board: 200 []
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    assert _open_count(db_conn, company_id) == 5  # nothing closed
    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[-1]["verdict"] == "UNVERIFIED"
    assert harvests[-1]["verdict_reason"] == "zero_unproven"
    runs = _scrape_runs(db_conn, company_id)
    # D1: verdict-first — the gate reason wins over the empty_scrape guard.
    assert runs[-1]["guard_reason"] == "unverified_harvest"
    assert runs[-1]["closed_jobs"] == 0
    assert _max_misses(db_conn, company_id) == 0


# --------------------------------------------------------------------------- #
# F.7 — the fleet circuit breaker suppresses closes
# --------------------------------------------------------------------------- #

async def test_fleet_breaker_suppresses_closes(db_conn, monkeypatch):
    company_id = "u-fleet00001"
    _seed_custom_company(db_conn, company_id, "gh")
    _patch_env(monkeypatch)

    # Run 1 ({1,2,3}) + Run 2 ({1,2}) → job 3 at miss 1.
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2), _raw_job(3)], 3)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    # Trip the fleet breaker: 5 failed custom runs (> 20% of the night's total).
    for i in range(5):
        _insert_custom_run(db_conn, f"other{i}", success=False)

    backdate_last_seen(db_conn, company_id, "3", 37)
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)   # run 3 — would close, but breaker
    db_conn.rollback()

    jobs = _job_status(db_conn, company_id)
    assert jobs["3"]["status"] == "OPEN"
    runs = _scrape_runs(db_conn, company_id)
    assert runs[-1]["guard_reason"] == "fleet_breaker"
    assert runs[-1]["closed_jobs"] == 0

    # Flip the fleet healthy → the same setup now closes.
    cur = db_conn.cursor()
    cur.execute("UPDATE scrape_runs SET success = TRUE WHERE success IS FALSE")
    db_conn.commit()
    backdate_last_seen(db_conn, company_id, "3", 37)
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)   # run 4
    db_conn.rollback()
    assert _job_status(db_conn, company_id)["3"]["status"] == "CLOSED"


# --------------------------------------------------------------------------- #
# F.8 — self_consistent needs a 3-VERIFIED streak (vs declared_probed's 2)
# --------------------------------------------------------------------------- #

async def test_self_consistent_needs_three_verified_runs_to_close(db_conn, monkeypatch):
    company_id = "u-selfcons01"
    _seed_custom_company(db_conn, company_id, "lever", ats="lever")
    # Pre-set tracking so first_verified_run does not fire — isolate the streak.
    _set_tracking(db_conn, company_id)
    # Seed {1,2,3}; job 3 is aged past 36h and never re-harvested.
    _seed_open_jobs(db_conn, company_id, 1, 3, last_seen_hours_ago=37)
    _patch_env(monkeypatch)

    # Runs 1 & 2: VERIFIED but streak_too_short → misses accrue, no close yet.
    for run in range(2):
        _patch_lever(monkeypatch, _lever_raw([1, 2]))
        await fetch_custom_company(company_id=company_id)
        db_conn.rollback()
        assert _job_status(db_conn, company_id)["3"]["status"] == "OPEN"
        assert _scrape_runs(db_conn, company_id)[run]["guard_reason"] == "streak_too_short"

    # Run 3: the streak completes → the accrued misses close job 3 (36h satisfied).
    _patch_lever(monkeypatch, _lever_raw([1, 2]))
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    assert _job_status(db_conn, company_id)["3"]["status"] == "CLOSED"
    runs = _scrape_runs(db_conn, company_id)
    assert runs[-1]["guard_reason"] is None
    assert runs[-1]["closed_jobs"] == 1


class _FakeEfHttp:
    """Async-context httpx stand-in for Eightfold: `real_total` real jobs but a
    server `count` that under-reports, driving a full-page count-break whose
    confirming probe finds MORE jobs (Finding 5)."""

    def __init__(self, real_total, count):
        self._real = real_total
        self._count = count

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None, timeout=None):
        start = params["start"]
        n = min(10, max(0, self._real - start))
        positions = [
            {"id": start + k, "name": f"J{start+k}",
             "canonicalPositionUrl": f"https://x/{start+k}"}
            for k in range(n)
        ]
        return _Resp({"positions": positions, "count": self._count})


async def test_eightfold_count_underreport_stays_unverified_and_cannot_close(db_conn, monkeypatch):
    """Finding 5 end-to-end: an Eightfold self_consistent tenant whose `count`
    under-reports terminates on a full-page count-break → the confirming probe
    proves incompleteness → UNVERIFIED `not_terminated_cleanly`, so pre-existing
    OPEN jobs are never closed."""
    company_id = "u-ef8fold001"
    _seed_custom_company(
        db_conn, company_id, "ef", ats="eightfold",
        provider_config={"tenant_host": "foo.eightfold.ai", "domain": "d"},
    )
    _seed_open_jobs(db_conn, company_id, 900, 901)  # two live jobs not in the harvest
    _patch_env(monkeypatch)
    # Drive the REAL client loop; count=30 under-reports a 50-job board.
    monkeypatch.setattr(task_mod.httpx, "AsyncClient", lambda *a, **k: _FakeEfHttp(50, 30))

    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()

    harvests = _rows(db_conn, "company_harvests", company_id)
    assert harvests[-1]["verdict"] == "UNVERIFIED"
    assert harvests[-1]["verdict_reason"] == "not_terminated_cleanly"
    assert harvests[-1]["cap_hit"] is False
    # The pre-existing live jobs are untouched; nothing closed.
    jobs = _job_status(db_conn, company_id)
    assert jobs["900"]["status"] == "OPEN" and jobs["901"]["status"] == "OPEN"
    assert _scrape_runs(db_conn, company_id)[-1]["closed_jobs"] == 0
    assert _scrape_runs(db_conn, company_id)[-1]["guard_reason"] == "unverified_harvest"


async def test_declared_probed_closes_a_run_earlier_than_self_consistent(db_conn, monkeypatch):
    """The distinguishing counterpart to F.8: a declared_probed (Greenhouse)
    company with tracking pre-set closes on its 2nd miss — no streak gate — one
    run earlier than the self_consistent company above."""
    company_id = "u-declprobed1"
    _seed_custom_company(db_conn, company_id, "gh")
    _set_tracking(db_conn, company_id)
    _seed_open_jobs(db_conn, company_id, 3, 3, last_seen_hours_ago=37)  # job 3 aged
    _patch_env(monkeypatch)

    # Run 1: {1,2} declared 2 → VERIFIED, close-eligible immediately (tracking set);
    # job 3 → miss 1.
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    assert _job_status(db_conn, company_id)["3"]["status"] == "OPEN"

    # Run 2: miss 2 + 36h → CLOSE (one run earlier than self_consistent).
    patch_greenhouse_meta(monkeypatch, [_raw_job(1), _raw_job(2)], 2)
    await fetch_custom_company(company_id=company_id)
    db_conn.rollback()
    assert _job_status(db_conn, company_id)["3"]["status"] == "CLOSED"
