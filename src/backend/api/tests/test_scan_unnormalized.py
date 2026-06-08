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
    "first_seen_at": "2025-01-10T10:00:00Z", "last_seen_at": "2025-01-10T10:00:00Z",
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
