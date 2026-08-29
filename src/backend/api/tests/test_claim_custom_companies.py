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
from api.services import custom_companies_service as ccs
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


# --- cadence + jitter: the scheduling arithmetic -------------------------------
#
# These pin the two numbers a faster cadence made load-bearing:
#
#   1. the cadence itself, against what a PUBLISHED company actually gets, and
#   2. the jitter bound, which used to be a flat ±90 min and is now a fraction of
#      the cadence — because a flat ±90 min on a 1 h cadence puts ``next_run_at``
#      in the PAST for roughly half of all draws, dissolving the interlock that
#      makes two concurrent harvests of one board impossible.


def _published_fan_out_interval_minutes() -> int:
    """The interval a PUBLISHED company is actually re-read on, read off the app.

    Read from Procrastinate's live periodic registry rather than from a literal, so
    this measures the deployed schedule instead of a copy of it. All six ATS fan-outs
    share one cron; if that ever stops being true the assert below fails, which is the
    correct outcome — "what a published company gets" would no longer be one number.
    """
    import api.tasks.enqueue_ashby_fan_out  # noqa: F401
    import api.tasks.enqueue_eightfold_fan_out  # noqa: F401
    import api.tasks.enqueue_gem_fan_out  # noqa: F401
    import api.tasks.enqueue_greenhouse_fan_out  # noqa: F401
    import api.tasks.enqueue_lever_fan_out  # noqa: F401
    import api.tasks.enqueue_workday_fan_out  # noqa: F401
    from api.tasks.procrastinate_app import procrastinate_app

    registry = procrastinate_app.periodic_registry.periodic_tasks
    crons = {
        task.cron
        for (task_name, _), task in registry.items()
        if task_name.startswith("enqueue_") and task_name.endswith("_fan_out")
    }
    assert len(crons) == 1, f"the six ATS fan-outs no longer share one cron: {crons}"
    cron = crons.pop()
    minute_field = cron.split()[0]
    assert minute_field.startswith("*/"), f"unexpected fan-out cron {cron!r}"
    return int(minute_field[2:])


def test_the_custom_cadence_matches_what_a_published_company_gets():
    """THE CADENCE DECISION, pinned to the evidence it was taken from.

    A published board is re-read every ``*/30`` minutes. ``cadence_hours`` is an
    INTEGER column, so 30 minutes is not expressible and 1 hour is the nearest legal
    value — same order of magnitude, erring SLOW. The two bounds are the whole
    argument:

    * never FASTER than the published fleet — a private, unverified board must not be
      privileged over a curated one; and
    * never more than 2× slower. The old 24 h was 48× slower, which is precisely what
      made a close take two days.
    """
    published_s = _published_fan_out_interval_minutes() * 60
    custom_s = ccs.DEFAULT_CADENCE_HOURS * 3600

    assert custom_s >= published_s
    assert custom_s <= 2 * published_s


def test_the_cadence_is_longer_than_one_harvests_own_timeout():
    """Why "every 15 minutes" was never an option, stated as a test.

    ``fetch_custom_company`` gives a single harvest 900 s before it is killed. A
    cadence at or below that schedules a board's next run while its current one may
    still legally be executing; the queueing lock would absorb the collision, but only
    by silently dropping alternate runs.
    """
    from api.tasks.fetch_custom_company import _TASK_TIMEOUT_S

    assert ccs.DEFAULT_CADENCE_HOURS * 3600 > _TASK_TIMEOUT_S


def _seed(db_conn, company_id: str, cadence_hours) -> None:
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, "
        "provider_config, visibility, cadence_hours, next_run_at, health_state) "
        "VALUES (%s, %s, 'greenhouse', %s, TRUE, '{}'::jsonb, 'user', %s, now(), "
        "'unverified')",
        (company_id, company_id, company_id, cadence_hours),
    )
    db_conn.commit()


def _next_run_offset_s(db_conn, company_id: str) -> float:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        "SELECT EXTRACT(EPOCH FROM (next_run_at - now())) AS s "
        "FROM companies WHERE id = %s",
        (company_id,),
    )
    return float(cur.fetchone()["s"])


