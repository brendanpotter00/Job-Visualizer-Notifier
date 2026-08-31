"""The ownerless-row reaper: a private company nobody owns cannot survive — E7.

``u-6hkpc6fh0z`` ("Amazon (live check)") sat in the dev database for nine days: a
``companies`` row with a recipe, six harvests and 12,437 job rows and ZERO
``user_companies`` rows. Invisible in every UI (the list JOINs ownership), undeletable
through the API (the delete route proves ownership first), and still harvesting on its
own cadence (24 h at the time; 1 h since 2026-08-29, so an orphan now burns 24× the
requests it did then), because the claim tick does not join ``user_companies`` either.

These tests pin the sweep that ends that state, and — more importantly — the three
conditions that keep it from deleting a board somebody is in the middle of adding:
no owner, older than the grace, and no live job on the broker. Getting that wrong
costs a user their board AND its whole job history, so each guard has its own test on
BOTH sides.

No broker and no worker: Procrastinate's TABLES are opened through the test connection
(the ``procrastinate_schema`` fixture) and ``procrastinate_app`` is never touched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from psycopg2 import sql

from api.services import custom_companies_service as ccs
from api.main import _BULK_QUEUES
from api.tasks.reap_ownerless_companies import (
    _FIND_ORPHANS_SQL,
    _purge,
    _ORPHAN_GRACE_SECONDS,
    _SWEEP_LIMIT,
    reap_ownerless_companies,
    sweep_ownerless_companies,
)

_GRACE_MINUTES = _ORPHAN_GRACE_SECONDS // 60
_SUBMITTED = "https://acme.example/careers"


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


def _owned_board(db_conn, user_id: str, url: str) -> str:
    """A real private company created the way the add path creates one."""
    created = ccs.add_discovering_placeholder(
        db_conn, user_id=user_id, submitted_url=_SUBMITTED,
        normalized_url=url, display_name="Acme",
    )
    return str(created["id"])


def _orphan(db_conn, user_id: str, url: str) -> str:
    """``u-6hkpc6fh0z``'s exact shape: a real board whose ownership row was deleted
    without the purge that is supposed to follow it — the test path that leaked it."""
    company_id = _owned_board(db_conn, user_id, url)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("DELETE FROM {} WHERE company_id = %s").format(
            sql.Identifier("user_companies")
        ),
        (company_id,),
    )
    db_conn.commit()
    return company_id


def _age(db_conn, company_id: str, *, minutes: int) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET created_at = %s WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (datetime.now(timezone.utc) - timedelta(minutes=minutes), company_id),
    )
    db_conn.commit()


def _count(db_conn, table: str, where: str, params: tuple) -> int:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT count(*) AS n FROM {} " + where).format(sql.Identifier(table)),
        params,
    )
    return int(cur.fetchone()["n"])


def _seed_job(db_conn, company_id: str, job_id: str, *, status: str = "OPEN") -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, now(), now(), %s)"
        ).format(sql.Identifier("job_listings")),
        (job_id, "Eng", company_id, "https://x/1", f"custom:{company_id}", status),
    )
    db_conn.commit()


def _queue_job(
    db_conn, *, lock: str, status: str, event_minutes_ago: int | None,
    task_name: str = "fetch_custom_company",
) -> int:
    """One ``procrastinate_jobs`` row with EXACTLY the event history we want.

    Procrastinate's INSERT trigger writes a ``deferred`` event stamped ``now()`` for
    any row created as ``todo``, so the auto-events are cleared and replaced: what
    makes a job look alive or dead here is the AGE of its newest event, and a test
    that could not control that age would assert against wall-clock luck.
    """
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO procrastinate_jobs (
            queue_name, task_name, queueing_lock, args, status
        ) VALUES ('custom_ats_fetch', %s, %s, '{}'::jsonb, %s)
        RETURNING id
        """,
        (task_name, lock, status),
    )
    job_id = int(cur.fetchone()["id"])
    cur.execute("DELETE FROM procrastinate_events WHERE job_id = %s", (job_id,))
    if event_minutes_ago is not None:
        cur.execute(
            "INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, %s, %s)",
            (job_id, "started",
             datetime.now(timezone.utc) - timedelta(minutes=event_minutes_ago)),
        )
    db_conn.commit()
    return job_id


