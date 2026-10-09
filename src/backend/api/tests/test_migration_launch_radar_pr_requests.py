"""Integration test: revision ``b7c4d1370996`` creates ``launch_radar_pr_requests``,
backfills a row for every saved card, and its downgrade drops the table.

Modelled on test_migration_launch_radar_tables.py: the shared ``db_conn`` fixture
builds the schema with ``create_all`` and stamps head, so no normal test runs this
revision's own DDL or its hand-written backfill. This runs both against a
throwaway database of its own: stamped at ``33ff7e590a46``'s parent, upgraded to
``33ff7e590a46`` (the launch_radar tables), seeded with cards, then upgraded to
this revision.

The backfill (PLAN D10): a saved card gets ``already_tracked`` when it has a
tracked company, else ``queued``; every other status gets nothing; the legacy
``launch_radar_cards.pr_url`` column changes nothing.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import Json, RealDictCursor

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

_GRANDPARENT_REVISION = "904d5bc44e4b"
_PARENT_REVISION = "33ff7e590a46"
_PR_REQUESTS_REVISION = "b7c4d1370996"

_LEGACY_PR = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/333"
_GOOD_PR = "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/400"


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _table_exists(conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('public.launch_radar_pr_requests') IS NOT NULL AS ok")
    return bool(cur.fetchone()["ok"])


def _indexes(conn) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname = 'public' AND tablename = 'launch_radar_pr_requests'"
    )
    return {r["indexname"] for r in cur.fetchall()}


def _insert_card(
    conn,
    domain: str,
    status: str,
    *,
    tracked: str | None = None,
    pr_url: str | None = None,
) -> int:
    payload = None if status == "deleted" else Json({"domain": domain})
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO launch_radar_cards "
        "(domain, company_name, status, tracked_company_id, pr_url, payload) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (domain, domain, status, tracked, pr_url, payload),
    )
    return int(cur.fetchone()["id"])


def _requests(conn) -> dict[int, dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT card_id, status, attempts, pr_url, pr_number, last_reason, "
        "retry_after, claimed_at, finished_at, requested_at FROM launch_radar_pr_requests"
    )
    return {r["card_id"]: dict(r) for r in cur.fetchall()}


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_launch_radar_pr_requests_upgrade_backfill_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    roundtrip_db = f"lr_pr_requests_{uuid.uuid4().hex[:8]}"
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint.cursor().execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
    maint.cursor().execute(f'CREATE DATABASE "{roundtrip_db}"')
    maint.close()

    roundtrip_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{roundtrip_db}"

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _GRANDPARENT_REVISION)
        command.upgrade(cfg, _PARENT_REVISION)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            saved = _insert_card(conn, "saved.ai", "saved")
            saved_tracked = _insert_card(conn, "tracked.ai", "saved", tracked="tracked")
            saved_legacy = _insert_card(conn, "legacy.ai", "saved", pr_url=_LEGACY_PR)
            new_legacy = _insert_card(
                conn,
                "newlegacy.ai",
                "new",
                pr_url="https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/334",
            )
            archived = _insert_card(conn, "archived.ai", "archived")
            deleted = _insert_card(conn, "deleted.ai", "deleted")
            assert _table_exists(conn) is False
        finally:
            conn.close()

        command.upgrade(cfg, _PR_REQUESTS_REVISION)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            assert _table_exists(conn) is True
            assert _indexes(conn) == {
                "launch_radar_pr_requests_pkey",
                "uq_launch_radar_pr_requests_card_id",
                "uq_launch_radar_pr_requests_pr_url",
                "idx_launch_radar_pr_requests_status_requested",
            }
            rows = _requests(conn)
            # Saved cards only; the legacy pr_url column changes nothing.
            assert set(rows) == {saved, saved_tracked, saved_legacy}
            for card_id in (saved, saved_legacy):
                row = rows[card_id]
                assert row["status"] == "queued" and row["finished_at"] is None
                assert row["attempts"] == 0 and row["pr_url"] is None and row["pr_number"] is None
                assert row["last_reason"] is None and row["retry_after"] is None
                assert row["claimed_at"] is None and row["requested_at"] is not None
            tracked_row = rows[saved_tracked]
            assert tracked_row["status"] == "already_tracked"
            assert tracked_row["finished_at"] is not None and tracked_row["pr_url"] is None
            for card_id in (new_legacy, archived, deleted):
                assert card_id not in rows

            cur = conn.cursor()
            # The CHECKs hold in the migrated database.
            with pytest.raises(psycopg2.errors.CheckViolation):  # open without a URL
                cur.execute(
                    "UPDATE launch_radar_pr_requests SET status = 'open' WHERE card_id = %s",
                    (saved,),
                )
            for bad in (
                "https://github.com/someone-else/Job-Visualizer-Notifier/pull/1",
                "https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/1/files",
                "https://github.com/brendanpotter00/Job-Visualizer-Notifier/issues/1",
                "http://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/1",
                "https://githubXcom/brendanpotter00/Job-Visualizer-Notifier/pull/1",
            ):
                with pytest.raises(psycopg2.errors.CheckViolation):
                    cur.execute(
                        "UPDATE launch_radar_pr_requests SET status = 'open', pr_url = %s, "
                        "pr_number = 1 WHERE card_id = %s",
                        (bad, saved),
                    )
            with pytest.raises(psycopg2.errors.CheckViolation):  # a URL needs its number
                cur.execute(
                    "UPDATE launch_radar_pr_requests SET status = 'open', pr_url = %s "
                    "WHERE card_id = %s",
                    (_GOOD_PR, saved),
                )
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE launch_radar_pr_requests SET status = 'merged' WHERE card_id = %s",
                    (saved,),
                )
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE launch_radar_pr_requests SET attempts = -1 WHERE card_id = %s",
                    (saved,),
                )
            cur.execute(
                "UPDATE launch_radar_pr_requests SET status = 'open', pr_url = %s, "
                "pr_number = 400 WHERE card_id = %s",
                (_GOOD_PR, saved),
            )
            # One PR is never recorded for two cards; one request per card.
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    "UPDATE launch_radar_pr_requests SET status = 'open', pr_url = %s, "
                    "pr_number = 400 WHERE card_id = %s",
                    (_GOOD_PR, saved_legacy),
                )
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute("INSERT INTO launch_radar_pr_requests (card_id) VALUES (%s)", (saved,))
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cur.execute("INSERT INTO launch_radar_pr_requests (card_id) VALUES (999999)")
        finally:
            conn.close()

        command.downgrade(cfg, _PARENT_REVISION)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(conn) is False
            assert _indexes(conn) == set()
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version")
            assert cur.fetchone()["version_num"] == _PARENT_REVISION
            # The cards themselves are untouched, legacy pr_url included.
            cur.execute("SELECT count(*) AS n FROM launch_radar_cards")
            assert cur.fetchone()["n"] == 6
            cur.execute("SELECT pr_url FROM launch_radar_cards WHERE id = %s", (saved_legacy,))
            assert cur.fetchone()["pr_url"] == _LEGACY_PR
        finally:
            conn.close()

        # And back up again: the revision re-runs, and the backfill with it.
        command.upgrade(cfg, _PR_REQUESTS_REVISION)
        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            rows = _requests(conn)
            assert {k: v["status"] for k, v in rows.items()} == {
                saved: "queued",
                saved_tracked: "already_tracked",
                saved_legacy: "queued",
            }
        finally:
            conn.close()
    finally:
        maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
        maint.autocommit = True
        maint_cur = maint.cursor()
        maint_cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (roundtrip_db,),
        )
        maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
        maint.close()
