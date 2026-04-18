"""
Integration tests for the migration system end-to-end.

Verifies that:
- init_schema (now backed by the migration runner) creates all expected tables
  and constraints matching the current state of main
- Migration 0002 actually applies the UNIQUE constraint on users.email
- Roll back and re-apply round-trip works
"""

import sys
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared import database as db  # noqa: E402
from shared.migrations import runner  # noqa: E402


def _constraint_exists(conn, name):
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,))
    return cursor.fetchone() is not None


class TestEndToEnd:
    def test_init_schema_creates_users_with_email_unique(self, in_memory_db, test_env):
        """After init_schema, users.email has a UNIQUE constraint."""
        assert _constraint_exists(in_memory_db, f"users_{test_env}_email_key")

    def test_duplicate_email_rejected(self, in_memory_db, test_env):
        cursor = in_memory_db.cursor()
        users_table = f"users_{test_env}"
        common = {
            "display_name": None,
            "given_name": "T",
            "family_name": "U",
            "picture_url": None,
            "created_at": "2026-04-15T00:00:00Z",
            "updated_at": "2026-04-15T00:00:00Z",
        }
        cursor.execute(
            f"INSERT INTO {users_table} (id, auth0_id, email, display_name, "
            f"given_name, family_name, picture_url, created_at, updated_at) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ("u1", "auth0|1", "dup@example.com", *common.values()),
        )
        in_memory_db.commit()

        with pytest.raises(psycopg2.errors.UniqueViolation):
            cursor.execute(
                f"INSERT INTO {users_table} (id, auth0_id, email, display_name, "
                f"given_name, family_name, picture_url, created_at, updated_at) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                ("u2", "auth0|2", "dup@example.com", *common.values()),
            )
        in_memory_db.rollback()

    def test_rollback_then_reapply(self, in_memory_db, test_env):
        """Running down then up leaves the schema in the same final state."""
        # Rollback only 0002 (email UNIQUE)
        runner.migrate_down(in_memory_db, test_env, target_version=1)
        assert not _constraint_exists(in_memory_db, f"users_{test_env}_email_key")

        # Re-apply
        runner.migrate_up(in_memory_db, test_env)
        assert _constraint_exists(in_memory_db, f"users_{test_env}_email_key")


def _posted_on_type(conn, table):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = 'posted_on'",
        (table,),
    )
    row = cursor.fetchone()
    return row["data_type"] if row else None


class TestPostedOnTimestamptz:
    """Migration 0003 converts job_listings.posted_on from text to timestamptz."""

    def test_posted_on_is_timestamptz_after_init(self, in_memory_db, test_env):
        assert _posted_on_type(in_memory_db, f"job_listings_{test_env}") == "timestamp with time zone"

    def test_inserting_iso_string_works(self, in_memory_db, test_env):
        """Existing scraper code passes ISO 8601 strings; psycopg2 implicit cast must still work."""
        cursor = in_memory_db.cursor()
        table = f"job_listings_{test_env}"
        cursor.execute(
            f"INSERT INTO {table} (id, title, company, url, source_id, posted_on, "
            f"created_at, first_seen_at, last_seen_at) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "j1", "SWE", "apple", "https://example/1", "src",
                "2026-01-08T19:04:30.284+00:00",
                "2026-04-15T00:00:00Z", "2026-04-15T00:00:00Z", "2026-04-15T00:00:00Z",
            ),
        )
        in_memory_db.commit()
        cursor.execute(f"SELECT posted_on FROM {table} WHERE id = 'j1'")
        value = cursor.fetchone()["posted_on"]
        # psycopg2 returns a tz-aware datetime for timestamptz columns
        assert value is not None
        assert value.tzinfo is not None

    def test_rollback_restores_text(self, in_memory_db, test_env):
        runner.migrate_down(in_memory_db, test_env, target_version=2)
        assert _posted_on_type(in_memory_db, f"job_listings_{test_env}") == "text"

        runner.migrate_up(in_memory_db, test_env)
        assert _posted_on_type(in_memory_db, f"job_listings_{test_env}") == "timestamp with time zone"


def _column_type(conn, table, column):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    row = cursor.fetchone()
    return row["data_type"] if row else None


class TestJobTimestampColumns:
    """Migration 0004 converts created_at, closed_on, first_seen_at, last_seen_at to timestamptz."""

    COLUMNS = ("created_at", "closed_on", "first_seen_at", "last_seen_at")

    def test_all_columns_are_timestamptz_after_init(self, in_memory_db, test_env):
        table = f"job_listings_{test_env}"
        for col in self.COLUMNS:
            assert _column_type(in_memory_db, table, col) == "timestamp with time zone", col

    def test_not_null_constraints_preserved(self, in_memory_db, test_env):
        """ALTER COLUMN TYPE must not drop the NOT NULL constraints on the three required cols."""
        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = ANY(%s)",
            (f"job_listings_{test_env}", list(self.COLUMNS)),
        )
        nullable = {row["column_name"]: row["is_nullable"] for row in cursor.fetchall()}
        assert nullable["created_at"] == "NO"
        assert nullable["first_seen_at"] == "NO"
        assert nullable["last_seen_at"] == "NO"
        assert nullable["closed_on"] == "YES"

    def test_rollback_restores_text(self, in_memory_db, test_env):
        runner.migrate_down(in_memory_db, test_env, target_version=3)
        table = f"job_listings_{test_env}"
        for col in self.COLUMNS:
            assert _column_type(in_memory_db, table, col) == "text", col

        runner.migrate_up(in_memory_db, test_env)
        for col in self.COLUMNS:
            assert _column_type(in_memory_db, table, col) == "timestamp with time zone", col


