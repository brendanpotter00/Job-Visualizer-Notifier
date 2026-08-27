"""The wedged-row reconciler: a 'discovering' row can never spin forever — E7.

Two rows sat at "Setting up… / Opening the page" indefinitely on 2026-08-26 because the
interactive worker was dead. The worker is fixed; the ROW had no way back regardless,
because ``discover_custom_company`` is ``retry=1`` and nothing else ever writes that
state. These tests pin the sweep that ends it, and — more importantly — they pin the two
sides of the recognition rule, because a reaper that gets this wrong destroys a
successful setup that was merely slow:

* a run whose task is GENUINELY STILL RUNNING is never reaped, even when it has
  published no progress for an hour (the progress writer swallows its own failures by
  design, so silence is not death), and
* an abandoned one lands on the ORDINARY refusal — the same state, badge and copy the
  discovery-timeout path already produces — never on some new state the frontend would
  have to learn.

No broker and no worker: these open Procrastinate's TABLES through the test connection
(the ``procrastinate_schema`` fixture) and never touch ``procrastinate_app``, whose
connector is built at import time from the developer's real database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from psycopg2 import sql

import api.tasks.reconcile_discovering as reconcile
from api.main import _BULK_QUEUES, _INTERACTIVE_QUEUES
from api.services import custom_companies_service as ccs
from api.tasks.reconcile_discovering import (
    _STALL_GRACE_SECONDS,
    reconcile_discovering_companies,
    sweep_stalled_discoveries,
)

_SUBMITTED = "https://acme.example/careers"

_GRACE_MINUTES = _STALL_GRACE_SECONDS // 60


def _row(db_conn, query: str, params: tuple = ()):
    cur = db_conn.cursor()
    cur.execute(query, params)
    return cur.fetchone()


def _seed_user(db_conn) -> str:
    user_id = uuid.uuid4().hex
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at) "
            "VALUES (%s, %s, %s, now(), now())"
        ).format(sql.Identifier("users")),
        (user_id, f"auth0|{user_id[:12]}", f"{user_id[:8]}@example.com"),
    )
    db_conn.commit()
    return user_id


def _discovering(db_conn, user_id: str, url: str) -> str:
    """The provisional row the 202 add path inserts, already narrating step 1."""
    created = ccs.add_discovering_placeholder(
        db_conn, user_id=user_id, submitted_url=_SUBMITTED,
        normalized_url=url, display_name="Acme",
    )
    return str(created["id"])


def _age(db_conn, company_id: str, *, minutes: int) -> None:
    """Backdate BOTH the blob's ``updated_at`` and ``created_at`` by ``minutes``.

    Both, because the fallback exists precisely so a row with an unreadable blob is
    still measurable — ageing only one of them would let a test pass on the wrong
    signal.
    """
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    cur = db_conn.cursor()
    cur.execute(
        """
        UPDATE companies
        SET created_at = %s,
            provider_config = jsonb_set(
                provider_config, '{discovery,updated_at}', to_jsonb(%s::text)
            )
        WHERE id = %s
        """,
        (stamp, stamp.isoformat(), company_id),
    )
    db_conn.commit()


def _queue_job(
    db_conn,
    *,
    lock: str,
    status: str,
    event_minutes_ago: int | None,
    event_type: str = "started",
    task_name: str = "discover_custom_company",
) -> int:
    """One ``procrastinate_jobs`` row with EXACTLY the event history we want to test.

    Procrastinate's own INSERT trigger writes a ``deferred`` event stamped ``now()`` for
    any row created as ``todo``, so the auto-events are cleared and replaced: what makes
    a job look alive or dead here is the AGE of its newest event, and a test that could
    not control that age would be asserting against wall-clock luck.
    """
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO procrastinate_jobs (
            queue_name, task_name, queueing_lock, args, status
        ) VALUES ('custom_discovery', %s, %s, '{}'::jsonb, %s)
        RETURNING id
        """,
        (task_name, lock, status),
    )
    job_id = int(cur.fetchone()["id"])
    cur.execute("DELETE FROM procrastinate_events WHERE job_id = %s", (job_id,))
    if event_minutes_ago is not None:
        cur.execute(
            "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, %s, %s)",
            (job_id, event_type,
             datetime.now(timezone.utc) - timedelta(minutes=event_minutes_ago)),
        )
    db_conn.commit()
    return job_id


