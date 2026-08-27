"""Removing a custom company takes its QUEUED work with it — the resurrection bug.

``remove_owned_company`` deleted the company row and left the broker holding the
``discover_custom_company`` job that had been deferred for it. That job is keyed on
``(user, URL)`` rather than on the company id, so minutes later it ran, found no owned
row, and INSERTed a brand-new company — a board the user had deleted came back, tracked,
with jobs. Cancelling the queued job is the cause-removal half of the fix (the
``add_discovered_company`` refusal in ``test_discover_custom_company_task.py`` is the
guarantee half, and the only one that also covers a removal landing mid-run).

Procrastinate's TABLES only, through the test connection — never ``procrastinate_app``,
whose connector is built at import time from the developer's real database.
"""

from __future__ import annotations

import os
import uuid

from psycopg2 import sql

from api.services import custom_companies_service as ccs

_SUBMITTED = "https://acme.example/careers"


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


def _job(db_conn, *, lock: str, task_name: str, status: str = "todo") -> int:
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO procrastinate_jobs (queue_name, task_name, queueing_lock, args, status)
        VALUES ('custom_discovery', %s, %s, '{}'::jsonb, %s)
        RETURNING id
        """,
        (task_name, lock, status),
    )
    job_id = int(cur.fetchone()["id"])
    db_conn.commit()
    return job_id


def _status(db_conn, job_id: int) -> str:
    db_conn.rollback()
    return str(_row(
        db_conn, "SELECT status FROM procrastinate_jobs WHERE id = %s", (job_id,)
    )["status"])


def test_removing_a_board_mid_setup_cancels_its_queued_discovery(
    db_conn, procrastinate_schema
) -> None:
    """THE FIX. Without it the job survives its company and re-creates it four minutes
    later — and, on the way, spends a headless Chromium session and a Claude call on a
    board nobody owns."""
    user_id = _seed_user(db_conn)
    url = "https://careers.cancel-me.example/jobs"
    company_id = str(
        ccs.add_discovering_placeholder(
            db_conn, user_id=user_id, submitted_url=_SUBMITTED,
            normalized_url=url, display_name="Acme",
        )["id"]
    )
    job_id = _job(
        db_conn,
        lock=ccs.discovery_queueing_lock(user_id, url),
        task_name="discover_custom_company",
    )

    assert ccs.remove_owned_company(db_conn, user_id, company_id) == "purged"

    assert _status(db_conn, job_id) == "cancelled"


def test_removing_a_board_cancels_its_queued_harvest_too(
    db_conn, procrastinate_schema
) -> None:
    """Same reasoning one step later in the lifecycle: a queued ``fetch_custom_company``
    for a company that no longer exists is a guaranteed no-op that still costs a worker
    slot, and it is keyed by the id we are about to delete."""
    user_id = _seed_user(db_conn)
    url = "https://careers.cancel-harvest.example/jobs"
    company_id = str(
        ccs.add_custom_company(
            db_conn, user_id=user_id, ats="greenhouse", board_token="acme",
            provider_config={}, display_name="Acme", submitted_url=_SUBMITTED,
            normalized_url=url,
        )["id"]
    )
    job_id = _job(
        db_conn,
        lock=ccs.harvest_queueing_lock(company_id),
        task_name="fetch_custom_company",
    )

    assert ccs.remove_owned_company(db_conn, user_id, company_id) == "purged"

    assert _status(db_conn, job_id) == "cancelled"


def test_a_discovery_already_running_is_left_alone(
    db_conn, procrastinate_schema
) -> None:
    """A ``doing`` job cannot be un-run, and pretending otherwise would corrupt
    Procrastinate's state machine under a worker that is mid-task. That case is covered
    by the OTHER half of the fix — ``add_discovered_company`` refuses to create a row
    whose placeholder is gone — so the right thing here is to leave the job alone."""
    user_id = _seed_user(db_conn)
    url = "https://careers.in-flight.example/jobs"
    company_id = str(
        ccs.add_discovering_placeholder(
            db_conn, user_id=user_id, submitted_url=_SUBMITTED,
            normalized_url=url, display_name="Acme",
        )["id"]
    )
    job_id = _job(
        db_conn,
        lock=ccs.discovery_queueing_lock(user_id, url),
        task_name="discover_custom_company",
        status="doing",
    )

    assert ccs.remove_owned_company(db_conn, user_id, company_id) == "purged"

    assert _status(db_conn, job_id) == "doing"


def test_another_users_queued_discovery_of_the_same_url_survives(
    db_conn, procrastinate_schema
) -> None:
    """The lock is per (user, URL) precisely so two people adding the same non-ATS board
    each get their own run. Cancelling on a URL alone would let one user's Remove kill
    another user's setup."""
    mine = _seed_user(db_conn)
    theirs = _seed_user(db_conn)
    url = "https://careers.shared-url.example/jobs"
    company_id = str(
        ccs.add_discovering_placeholder(
            db_conn, user_id=mine, submitted_url=_SUBMITTED,
            normalized_url=url, display_name="Acme",
        )["id"]
    )
    ccs.add_discovering_placeholder(
        db_conn, user_id=theirs, submitted_url=_SUBMITTED,
        normalized_url=url, display_name="Acme",
    )
    their_job = _job(
        db_conn,
        lock=ccs.discovery_queueing_lock(theirs, url),
        task_name="discover_custom_company",
    )

    assert ccs.remove_owned_company(db_conn, mine, company_id) == "purged"

    assert _status(db_conn, their_job) == "todo"


def test_removal_still_works_with_no_procrastinate_schema_at_all(db_conn) -> None:
    """``procrastinate_jobs`` is absent until a worker has booted against the database.
    The cancel runs INSIDE the removal transaction, so an unguarded statement there
    would abort it — turning "Remove" into a 500 in exactly the environment where a user
    is most likely to be trying things out.

    "Absent" is staged CAREFULLY, and the care is the point. A bare
    ``DROP TABLE procrastinate_jobs`` here resolves through the search_path and takes
    out ``public.procrastinate_jobs`` — which ``test_procrastinate_bootstrap`` leaves
    behind (its ``PGOPTIONS`` pin does not reach the connector's pool) and
    ``test_worker_lanes`` then reads, two modules away. The first version of this test
    did exactly that and turned five ``test_worker_lanes`` tests red in the full suite
    while passing on its own. So the drop is schema-qualified and ``public`` is taken
    off the search path instead of being touched.
    """
    schema = os.environ["PYTEST_SCHEMA"]
    cur = db_conn.cursor()
    # Both halves are needed to make the tables genuinely unresolvable: drop this
    # schema's copy BY NAME (never unqualified), and take ``public`` off the search
    # path so the bootstrap module's leftover copy there is not found either.
    cur.execute(
        f'DROP TABLE IF EXISTS "{schema}".procrastinate_events, '
        f'"{schema}".procrastinate_jobs CASCADE'
    )
    cur.execute(f'SET search_path TO "{schema}"')
    db_conn.commit()
    try:
        user_id = _seed_user(db_conn)
        url = "https://careers.no-broker.example/jobs"
        company_id = str(
            ccs.add_discovering_placeholder(
                db_conn, user_id=user_id, submitted_url=_SUBMITTED,
                normalized_url=url, display_name="Acme",
            )["id"]
        )

        assert ccs.remove_owned_company(db_conn, user_id, company_id) == "purged"
        assert _row(
            db_conn, "SELECT count(*) AS n FROM companies WHERE id = %s", (company_id,)
        )["n"] == 0
    finally:
        cur = db_conn.cursor()
        cur.execute(f'SET search_path TO "{schema}", public')
        db_conn.commit()
