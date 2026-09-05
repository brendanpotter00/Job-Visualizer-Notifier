"""Integration tests: scan_unnormalized safety-net periodic task body.

Real Postgres via module-scoped db_conn; normalize_location deferral mocked.
job_listings truncated before each test by conftest's autouse clean_tables.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import psycopg2
import pytest
from procrastinate import exceptions as procrastinate_exceptions
from psycopg2 import sql

import api.tasks.scan_unnormalized as scan_mod
from api.config import settings
from api.tasks.scan_unnormalized import scan_unnormalized

pytestmark = pytest.mark.asyncio

_REQUIRED_COLS = {
    "title": "Software Engineer", "company": "acme", "url": "https://example.com/job",
    "source_id": "scan_test_source", "created_at": "2025-01-10T10:00:00Z",
    "first_seen_at": "2025-01-10T10:00:00Z",
}


def _insert_job(conn, job_id, normalization_status):
    cols = ["id", *_REQUIRED_COLS.keys(), "normalization_status"]
    vals = [job_id, *_REQUIRED_COLS.values(), normalization_status]
    cur = conn.cursor()
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier("job_listings"),
        sql.SQL(", ").join(sql.Identifier(c) for c in cols),
        sql.SQL(", ").join(sql.Placeholder() for _ in vals),
    )
    cur.execute(query, vals)
    conn.commit()


@pytest.fixture
def defer_mock(monkeypatch):
    async_defer = AsyncMock()
    configured = MagicMock()
    configured.defer_async = async_defer
    configure = MagicMock(return_value=configured)
    monkeypatch.setattr(scan_mod.normalize_location, "configure", configure)
    async_defer._configure = configure
    return async_defer


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


async def test_defers_one_per_null_row(db_conn, defer_mock):
    ids = [f"job-{i}" for i in range(5)]
    for jid in ids:
        _insert_job(db_conn, jid, None)
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 5
    assert defer_mock.await_count == 5
    assert {c.kwargs["job_id"] for c in defer_mock.await_args_list} == set(ids)
    locks = {c.kwargs["queueing_lock"] for c in defer_mock._configure.call_args_list}
    assert locks == {f"normalize:{jid}" for jid in ids}


async def test_throttle_caps_at_limit(db_conn, defer_mock):
    for i in range(10):
        _insert_job(db_conn, f"job-{i}", None)
    deferred = await scan_unnormalized(timestamp=0, limit=3)
    assert deferred == 3
    assert defer_mock.await_count == 3


async def test_only_null_rows_selected(db_conn, defer_mock):
    _insert_job(db_conn, "null-1", None)
    _insert_job(db_conn, "null-2", None)
    _insert_job(db_conn, "done-1", "done")
    _insert_job(db_conn, "failed-1", "failed")
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 2
    assert {c.kwargs["job_id"] for c in defer_mock.await_args_list} == {"null-1", "null-2"}


async def test_skip_when_no_key(db_conn, defer_mock, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    for i in range(3):
        _insert_job(db_conn, f"job-{i}", None)
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 0
    defer_mock.assert_not_awaited()


async def test_skip_when_empty_string_key(db_conn, defer_mock, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    _insert_job(db_conn, "job-0", None)
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 0
    defer_mock.assert_not_awaited()


async def test_already_enqueued_is_swallowed(db_conn, defer_mock):
    for jid in [f"job-{i}" for i in range(3)]:
        _insert_job(db_conn, jid, None)
    call_count = {"n": 0}
    async def flaky(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise procrastinate_exceptions.AlreadyEnqueued("dup")
        return None
    defer_mock.side_effect = flaky
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 2
    assert call_count["n"] == 3


async def test_connector_error_is_swallowed(db_conn, defer_mock):
    for jid in [f"job-{i}" for i in range(3)]:
        _insert_job(db_conn, jid, None)
    call_count = {"n": 0}
    async def flaky(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise psycopg2.OperationalError("transient blip")
        return None
    defer_mock.side_effect = flaky
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 2
    assert call_count["n"] == 3


async def test_no_rows_returns_zero(db_conn, defer_mock):
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 0
    defer_mock.assert_not_awaited()


async def test_all_defers_failed_escalates_to_error(db_conn, defer_mock, caplog):
    """A fully-broken tick (every defer fails, deferred==0) escalates to a
    distinct ERROR summary so it surfaces in Railway's @level:error stream,
    not just the INFO summary (FIX-5)."""
    import logging

    for jid in [f"job-{i}" for i in range(3)]:
        _insert_job(db_conn, jid, None)
    defer_mock.side_effect = procrastinate_exceptions.ConnectorException("connector down")

    with caplog.at_level(logging.ERROR, logger="api.tasks.scan_unnormalized"):
        deferred = await scan_unnormalized(timestamp=0, limit=10)

    assert deferred == 0
    # The distinctive fully-failed-tick escalation message (not the per-id
    # logger.exception lines) must be present at ERROR level.
    assert any(
        rec.levelno == logging.ERROR
        and rec.name == "api.tasks.scan_unnormalized"
        and "ALL" in rec.getMessage()
        and "no progress this tick" in rec.getMessage()
        for rec in caplog.records
    )


# --- cold-key collapse: don't pay Haiku N times for one answer ---------------

def _insert_job_at(conn, job_id, location):
    """Insert a NULL-status job carrying a specific raw location."""
    cols = ["id", *_REQUIRED_COLS.keys(), "normalization_status", "location"]
    vals = [job_id, *_REQUIRED_COLS.values(), None, location]
    cur = conn.cursor()
    cur.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier("job_listings"),
            sql.SQL(", ").join(sql.Identifier(c) for c in cols),
            sql.SQL(", ").join(sql.Placeholder() for _ in vals),
        ),
        vals,
    )
    conn.commit()


def _seed_alias(conn, raw_text):
    """Make `raw_text` a Tier-1 cache HIT (an alias row is all the scan checks)."""
    cur = conn.cursor()
    cur.execute(
        sql.SQL("INSERT INTO {} (raw_text, source, confidence) VALUES (%s, 'llm', 0.9) "
                "ON CONFLICT (raw_text) DO NOTHING").format(sql.Identifier("location_aliases")),
        (raw_text,),
    )
    conn.commit()


async def test_collapses_jobs_sharing_one_cold_location(db_conn, defer_mock):
    """5 jobs, one uncached location -> ONE defer, not five.

    This is the spend fix: in prod ~2,000 OPEN jobs read exactly "San Francisco".
    Deferring all of them means 2,000 Haiku calls for one cache entry.
    """
    for i in range(5):
        _insert_job_at(db_conn, f"sf-{i}", "San Francisco")
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 1
    assert defer_mock.await_count == 1


async def test_does_not_collapse_when_the_key_is_already_cached(db_conn, defer_mock):
    """A cached key costs no LLM call, so all 5 defer -- that is how the backlog drains."""
    _seed_alias(db_conn, "san francisco")
    for i in range(5):
        _insert_job_at(db_conn, f"sf-{i}", "San Francisco")
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 5
    assert defer_mock.await_count == 5


async def test_distinct_cold_locations_all_defer(db_conn, defer_mock):
    cities = ["Austin, TX", "Seattle, WA", "Denver, CO", "Boston, MA"]
    for i, city in enumerate(cities):
        _insert_job_at(db_conn, f"job-{i}", city)
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == len(cities)


async def test_collapse_keys_on_the_normalized_form(db_conn, defer_mock):
    """Casing/whitespace/dash variants are ONE key, so they collapse together."""
    for i, raw in enumerate(["San Francisco", "  san   francisco ", "SAN FRANCISCO"]):
        _insert_job_at(db_conn, f"sf-{i}", raw)
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 1


async def test_null_location_jobs_are_never_collapsed(db_conn, defer_mock):
    """They terminate in tx1 (marked 'failed') without touching the LLM.

    Collapsing them would drain a NULL-location backlog at one row per tick for
    no saving at all.
    """
    for i in range(5):
        _insert_job_at(db_conn, f"nul-{i}", None)
    deferred = await scan_unnormalized(timestamp=0, limit=10)
    assert deferred == 5