def _state(db_conn, company_id: str) -> dict:
    db_conn.rollback()
    return dict(
        _row(
            db_conn,
            "SELECT health_state, enabled, next_run_at, provider_config "
            "FROM companies WHERE id = %s",
            (company_id,),
        )
    )


# --- the recognition rule ------------------------------------------------------


def test_an_abandoned_discovering_row_is_refused(db_conn, procrastinate_schema) -> None:
    """THE BUG. No progress for well past the grace, and no job on the broker at all —
    the SIGKILL case, where the worker died between the first progress write and the
    persist. Nothing else will ever move this row."""
    user_id = _seed_user(db_conn)
    url = "https://careers.wedged.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 15)

    assert sweep_stalled_discoveries(db_conn) == 1

    state = _state(db_conn, company_id)
    assert state["health_state"] == "refused"
    assert state["enabled"] is False
    assert state["next_run_at"] is None


def test_a_genuinely_running_discovery_is_never_reaped(
    db_conn, procrastinate_schema
) -> None:
    """THE ONE THAT MUST NOT REGRESS. The row has published no progress for an hour —
    which happens for real, because ``_progress_writer`` swallows connection failures on
    purpose so narration can never decide an outcome — but its job is ``doing`` and
    Procrastinate saw it start two minutes ago. Reaping here would refuse a board we are
    in the middle of successfully reading, and would then race the accept."""
    user_id = _seed_user(db_conn)
    url = "https://careers.still-running.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 30)
    _queue_job(
        db_conn,
        lock=ccs.discovery_queueing_lock(user_id, url),
        status="doing",
        event_minutes_ago=2,
    )

    assert sweep_stalled_discoveries(db_conn) == 0
    assert _state(db_conn, company_id)["health_state"] == "discovering"


def test_a_row_that_narrated_a_moment_ago_is_never_reaped(
    db_conn, procrastinate_schema
) -> None:
    """The first condition on its own. A run that published a step a minute ago is
    working, whatever the broker says — and this is the common case for every add, so
    getting it wrong would refuse boards in the middle of a normal setup."""
    user_id = _seed_user(db_conn)
    url = "https://careers.fresh.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=1)

    assert sweep_stalled_discoveries(db_conn) == 0
    assert _state(db_conn, company_id)["health_state"] == "discovering"


def test_a_row_just_inside_the_grace_is_never_reaped(
    db_conn, procrastinate_schema
) -> None:
    """The boundary, from the safe side. The grace is 30 minutes against a task whose
    whole budget is 240 seconds; a sweep that fired at 29 minutes would still be wrong
    about nothing, but pinning the edge stops the constant being 'tuned' downward
    without someone reading why it is where it is."""
    user_id = _seed_user(db_conn)
    url = "https://careers.boundary.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES - 2)

    assert sweep_stalled_discoveries(db_conn) == 0
    assert _state(db_conn, company_id)["health_state"] == "discovering"


def test_a_job_the_queue_never_drained_is_reaped_and_cancelled(
    db_conn, procrastinate_schema
) -> None:
    """THE OWNER'S CASE. The interactive worker was dead, so the job sat in ``todo``
    from the moment it was deferred and the row narrated nothing past step 1. The job is
    cancelled as well as the row refused: without that, a worker coming back an hour
    later would run it and ``add_discovered_company`` would promote the refused row
    straight back to 'tracking' with no user action in between."""
    user_id = _seed_user(db_conn)
    url = "https://careers.undrained.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)
    job_id = _queue_job(
        db_conn,
        lock=ccs.discovery_queueing_lock(user_id, url),
        status="todo",
        event_minutes_ago=_GRACE_MINUTES + 5,
        event_type="deferred",
    )

    assert sweep_stalled_discoveries(db_conn) == 1
    assert _state(db_conn, company_id)["health_state"] == "refused"
    assert _row(
        db_conn, "SELECT status FROM procrastinate_jobs WHERE id = %s", (job_id,)
    )["status"] == "cancelled"


