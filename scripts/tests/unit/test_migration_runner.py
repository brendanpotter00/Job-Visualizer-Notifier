"""
Unit tests for the migration runner (scripts/shared/migrations/runner.py).

Discovery and module-loading tests run without a DB. Application tests use the
real PostgreSQL fixture because psycopg2 transaction semantics aren't realistic
to mock — keeping the test close to production behavior is worth the extra
setup.
"""

import logging
import re
import sys
from pathlib import Path

import pytest

# Ensure scripts package is importable as in other test files
scripts_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(scripts_dir))

from shared.migrations import runner


class TestDiscoverMigrations:
    def test_discovers_and_sorts_by_version(self):
        migrations = runner.discover_migrations()
        assert len(migrations) >= 2
        versions = [m.version for m in migrations]
        assert versions == sorted(versions)
        assert versions[0] == 1

    def test_each_migration_has_upgrade_and_downgrade(self):
        for m in runner.discover_migrations():
            assert callable(m.upgrade)
            assert callable(m.downgrade)


class TestAdvisoryLockKey:
    def test_stable_across_calls(self):
        assert runner._advisory_lock_key("local") == runner._advisory_lock_key("local")

    def test_different_envs_get_different_keys(self):
        assert runner._advisory_lock_key("local") != runner._advisory_lock_key("prod")


class TestTrackingTable:
    def test_invalid_env_raises(self):
        with pytest.raises(ValueError):
            runner._tracking_table("bad; DROP TABLE")

    def test_valid_env_returns_expected_name(self):
        assert runner._tracking_table("local") == "schema_migrations_local"
        assert runner._tracking_table("test_abc12345") == "schema_migrations_test_abc12345"


class TestMigrateUp:
    def test_applies_all_pending_then_idempotent(self, postgres_db, test_env):
        # After the postgres_db fixture, init_schema has already run which
        # applies all migrations. Calling migrate_up again must be a no-op.
        second_run = runner.migrate_up(postgres_db, test_env)
        assert second_run == []

        applied = runner.get_applied_versions(postgres_db, test_env)
        all_versions = {m.version for m in runner.discover_migrations()}
        assert applied == all_versions

    def test_tracking_table_records_applied(self, postgres_db, test_env):
        cursor = postgres_db.cursor()
        cursor.execute(
            f"SELECT version, name FROM schema_migrations_{test_env} ORDER BY version"
        )
        rows = cursor.fetchall()
        # fixture init_schema should have applied at least the 0001 baseline
        assert len(rows) >= 1
        # RealDictCursor returns dicts; handle both cases defensively
        first = rows[0]
        version = first["version"] if isinstance(first, dict) else first[0]
        assert version == 1


class TestMigrateDown:
    def test_rolls_back_to_target(self, postgres_db, test_env):
        runner.migrate_up(postgres_db, test_env)  # ensure current

        # Roll back to version 1 (leaves only 0001 applied)
        rolled = runner.migrate_down(postgres_db, test_env, target_version=1)
        assert 2 in rolled

        applied = runner.get_applied_versions(postgres_db, test_env)
        assert 1 in applied
        assert 2 not in applied

    def test_rollback_to_zero_removes_all(self, postgres_db, test_env):
        runner.migrate_up(postgres_db, test_env)
        runner.migrate_down(postgres_db, test_env, target_version=0)
        applied = runner.get_applied_versions(postgres_db, test_env)
        assert applied == set()


class TestAdvisoryLockLogging:
    """Confirm operators can see lock acquire/release in Railway logs."""

    def test_acquire_and_release_are_logged(self, postgres_db, test_env, caplog):
        # The fixture has already applied migrations, so calling migrate_up
        # again wouldn't emit a pending-plan line. Roll back one and reapply
        # so we exercise the full locked path with work to do.
        runner.migrate_down(postgres_db, test_env, target_version=1)
        caplog.clear()

        with caplog.at_level(logging.INFO, logger="shared.migrations.runner"):
            runner.migrate_up(postgres_db, test_env)

        messages = [record.getMessage() for record in caplog.records]
        assert any("Acquired migration advisory lock" in m for m in messages), messages
        # The release line must include `released=True` so operators grepping
        # per DEPLOY.md see the pass/fail signal, not just the verb.
        assert any(
            "Released migration advisory lock" in m and "released=True" in m
            for m in messages
        ), messages
        assert any(f"Pending migrations env={test_env}" in m for m in messages), messages
        # Per-migration elapsed-time format is called out in DEPLOY.md; a
        # format drift would silently break monitoring greps.
        elapsed_re = re.compile(r"^Applied migration \d{4}_.+ in \d+\.\d{2}s$")
        assert any(elapsed_re.match(m) for m in messages), messages


class TestRequireTransactional:
    """Ensures the autocommit guard fires before SET LOCAL would silently
    no-op. Without this guard, a caller flipping conn.autocommit = True would
    freeze deploys on a stuck advisory lock (lock_timeout wouldn't apply).
    """

    def test_migrate_up_raises_under_autocommit(self, postgres_db, test_env):
        postgres_db.autocommit = True
        try:
            with pytest.raises(RuntimeError, match="autocommit must be False"):
                runner.migrate_up(postgres_db, test_env)
        finally:
            postgres_db.autocommit = False

    def test_migrate_down_raises_under_autocommit(self, postgres_db, test_env):
        postgres_db.autocommit = True
        try:
            with pytest.raises(RuntimeError, match="autocommit must be False"):
                runner.migrate_down(postgres_db, test_env, target_version=0)
        finally:
            postgres_db.autocommit = False

    def test_advisory_lock_context_manager_raises_under_autocommit(
        self, postgres_db, test_env
    ):
        postgres_db.autocommit = True
        try:
            with pytest.raises(RuntimeError, match="autocommit must be False"):
                with runner._advisory_lock(postgres_db, test_env):
                    pass
        finally:
            postgres_db.autocommit = False
