"""Tests for the custom-company claim task's backpressure counting (E7).

The load-bearing property (ASSESS 2): a fetch job wedged in ``'doing'`` (worker
killed mid-task — Procrastinate does not auto-requeue stalled jobs) must NEVER
count toward the claim budget, or three wedged jobs would starve the whole
feature forever. The ceiling counts ``'todo'`` (queued-but-not-started) ONLY.
"""

from __future__ import annotations

from psycopg2 import sql

from api.tasks.claim_custom_companies import (
    _QUEUE_BACKPRESSURE_CEILING,
    _count_queued_fetches,
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
