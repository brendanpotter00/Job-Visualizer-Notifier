"""Data access for custom (user-added, private) companies — E7 Phase 1.

Shared by the ``/api/users/companies`` endpoints and the ``custom_ats_fetch``
worker. Every custom company is ``visibility='user'`` and owned by one or more
users via ``user_companies``; its jobs live under the per-company
``source_id = custom:<id>`` namespace so the database enforces cross-company
isolation on every destructive lifecycle write.

None of these helpers touch the six public ATS fan-outs or the public read
paths — those are guarded separately (see the visibility-leak fixes).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import psycopg2
from psycopg2.extensions import connection as Connection

from scripts.shared.constants import custom, new_custom_company_id

# A custom company is scraped daily; next_run_at is seeded to now() so the first
# harvest happens on the next claim tick rather than 24h later.
DEFAULT_CADENCE_HOURS = 24
# Bounded retry on the astronomically-unlikely companies.id PK collision.
_ID_GENERATION_ATTEMPTS = 5


def canonical_source_key(ats: str, board_token: str) -> str:
    """The idempotency key for ``UNIQUE(user_id, canonical_source_key)``."""
    return f"{ats}:{board_token}"


def find_owned_company_by_source_key(
    conn: Connection, user_id: str, source_key: str
) -> Optional[dict[str, Any]]:
    """The caller's company for ``source_key`` (idempotent re-add), or None."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.id, c.display_name, c.ats, c.board_token, c.health_state,
               c.last_success_at, c.tracking_started_at, c.created_at
        FROM user_companies uc
        JOIN companies c ON c.id = uc.company_id
        WHERE uc.user_id = %s AND uc.canonical_source_key = %s
        """,
        (user_id, source_key),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def record_add_attempt(
    conn: Connection,
    *,
    user_id: str,
    submitted_url: str,
    normalized_url: Optional[str],
    outcome: str,
    error_detail: Optional[str] = None,
    resolved_ats: Optional[str] = None,
    board_token: Optional[str] = None,
    company_id: Optional[str] = None,
) -> None:
    """Append one ``company_add_attempts`` audit row and commit.

    Committed on its own so a refused/unsupported attempt is durably audited
    even though nothing else is written on that path.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO company_add_attempts (
                user_id, submitted_url, normalized_url, outcome, error_detail,
                resolved_ats, board_token, company_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id, submitted_url, normalized_url, outcome, error_detail,
                resolved_ats, board_token, company_id,
            ),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


