"""Alembic environment — wires DATABASE_URL to Alembic.

Reads via src.backend.api.config.Settings so the app and Alembic share
one config surface. Uses Alembic's default `alembic_version` tracker —
envAgnosticTables Unit 2 removed the per-env `alembic_version_{env}`
variant since tables are now bare-named across all environments.

compare_type and compare_server_default are enabled so the parity test
(and all future autogenerate runs) catch column type and default drift.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# Make `api.*` imports resolve regardless of how Alembic was invoked.
#
# Dev layout: src/backend/alembic/env.py — parents[3] is the repo root; add it
# and src/backend so both `src.backend.api.*` and `api.*` forms work from any
# cwd (operator laptop, pytest from repo root or from src/backend).
#
# Docker layout: /app/alembic/env.py — only 3 parents (/app/alembic, /app, /),
# so parents[3] raises IndexError. The Dockerfile already sets PYTHONPATH=/app
# and COPYs api/ to /app/api/, so `from api.config import settings` resolves
# without any sys.path munging. Skip the dev-only block when the chain is too
# shallow instead of crashing on the IndexError (root cause of the 2026-04-19
# post-merge crashloop on Railway).
_HERE = Path(__file__).resolve()
if len(_HERE.parents) > 3:
    _REPO_ROOT = _HERE.parents[3]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    _BACKEND_ROOT = _REPO_ROOT / "src" / "backend"
    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))

from api.config import settings  # noqa: E402  (path prepended above)
from api.db_models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Pull DATABASE_URL from the same Settings object the app uses. If
# alembic.ini already set sqlalchemy.url (e.g. from a CLI override),
# honor that; otherwise inject from settings.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url)

# PYTEST_SCHEMA carves out a per-pytest-worker Postgres schema so parallel
# test runs (and interrupted runs) don't collide in the shared `public`
# schema. When unset (prod, local dev, scraper runs), search_path is
# untouched and behavior is identical to not having the feature.
# Validated with a strict regex so a malicious/buggy env var can't inject
# DDL through the quoted identifier.
import os as _os
import re as _re

_PYTEST_SCHEMA = _os.environ.get("PYTEST_SCHEMA")
_PYTEST_SCHEMA_RE = _re.compile(r"^(?:public|test_[a-f0-9]{8,})$")
if _PYTEST_SCHEMA is not None and not _PYTEST_SCHEMA_RE.match(_PYTEST_SCHEMA):
    raise ValueError(
        f"PYTEST_SCHEMA={_PYTEST_SCHEMA!r} does not match expected pattern "
        f"'test_<hex>' or 'public'. Refusing to interpolate into SQL."
    )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout).

    PYTEST_SCHEMA is NOT honored here — offline mode is not used by this
    repo's operators or CI. If that changes, emit `SET search_path` as the
    first statement via context.execute.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Schema-per-worker test isolation. Must run BEFORE context.configure
        # so the version table + all DDL land inside the test schema, not
        # in public. Regex above already validated the schema name.
        #
        # SQLAlchemy 2.x connections use explicit transactions by default, so
        # the CREATE SCHEMA would roll back when the `with` block exits if we
        # didn't commit it ourselves. SET search_path is session-local and
        # doesn't need a commit, but we commit here so both statements land.
        if _PYTEST_SCHEMA:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{_PYTEST_SCHEMA}"'))
            connection.execute(text(f'SET search_path TO "{_PYTEST_SCHEMA}", public'))
            connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
