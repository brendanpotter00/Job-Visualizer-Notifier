"""Tests for the /health/worker DB-freshness liveness endpoint.

The endpoint queries `MAX(procrastinate_events.at)`; if older than 35
minutes it returns 503. This is what Railway will use as healthcheckPath
so it can restart the container when the worker silently hangs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _wipe(db_conn) -> None:
    cur = db_conn.cursor()
    cur.execute("DELETE FROM procrastinate_events")
    cur.execute("DELETE FROM worker_heartbeats")
    db_conn.commit()


def _insert_event(db_conn, age_seconds: float) -> None:
    """Insert one synthetic procrastinate_events row with the given age."""
    cur = db_conn.cursor()
    # Procrastinate's schema requires a non-null job_id with a FK to
    # procrastinate_jobs; create a stub row first.
    cur.execute(
        """
        INSERT INTO procrastinate_jobs (queue_name, task_name, args, status)
        VALUES ('test_q', 'test_task', '{}'::jsonb, 'succeeded')
        RETURNING id
        """
    )
    job_id = cur.fetchone()["id"]
    at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    cur.execute(
        "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, 'succeeded', %s)",
        (job_id, at),
    )
    db_conn.commit()


def _insert_heartbeat(db_conn, age_seconds: float) -> None:
    at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    cur = db_conn.cursor()
    cur.execute("INSERT INTO worker_heartbeats (at) VALUES (%s)", (at,))
    db_conn.commit()


def test_health_worker_returns_ok_when_both_recent(client, db_conn):
    _wipe(db_conn)
    _insert_event(db_conn, age_seconds=120)
    _insert_heartbeat(db_conn, age_seconds=60)

    resp = client.get("/health/worker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["gap_seconds"] < 300
    assert body["heartbeat_gap_seconds"] < 120


def test_health_worker_returns_503_when_events_stale(client, db_conn):
    _wipe(db_conn)
    _insert_event(db_conn, age_seconds=40 * 60)  # past 35-min threshold
    _insert_heartbeat(db_conn, age_seconds=60)  # fresh

    resp = client.get("/health/worker")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "stale"
    assert body["gap_seconds"] > 35 * 60


def test_health_worker_returns_503_when_heartbeat_stale(client, db_conn):
    """A stale heartbeat alone is enough to flip to 503 — catches the case
    where event writes still succeed but the scheduler is hung."""
    _wipe(db_conn)
    _insert_event(db_conn, age_seconds=60)  # fresh
    _insert_heartbeat(db_conn, age_seconds=15 * 60)  # past 10-min threshold

    resp = client.get("/health/worker")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "stale"
    assert body["heartbeat_gap_seconds"] > 10 * 60


def test_health_worker_cold_start_is_ok(client, db_conn):
    """No events or heartbeats ever → cold-start state, not stale."""
    _wipe(db_conn)

    resp = client.get("/health/worker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cold"
    assert body["latest_event"] is None
    assert body["latest_heartbeat"] is None