@pytest.mark.parametrize("unit", [-1.0, 1.0])
@pytest.mark.parametrize("cadence_hours", [1, 24, None])
def test_a_push_never_leaves_the_row_due_again(
    db_conn, monkeypatch, unit, cadence_hours
):
    """THE REGRESSION GUARD for the flat-jitter bug, at both extremes of the draw.

    ``push_next_run_at`` is documented as the PRIMARY interlock against a double
    harvest: the ``*/15`` tick selects on ``next_run_at <= now()``, so a pushed row is
    not a candidate at all. That holds only while ``|jitter| < cadence``. With the old
    flat ±90 min and a 1 h cadence, ``unit = -1`` lands 30 minutes in the PAST and the
    interlock is simply gone — hence the strict inequality rather than "roughly a
    cadence away". ``None`` exercises the COALESCE fallback.
    """
    monkeypatch.setattr(claim_mod, "_jitter_unit", lambda: unit)
    company_id = f"u-push{int(unit)}{cadence_hours}"
    _seed(db_conn, company_id, cadence_hours)

    claim_mod.push_next_run_at(db_conn, company_id)

    assert _next_run_offset_s(db_conn, company_id) > 0
    assert company_id not in claim_mod._claim_due_companies(db_conn, 10)


@pytest.mark.parametrize(
    "cadence_hours,expected_bound_s",
    [
        # 0.25 x 1 h = 15 min, under the 90-minute cap.
        (1, 15 * 60),
        # 0.25 x 24 h = 6 h, so the cap binds and an explicitly-24h row keeps EXACTLY
        # the old +/-90 min spread. The change is a no-op for anything already scheduled.
        (24, 90 * 60),
    ],
)
def test_the_jitter_bound_is_a_quarter_of_the_cadence_capped_at_ninety_minutes(
    db_conn, monkeypatch, cadence_hours, expected_bound_s
):
    """The bound itself, measured at both extremes rather than inferred.

    The last assert is the de-synchronisation guarantee the jitter exists for: two
    companies added in the same second must not land on the same tick forever, so the
    spread between the extreme draws has to stay non-zero.
    """
    cadence_s = cadence_hours * 3600
    offsets = {}
    for unit in (-1.0, 1.0):
        monkeypatch.setattr(claim_mod, "_jitter_unit", lambda u=unit: u)
        company_id = f"u-bound{cadence_hours}{int(unit)}"
        _seed(db_conn, company_id, cadence_hours)
        claim_mod.push_next_run_at(db_conn, company_id)
        offsets[unit] = _next_run_offset_s(db_conn, company_id)

    # 5 s of slack for the clock moving between the UPDATE and the read-back.
    assert offsets[-1.0] == pytest.approx(cadence_s - expected_bound_s, abs=5)
    assert offsets[1.0] == pytest.approx(cadence_s + expected_bound_s, abs=5)
    assert offsets[1.0] - offsets[-1.0] == pytest.approx(2 * expected_bound_s, abs=5)


def test_the_jitter_draw_is_symmetric_and_actually_varies():
    """The de-synchronisation half, which the parametrised tests above cannot see.

    They pin ``_jitter_unit`` to its extremes, so a mutant that returns a CONSTANT — 0.0
    is the tempting simplification once the bound is derived in SQL — passes all of them
    while re-synchronising every company added in the same tick, forever. That herd is
    the only thing the jitter exists to prevent. Symmetric, too: a one-sided draw would
    walk the whole fleet in one direction instead of spreading it.
    """
    draws = [claim_mod._jitter_unit() for _ in range(500)]

    assert all(-1.0 <= d <= 1.0 for d in draws)
    assert any(d < -0.5 for d in draws)
    assert any(d > 0.5 for d in draws)


def test_the_claim_tick_pushes_a_claimed_row_out_of_its_own_next_selection(
    db_conn, monkeypatch
):
    """The claim path shares the statement, so it inherits the same guarantee.

    Worst-case draw, claimed and re-selected in the same breath: a row the tick just
    handed to a harvest must not be handed out again on the very next tick.
    """
    monkeypatch.setattr(claim_mod, "_jitter_unit", lambda: -1.0)
    company_id = "u-tickpush"
    _seed(db_conn, company_id, ccs.DEFAULT_CADENCE_HOURS)

    assert company_id in claim_mod._claim_due_companies(db_conn, 10)
    assert company_id not in claim_mod._claim_due_companies(db_conn, 10)