def test_a_doing_job_that_died_hours_ago_does_not_protect_the_row(
    db_conn, procrastinate_schema
) -> None:
    """A SIGKILLed job stays ``doing`` FOREVER — Procrastinate does not requeue stalled
    jobs. So "there is a doing job" cannot be the liveness test; the age of its newest
    event is. Three hours past a 240-second budget is not slow, it is dead."""
    user_id = _seed_user(db_conn)
    url = "https://careers.sigkilled.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=180)
    _queue_job(
        db_conn,
        lock=ccs.discovery_queueing_lock(user_id, url),
        status="doing",
        event_minutes_ago=180,
    )

    assert sweep_stalled_discoveries(db_conn) == 1
    assert _state(db_conn, company_id)["health_state"] == "refused"


def test_an_unfinished_job_we_cannot_date_counts_as_alive(
    db_conn, procrastinate_schema
) -> None:
    """The deliberately conservative branch. With no event rows there is no way to tell
    a job that started ten seconds ago from one killed yesterday, and the two costs are
    not symmetric: leaving a wedge for another sweep is the status quo, reaping a live
    run is not."""
    user_id = _seed_user(db_conn)
    url = "https://careers.undatable.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 60)
    _queue_job(
        db_conn,
        lock=ccs.discovery_queueing_lock(user_id, url),
        status="doing",
        event_minutes_ago=None,
    )

    assert sweep_stalled_discoveries(db_conn) == 0
    assert _state(db_conn, company_id)["health_state"] == "discovering"


def test_another_boards_live_job_does_not_protect_this_one(
    db_conn, procrastinate_schema
) -> None:
    """The lock is per (user, URL). A busy discovery for a DIFFERENT board must not keep
    a wedged row alive — which is what a task-name-only probe would do, and what would
    make the sweep silently useless for anyone who adds two boards."""
    user_id = _seed_user(db_conn)
    url = "https://careers.mine.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)
    _queue_job(
        db_conn,
        lock=ccs.discovery_queueing_lock(user_id, "https://careers.theirs.example/jobs"),
        status="doing",
        event_minutes_ago=1,
    )

    assert sweep_stalled_discoveries(db_conn) == 1
    assert _state(db_conn, company_id)["health_state"] == "refused"


def test_a_settled_row_is_never_swept(db_conn, procrastinate_schema) -> None:
    """Only 'discovering' is a wedge. A tracked board that has not been harvested for a
    week is a scheduling question, not a setup one, and refusing it would take a working
    company off the user's list."""
    user_id = _seed_user(db_conn)
    url = "https://careers.tracked.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    ccs.add_discovered_company(
        db_conn, user_id=user_id, submitted_url=_SUBMITTED, normalized_url=url,
        display_name="Acme", script={"script_version": 1},
        transport="http_json", oracle_kind="none",
    )
    _age(db_conn, company_id, minutes=60 * 24 * 7)

    assert sweep_stalled_discoveries(db_conn) == 0
    assert _state(db_conn, company_id)["health_state"] == "unverified"


# --- what the user is left looking at ------------------------------------------


