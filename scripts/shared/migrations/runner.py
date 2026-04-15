"""
Database migration runner.

Discovers migration files (NNNN_*.py) in this package, tracks applied versions
in a schema_migrations_{env} table, and applies migrations in order.

Each migration file defines:
    def upgrade(conn, env): ...
    def downgrade(conn, env): ...

Env-suffixed table naming (schema_migrations_local, schema_migrations_prod, etc.)
matches the rest of the schema and supports per-env test isolation.
"""

import hashlib
import importlib.util
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Set

import psycopg2

logger = logging.getLogger(__name__)

# Type alias for database connections
Connection = psycopg2.extensions.connection

_MIGRATIONS_DIR = Path(__file__).parent
_FILENAME_PATTERN = re.compile(r"^(\d{4})_([a-z0-9_]+)\.py$")

# Reuse the same env validation as database.py to keep rules consistent.
_ALLOWED_ENVS = frozenset({"local", "qa", "prod"})
_TEST_ENV_PATTERN = re.compile(r"^test_[a-f0-9]{8}$")


def _is_valid_env(env: str) -> bool:
    return env in _ALLOWED_ENVS or bool(_TEST_ENV_PATTERN.match(env))


def _tracking_table(env: str) -> str:
    if not _is_valid_env(env):
        raise ValueError(f"Invalid environment: {env!r}")
    return f"schema_migrations_{env}"


def _advisory_lock_key(env: str) -> int:
    """Stable 64-bit signed int derived from env, for pg_advisory_lock."""
    digest = hashlib.sha256(f"job-visualizer:migrations:{env}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
def _advisory_lock(conn: Connection, env: str):
    """Serialize migration runs across processes/instances for this env."""
    key = _advisory_lock_key(env)
    cursor = conn.cursor()
    cursor.execute("SELECT pg_advisory_lock(%s)", (key,))
    try:
        yield
    finally:
        cursor.execute("SELECT pg_advisory_unlock(%s)", (key,))
        conn.commit()


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: Callable[[Connection, str], None]
    downgrade: Callable[[Connection, str], None]

    @property
    def label(self) -> str:
        return f"{self.version:04d}_{self.name}"


def discover_migrations() -> List[Migration]:
    """Find and load all NNNN_*.py migration files in this package."""
    migrations: List[Migration] = []
    seen_versions: Set[int] = set()

    for path in sorted(_MIGRATIONS_DIR.iterdir()):
        if not path.is_file() or path.suffix != ".py":
            continue
        match = _FILENAME_PATTERN.match(path.name)
        if not match:
            continue

        version = int(match.group(1))
        name = match.group(2)

        if version in seen_versions:
            raise RuntimeError(f"Duplicate migration version {version} in {path.name}")
        seen_versions.add(version)

        spec = importlib.util.spec_from_file_location(f"_migration_{version:04d}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load migration {path.name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for attr in ("upgrade", "downgrade"):
            if not callable(getattr(module, attr, None)):
                raise RuntimeError(f"Migration {path.name} missing {attr}(conn, env)")

        migrations.append(
            Migration(
                version=version,
                name=name,
                upgrade=module.upgrade,
                downgrade=module.downgrade,
            )
        )

    migrations.sort(key=lambda m: m.version)
    return migrations


def _ensure_tracking_table(conn: Connection, env: str) -> None:
    table = _tracking_table(env)
    cursor = conn.cursor()
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.commit()


def get_applied_versions(conn: Connection, env: str) -> Set[int]:
    """Return the set of migration versions already applied for this env."""
    _ensure_tracking_table(conn, env)
    table = _tracking_table(env)
    cursor = conn.cursor()
    cursor.execute(f"SELECT version FROM {table}")
    return {row[0] if not isinstance(row, dict) else row["version"] for row in cursor.fetchall()}


def migrate_up(conn: Connection, env: str) -> List[int]:
    """Apply all pending migrations. Returns list of newly-applied versions."""
    table = _tracking_table(env)
    with _advisory_lock(conn, env):
        applied = get_applied_versions(conn, env)
        migrations = discover_migrations()
        newly_applied: List[int] = []

        for migration in migrations:
            if migration.version in applied:
                continue
            logger.info(f"Applying migration {migration.label} (env={env})")
            try:
                migration.upgrade(conn, env)
                cursor = conn.cursor()
                cursor.execute(
                    f"INSERT INTO {table} (version, name) VALUES (%s, %s)",
                    (migration.version, migration.name),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception(f"Migration {migration.label} failed; stopping")
                raise
            newly_applied.append(migration.version)

        return newly_applied


def migrate_down(conn: Connection, env: str, target_version: int = 0) -> List[int]:
    """Roll back migrations down to target_version (exclusive). CLI-only."""
    table = _tracking_table(env)
    with _advisory_lock(conn, env):
        applied = get_applied_versions(conn, env)
        migrations = {m.version: m for m in discover_migrations()}
        rolled_back: List[int] = []

        for version in sorted(applied, reverse=True):
            if version <= target_version:
                break
            if version not in migrations:
                raise RuntimeError(
                    f"Cannot rollback version {version}: migration file missing"
                )
            migration = migrations[version]
            logger.info(f"Rolling back migration {migration.label} (env={env})")
            try:
                migration.downgrade(conn, env)
                cursor = conn.cursor()
                cursor.execute(f"DELETE FROM {table} WHERE version = %s", (version,))
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception(f"Rollback of {migration.label} failed; stopping")
                raise
            rolled_back.append(version)

        return rolled_back