# --- the recognition rule ------------------------------------------------------


def test_an_ownerless_private_company_is_purged(db_conn, procrastinate_schema) -> None:
    """THE STATE. No owner, well past the grace, nothing queued — the only thing that
    can end it is this sweep."""
    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.orphan.example/jobs")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 15)
    _seed_job(db_conn, company_id, "orphan-job-1")

    assert sweep_ownerless_companies(db_conn) == 1

    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 0
    assert _count(
        db_conn, "job_listings", "WHERE source_id = %s", (f"custom:{company_id}",)
    ) == 0
    assert _count(
        db_conn, "company_scripts", "WHERE company_id = %s", (company_id,)
    ) == 0


def test_an_owned_company_is_never_touched(db_conn, procrastinate_schema) -> None:
    """THE ONE THAT MUST NOT REGRESS. Every legitimate board is old and owned; if the
    ownership check ever stopped being the whole predicate, this sweep would delete
    the entire custom fleet."""
    user_id = _seed_user(db_conn)
    company_id = _owned_board(db_conn, user_id, "https://careers.owned.example/jobs")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 500)
    _seed_job(db_conn, company_id, "owned-job-1")

    assert sweep_ownerless_companies(db_conn) == 0

    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1
    assert _count(
        db_conn, "job_listings", "WHERE source_id = %s", (f"custom:{company_id}",)
    ) == 1


def test_a_board_being_added_right_now_is_never_purged(
    db_conn, procrastinate_schema
) -> None:
    """⚠️ THE EXPENSIVE MISTAKE. The mid-add shape — a fresh company with no ownership
    row visible — must survive the sweep on AGE ALONE, so that a future insert path
    which splits the two INSERTs into separate transactions still cannot be raced."""
    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.midadd.example/jobs")
    _seed_job(db_conn, company_id, "midadd-job-1")

    assert sweep_ownerless_companies(db_conn) == 0

    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1
    assert _count(
        db_conn, "job_listings", "WHERE source_id = %s", (f"custom:{company_id}",)
    ) == 1


def test_a_board_one_minute_inside_the_grace_is_never_purged(
    db_conn, procrastinate_schema
) -> None:
    """The boundary, from the safe side. Ageing to one minute short of the grace must
    still be untouchable — an off-by-one in the interval is exactly how a 30-minute
    floor silently becomes a zero-second one."""
    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.boundary.example/jobs")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES - 1)

    assert sweep_ownerless_companies(db_conn) == 0
    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1


def test_an_orphan_with_a_live_harvest_job_is_left_alone(
    db_conn, procrastinate_schema
) -> None:
    """Condition 3. A harvest picked up two minutes ago is running RIGHT NOW against
    this board's namespace; deleting the rows out from under it is the one outcome
    worse than leaving an orphan for another hour."""
    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.busy.example/jobs")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 60)
    _queue_job(
        db_conn, lock=ccs.harvest_queueing_lock(company_id), status="doing",
        event_minutes_ago=2,
    )

    assert sweep_ownerless_companies(db_conn) == 0
    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1


def test_an_orphan_with_a_live_discovery_job_is_left_alone(
    db_conn, procrastinate_schema
) -> None:
    """The discovery lock carries a user id an ownerless row cannot supply, so it is
    matched on the URL suffix instead. A running discovery must still protect the row
    it is about to promote."""
    user_id = _seed_user(db_conn)
    url = "https://careers.discovering.example/jobs"
    company_id = _orphan(db_conn, user_id, url)
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 60)
    _queue_job(
        db_conn, lock=ccs.discovery_queueing_lock(user_id, url), status="doing",
        event_minutes_ago=1, task_name="discover_custom_company",
    )

    assert sweep_ownerless_companies(db_conn) == 0
    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1