def test_the_reaped_row_reuses_the_refusal_vocabulary(
    db_conn, procrastinate_schema
) -> None:
    """It must stop claiming setup is in progress WITHOUT inventing a state.

    ``health_state='refused'`` is what the list already renders as "We couldn't read
    {board}'s board", and writing NO progress blob leaves the last live snapshot in
    place — so the checklist still shows how far the run got, the leftover ``active``
    rung draws as a plain ○ under a terminal outcome, and the panel says "This setup
    stopped before it could finish." above the one action that changes the answer. That
    is the discovery-timeout rendering, verbatim.
    """
    user_id = _seed_user(db_conn)
    url = "https://careers.vocabulary.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)

    assert sweep_stalled_discoveries(db_conn) == 1

    state = _state(db_conn, company_id)
    steps = {s["key"]: s for s in state["provider_config"]["discovery"]["steps"]}
    assert steps["open_page"]["status"] == "active", (
        "the last live snapshot must survive — it is the how-far-did-we-get the user "
        "reads, and the frontend already downgrades a leftover active rung on a "
        "terminal run"
    )
    # No step is marked failed, which is exactly what makes the panel render
    # "This setup stopped before it could finish." rather than blaming a step.
    assert not any(s["status"] == "failed" for s in steps.values())
    # Nothing was ever scraped and nothing can be: no script row.
    assert _row(
        db_conn, "SELECT count(*) AS n FROM company_scripts WHERE company_id = %s",
        (company_id,),
    )["n"] == 0


def test_the_audit_row_says_it_stalled_rather_than_blaming_the_board(
    db_conn, procrastinate_schema
) -> None:
    """The half that must NOT look like an ordinary refusal. A user-facing refusal reads
    "we couldn't read your board"; the append-only audit is where an operator finds out
    it was our setup that stopped, and how long it had been silent."""
    user_id = _seed_user(db_conn)
    url = "https://careers.audit.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)

    sweep_stalled_discoveries(db_conn)

    attempt = _row(
        db_conn,
        "SELECT error_detail FROM company_add_attempts "
        "WHERE company_id = %s AND outcome = 'refused'",
        (company_id,),
    )
    assert attempt is not None
    assert "setup stopped before it could finish" in attempt["error_detail"]
    assert "no progress for" in attempt["error_detail"]


