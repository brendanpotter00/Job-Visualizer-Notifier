"""Integration tests for the normalize_location task (Unit 5). Real Postgres via
db_conn; LLM mocked. Invoke by awaiting the coroutine directly. db_conn.rollback()
after each run to observe the task connection's committed writes (cross-session).
"""

from __future__ import annotations

import uuid

import pytest
from psycopg2 import sql

from procrastinate import JobContext
from procrastinate.jobs import Job

from api.services.llm_client import CanonicalLocation, LocationLLMError, MissingAnthropicKeyError
from api.services.location_normalization import normalize_string
from api.tasks.normalize_location import _RETRY_MAX_ATTEMPTS, CONFIDENCE_FLOOR, normalize_location

pytestmark = pytest.mark.asyncio

_LOCATIONS = sql.Identifier("locations")
_LOCATION_ALIASES = sql.Identifier("location_aliases")
_ALIAS_LOCATIONS = sql.Identifier("alias_locations")
_JOB_LOCATIONS = sql.Identifier("job_locations")
_JOB_LISTINGS = sql.Identifier("job_listings")
_SOURCE_ID = "google_scraper"


@pytest.fixture(autouse=True)
def _clean(db_conn):
    cur = db_conn.cursor()
    cur.execute(sql.SQL("TRUNCATE {}, {}, {}, {}, {} CASCADE").format(
        _JOB_LOCATIONS, _ALIAS_LOCATIONS, _LOCATION_ALIASES, _LOCATIONS, _JOB_LISTINGS))
    db_conn.commit()


def _insert_job(db_conn, *, location, job_id=None):
    jid = job_id or f"job-{uuid.uuid4().hex[:8]}"
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("INSERT INTO {} (id, title, company, location, url, source_id, "
                "created_at, first_seen_at, last_seen_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)").format(_JOB_LISTINGS),
        (jid, "Software Engineer", "acme", location, "https://example.com/jobs/1", _SOURCE_ID,
         "2025-01-10T10:00:00Z", "2025-01-10T10:00:00Z", "2025-01-15T10:00:00Z"),
    )
    db_conn.commit()
    return jid


def _status(db_conn, job_id):
    cur = db_conn.cursor()
    cur.execute(sql.SQL("SELECT normalization_status AS s FROM {} WHERE id = %s").format(_JOB_LISTINGS), (job_id,))
    row = cur.fetchone()
    return (row["s"] if isinstance(row, dict) else row[0]) if row else None


def _job_locations(db_conn, job_id):
    cur = db_conn.cursor()
    cur.execute(sql.SQL("SELECT normalized_location_id AS lid, is_primary FROM {} "
                        "WHERE job_listing_id = %s ORDER BY is_primary DESC, normalized_location_id").format(_JOB_LOCATIONS), (job_id,))
    return [dict(r) for r in cur.fetchall()]


def _count(db_conn, ident, where_sql="", params=()):
    cur = db_conn.cursor()
    q = sql.SQL("SELECT COUNT(*) AS n FROM {}").format(ident)
    if where_sql:
        q = q + sql.SQL(" WHERE " + where_sql)
    cur.execute(q, params)
    row = cur.fetchone()
    return int(row["n"] if isinstance(row, dict) else row[0])


def _patch_llm(monkeypatch, *, return_value=None, side_effect=None):
    from unittest.mock import AsyncMock
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    else:
        mock.return_value = return_value
    monkeypatch.setattr("api.tasks.normalize_location.normalize_location_via_llm", mock)
    return mock


def _loc(canonical, kind, city=None, region=None, country=None, remote_scope=None, confidence=0.95):
    return CanonicalLocation(canonical_name=canonical, kind=kind, city=city, region=region,
                             country=country, remote_scope=remote_scope, confidence=confidence)


