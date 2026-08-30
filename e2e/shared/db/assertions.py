"""Shared DB predicates for add-companies API cases (PLAN.md §1).

Company-shape aware (companies / user_companies / company_add_attempts /
job_listings / procrastinate_jobs) since that shape is what this section
tests — kept here instead of duplicated per test file, per PLAN.md's
"anything a second section could reuse belongs in shared/" convention.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx
import psycopg2
import psycopg2.extras

EXPECTED_DB = "jobscraper_e2e"


def connect(dsn: str) -> Any:
    """A RealDictCursor connection to jobscraper_e2e — refuses anything else.

    Same hard guard as e2e_app.py (PLAN.md §2): a helper that *can* connect to
    the owner's database once will connect to it at 2am.
    """
    db_name = dsn.rsplit("/", 1)[-1].split("?", 1)[0]
    if db_name != EXPECTED_DB:
        raise RuntimeError(
            f"assertions.connect refuses dsn resolving to database {db_name!r}, "
            f"not {EXPECTED_DB!r}"
        )
    return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)


def visibility_count(conn: Any, visibility: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM companies WHERE visibility = %s", (visibility,)
        )
        return int(cur.fetchone()["n"])


def add_attempts_count(conn: Any, *, user_id: str | None = None) -> int:
    with conn.cursor() as cur:
        if user_id:
            cur.execute(
                "SELECT count(*) AS n FROM company_add_attempts WHERE user_id = %s",
                (user_id,),
            )
        else:
            cur.execute("SELECT count(*) AS n FROM company_add_attempts")
        return int(cur.fetchone()["n"])


def clear_add_attempts(conn: Any, *, user_id: str) -> int:
    """Wipe one user's ``company_add_attempts`` rows. TEST FIXTURE ONLY.

    The monthly add cap counts these rows, and nothing in the product can delete
    them — a company purge deliberately leaves the audit behind, which is exactly what
    makes "deleting a company doesn't refund a slot" real. So a suite that re-runs
    against a persistent ``jobscraper_e2e`` accumulates spend forever, and the only way
    to place the test user at a known count is to reach past the API and truncate here.

    Refuses any database but ``jobscraper_e2e`` by construction: the connection came
    from :func:`connect`, which asserts the database name.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM company_add_attempts WHERE user_id = %s", (user_id,))
        deleted = cur.rowcount
    conn.commit()
    return int(deleted)


def seed_add_attempts(conn: Any, *, user_id: str, n: int) -> None:
    """Place a user at a known monthly spend. TEST FIXTURE ONLY, and the mirror of
    :func:`clear_add_attempts` above.

    The cap counts ``company_add_attempts`` rows, and the endpoint only writes one for
    a URL it actually acted on — a refusal we could not even read (a bad scheme, a dead
    domain) deliberately writes nothing and charges nothing, which is exactly what
    AC-14's first case asserts. So there is no longer a CHEAP way to spend a slot
    through the API: every real one costs a live board, a harvest, or an LLM call. The
    audit is append-only by design, so the only way to sit a user at the boundary
    without spending real money is to write the rows.

    ``resolved_ats`` is a real ATS name on purpose: ``'discovered'`` rows are the ones
    the quota predicate EXCLUDES (they are the worker's terminal half of a submission
    already billed), so seeding those would count for nothing.
    """
    with conn.cursor() as cur:
        for i in range(n):
            cur.execute(
                "INSERT INTO company_add_attempts "
                "(user_id, submitted_url, outcome, resolved_ats) "
                "VALUES (%s, %s, 'added', 'greenhouse')",
                (user_id, f"https://seeded-{i}.e2e.test/careers"),
            )
    conn.commit()


def latest_add_attempt(conn: Any, *, user_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM company_add_attempts WHERE user_id = %s "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def procrastinate_job_count(
    conn: Any,
    *,
    queue_name: str | None = None,
    task_name: str | None = None,
    queueing_lock: str | None = None,
    status: str | None = None,
) -> int:
    clauses: list[str] = []
    params: list[str] = []
    if queue_name:
        clauses.append("queue_name = %s")
        params.append(queue_name)
    if task_name:
        clauses.append("task_name = %s")
        params.append(task_name)
    if queueing_lock:
        clauses.append("queueing_lock = %s")
        params.append(queueing_lock)
    if status:
        clauses.append("status = %s")
        params.append(status)
    where = " AND ".join(clauses) or "TRUE"
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM procrastinate_jobs WHERE {where}", params)  # noqa: S608
        return int(cur.fetchone()["n"])


def job_listing_count(conn: Any, *, source_id: str, status: str | None = None) -> int:
    with conn.cursor() as cur:
        if status:
            cur.execute(
                "SELECT count(*) AS n FROM job_listings WHERE source_id = %s AND status = %s",
                (source_id, status),
            )
        else:
            cur.execute(
                "SELECT count(*) AS n FROM job_listings WHERE source_id = %s",
                (source_id,),
            )
        return int(cur.fetchone()["n"])


def open_title_snapshot(conn: Any, *, company: str, source_id: str) -> tuple[int, str]:
    """(distinct OPEN title count, sha256 of the sorted set) — for a
    before/after "job_listings did not change" check (AC-06 assertion #3)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT title FROM job_listings "
            "WHERE company = %s AND source_id = %s AND status = 'OPEN' "
            "ORDER BY title",
            (company, source_id),
        )
        titles = [row["title"] for row in cur.fetchall()]
    digest = hashlib.sha256("\n".join(titles).encode("utf-8")).hexdigest()
    return len(titles), digest


def company_row(conn: Any, company_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM companies WHERE id = %s", (company_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def user_companies_row(conn: Any, user_id: str, company_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM user_companies WHERE user_id = %s AND company_id = %s",
            (user_id, company_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def company_script_row(conn: Any, company_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM company_scripts WHERE company_id = %s", (company_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def latest_harvest(conn: Any, company_id: str) -> dict[str, Any] | None:
    """The newest ``company_harvests`` row for a company, or None.

    This is the audit row the verification gate writes on every executed run:
    ``verdict``, ``verdict_reason``, ``oracle_kind``, ``records_harvested``,
    ``declared_total``, ``cap_hit``, ``page_advance_ok``. A case that wants to
    assert WHY a board is (or is not) verified reads this rather than the
    ``health_state`` string it produces, which is a projection of it.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM company_harvests WHERE company_id = %s "
            "ORDER BY started_at DESC LIMIT 1",
            (company_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def latest_scrape_run(conn: Any, company_id: str) -> dict[str, Any] | None:
    """The newest ``scrape_runs`` row for a custom company's source.

    Carries ``guard_reason`` (WHY the destructive tail was skipped) and
    ``closed_jobs``, which together are the only honest way to assert that a
    run did or did not reach the close path.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM scrape_runs WHERE source_id = %s "
            "ORDER BY started_at DESC LIMIT 1",
            (f"custom:{company_id}",),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def user_id_for_email(conn: Any, email: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        return str(row["id"]) if row else None


def ownerless_count(base_url: str) -> int:
    """`ownerlessCount` off /api/jobs-qa/custom-company-integrity.

    Baseline caution (PLAN.md §5, AC-07): this is NOT guaranteed to be 0 —
    assert the DELTA around an operation, never the absolute value directly,
    unless you've just confirmed the pre-run baseline yourself.
    """
    resp = httpx.get(f"{base_url}/api/jobs-qa/custom-company-integrity", timeout=10.0)
    resp.raise_for_status()
    return int(resp.json()["ownerlessCount"])
