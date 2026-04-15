"""
Unit tests for the migration runner (scripts/shared/migrations/runner.py).

Discovery and module-loading tests run without a DB. Application tests use the
real PostgreSQL fixture because psycopg2 transaction semantics aren't realistic
to mock — keeping the test close to production behavior is worth the extra
setup.
"""

import sys
from pathlib import Path

import pytest

# Ensure scripts package is importable as in other test files
scripts_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(scripts_dir.parent))

from scripts.shared.migrations import runner


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
