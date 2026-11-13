"""Integration test: the drop revision removes the five launch_radar_* tables,
with rows in them, and its downgrade recreates them empty.

Why this exists: the shared ``db_conn`` fixture builds the schema with
``create_all`` and stamps head, and the parity test never runs an upgrade body,
so no other test executes this revision's DDL. Autogenerate emitted the drops
in an order Postgres refuses (``launch_radar_cards`` before
``launch_radar_pr_requests``, whose foreign key points at it). Shipped like
that, Railway's boot-time ``alembic upgrade head`` fails and the deploy never
turns healthy. This test runs the real upgrade against tables built by the real
historical revisions.

Every revision between ``b7c4d1370996`` and the drop (today the two company
seeds ``1cf20b0f50ee`` and ``6c43ef2ae344``) inserts into ``companies``, which
an empty database does not have, so they are stamped over rather than run. The
drop's parent is read from the revision graph, so re-parenting the drop needs
no edit here.
"""

from __future__ import annotations

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

_BEFORE_TABLES = "904d5bc44e4b"  # parent of the revision that created them
_TABLES_CREATED = "b7c4d1370996"  # all five tables exist from here
_DROP_REVISION = "d0342324554a"  # the drop; its parent is read from the graph

_TABLES = {
    "launch_radar_cards",
    "launch_radar_monitors",
    "launch_radar_pr_requests",
    "launch_radar_runs",
    "launch_radar_spend",
}


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _relations(conn, relkind: str) -> set[str]:
    """Tables ('r'), indexes ('i') or sequences ('S') named launch_radar_* or *_launch_radar_*."""
    cur = conn.cursor()
    cur.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = %s AND c.relname LIKE %s",
        (relkind, "%launch\\_radar\\_%"),
    )
    return {r["relname"] for r in cur.fetchall()}


def _foreign_keys(conn) -> set[tuple[str, str]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT conrelid::regclass::text AS tbl, confrelid::regclass::text AS ref "
        "FROM pg_constraint WHERE contype = 'f' "
        "AND conrelid::regclass::text LIKE 'launch\\_radar\\_%'"
    )
    return {(r["tbl"], r["ref"]) for r in cur.fetchall()}


def _version(conn) -> str:
    cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version")
    return cur.fetchone()["version_num"]


def _seed_every_table(conn) -> None:
    """One row per table, across every foreign key, like production has."""
    cur = conn.cursor()
    cur.execute("INSERT INTO launch_radar_runs (run_uuid, budget_usd) VALUES ('r-1', 1.0) RETURNING id")
    run_id = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO launch_radar_spend (run_id, step, amount_usd) VALUES (%s, 'brief', 0.01)",
        (run_id,),
    )
    cur.execute(
        "INSERT INTO launch_radar_monitors (slot, monitor_id, query, processor, frequency, "
        "charged_through) VALUES ('seed', 'monitor_1', 'q', 'base', '1d', now())"
    )
    cur.execute(
        "INSERT INTO launch_radar_cards (domain, company_name, status, payload, run_id) "
        "VALUES ('example.ai', 'Example', 'saved', '{}'::jsonb, %s) RETURNING id",
        (run_id,),
    )
    card_id = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO launch_radar_pr_requests (card_id, status, pr_url, pr_number) VALUES "
        "(%s, 'open', 'https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/1', 1)",
        (card_id,),
    )


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_drop_revision_drops_populated_tables_and_downgrade_recreates_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    roundtrip_db = f"lr_drop_{uuid.uuid4().hex[:8]}"
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
        from alembic.script import ScriptDirectory

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        drop_script = ScriptDirectory.from_config(cfg).get_revision(_DROP_REVISION)
        assert drop_script is not None, _DROP_REVISION
        drop_parent = drop_script.down_revision
        assert isinstance(drop_parent, str), drop_parent  # one parent, never a merge

        # Build the tables exactly as production got them: by the historical revisions.
        command.stamp(cfg, _BEFORE_TABLES)
        command.upgrade(cfg, _TABLES_CREATED)
        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            assert _relations(conn, "r") == _TABLES
            _seed_every_table(conn)
        finally:
            conn.close()
        command.stamp(cfg, drop_parent)

        # The drop: every table, index and sequence goes, rows and all.
        command.upgrade(cfg, _DROP_REVISION)
        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _version(conn) == _DROP_REVISION
            assert _relations(conn, "r") == set()
            assert _relations(conn, "i") == set()
            assert _relations(conn, "S") == set()
        finally:
            conn.close()

        # Downgrade recreates the five tables, empty, with their links and indexes.
        command.downgrade(cfg, drop_parent)
        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _version(conn) == drop_parent
            assert _relations(conn, "r") == _TABLES
            assert _foreign_keys(conn) == {
                ("launch_radar_cards", "launch_radar_runs"),
                ("launch_radar_spend", "launch_radar_runs"),
                ("launch_radar_pr_requests", "launch_radar_cards"),
            }
            assert {
                "idx_launch_radar_runs_started_at",
                "idx_launch_radar_spend_run_id",
                "idx_launch_radar_cards_status_posted",
                "idx_launch_radar_pr_requests_status_requested",
                "uq_launch_radar_pr_requests_pr_url",
            } <= _relations(conn, "i")
            cur = conn.cursor()
            for table in sorted(_TABLES):
                cur.execute(f"SELECT count(*) AS n FROM {table}")
                assert cur.fetchone()["n"] == 0, table
        finally:
            conn.close()

        # And the drop is re-runnable after a downgrade.
        command.upgrade(cfg, _DROP_REVISION)
        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _relations(conn, "r") == set()
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