def add_custom_company(
    conn: Connection,
    *,
    user_id: str,
    ats: str,
    board_token: str,
    provider_config: dict[str, Any],
    display_name: str,
    submitted_url: str,
    normalized_url: Optional[str],
) -> dict[str, Any]:
    """Create the four rows for a new custom company in ONE transaction.

    ``companies`` (visibility='user', health_state='unverified', cadence_hours,
    next_run_at=now(), enabled=true) + ``user_companies`` ownership +
    ``company_scripts`` (the one-primitive ats_client script, oracle_kind='none')
    + a ``company_add_attempts`` audit row (outcome='added'). All-or-nothing.

    Idempotency is the CALLER's responsibility (check
    ``find_owned_company_by_source_key`` first); as a race backstop this catches
    the ``UNIQUE(user_id, canonical_source_key)`` violation and returns the
    existing row instead of erroring.
    """
    source_key = canonical_source_key(ats, board_token)
    script = {"kind": "ats_client", "provider": ats, "token": board_token}
    # Store the real oracle for the resolved ATS (DECISION D2). This is
    # book-keeping only — the gate derives the effective oracle from the provider
    # at gate time, so a row left at 'none' (a Phase-1 add) still graduates. New
    # adds record it so a reader can see it without re-deriving.
    from .harvest_verification import effective_oracle_kind

    oracle_kind = effective_oracle_kind(ats)

    last_error: Optional[psycopg2.Error] = None
    for _ in range(_ID_GENERATION_ATTEMPTS):
        company_id = new_custom_company_id()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO companies (
                    id, display_name, ats, board_token, enabled, provider_config,
                    visibility, cadence_hours, next_run_at, health_state,
                    consecutive_failures
                ) VALUES (
                    %s, %s, %s, %s, TRUE, %s::jsonb,
                    'user', %s, now(), 'unverified', 0
                )
                """,
                (
                    company_id, display_name, ats, board_token,
                    json.dumps(provider_config), DEFAULT_CADENCE_HOURS,
                ),
            )
            cursor.execute(
                """
                INSERT INTO user_companies (user_id, company_id, canonical_source_key)
                VALUES (%s, %s, %s)
                """,
                (user_id, company_id, source_key),
            )
            cursor.execute(
                """
                INSERT INTO company_scripts (
                    company_id, script, script_version, transport, oracle_kind
                ) VALUES (%s, %s::jsonb, 1, 'ats_client', %s)
                """,
                (company_id, json.dumps(script), oracle_kind),
            )
            cursor.execute(
                """
                INSERT INTO company_add_attempts (
                    user_id, submitted_url, normalized_url, outcome,
                    resolved_ats, board_token, company_id
                ) VALUES (%s, %s, %s, 'added', %s, %s, %s)
                """,
                (
                    user_id, submitted_url, normalized_url, ats, board_token,
                    company_id,
                ),
            )
            conn.commit()
            return {
                "id": company_id,
                "display_name": display_name,
                "ats": ats,
                "board_token": board_token,
                "health_state": "unverified",
                "last_success_at": None,
                "tracking_started_at": None,
                "source_id": custom(company_id),
                "open_job_count": 0,
            }
        except psycopg2.errors.UniqueViolation as exc:
            conn.rollback()
            # Two shapes: (a) a companies.id PK collision — regenerate and retry;
            # (b) the (user_id, canonical_source_key) race backstop — the company
            # already exists for this user, so resolve to it idempotently.
            existing = find_owned_company_by_source_key(conn, user_id, source_key)
            if existing is not None:
                existing["source_id"] = custom(existing["id"])
                existing["open_job_count"] = count_open_jobs(conn, existing["id"])
                return existing
            last_error = exc
            continue
        except psycopg2.Error as exc:
            conn.rollback()
            last_error = exc
            raise

    raise RuntimeError(
        "failed to generate a unique custom company id after "
        f"{_ID_GENERATION_ATTEMPTS} attempts"
    ) from last_error


def count_open_jobs(conn: Connection, company_id: str) -> int:
    """OPEN job_listings for a custom company (scoped by its own source_id)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT count(*) AS n FROM job_listings "
        "WHERE company = %s AND source_id = %s AND status = 'OPEN'",
        (company_id, custom(company_id)),
    )
    row = cursor.fetchone()
    return int(row["n"]) if row else 0


def list_owned_companies(conn: Connection, user_id: str) -> list[dict[str, Any]]:
    """The caller's custom companies + health, open-job count, last-success.

    ``open_job_count`` is computed inline against the per-company source_id
    (``'custom:'||c.id``) so a single round-trip returns everything the list
    view needs.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            c.id, c.display_name, c.ats, c.board_token, c.health_state,
            c.last_success_at, c.tracking_started_at, c.enabled, c.created_at,
            (
                SELECT count(*) FROM job_listings j
                WHERE j.company = c.id
                  AND j.source_id = 'custom:' || c.id
                  AND j.status = 'OPEN'
            ) AS open_job_count
        FROM user_companies uc
        JOIN companies c ON c.id = uc.company_id
        WHERE uc.user_id = %s
        ORDER BY c.created_at DESC, c.id
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["source_id"] = custom(d["id"])
        out.append(d)
    return out


def get_company_if_owner(
    conn: Connection, user_id: str, company_id: str
) -> Optional[dict[str, Any]]:
    """The company row IF ``user_id`` owns ``company_id``, else None (→ 403)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.id, c.display_name, c.ats, c.board_token, c.health_state,
               c.last_success_at, c.tracking_started_at, c.enabled, c.created_at
        FROM user_companies uc
        JOIN companies c ON c.id = uc.company_id
        WHERE uc.user_id = %s AND c.id = %s
        """,
        (user_id, company_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def delete_ownership(conn: Connection, user_id: str, company_id: str) -> str:
    """Remove the caller's ownership; disable the company if it was the last owner.

    Returns:
        ``'not_owner'`` if the caller did not own it (→ router 404),
        ``'disabled'`` if this removed the last owner and the company was set
        ``enabled=false`` (rows are kept, never deleted),
        ``'removed'`` if other owners remain.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM user_companies WHERE user_id = %s AND company_id = %s",
            (user_id, company_id),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return "not_owner"
        cursor.execute(
            "SELECT count(*) AS n FROM user_companies WHERE company_id = %s",
            (company_id,),
        )
        remaining = cursor.fetchone()
        if remaining and int(remaining["n"]) == 0:
            # Last owner gone: disable (never DELETE — keep the jobs + audit).
            # ``AND visibility = 'user'`` is defense-in-depth: this path should
            # only ever reach a private company, but the guard makes it
            # impossible to disable a curated public company even if a future
            # caller passed a public id (which would take a public board's jobs
            # off the site).
            cursor.execute(
                "UPDATE companies SET enabled = FALSE "
                "WHERE id = %s AND visibility = 'user'",
                (company_id,),
            )
            conn.commit()
            return "disabled"
        conn.commit()
        return "removed"
    except psycopg2.Error:
        conn.rollback()
        raise


