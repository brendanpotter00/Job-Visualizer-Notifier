"""Tests for the heartbeat periodic task + cleanup.

Covers:
- ``_insert_heartbeat_sync`` writes one row with a near-now ``at``.
- ``_cleanup_heartbeats_sync`` deletes rows older than 24h, keeps the rest.
- The async ``worker_heartbeat`` task swallows ``psycopg2.Error`` /
  ``OSError`` (transient DB hiccups don't kill the canary; the freshness
  probe will catch a real outage) — pinned so a future widen to
  ``except Exception`` is caught.
- The async ``worker_heartbeat`` task PROPAGATES programmer errors
  (``AttributeError`` etc.) so Procrastinate marks the task failed —
  pinned so the narrow ``(psycopg2.Error, OSError)`` catch can't quietly
  become ``except Exception``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from api.tasks.heartbeat import (
    _cleanup_heartbeats_sync,
    _insert_heartbeat_sync,
    worker_heartbeat,
)


@pytest.fixture(autouse=True)
def _wipe_heartbeats(db_conn):
    cur = db_conn.cursor()
    cur.execute("DELETE FROM worker_heartbeats")
    db_conn.commit()
    yield


def _select_heartbeats(db_conn) -> list[dict]:
    cur = db_conn.cursor()
    cur.execute("SELECT id, at FROM worker_heartbeats ORDER BY at DESC")
    return list(cur.fetchall())


def test_insert_heartbeat_writes_one_row(db_conn):
    import os

    db_url = os.environ["DATABASE_URL"]
    _insert_heartbeat_sync(db_url)
    db_conn.rollback()

    rows = _select_heartbeats(db_conn)
    assert len(rows) == 1
    # The `at` value should be within the last 10 seconds.
    age = (datetime.now(timezone.utc) - rows[0]["at"]).total_seconds()
    assert 0 <= age < 10


def test_cleanup_prunes_only_old_rows(db_conn):
    import os

    db_url = os.environ["DATABASE_URL"]
    cur = db_conn.cursor()
    # Three old rows (25h-26h ago) and two fresh rows.
    now = datetime.now(timezone.utc)
    for hours_ago in (26, 25, 24.5):
        cur.execute(
            "INSERT INTO worker_heartbeats (at) VALUES (%s)",
            (now - timedelta(hours=hours_ago),),
        )
    for minutes_ago in (5, 1):
        cur.execute(
            "INSERT INTO worker_heartbeats (at) VALUES (%s)",
            (now - timedelta(minutes=minutes_ago),),
        )
    db_conn.commit()

    deleted = _cleanup_heartbeats_sync(db_url)
    db_conn.rollback()

    assert deleted == 3
    remaining = _select_heartbeats(db_conn)
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_worker_heartbeat_swallows_psycopg_error(monkeypatch, caplog):
    """A transient DB error inside the insert path is caught and logged
    at ERROR — the task itself returns None so Procrastinate doesn't
    mark it failed and pile up retries. The freshness probe is the
    canary for a persistent failure, not Procrastinate's retry state.
    """
    import logging
    import api.tasks.heartbeat as heartbeat_mod

    def boom(_db_url):
        raise psycopg2.OperationalError("simulated DB hiccup")

    monkeypatch.setattr(heartbeat_mod, "_insert_heartbeat_sync", boom)

    with caplog.at_level(logging.ERROR, logger="api.tasks.heartbeat"):
        result = await worker_heartbeat(timestamp=0)

    assert result is None
    matching = [
        r for r in caplog.records
        if r.levelno == logging.ERROR
        and "worker_heartbeat insert failed" in r.getMessage()
    ]
    assert matching, "expected ERROR log for the swallowed psycopg2 error"
    # exc_info=True is load-bearing: Railway's @level:error surface relies
    # on the stack trace to be greppable. A future refactor to drop
    # exc_info would silently break post-mortem debugging.
    assert matching[0].exc_info is not None, (
        "log line must include exc_info=True so the stack trace appears in Railway"
    )


@pytest.mark.asyncio
async def test_worker_heartbeat_propagates_programmer_error(monkeypatch):
    """An ``AttributeError`` (programmer bug) must propagate so
    Procrastinate marks the task failed. This pins the narrow
    ``(psycopg2.Error, OSError)`` catch against a quiet widening to
    ``except Exception`` — which would silently swallow real bugs.
    """
    import api.tasks.heartbeat as heartbeat_mod

    def boom(_db_url):
        raise AttributeError("simulated programmer error")

    monkeypatch.setattr(heartbeat_mod, "_insert_heartbeat_sync", boom)

    with pytest.raises(AttributeError, match="simulated programmer error"):
        await worker_heartbeat(timestamp=0)