def test_an_unfinished_job_with_no_events_counts_as_alive(
    db_conn, procrastinate_schema
) -> None:
    """The generous half of the liveness rule, copied from ``reconcile_discovering``:
    a job we cannot DATE is treated as running. Waiting another hour is the status
    quo; reaping a board a worker is holding is not."""
    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.undated.example/jobs")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 60)
    _queue_job(
        db_conn, lock=ccs.harvest_queueing_lock(company_id), status="todo",
        event_minutes_ago=None,
    )

    assert sweep_ownerless_companies(db_conn) == 0
    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1


def test_a_long_dead_queued_job_does_not_protect_the_row(
    db_conn, procrastinate_schema
) -> None:
    """The other side of the same rule. A ``todo`` job whose newest event is hours old
    is the SIGKILL / undrained-queue corpse — exactly what the sweep came for — and it
    is cancelled by the purge rather than left to run against deleted rows."""
    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.corpse.example/jobs")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 60)
    job_id = _queue_job(
        db_conn, lock=ccs.harvest_queueing_lock(company_id), status="todo",
        event_minutes_ago=_GRACE_MINUTES + 45,
    )

    assert sweep_ownerless_companies(db_conn) == 1

    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 0
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute("SELECT status FROM procrastinate_jobs WHERE id = %s", (job_id,))
    assert cur.fetchone()["status"] == "cancelled"


def test_a_public_company_is_never_reaped(db_conn, procrastinate_schema) -> None:
    """Every curated board has zero ``user_companies`` rows BY DESIGN. Without the
    ``visibility='user'`` predicate this sweep deletes the public site."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "visibility, created_at) VALUES (%s, %s, %s, %s, TRUE, 'public', %s)"
        ).format(sql.Identifier("companies")),
        ("pubco", "Pub Co", "greenhouse", "pubco",
         datetime.now(timezone.utc) - timedelta(days=90)),
    )
    db_conn.commit()

    assert sweep_ownerless_companies(db_conn) == 0
    assert _count(db_conn, "companies", "WHERE id = %s", ("pubco",)) == 1


# --- the SCAN's own predicate, separately from the purge's re-check -------------
#
# The two guards are deliberately duplicated: the scan names candidates, and ``_purge``
# re-reads ``visibility`` and the owner count under ``FOR UPDATE`` before deleting
# anything. That defence in depth means EITHER layer alone keeps the sweep correct — so
# the tests above cannot tell which one is doing the work, and a guard could be deleted
# from the scan with no visible effect until the day the other one is refactored. These
# two pin the scan itself.


def _scanned(db_conn) -> list[str]:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(_FIND_ORPHANS_SQL, (_ORPHAN_GRACE_SECONDS, _SWEEP_LIMIT))
    rows = [str(r["id"]) for r in cur.fetchall()]
    db_conn.rollback()
    return rows


def test_the_scan_never_names_a_public_company(db_conn) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "visibility, created_at) VALUES (%s, %s, %s, %s, TRUE, 'public', %s)"
        ).format(sql.Identifier("companies")),
        ("pubscan", "Pub Scan", "greenhouse", "pubscan",
         datetime.now(timezone.utc) - timedelta(days=90)),
    )
    db_conn.commit()

    assert "pubscan" not in _scanned(db_conn)


def test_the_scan_never_names_an_owned_company(db_conn) -> None:
    user_id = _seed_user(db_conn)
    company_id = _owned_board(db_conn, user_id, "https://careers.scan-owned.example/j")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 500)

    assert company_id not in _scanned(db_conn)


def test_the_purge_refuses_a_board_that_gained_an_owner_since_the_scan(
    db_conn, procrastinate_schema
) -> None:
    """⚠️ THE RACE. The scan and the purge are separate statements, so a board can be
    re-added (or shared) in between. ``_purge`` re-reads the owner count under the
    row lock and must back out — this is unreachable through ``sweep_ownerless_companies``
    single-threaded, so it is driven directly."""
    user_id = _seed_user(db_conn)
    company_id = _owned_board(db_conn, user_id, "https://careers.raced.example/jobs")
    _seed_job(db_conn, company_id, "raced-job-1")
    row = {
        "id": company_id, "display_name": "Acme",
        "board_token": "https://careers.raced.example/jobs", "created_at": None,
    }

    assert _purge(db_conn, row) is False

    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1
    assert _count(
        db_conn, "job_listings", "WHERE source_id = %s", (f"custom:{company_id}",)
    ) == 1


def test_the_purge_refuses_a_public_company_handed_to_it_directly(
    db_conn, procrastinate_schema
) -> None:
    """The same second layer for ``visibility``. A caller (a future sweep, an
    operator script) handing this a public id must get nothing done, not a deleted
    curated board."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "visibility) VALUES (%s, %s, %s, %s, TRUE, 'public')"
        ).format(sql.Identifier("companies")),
        ("pubdirect", "Pub Direct", "greenhouse", "pubdirect"),
    )
    db_conn.commit()

    assert _purge(db_conn, {"id": "pubdirect", "display_name": "Pub Direct",
                            "board_token": "pubdirect", "created_at": None}) is False
    assert _count(db_conn, "companies", "WHERE id = %s", ("pubdirect",)) == 1