def test_the_sweep_never_touches_job_listings(db_conn, procrastinate_schema) -> None:
    """NEVER-WRONG-CLOSE. Nothing this task does may close a job or accrue a miss. A
    'discovering' row has no script and has therefore never harvested, but the
    invariant is asserted against real rows rather than against that argument."""
    user_id = _seed_user(db_conn)
    url = "https://careers.no-close.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)

    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO job_listings (
            id, title, company, location, url, source_id, details, created_at,
            status, first_seen_at
        ) VALUES ('j1', 'Engineer', 'google', 'Remote', 'https://x.example/1',
                  'google_scraper', '{}'::jsonb, now(), 'OPEN', now())
        """
    )
    db_conn.commit()

    before = _row(
        db_conn,
        "SELECT count(*) AS n, count(*) FILTER (WHERE status = 'OPEN') AS open, "
        "sum(f.consecutive_misses) AS misses "
        "FROM job_listings j JOIN job_freshness f USING (source_id, id)",
    )

    sweep_stalled_discoveries(db_conn)

    after = _row(
        db_conn,
        "SELECT count(*) AS n, count(*) FILTER (WHERE status = 'OPEN') AS open, "
        "sum(f.consecutive_misses) AS misses "
        "FROM job_listings j JOIN job_freshness f USING (source_id, id)",
    )
    assert dict(before) == dict(after)


# --- where it runs -------------------------------------------------------------


def test_the_sweep_rides_the_bulk_lane_not_the_interactive_one() -> None:
    """THE PLACEMENT ARGUMENT, pinned. A dead interactive worker is one of the three
    things that wedges a row. A reconciler on that lane would be queued behind the very
    wedge it exists to clear and would only ever run when it was not needed."""
    queue = reconcile_discovering_companies.queue
    assert queue in _BULK_QUEUES, (
        f"the wedged-row sweep is on {queue!r}, which no bulk worker drains — it must "
        "keep running when the interactive lane is dead, because that is one of the "
        "causes it recovers from"
    )
    assert queue not in _INTERACTIVE_QUEUES


def test_the_sweep_is_periodic() -> None:
    """It is a sweep, not something a human remembers to run. Without the periodic
    registration this module is dead code that passes its own unit tests."""
    registered = reconcile.procrastinate_app.periodic_registry.periodic_tasks
    assert (
        "reconcile_discovering_companies",
        "reconcile_discovering_companies",
    ) in registered, "the sweep must be registered on the periodic deferrer"


@pytest.mark.asyncio
async def test_the_task_body_sweeps_and_reports(db_conn, procrastinate_schema, monkeypatch) -> None:
    """The task wrapper itself — it opens its own connection from
    ``settings.database_url`` (pointed at the test schema) and returns the count, which
    is what the log line reports."""
    import os

    from api.config import settings

    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    user_id = _seed_user(db_conn)
    url = "https://careers.task-body.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)

    assert await reconcile_discovering_companies(0) == 1
    assert _state(db_conn, company_id)["health_state"] == "refused"


# --- which timestamp is actually believed ---------------------------------------


def test_the_blobs_own_timestamp_beats_the_rows_age(db_conn, procrastinate_schema) -> None:
    """``created_at`` is only the FALLBACK. A row created two hours ago whose checklist
    published a step a minute ago is a run in progress — re-adding a board that is
    already 'discovering' resolves to the existing row and leaves ``created_at`` where
    it was, so the two timestamps legitimately disagree. Measuring the row's age instead
    of the run's would refuse a board mid-narration."""
    user_id = _seed_user(db_conn)
    url = "https://careers.old-row-fresh-run.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    fresh = datetime.now(timezone.utc) - timedelta(minutes=1)
    cur = db_conn.cursor()
    cur.execute(
        """
        UPDATE companies
        SET created_at = now() - interval '2 hours',
            provider_config = jsonb_set(
                provider_config, '{discovery,updated_at}', to_jsonb(%s::text)
            )
        WHERE id = %s
        """,
        (fresh.isoformat(), company_id),
    )
    db_conn.commit()

    assert sweep_stalled_discoveries(db_conn) == 0
    assert _state(db_conn, company_id)["health_state"] == "discovering"


def test_an_unreadable_timestamp_falls_back_instead_of_raising(
    db_conn, procrastinate_schema
) -> None:
    """The blob is a JSONB column an operator can edit and an older deployment may have
    written. A NAIVE timestamp is the sharp case — comparing it to an aware ``now``
    raises TypeError, and a reaper that dies on row three silently stops reconciling
    every row after it. It falls back to ``created_at``, which is older, so the row is
    still recovered."""
    user_id = _seed_user(db_conn)
    url = "https://careers.naive-stamp.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)
    cur = db_conn.cursor()
    cur.execute(
        """
        UPDATE companies
        SET provider_config = jsonb_set(
            provider_config, '{discovery,updated_at}', to_jsonb('2026-01-01T00:00:00'::text)
        )
        WHERE id = %s
        """,
        (company_id,),
    )
    db_conn.commit()

    assert sweep_stalled_discoveries(db_conn) == 1
    assert _state(db_conn, company_id)["health_state"] == "refused"


def test_a_discovering_row_with_no_checklist_at_all_is_still_recovered(
    db_conn, procrastinate_schema
) -> None:
    """A row written before the checklist existed — or by a path that never seeded one —
    has no blob to date. That is the row MOST likely to be wedged, so "no timestamp"
    must mean "use ``created_at``", never "skip it"."""
    user_id = _seed_user(db_conn)
    url = "https://careers.no-blob.example/jobs"
    company_id = _discovering(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE companies SET provider_config = '{}'::jsonb WHERE id = %s",
        (company_id,),
    )
    db_conn.commit()

    assert sweep_stalled_discoveries(db_conn) == 1
    assert _state(db_conn, company_id)["health_state"] == "refused"