# --- Worker-facing --------------------------------------------------------


def load_custom_company_for_run(
    conn: Connection, company_id: str
) -> Optional[dict[str, Any]]:
    """The company + its stored script, everything the leaf task needs to run.

    Returns None if the company or its script row is missing (the leaf task
    treats that as nothing to do). ``provider_config`` and ``script`` come back
    as dicts (psycopg2 deserializes JSONB).
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.ats, c.board_token, c.provider_config, c.enabled, c.visibility,
               c.cadence_hours, c.tracking_started_at,
               s.script, s.oracle_kind, s.transport, s.script_version
        FROM companies c
        JOIN company_scripts s ON s.company_id = c.id
        WHERE c.id = %s
        """,
        (company_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def mark_last_success(conn: Connection, company_id: str) -> None:
    """Stamp ``companies.last_success_at = now()`` after a successful harvest.

    Called on every SUCCESSFUL (non-FAILED) custom-company run — i.e. wherever
    ``scrape_runs.success = true`` is written. In Phase 1 every run is UNVERIFIED,
    so this is the ONLY thing that ever moves ``last_success_at`` off NULL; gating
    it on VERIFIED would leave the "last checked" UI reading "Not yet checked"
    forever for every custom company.

    Deliberately does NOT touch ``health_state`` (stays 'unverified' in Phase 1 —
    no oracle exists) or ``tracking_started_at`` (§2: set only on the first
    VERIFIED harvest, so it stays NULL until Phase 2). Commits on its own,
    mirroring ``record_scrape_run`` / ``record_company_harvest``.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE companies SET last_success_at = now() WHERE id = %s",
            (company_id,),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


def mark_verified(conn: Connection, company_id: str, *, set_tracking: bool) -> None:
    """Flip a custom company to ``health_state='healthy'`` after a VERIFIED run.

    Called on every VERIFIED harvest (the run PROVED it saw the whole board, so
    the company is healthy regardless of whether it closed anything this run).
    On the FIRST VERIFIED run (``set_tracking=True``) it also stamps
    ``tracking_started_at`` — but only if still NULL, via ``COALESCE``, so a
    retry or a later run can never move the tracking origin. Commits on its own,
    mirroring ``mark_last_success`` / ``record_company_harvest``.
    """
    cursor = conn.cursor()
    try:
        if set_tracking:
            cursor.execute(
                "UPDATE companies SET health_state = 'healthy', "
                "tracking_started_at = COALESCE(tracking_started_at, now()) "
                "WHERE id = %s",
                (company_id,),
            )
        else:
            cursor.execute(
                "UPDATE companies SET health_state = 'healthy' WHERE id = %s",
                (company_id,),
            )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


def consecutive_verified(conn: Connection, company_id: str, *, limit: int = 10) -> int:
    """Count the company's trailing run of VERIFIED harvests (E7 §Task D.3).

    Reads ``company_harvests`` most-recent-first and counts the leading run of
    ``verdict='VERIFIED'`` rows until the first non-VERIFIED (or NULL) row stops
    the count — mirroring ``count_consecutive_partial_skips``. Gates
    ``self_consistent`` closes: a company may only close once THIS run makes its
    consecutive-VERIFIED streak reach 3.

    NOTE: the current run's ``company_harvests`` row is written in the leaf task's
    ``finally`` — AFTER this is read — so the returned count is the PRIOR streak,
    excluding the run in flight.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT verdict FROM company_harvests
            WHERE company_id = %s
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (company_id, max(1, limit)),
        )
        rows = cursor.fetchall()
    finally:
        # SELECT-only — never leave the caller's connection idle-in-transaction.
        conn.rollback()

    streak = 0
    for row in rows:
        if row["verdict"] != "VERIFIED":
            break
        streak += 1
    return streak


