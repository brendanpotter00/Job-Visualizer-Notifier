"""Integration test: composite PK migration on job_listings.

Runs the real alembic upgrade / downgrade against a freshly-created
database. Mirrors test_migration_companies.py.

Test cases:
  1. Greenhouse id rewrite: ``greenhouse_12345`` -> ``12345`` for
     ``source_id = 'greenhouse_api'``; non-Greenhouse rows untouched.
  2. Composite PK enforced: after upgrade, duplicate ``(greenhouse_api,
     12345)`` insert raises UniqueViolation; ``(other_source, 12345)`` OK.
  3. Collision pre-flight: pre-seed colliding rows; upgrade RAISES and
     leaves the table state unchanged.
  4. Downgrade reversibility: upgrade -> downgrade -1 -> upgrade
     round-trip preserves data and PK shape.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import errors as pg_errors
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

NEW_REV = "ebb479b7eed5"
PREV_REV = "e6cbbb3c2f17"


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _create_pre_migration_job_listings(conn) -> None:
    """Manually create the job_listings table with the pre-migration shape.

    Pre-PREV_REV the table has a single-column PK on ``id``. Subsequent
    Alembic migrations down to e6cbbb3c2f17 don't recreate this table; the
    real production schema was bootstrapped by an earlier (pre-Alembic)
    runner. To simulate that starting state in a scratch DB we create the
    table directly here.
    """
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS job_listings (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            url TEXT NOT NULL,
            source_id TEXT NOT NULL,
            details JSONB DEFAULT '{}'::jsonb,
            posted_on TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            closed_on TIMESTAMP WITH TIME ZONE,
            status TEXT DEFAULT 'OPEN',
            has_matched BOOLEAN DEFAULT false,
            ai_metadata JSONB DEFAULT '{}'::jsonb,
            first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
            last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
            consecutive_misses INTEGER DEFAULT 0,
            details_scraped BOOLEAN DEFAULT false
        )
        """
    )


def _seed_pre_migration_row(conn, *, id: str, source_id: str, company: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO job_listings ("
        " id, title, company, location, url, source_id, details,"
        " created_at, status, has_matched, ai_metadata,"
        " first_seen_at, last_seen_at, consecutive_misses, details_scraped"
        ") VALUES ("
        " %s, %s, %s, %s, %s, %s, '{}'::jsonb,"
        " '2025-01-01T00:00:00Z', 'OPEN', false, '{}'::jsonb,"
        " '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', 0, true"
        ")",
        (id, "T", company, "L", "https://x", source_id),
    )


def _pk_columns(conn, table: str) -> list[str]:
    """Return ordered list of column names in the table's primary key."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.attname AS col
        FROM pg_index i
        JOIN pg_attribute a
          ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
        ORDER BY array_position(i.indkey, a.attnum)
        """,
        (table,),
    )
    return [r["col"] for r in cur.fetchall()]


def _select_ids(conn, source_id: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM job_listings WHERE source_id = %s ORDER BY id",
        (source_id,),
    )
    return {row["id"] for row in cur.fetchall()}


def _make_scratch_db_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _create_scratch_db(name: str) -> str:
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    cur = maint.cursor()
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (name,),
    )
    cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    cur.execute(f'CREATE DATABASE "{name}"')
    maint.close()
    return TEST_DB_URL.rsplit("/", 1)[0] + f"/{name}"


def _drop_scratch_db(name: str) -> None:
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    try:
        maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
        maint.autocommit = True
        cur = maint.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        maint.close()
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Failed to drop scratch DB %s: %s", name, exc
        )