def _load_migration(version):
    """Import a specific migration module by version number for direct invocation."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).parent.parent.parent / "shared" / "migrations"
    )
    match = next(p for p in path.iterdir() if p.name.startswith(f"{version:04d}_"))
    spec = importlib.util.spec_from_file_location(f"_mig_{version}", match)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPostedOnIdempotent:
    """Re-running 0003 against an already-converted column must be a no-op."""

    def test_upgrade_noops_when_already_timestamptz(self, in_memory_db, test_env):
        mig = _load_migration(3)
        # Column is already timestamptz after the fixture's init_schema; calling
        # upgrade again must not raise.
        mig.upgrade(in_memory_db, test_env)
        assert _posted_on_type(in_memory_db, f"job_listings_{test_env}") == "timestamp with time zone"


class TestJobTimestampIdempotent:
    """Re-running 0004 against already-converted columns must be a no-op."""

    COLUMNS = ("created_at", "closed_on", "first_seen_at", "last_seen_at")

    def test_upgrade_noops_when_already_timestamptz(self, in_memory_db, test_env):
        mig = _load_migration(4)
        mig.upgrade(in_memory_db, test_env)
        table = f"job_listings_{test_env}"
        for col in self.COLUMNS:
            assert _column_type(in_memory_db, table, col) == "timestamp with time zone", col


class TestPostedOnMalformedRowGuard:
    """If a row has a non-ISO 8601 posted_on, 0003 must fail fast with a clear error."""

    def test_malformed_row_blocks_upgrade(self, in_memory_db, test_env):
        # Roll back to baseline where posted_on is still TEXT, so we can insert
        # the bad value without postgres rejecting it at INSERT time.
        runner.migrate_down(in_memory_db, test_env, target_version=2)
        table = f"job_listings_{test_env}"
        assert _posted_on_type(in_memory_db, table) == "text"

        cursor = in_memory_db.cursor()
        cursor.execute(
            f"INSERT INTO {table} (id, title, company, url, source_id, posted_on, "
            f"created_at, first_seen_at, last_seen_at) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "bad-1", "SWE", "apple", "https://example/1", "src",
                "not-a-date",
                "2026-04-15T00:00:00Z", "2026-04-15T00:00:00Z", "2026-04-15T00:00:00Z",
            ),
        )
        in_memory_db.commit()

        try:
            with pytest.raises(RuntimeError, match="ISO 8601 prefix"):
                runner.migrate_up(in_memory_db, test_env)

            # 0003 did not complete: column is still text, tracking table lacks v3.
            assert _posted_on_type(in_memory_db, table) == "text"
            applied = runner.get_applied_versions(in_memory_db, test_env)
            assert 3 not in applied
            assert {1, 2}.issubset(applied)
        finally:
            # Clean up so later tests in this module's session see a valid
            # state, even if the assertion/match above fails. Without this,
            # a message-string drift would cascade to every downstream test.
            try:
                cursor.execute(f"DELETE FROM {table} WHERE id = 'bad-1'")
                in_memory_db.commit()
            except Exception:
                in_memory_db.rollback()
            runner.migrate_up(in_memory_db, test_env)


class TestSchemaDriftGuards:
    """0003 and 0004 must raise a contextual RuntimeError — not an opaque
    psycopg2 UndefinedTable/UndefinedColumn — when the table or column they
    depend on has disappeared. Pass 1 added these guards; this test locks
    them in so a future refactor can't silently regress.
    """

    def test_0003_raises_when_table_missing(self, in_memory_db, test_env):
        # Roll back to v2 so posted_on is TEXT, then drop the whole table to
        # simulate severe drift (we need to DROP, not just alter, to hit the
        # missing-table branch).
        runner.migrate_down(in_memory_db, test_env, target_version=2)
        cursor = in_memory_db.cursor()
        cursor.execute(f"DROP TABLE job_listings_{test_env} CASCADE")
        in_memory_db.commit()

        mig = _load_migration(3)
        try:
            with pytest.raises(RuntimeError, match=f"table job_listings_{test_env} not found"):
                mig.upgrade(in_memory_db, test_env)
        finally:
            in_memory_db.rollback()

    def test_0003_raises_when_posted_on_column_missing(self, in_memory_db, test_env):
        runner.migrate_down(in_memory_db, test_env, target_version=2)
        cursor = in_memory_db.cursor()
        cursor.execute(f"ALTER TABLE job_listings_{test_env} DROP COLUMN posted_on")
        in_memory_db.commit()

        mig = _load_migration(3)
        try:
            with pytest.raises(RuntimeError, match="column posted_on"):
                mig.upgrade(in_memory_db, test_env)
        finally:
            in_memory_db.rollback()

    def test_0004_raises_when_column_missing(self, in_memory_db, test_env):
        runner.migrate_down(in_memory_db, test_env, target_version=3)
        cursor = in_memory_db.cursor()
        # Drop one of 0004's target columns. 'closed_on' is nullable so the
        # DROP succeeds without needing to clear data first.
        cursor.execute(f"ALTER TABLE job_listings_{test_env} DROP COLUMN closed_on")
        in_memory_db.commit()

        mig = _load_migration(4)
        try:
            with pytest.raises(RuntimeError, match="column closed_on"):
                mig.upgrade(in_memory_db, test_env)
        finally:
            in_memory_db.rollback()