def script_changed_since_last(conn: Connection, company_id: str) -> bool:
    """True iff the stored script changed since the last VERIFIED harvest (D.2).

    ``company_scripts.updated_at > max(completed_at of prior VERIFIED
    company_harvests)`` — uses the existing ``updated_at`` (no new column). "The
    first run after any script/baseline change closes nothing" is enforced by
    this returning True on that first run.

    In Phase 2 scripts never change (repair is Phase 5), so ``updated_at`` is the
    creation time, which predates every harvest → this is always False and the
    branch is a forward seam. Returns False when there are no prior VERIFIED
    harvests (that day-one case is covered by the first-VERIFIED-run branch,
    which has precedence).
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT s.updated_at AS script_updated_at,
                   (
                       SELECT max(h.completed_at)
                       FROM company_harvests h
                       WHERE h.company_id = %s AND h.verdict = 'VERIFIED'
                   ) AS last_verified_at
            FROM company_scripts s
            WHERE s.company_id = %s
            """,
            (company_id, company_id),
        )
        row = cursor.fetchone()
    finally:
        conn.rollback()

    if row is None or row["last_verified_at"] is None:
        return False
    updated_at = row["script_updated_at"]
    if updated_at is None:
        return False
    return bool(updated_at > row["last_verified_at"])


def fleet_breaker_tripped(
    conn: Connection,
    *,
    window_hours: float = 24.0,
    min_sample: int = 5,
    fail_fraction: float = 0.20,
) -> bool:
    """Fleet circuit breaker (§4.3): did > 20% of the night's custom runs FAIL?

    If so, NO custom company closes that night — the check that would have made
    the 2026-03-29 mass closure a non-event. Computed as a night-scoped aggregate
    over ``scrape_runs`` (there is no barrier where "the night's companies" all
    finish, so each leaf task reads this right before its close step):

        tripped iff total >= min_sample AND failed / total > fail_fraction

    Global across ALL custom companies on purpose — a systemic failure (a shared
    client bug now, a Browserbase outage in Phase 4) is exactly the class this
    generalizes. It never touches another user's DATA (source_id isolation
    holds); it only SUPPRESSES this company's close.

    ``scrape_runs.started_at`` is ISO-8601 Text, so the cutoff is a Python-
    computed ISO string compared lexicographically (correct for zero-padded UTC).

    KNOWN LIMITATIONS (review Finding 2 — deferred to the fleet-hardening pass in
    STACK-ORCHESTRATION.md): this is a point-in-time aggregate over a full 24h
    window, read independently by each leaf task, so it is intentionally
    approximate:
      (a) a company that finishes EARLY may read a breaker that does not yet
          reflect not-yet-committed FAILED siblings from the same night, and
      (b) with same-time daily clustering the PRIOR night's successes (still
          inside the 24h window) dilute tonight's failure fraction.
    Both err toward NOT tripping (a close may slip through on a genuinely bad
    night). Safe-ish because every OTHER close gate still applies; the breaker is
    a fleet-wide backstop, not the only guard. TODO: scope to the current claim
    batch / a shorter night window and count only ``completed_at``-set runs.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=window_hours)
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE success IS FALSE) AS failed
            FROM scrape_runs
            WHERE source_id LIKE 'custom:%%' AND started_at >= %s
            """,
            (cutoff,),
        )
        row = cursor.fetchone()
    finally:
        conn.rollback()

    if row is None:
        return False
    total = int(row["total"] or 0)
    failed = int(row["failed"] or 0)
    if total < min_sample:
        return False
    return (failed / total) > fail_fraction


def record_company_harvest(
    conn: Connection,
    *,
    company_id: str,
    run_id: str,
    started_at: str,
    completed_at: str,
    verdict: str,
    verdict_reason: Optional[str],
    records_harvested: int,
    oracle_kind: str,
    id_dedup_dropped: int = 0,
    declared_total: Optional[int] = None,
    oracle_total: Optional[int] = None,
    cap_hit: bool = False,
    page_advance_ok: Optional[bool] = None,
    tolerance_used: float = 0.0,
) -> None:
    """Append one ``company_harvests`` evidence row and commit (autonomous).

    Committed on its own — mirroring ``record_scrape_run`` — so the per-run
    evidence lands even if written from the leaf task's ``finally`` after an
    error.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO company_harvests (
                company_id, run_id, started_at, completed_at, verdict,
                verdict_reason, records_harvested, declared_total, oracle_total,
                oracle_kind, cap_hit, page_advance_ok, id_dedup_dropped,
                tolerance_used
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                company_id, run_id, started_at, completed_at, verdict,
                verdict_reason, records_harvested, declared_total, oracle_total,
                oracle_kind, cap_hit, page_advance_ok, id_dedup_dropped,
                tolerance_used,
            ),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
