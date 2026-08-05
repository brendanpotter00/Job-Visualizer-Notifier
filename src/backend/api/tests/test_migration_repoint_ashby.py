"""Integration test: the Ashby-repoint / Unity-retirement data migration
(``a7c31d9e0b46``) applies, fully reverses, and is idempotent.

Mirrors ``test_migration_companies.py`` — a throwaway database plus the real
``alembic upgrade`` / ``alembic downgrade`` commands, so the migration's own
SQL is executed rather than short-circuited by ``stamp_alembic_head``.

One deliberate difference from ``test_migration_companies.py``: the schema is
materialized with ``Base.metadata.create_all`` and Alembic is then STAMPED at
``5ee285a3c724`` (this migration's ``down_revision``) instead of upgrading the
chain from base. Replaying the chain from base does not work on a fresh
database — ``050b9adc98e1`` (`add features and upvotes`) references a ``users``
table that was created by the pre-Alembic runner, so the very second revision
fails with ``relation "users" does not exist``. That is a pre-existing property
of the chain, unrelated to this migration, and it is exactly why
``conftest.py::db_conn`` and ``test_alembic_parity.py`` both use
create_all + stamp. ``a7c31d9e0b46`` makes no schema change, so create_all's
schema is an accurate stand-in for the schema at ``5ee285a3c724``.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_SCRIPT_LOCATION = _REPO_ROOT / "src" / "backend" / "alembic"
_SRC_BACKEND = _REPO_ROOT / "src" / "backend"

if str(_SRC_BACKEND) not in sys.path:
    sys.path.insert(0, str(_SRC_BACKEND))

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper",
)

BASE_REV = "5ee285a3c724"
REPOINT_REV = "a7c31d9e0b46"

# The sentinel the migration stamps onto every row it closes.
SENTINEL_CLOSED_ON = "2026-07-30T00:00:00+00:00"
# A pre-existing legitimate close, well before the sentinel. Must survive the
# upgrade unchanged AND must NOT be re-opened by the downgrade.
ORIGINAL_CLOSED_ON = "2026-07-06T19:01:18.671000+00:00"


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _companies(conn) -> dict[str, dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, ats, board_token, enabled, provider_config, created_at"
        " FROM companies ORDER BY id"
    )
    return {row["id"]: dict(row) for row in cur.fetchall()}


def _jobs(conn) -> dict[tuple[str, str], dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT source_id, id, company, status, closed_on FROM job_listings"
    )
    return {(row["source_id"], row["id"]): dict(row) for row in cur.fetchall()}


def _insert_company(conn, company_id: str, *, ats: str, board_token: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled)"
        " VALUES (%s, %s, %s, %s, TRUE)",
        (company_id, company_id.title(), ats, board_token),
    )
    conn.commit()


def _insert_job(
    conn,
    *,
    job_id: str,
    company: str,
    source_id: str,
    status: str,
    closed_on: str | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO job_listings"
        " (id, title, company, url, source_id, status, closed_on,"
        "  created_at, first_seen_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s,"
        "  '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
        (job_id, f"Engineer {job_id}", company,
         f"https://example.test/{job_id}", source_id, status, closed_on),
    )
    conn.commit()


def _seed(conn) -> None:
    """Seed the four affected companies plus decoys that must not move."""
    _insert_company(conn, "appliedintuition", ats="greenhouse", board_token="appliedintuition")
    _insert_company(conn, "fal", ats="greenhouse", board_token="fal")
    _insert_company(conn, "merge", ats="greenhouse", board_token="merge")
    _insert_company(conn, "unity3d", ats="greenhouse", board_token="unity3d")
    # Untouched-company decoy.
    _insert_company(conn, "stripe", ats="greenhouse", board_token="stripe")

    # Stale Greenhouse-era rows for the three re-pointed companies.
    _insert_job(conn, job_id="ai-open-1", company="appliedintuition",
                source_id="greenhouse_api", status="OPEN")
    _insert_job(conn, job_id="ai-open-2", company="appliedintuition",
                source_id="greenhouse_api", status="OPEN")
    _insert_job(conn, job_id="fal-open-1", company="fal",
                source_id="greenhouse_api", status="OPEN")
    _insert_job(conn, job_id="merge-open-1", company="merge",
                source_id="greenhouse_api", status="OPEN")
    # Legitimately closed BEFORE this migration — keeps its own closed_on and
    # must not be re-opened by the downgrade.
    _insert_job(conn, job_id="fal-closed-1", company="fal",
                source_id="greenhouse_api", status="CLOSED",
                closed_on=ORIGINAL_CLOSED_ON)
    # Ashby decoy for a re-pointed company: same company, different source_id.
    _insert_job(conn, job_id="ai-ashby-1", company="appliedintuition",
                source_id="ashby_api", status="OPEN")
    # Untouched-company decoy on the same source_id.
    _insert_job(conn, job_id="stripe-open-1", company="stripe",
                source_id="greenhouse_api", status="OPEN")
    # Unity's rows: soft-deactivation must not touch job_listings at all.
    _insert_job(conn, job_id="unity-open-1", company="unity3d",
                source_id="greenhouse_api", status="OPEN")
    _insert_job(conn, job_id="unity-closed-1", company="unity3d",
                source_id="greenhouse_api", status="CLOSED",
                closed_on=ORIGINAL_CLOSED_ON)


def _assert_upgraded(conn, *, created_at_before: dict[str, object]) -> None:
    companies = _companies(conn)

    for company_id, token in (
        ("appliedintuition", "applied"), ("fal", "fal-ai"), ("merge", "merge"),
    ):
        row = companies[company_id]
        assert row["ats"] == "ashby", f"{company_id} ats={row['ats']!r}"
        assert row["board_token"] == token, f"{company_id} token={row['board_token']!r}"
        assert row["enabled"] is True, f"{company_id} was deactivated by mistake"
        # created_at is the auto-enroll watermark — an in-place UPDATE must not
        # disturb it, or these three get force-added to every auto-enroll feed.
        assert row["created_at"] == created_at_before[company_id], (
            f"{company_id} created_at moved"
        )
        # Ashby rows carry an empty provider_config; all three already did.
        assert row["provider_config"] == {}, f"{company_id} provider_config changed"

    assert companies["unity3d"]["enabled"] is False, "unity3d not deactivated"
    # Unity's own provider config is untouched by the deactivation.
    assert companies["unity3d"]["ats"] == "greenhouse"
    assert companies["unity3d"]["board_token"] == "unity3d"
    # Decoy company untouched.
    assert companies["stripe"]["ats"] == "greenhouse"
    assert companies["stripe"]["enabled"] is True

    jobs = _jobs(conn)
    sentinel = _parse_ts(conn, SENTINEL_CLOSED_ON)
    original = _parse_ts(conn, ORIGINAL_CLOSED_ON)

    for key in (
        ("greenhouse_api", "ai-open-1"), ("greenhouse_api", "ai-open-2"),
        ("greenhouse_api", "fal-open-1"), ("greenhouse_api", "merge-open-1"),
    ):
        row = jobs[key]
        assert row["status"] == "CLOSED", f"{key} still OPEN"
        assert row["closed_on"] == sentinel, f"{key} closed_on={row['closed_on']!r}"

    # Pre-existing CLOSED row keeps its ORIGINAL timestamp (not the sentinel).
    assert jobs[("greenhouse_api", "fal-closed-1")]["status"] == "CLOSED"
    assert jobs[("greenhouse_api", "fal-closed-1")]["closed_on"] == original

    # Decoys: different source_id, and a different company, both still OPEN.
    assert jobs[("ashby_api", "ai-ashby-1")]["status"] == "OPEN"
    assert jobs[("ashby_api", "ai-ashby-1")]["closed_on"] is None
    assert jobs[("greenhouse_api", "stripe-open-1")]["status"] == "OPEN"
    assert jobs[("greenhouse_api", "stripe-open-1")]["closed_on"] is None

    # Unity's job rows are completely untouched — the retirement is a read-path
    # filter, not a data change.
    unity_rows = {k: v for k, v in jobs.items() if v["company"] == "unity3d"}
    assert len(unity_rows) == 2
    assert unity_rows[("greenhouse_api", "unity-open-1")]["status"] == "OPEN"
    assert unity_rows[("greenhouse_api", "unity-open-1")]["closed_on"] is None
    assert unity_rows[("greenhouse_api", "unity-closed-1")]["status"] == "CLOSED"
    assert unity_rows[("greenhouse_api", "unity-closed-1")]["closed_on"] == original


def _parse_ts(conn, value: str):
    """Round a literal through Postgres so comparisons use its own tz math."""
    cur = conn.cursor()
    cur.execute("SELECT CAST(%s AS timestamptz) AS t", (value,))
    return cur.fetchone()["t"]


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_repoint_ashby_migration_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """upgrade → assert → downgrade → assert full reversal → re-upgrade →
    assert idempotency, on a throwaway database."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_repoint_{suffix}"
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    roundtrip_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{roundtrip_db}"

    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint_cur = maint.cursor()
    maint_cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
        " WHERE datname = %s AND pid <> pg_backend_pid()",
        (roundtrip_db,),
    )
    maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
    maint_cur.execute(f'CREATE DATABASE "{roundtrip_db}"')
    maint.close()

    try:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine

        import api.db_models as _db_models

        engine = create_engine(roundtrip_url)
        _db_models.Base.metadata.create_all(engine)
        engine.dispose()

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None
        command.stamp(cfg, BASE_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            _seed(verify)
            before = _companies(verify)
            created_at_before = {k: v["created_at"] for k, v in before.items()}
            assert all(row["ats"] == "greenhouse" for row in before.values())
        finally:
            verify.close()

        # --- upgrade -------------------------------------------------------
        command.upgrade(cfg, REPOINT_REV)
        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            _assert_upgraded(verify, created_at_before=created_at_before)
        finally:
            verify.close()

        # --- downgrade: full reversal --------------------------------------
        command.downgrade(cfg, BASE_REV)
        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            companies = _companies(verify)
            for company_id, token in (
                ("appliedintuition", "appliedintuition"), ("fal", "fal"), ("merge", "merge"),
            ):
                assert companies[company_id]["ats"] == "greenhouse"
                assert companies[company_id]["board_token"] == token
                assert companies[company_id]["created_at"] == created_at_before[company_id]
            assert companies["unity3d"]["enabled"] is True, "unity3d not re-enabled"

            jobs = _jobs(verify)
            original = _parse_ts(verify, ORIGINAL_CLOSED_ON)
            for key in (
                ("greenhouse_api", "ai-open-1"), ("greenhouse_api", "ai-open-2"),
                ("greenhouse_api", "fal-open-1"), ("greenhouse_api", "merge-open-1"),
            ):
                assert jobs[key]["status"] == "OPEN", f"{key} not re-opened"
                assert jobs[key]["closed_on"] is None, f"{key} closed_on not cleared"
            # The sentinel match is what keeps this surgical: a row closed for
            # real before the migration stays CLOSED with its own timestamp.
            assert jobs[("greenhouse_api", "fal-closed-1")]["status"] == "CLOSED"
            assert jobs[("greenhouse_api", "fal-closed-1")]["closed_on"] == original
            assert jobs[("greenhouse_api", "unity-closed-1")]["status"] == "CLOSED"
            assert jobs[("ashby_api", "ai-ashby-1")]["status"] == "OPEN"
            assert jobs[("greenhouse_api", "stripe-open-1")]["status"] == "OPEN"
        finally:
            verify.close()

        # --- re-upgrade: idempotent ----------------------------------------
        command.upgrade(cfg, REPOINT_REV)
        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            _assert_upgraded(verify, created_at_before=created_at_before)
        finally:
            verify.close()

        # Running the upgrade body a SECOND time against already-upgraded data
        # must be a no-op (statements are scoped so they self-neutralize).
        command.downgrade(cfg, BASE_REV)
        command.upgrade(cfg, REPOINT_REV)
        command.stamp(cfg, BASE_REV)
        command.upgrade(cfg, REPOINT_REV)
        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            _assert_upgraded(verify, created_at_before=created_at_before)
        finally:
            verify.close()

    finally:
        try:
            maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
            maint.autocommit = True
            maint_cur = maint.cursor()
            maint_cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE datname = %s AND pid <> pg_backend_pid()",
                (roundtrip_db,),
            )
            maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
            maint.close()
        except Exception as drop_exc:
            logging.getLogger(__name__).error(
                "Failed to drop roundtrip test database %s during teardown: %s",
                roundtrip_db,
                drop_exc,
            )