def test_the_scan_names_a_real_orphan(db_conn) -> None:
    """The positive control: without it the two tests above pass on a scan that
    returns nothing at all."""
    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.scan-orphan.example/j")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 5)

    assert company_id in _scanned(db_conn)


# --- never-wrong-close ---------------------------------------------------------


def test_the_purge_closes_nothing_and_accrues_no_misses(
    db_conn, procrastinate_schema
) -> None:
    """⚠️ A purge is a DELETE, not a close. The orphan's own rows go entirely (so
    nothing is left to carry a CLOSED status), and no row belonging to any OTHER
    source is touched — no status flip, no ``closed_on``, no miss accrued."""
    user_id = _seed_user(db_conn)
    orphan_id = _orphan(db_conn, user_id, "https://careers.purge.example/jobs")
    _age(db_conn, orphan_id, minutes=_GRACE_MINUTES + 15)
    # ``job_freshness`` rows are written by the AFTER INSERT trigger on
    # ``job_listings``, so seeding a listing seeds its freshness row too.
    _seed_job(db_conn, orphan_id, "purge-job-1")

    keeper_id = _owned_board(db_conn, user_id, "https://careers.keeper.example/jobs")
    _seed_job(db_conn, keeper_id, "keeper-job-1")

    assert sweep_ownerless_companies(db_conn) == 1

    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT status, closed_on FROM {} WHERE id = %s").format(
            sql.Identifier("job_listings")
        ),
        ("keeper-job-1",),
    )
    keeper = cur.fetchone()
    assert keeper["status"] == "OPEN"
    assert keeper["closed_on"] is None
    cur.execute(
        sql.SQL(
            "SELECT consecutive_misses FROM {} WHERE source_id = %s AND id = %s"
        ).format(sql.Identifier("job_freshness")),
        (f"custom:{keeper_id}", "keeper-job-1"),
    )
    assert cur.fetchone()["consecutive_misses"] == 0
    # Nothing was CLOSED anywhere — a purge removes history, it never decides a job
    # went away.
    assert _count(db_conn, "job_listings", "WHERE status = 'CLOSED'", ()) == 0
    # And the orphan's freshness row went with its listing, by cascade.
    assert _count(
        db_conn, "job_freshness", "WHERE source_id = %s", (f"custom:{orphan_id}",)
    ) == 0


