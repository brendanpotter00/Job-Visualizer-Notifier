"""Tests for the custom-company claim task's backpressure counting + defer path (E7).

The load-bearing property (ASSESS 2): a fetch job wedged in ``'doing'`` (worker
killed mid-task — Procrastinate does not auto-requeue stalled jobs) must NEVER
count toward the claim budget, or three wedged jobs would starve the whole
feature forever. The ceiling counts ``'todo'`` (queued-but-not-started) ONLY.

The second half covers :func:`defer_fetch`, the ONE way a custom harvest is enqueued —
shared by this tick and by ``discover_custom_company``'s immediate first harvest. Its
per-company queueing lock is the backstop that makes two concurrent harvests of the
same board impossible even in the window where both paths reach the broker.
"""

from __future__ import annotations

import pytest
from procrastinate import exceptions as procrastinate_exceptions
from psycopg2 import sql

import api.tasks.claim_custom_companies as claim_mod
from api.tasks.claim_custom_companies import (
    _QUEUE_BACKPRESSURE_CEILING,
    _count_queued_fetches,
    defer_fetch,
)


def test_count_is_zero_when_procrastinate_table_absent(db_conn):
    # Fresh per-module schema has no procrastinate_jobs — best-effort → 0.
    assert _count_queued_fetches(db_conn) == 0


def test_doing_jobs_do_not_count_toward_the_budget(db_conn):
    """Three wedged 'doing' fetches + one 'todo': the count is 1, and the budget
    stays positive — the fleet keeps being claimed rather than starving."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("CREATE TABLE {} (id serial PRIMARY KEY, task_name text, status text)")
        .format(sql.Identifier("procrastinate_jobs"))
    )
    cur.execute(
        "INSERT INTO procrastinate_jobs (task_name, status) VALUES "
        "('fetch_custom_company', 'doing'),"
        "('fetch_custom_company', 'doing'),"
        "('fetch_custom_company', 'doing'),"
        "('fetch_custom_company', 'todo'),"
        "('fetch_custom_company', 'succeeded'),"
        "('some_other_task', 'todo')"
    )
    db_conn.commit()
    try:
        # Only the single 'todo' fetch_custom_company counts.
        assert _count_queued_fetches(db_conn) == 1
        # Budget stays > 0 despite three wedged 'doing' jobs — no starvation.
        assert _QUEUE_BACKPRESSURE_CEILING - _count_queued_fetches(db_conn) > 0
    finally:
        cur.execute(
            sql.SQL("DROP TABLE {}").format(sql.Identifier("procrastinate_jobs"))
        )
        db_conn.commit()


# --- defer_fetch: the single enqueue path and its per-company lock -------------


class _FakeBroker:
    """Procrastinate's queueing-lock semantics, minus the broker.

    A lock is unique among QUEUED jobs: a second ``defer`` under a lock that is already
    waiting raises ``AlreadyEnqueued``. Emulated rather than driven live because the
    property under test is ours (do the two enqueue paths collide?), not Procrastinate's
    — and the test suite has no broker connection.
    """

    def __init__(self) -> None:
        self.queued: list[str] = []

    def configure(self, **kwargs):
        lock = kwargs["queueing_lock"]
        broker = self

        class _Configured:
            async def defer_async(self, **job_kwargs):
                if lock in broker.queued:
                    raise procrastinate_exceptions.AlreadyEnqueued(lock)
                broker.queued.append(lock)

        return _Configured()


def _install_broker(monkeypatch) -> _FakeBroker:
    broker = _FakeBroker()
    monkeypatch.setattr(claim_mod.fetch_custom_company, "configure", broker.configure)
    return broker


@pytest.mark.asyncio
async def test_a_second_defer_for_the_same_company_cannot_create_a_second_harvest(
    monkeypatch,
):
    """THE INTERLOCK, backstop half. ``push_next_run_at`` normally keeps the tick from
    even looking at a company whose first harvest is already queued; if it ever does
    (clock skew, a reschedule that failed after the defer landed), the lock answers
    ``already_queued`` and ONE job exists — never two racing harvests of one board."""
    broker = _install_broker(monkeypatch)

    assert await defer_fetch("u-abc123") == "deferred"
    assert await defer_fetch("u-abc123") == "already_queued"

    assert broker.queued == ["custom:u-abc123"]


@pytest.mark.asyncio
async def test_the_lock_is_per_company_so_two_boards_still_both_run(monkeypatch):
    """The lock must isolate a company, not the feature: one board already queued cannot
    be allowed to block the rest of the fleet."""
    broker = _install_broker(monkeypatch)

    assert await defer_fetch("u-aaa") == "deferred"
    assert await defer_fetch("u-bbb") == "deferred"

    assert broker.queued == ["custom:u-aaa", "custom:u-bbb"]


@pytest.mark.asyncio
async def test_a_broker_error_is_reported_not_swallowed_into_success(monkeypatch):
    """``failed`` exists so a caller can tell "scheduled" from "not scheduled". Folding
    a broker error into a success is what would let the accepted-board path push
    ``next_run_at`` a day out for a harvest that was never queued."""
    class _Configured:
        async def defer_async(self, **kwargs):
            raise procrastinate_exceptions.ConnectorException("broker down")

    monkeypatch.setattr(
        claim_mod.fetch_custom_company, "configure", lambda **kw: _Configured()
    )

    assert await defer_fetch("u-ccc") == "failed"