def _alembic_cfg(roundtrip_url: str):
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", roundtrip_url)
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    cfg.config_file_name = None
    return cfg


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_greenhouse_id_rewrite_and_other_sources_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)
    name = _make_scratch_db_name("compositepk_rewrite")
    url = _create_scratch_db(name)
    try:
        from alembic import command

        cfg = _alembic_cfg(url)

        seed = psycopg2.connect(url, cursor_factory=RealDictCursor)
        seed.autocommit = True
        try:
            _create_pre_migration_job_listings(seed)
            _seed_pre_migration_row(
                seed, id="greenhouse_12345", source_id="greenhouse_api",
                company="stripe",
            )
            _seed_pre_migration_row(
                seed, id="987654321", source_id="google_scraper",
                company="google",
            )
        finally:
            seed.close()

        command.stamp(cfg, PREV_REV)
        command.upgrade(cfg, NEW_REV)

        verify = psycopg2.connect(url, cursor_factory=RealDictCursor)
        try:
            assert _select_ids(verify, "greenhouse_api") == {"12345"}, (
                "greenhouse_ prefix not stripped"
            )
            assert _select_ids(verify, "google_scraper") == {"987654321"}, (
                "non-greenhouse row was touched"
            )
            assert _pk_columns(verify, "job_listings") == ["source_id", "id"]
        finally:
            verify.close()
    finally:
        _drop_scratch_db(name)


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_composite_pk_enforced_after_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)
    name = _make_scratch_db_name("compositepk_enforce")
    url = _create_scratch_db(name)
    try:
        from alembic import command

        cfg = _alembic_cfg(url)

        bootstrap = psycopg2.connect(url, cursor_factory=RealDictCursor)
        bootstrap.autocommit = True
        try:
            _create_pre_migration_job_listings(bootstrap)
        finally:
            bootstrap.close()

        command.stamp(cfg, PREV_REV)
        command.upgrade(cfg, NEW_REV)

        conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            _seed_pre_migration_row(
                conn, id="12345", source_id="greenhouse_api", company="stripe",
            )
            with pytest.raises(pg_errors.UniqueViolation):
                _seed_pre_migration_row(
                    conn, id="12345", source_id="greenhouse_api", company="stripe",
                )
            # Same id under a different source_id is allowed.
            _seed_pre_migration_row(
                conn, id="12345", source_id="google_scraper", company="google",
            )
            cur = conn.cursor()
            cur.execute(
                "SELECT count(*) AS n FROM job_listings WHERE id = %s",
                ("12345",),
            )
            assert cur.fetchone()["n"] == 2
        finally:
            conn.close()
    finally:
        _drop_scratch_db(name)


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_upgrade_aborts_on_collision_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)
    name = _make_scratch_db_name("compositepk_collide")
    url = _create_scratch_db(name)
    try:
        from alembic import command

        cfg = _alembic_cfg(url)

        seed = psycopg2.connect(url, cursor_factory=RealDictCursor)
        seed.autocommit = True
        try:
            _create_pre_migration_job_listings(seed)
            _seed_pre_migration_row(
                seed, id="greenhouse_12345", source_id="greenhouse_api",
                company="stripe",
            )
            _seed_pre_migration_row(
                seed, id="12345", source_id="greenhouse_api",
                company="stripe",
            )
        finally:
            seed.close()

        command.stamp(cfg, PREV_REV)
        with pytest.raises(Exception) as exc_info:
            command.upgrade(cfg, NEW_REV)
        # The migration MUST abort via the descriptive DO $$ RAISE EXCEPTION
        # block in upgrade(). The pre-flight collision check now runs BEFORE
        # the destructive UPDATE (see migration upgrade() body), so the
        # operator's first signal is the descriptive "collisions ... aborting"
        # message, not a UniqueViolation on the legacy single-column PK.
        # This is the operator-runbook contract DEPLOY.md promises.
        message = str(exc_info.value).lower()
        assert "collision" in message and "aborting" in message, (
            f"expected descriptive collision/aborting message from "
            f"upgrade()'s DO $$ block, got: {exc_info.value!r}"
        )

        # Table state unchanged: both rows still present, prefix still on.
        verify = psycopg2.connect(url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT id FROM job_listings WHERE source_id = 'greenhouse_api' ORDER BY id"
            )
            ids = [row["id"] for row in cur.fetchall()]
            assert ids == ["12345", "greenhouse_12345"], (
                f"table state changed despite RAISE EXCEPTION: {ids!r}"
            )
            # PK is still single-column.
            assert _pk_columns(verify, "job_listings") == ["id"]
        finally:
            verify.close()
    finally:
        _drop_scratch_db(name)


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_downgrade_aborts_on_collision_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downgrade RAISES when re-prefixing greenhouse rows would collide
    with a non-greenhouse row whose id already equals 'greenhouse_<raw>'.

    Mirrors test_upgrade_aborts_on_collision_preflight: seed a state at
    head where the downgrade's `UPDATE ... SET id = 'greenhouse_' || id`
    would land on an id already used by another source. The DO $$ block
    in downgrade() must fire and roll back the transaction with table
    state intact (composite PK still in place, both rows still present
    and untouched).
    """
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)
    name = _make_scratch_db_name("compositepk_downgrade_collide")
    url = _create_scratch_db(name)
    try:
        from alembic import command

        cfg = _alembic_cfg(url)

        # Bootstrap pre-migration shape, stamp at PREV_REV, upgrade to head
        # so we have the composite PK in place and can seed colliding rows
        # in the post-migration shape.
        bootstrap = psycopg2.connect(url, cursor_factory=RealDictCursor)
        bootstrap.autocommit = True
        try:
            _create_pre_migration_job_listings(bootstrap)
        finally:
            bootstrap.close()

        command.stamp(cfg, PREV_REV)
        command.upgrade(cfg, NEW_REV)

        # Seed a colliding pair AT HEAD:
        #   - (source_id='greenhouse_api', id='42')           — would become
        #     'greenhouse_42' on downgrade.
        #   - (source_id='google_scraper', id='greenhouse_42') — already
        #     uses the would-be-prefixed shape, so the downgrade's
        #     `UPDATE ... SET id = 'greenhouse_' || id WHERE source_id =
        #     'greenhouse_api'` would create a (single-column-PK)
        #     duplicate id. The downgrade pre-flight must catch this.
        seed = psycopg2.connect(url, cursor_factory=RealDictCursor)
        seed.autocommit = True
        try:
            _seed_pre_migration_row(
                seed, id="42", source_id="greenhouse_api", company="stripe",
            )
            _seed_pre_migration_row(
                seed, id="greenhouse_42", source_id="google_scraper",
                company="google",
            )
        finally:
            seed.close()

        # Sanity: composite PK is in place before the downgrade attempt.
        verify_pre = psycopg2.connect(url, cursor_factory=RealDictCursor)
        try:
            assert _pk_columns(verify_pre, "job_listings") == ["source_id", "id"]
        finally:
            verify_pre.close()

        # Attempt downgrade; must RAISE with the descriptive message.
        with pytest.raises(Exception) as exc_info:
            command.downgrade(cfg, PREV_REV)
        message = str(exc_info.value).lower()
        assert "collide" in message and "aborting" in message, (
            f"expected descriptive collide/aborting message from "
            f"downgrade()'s DO $$ block, got: {exc_info.value!r}"
        )

        # Table state preserved: composite PK still in place, both rows
        # still present and unchanged.
        verify = psycopg2.connect(url, cursor_factory=RealDictCursor)
        try:
            assert _pk_columns(verify, "job_listings") == ["source_id", "id"], (
                "composite PK was dropped despite RAISE EXCEPTION"
            )
            cur = verify.cursor()
            cur.execute(
                "SELECT source_id, id FROM job_listings "
                "ORDER BY source_id, id"
            )
            rows = [(r["source_id"], r["id"]) for r in cur.fetchall()]
            assert rows == [
                ("google_scraper", "greenhouse_42"),
                ("greenhouse_api", "42"),
            ], f"table state changed despite RAISE EXCEPTION: {rows!r}"
        finally:
            verify.close()
    finally:
        _drop_scratch_db(name)


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_downgrade_round_trip_reversible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)
    name = _make_scratch_db_name("compositepk_roundtrip")
    url = _create_scratch_db(name)
    try:
        from alembic import command

        cfg = _alembic_cfg(url)

        seed = psycopg2.connect(url, cursor_factory=RealDictCursor)
        seed.autocommit = True
        try:
            _create_pre_migration_job_listings(seed)
            _seed_pre_migration_row(
                seed, id="greenhouse_42", source_id="greenhouse_api",
                company="stripe",
            )
            _seed_pre_migration_row(
                seed, id="googol", source_id="google_scraper",
                company="google",
            )
        finally:
            seed.close()

        command.stamp(cfg, PREV_REV)
        # upgrade head: prefix stripped, composite PK in place.
        command.upgrade(cfg, NEW_REV)
        verify = psycopg2.connect(url, cursor_factory=RealDictCursor)
        try:
            assert _select_ids(verify, "greenhouse_api") == {"42"}
            assert _select_ids(verify, "google_scraper") == {"googol"}
            assert _pk_columns(verify, "job_listings") == ["source_id", "id"]
        finally:
            verify.close()

        # downgrade -1: prefix restored, single-column PK back.
        command.downgrade(cfg, PREV_REV)
        verify = psycopg2.connect(url, cursor_factory=RealDictCursor)
        try:
            assert _select_ids(verify, "greenhouse_api") == {"greenhouse_42"}
            assert _select_ids(verify, "google_scraper") == {"googol"}
            assert _pk_columns(verify, "job_listings") == ["id"]
        finally:
            verify.close()

        # re-upgrade head: prefix stripped again, composite PK again.
        command.upgrade(cfg, NEW_REV)
        verify = psycopg2.connect(url, cursor_factory=RealDictCursor)
        try:
            assert _select_ids(verify, "greenhouse_api") == {"42"}
            assert _pk_columns(verify, "job_listings") == ["source_id", "id"]
        finally:
            verify.close()
    finally:
        _drop_scratch_db(name)