async def test_single_location_miss_writes_everything(db_conn, monkeypatch):
    jid = _insert_job(db_conn, location="sf")
    llm = _patch_llm(monkeypatch, return_value=[_loc("San Francisco, CA, US", "city", "San Francisco", "CA", "US", confidence=0.97)])
    await normalize_location(job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) == "done"
    assert llm.await_count == 1
    jl = _job_locations(db_conn, jid)
    assert len(jl) == 1 and jl[0]["is_primary"] is True
    assert _count(db_conn, _LOCATIONS) == 1
    assert _count(db_conn, _LOCATION_ALIASES, "raw_text = %s", (normalize_string("sf"),)) == 1
    assert _count(db_conn, _ALIAS_LOCATIONS) == 1


async def test_tier1_cache_hit_does_not_call_llm(db_conn, monkeypatch):
    key = normalize_string("San Francisco")
    cur = db_conn.cursor()
    cur.execute(sql.SQL("INSERT INTO {} (canonical_name, kind, city, region, country, remote_scope) "
                        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id").format(_LOCATIONS),
                ("San Francisco, CA, US", "city", "San Francisco", "CA", "US", None))
    r = cur.fetchone(); loc_id = r["id"] if isinstance(r, dict) else r[0]
    cur.execute(sql.SQL("INSERT INTO {} (raw_text, source, confidence) VALUES (%s,'llm',%s)").format(_LOCATION_ALIASES), (key, 0.97))
    cur.execute(sql.SQL("INSERT INTO {} (raw_text, normalized_location_id, position) VALUES (%s,%s,0)").format(_ALIAS_LOCATIONS), (key, loc_id))
    db_conn.commit()
    jid = _insert_job(db_conn, location="San Francisco")
    llm = _patch_llm(monkeypatch, return_value=[])
    await normalize_location(job_id=jid)
    db_conn.rollback()
    assert llm.await_count == 0
    assert _status(db_conn, jid) == "done"
    jl = _job_locations(db_conn, jid)
    assert len(jl) == 1 and jl[0]["lid"] == loc_id and jl[0]["is_primary"] is True
    assert _count(db_conn, _LOCATION_ALIASES) == 1


async def test_multi_location_two_rows_ordered(db_conn, monkeypatch):
    jid = _insert_job(db_conn, location="Sunnyvale, CA, USA; Kirkland, WA, USA")
    _patch_llm(monkeypatch, return_value=[
        _loc("Sunnyvale, CA, US", "city", "Sunnyvale", "CA", "US", confidence=0.96),
        _loc("Kirkland, WA, US", "city", "Kirkland", "WA", "US", confidence=0.96)])
    await normalize_location(job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) == "done"
    assert _count(db_conn, _LOCATIONS) == 2
    assert _count(db_conn, _ALIAS_LOCATIONS) == 2
    jl = _job_locations(db_conn, jid)
    assert len(jl) == 2 and len([r for r in jl if r["is_primary"]]) == 1
    cur = db_conn.cursor()
    cur.execute(sql.SQL("SELECT position FROM {} ORDER BY position").format(_ALIAS_LOCATIONS))
    assert [(r["position"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()] == [0, 1]


async def test_null_location_marks_failed_no_llm(db_conn, monkeypatch):
    jid = _insert_job(db_conn, location=None)
    llm = _patch_llm(monkeypatch, return_value=[])
    await normalize_location(job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) == "failed"
    assert llm.await_count == 0
    assert _job_locations(db_conn, jid) == []


async def test_empty_whitespace_location_marks_failed_no_llm(db_conn, monkeypatch):
    jid = _insert_job(db_conn, location="   ")
    llm = _patch_llm(monkeypatch, return_value=[])
    await normalize_location(job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) == "failed"
    assert llm.await_count == 0


async def test_missing_api_key_leaves_null_no_raise(db_conn, monkeypatch):
    jid = _insert_job(db_conn, location="sf")
    _patch_llm(monkeypatch, side_effect=MissingAnthropicKeyError("no key"))
    await normalize_location(job_id=jid)  # must NOT raise
    db_conn.rollback()
    assert _status(db_conn, jid) is None
    assert _count(db_conn, _LOCATIONS) == 0
    assert _count(db_conn, _LOCATION_ALIASES) == 0


def _ctx(attempts: int) -> JobContext:
    """A worker-style JobContext whose job has run ``attempts`` prior times."""
    return JobContext(job=Job(
        queue="normalize", lock=None, queueing_lock=None,
        task_name="normalize_location", attempts=attempts,
    ))


async def test_llm_error_propagates_and_status_stays_null(db_conn, monkeypatch):
    """Non-final attempts: LocationLLMError propagates (Procrastinate retries) and
    the row stays NULL so a retry / the safety-net can still pick it up."""
    jid = _insert_job(db_conn, location="sf")
    _patch_llm(monkeypatch, side_effect=LocationLLMError("unparseable"))
    with pytest.raises(LocationLLMError):
        await normalize_location(_ctx(attempts=0), job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) is None
    assert _count(db_conn, _LOCATIONS) == 0


async def test_llm_error_final_attempt_marks_failed(db_conn, monkeypatch):
    """FINAL attempt of a permanent parse failure must mark the row 'failed'.

    Without this, the terminal queue failure frees the queueing_lock while the
    row stays NULL, so scan_unnormalized re-defers the same job every tick
    forever — an unbounded LLM-spend loop for any string the model can never
    parse. 'failed' is terminal: the safety-net's WHERE normalization_status
    IS NULL no longer selects the row.
    """
    jid = _insert_job(db_conn, location="sf")
    _patch_llm(monkeypatch, side_effect=LocationLLMError("permanently unparseable"))
    with pytest.raises(LocationLLMError):
        await normalize_location(_ctx(attempts=_RETRY_MAX_ATTEMPTS), job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) == "failed"
    assert _count(db_conn, _LOCATIONS) == 0
    assert _job_locations(db_conn, jid) == []


async def test_llm_error_without_context_stays_null(db_conn, monkeypatch):
    """Direct invocation with no JobContext (attempts unknown) must behave like a
    non-final attempt: propagate and leave the row NULL."""
    jid = _insert_job(db_conn, location="sf")
    _patch_llm(monkeypatch, side_effect=LocationLLMError("unparseable"))
    with pytest.raises(LocationLLMError):
        await normalize_location(job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) is None


async def test_low_confidence_marks_failed_no_writes(db_conn, monkeypatch):
    jid = _insert_job(db_conn, location="someplace ambiguous")
    below = max(CONFIDENCE_FLOOR - 0.1, 0.0)
    _patch_llm(monkeypatch, return_value=[_loc("Guess City, ZZ, US", "city", "Guess City", "ZZ", "US", confidence=below)])
    await normalize_location(job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) == "failed"
    assert _count(db_conn, _LOCATIONS) == 0
    assert _count(db_conn, _LOCATION_ALIASES) == 0
    assert _job_locations(db_conn, jid) == []


async def test_idempotent_double_run_no_duplicates(db_conn, monkeypatch):
    jid = _insert_job(db_conn, location="sf")
    _patch_llm(monkeypatch, return_value=[_loc("San Francisco, CA, US", "city", "San Francisco", "CA", "US", confidence=0.97)])
    await normalize_location(job_id=jid)
    db_conn.rollback()
    # Reset to NULL and re-run to exercise ON CONFLICT DO NOTHING convergence (not just the done short-circuit).
    cur = db_conn.cursor()
    cur.execute(sql.SQL("UPDATE {} SET normalization_status = NULL WHERE id = %s").format(_JOB_LISTINGS), (jid,))
    db_conn.commit()
    await normalize_location(job_id=jid)
    db_conn.rollback()
    assert _status(db_conn, jid) == "done"
    assert _count(db_conn, _LOCATIONS) == 1
    assert len(_job_locations(db_conn, jid)) == 1
    assert _count(db_conn, _LOCATION_ALIASES) == 1
    assert _count(db_conn, _ALIAS_LOCATIONS) == 1


async def test_job_vanished_returns_without_error(db_conn, monkeypatch):
    llm = _patch_llm(monkeypatch, return_value=[])
    await normalize_location(job_id="does-not-exist")
    assert llm.await_count == 0


async def test_renormalization_replaces_links(db_conn, monkeypatch):
    """Re-running with a DIFFERENT result must REPLACE job_locations (drives FIX-1).

    Without the DELETE-before-INSERT, the job would stay linked to BOTH A and B
    (and could carry two is_primary=true rows). We force a Tier-1 MISS on both
    runs by using a distinct raw location each time (different cache key), so the
    Tier-2 writer path runs both times.
    """
    jid = _insert_job(db_conn, location="city-a-raw")
    _patch_llm(monkeypatch, return_value=[_loc("Alpha City, AA, US", "city", "Alpha City", "AA", "US", confidence=0.97)])
    await normalize_location(job_id=jid)
    db_conn.rollback()
    jl = _job_locations(db_conn, jid)
    assert len(jl) == 1
    a_id = jl[0]["lid"]
    assert jl[0]["is_primary"] is True

    # Reset status to NULL and change BOTH the raw location (fresh cache key ->
    # Tier-1 miss) and the LLM result to a DIFFERENT location B.
    cur = db_conn.cursor()
    cur.execute(sql.SQL("UPDATE {} SET normalization_status = NULL, location = %s WHERE id = %s").format(_JOB_LISTINGS),
                ("city-b-raw", jid))
    db_conn.commit()
    _patch_llm(monkeypatch, return_value=[_loc("Beta City, BB, US", "city", "Beta City", "BB", "US", confidence=0.97)])
    await normalize_location(job_id=jid)
    db_conn.rollback()

    assert _status(db_conn, jid) == "done"
    jl2 = _job_locations(db_conn, jid)
    # Old A link is gone; only B remains; exactly one is_primary=true.
    assert len(jl2) == 1
    b_id = jl2[0]["lid"]
    assert b_id != a_id
    assert jl2[0]["is_primary"] is True
    assert len([r for r in jl2 if r["is_primary"]]) == 1


async def test_remote_existing_row_dedup_via_is_not_distinct_from(db_conn, monkeypatch):
    """Pre-seeded REMOTE location (NULL city/region/country) must dedup on re-use.

    Exercises persist_llm_result's ON CONFLICT DO NOTHING -> IS NOT DISTINCT FROM
    fallback against the NULL-bearing canonical columns (uq_locations_canonical is
    NULLS NOT DISTINCT). No duplicate locations row may be created.
    """
    cur = db_conn.cursor()
    cur.execute(sql.SQL("INSERT INTO {} (canonical_name, kind, city, region, country, remote_scope) "
                        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id").format(_LOCATIONS),
                ("Remote (US)", "remote", None, None, None, "us"))
    r = cur.fetchone()
    pre_id = r["id"] if isinstance(r, dict) else r[0]
    db_conn.commit()
    assert _count(db_conn, _LOCATIONS) == 1

    jid = _insert_job(db_conn, location="Remote - United States")
    _patch_llm(monkeypatch, return_value=[
        _loc("Remote (US)", "remote", city=None, region=None, country=None, remote_scope="us", confidence=0.95)])
    await normalize_location(job_id=jid)
    db_conn.rollback()

    assert _status(db_conn, jid) == "done"
    # No duplicate locations row: the existing remote row was reused.
    assert _count(db_conn, _LOCATIONS) == 1
    jl = _job_locations(db_conn, jid)
    assert len(jl) == 1 and jl[0]["lid"] == pre_id and jl[0]["is_primary"] is True