def test_the_purge_does_not_reach_a_public_listing_sharing_a_job_id(
    db_conn, procrastinate_schema
) -> None:
    """``job_locations`` carries no source_id, so the ``NOT EXISTS`` guard is the only
    thing keeping a public listing that happens to share a job id from losing its
    location tags."""
    user_id = _seed_user(db_conn)
    orphan_id = _orphan(db_conn, user_id, "https://careers.shared.example/jobs")
    _age(db_conn, orphan_id, minutes=_GRACE_MINUTES + 15)
    _seed_job(db_conn, orphan_id, "shared-id")

    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, now(), now(), 'OPEN')"
        ).format(sql.Identifier("job_listings")),
        ("shared-id", "Eng", "pub-co", "https://x/2", "greenhouse:pubco"),
    )
    # ``remote_scope`` carries the uniqueness of ``uq_locations_canonical``
    # (NULLS NOT DISTINCT) — the db_conn fixture is module-scoped.
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (canonical_name, kind, remote_scope) "
            "VALUES (%s, 'remote', %s) RETURNING id"
        ).format(sql.Identifier("locations")),
        ("reap-shared", "reap-shared"),
    )
    location_id = int(cur.fetchone()["id"])
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (job_listing_id, normalized_location_id, is_primary) "
            "VALUES (%s, %s, TRUE)"
        ).format(sql.Identifier("job_locations")),
        ("shared-id", location_id),
    )
    db_conn.commit()

    assert sweep_ownerless_companies(db_conn) == 1

    assert _count(db_conn, "job_listings", "WHERE id = %s", ("shared-id",)) == 1
    assert _count(
        db_conn, "job_locations", "WHERE job_listing_id = %s", ("shared-id",)
    ) == 1


# --- the sweep's own shape -----------------------------------------------------


def test_the_integrity_report_and_the_sweep_agree(db_conn, procrastinate_schema) -> None:
    """The detector must name exactly what the reaper collects, or the badge stays lit
    over a board the sweep will never take (or worse, goes dark over one it did)."""
    from api.services.custom_company_integrity import get_ownerless_custom_companies

    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.agree.example/jobs")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 15)

    before = get_ownerless_custom_companies(db_conn)
    assert before["ownerlessCount"] == 1
    assert before["ownerless"][0]["companyId"] == company_id

    assert sweep_ownerless_companies(db_conn) == 1

    after = get_ownerless_custom_companies(db_conn)
    assert after["ownerlessCount"] == 0


def test_the_sweep_is_actually_registered_as_a_periodic() -> None:
    """A reaper that never ticks is worse than no reaper: the ownerless report would
    read 0 only because nothing ever looked, and ``custom_company_integrity``'s
    tripwire would be pointing at a sweep that was silently unregistered."""
    import api.tasks  # noqa: F401  — side-effect imports register every task

    from api.tasks.procrastinate_app import procrastinate_app

    registered = {
        entry.task.name: (entry.cron, entry.task.queue)
        for entry in procrastinate_app.periodic_registry.periodic_tasks.values()
    }
    assert "reap_ownerless_companies" in registered, (
        "the sweep is not on the periodic registry — api/tasks/__init__.py must import "
        "the module for its decorators to run"
    )
    cron, queue = registered["reap_ownerless_companies"]
    assert queue == "custom_ats_fetch"
    # Hourly, not more often: this is the most destructive periodic in the codebase.
    assert cron.split()[1] == "*" and cron.split()[0].isdigit()


def test_the_sweep_runs_on_the_bulk_lane() -> None:
    """A dead interactive worker is one of the things that leaves work stranded, so a
    cleanup that rode that lane would be queued behind the mess it exists to clear."""
    assert reap_ownerless_companies.queue == "custom_ats_fetch"
    assert "custom_ats_fetch" in _BULK_QUEUES


def test_the_sweep_is_a_no_op_without_the_procrastinate_schema(db_conn) -> None:
    """It must work against a database no worker has ever booted against — an absent
    broker means no live jobs, which is a ``False``, never an error."""
    user_id = _seed_user(db_conn)
    company_id = _orphan(db_conn, user_id, "https://careers.nobroker.example/jobs")
    _age(db_conn, company_id, minutes=_GRACE_MINUTES + 15)

    assert sweep_ownerless_companies(db_conn) == 1
    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 0
