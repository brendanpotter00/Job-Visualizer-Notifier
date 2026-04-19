"""Alembic environment — wires DATABASE_URL + SCRAPER_ENVIRONMENT to Alembic.

Reads both via src.backend.api.config.Settings so the app and Alembic share
one config surface. Uses version_table=alembic_version_{env} so local/qa/prod
tracking rows never collide in a shared database.

compare_type and compare_server_default are enabled so the Unit 3 parity test
(and all future autogenerate runs) catch column type and default drift.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the repo root is on sys.path so `src.backend.api.*` imports resolve
# when Alembic is invoked from any cwd (Railway container, operator laptop).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# Also add src/backend so `from api.db_models import Base` works when invoked
# with cwd=src/backend (the documented operator workflow).
_BACKEND_ROOT = _REPO_ROOT / "src" / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from api.config import settings  # noqa: E402  (path prepended above)
from api.db_models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Pull DATABASE_URL and SCRAPER_ENVIRONMENT from the same Settings object the
# app uses. If alembic.ini already set sqlalchemy.url (e.g. from a CLI
# override), honor that; otherwise inject from settings.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url)

_env_suffix = settings.scraper_environment
_version_table = f"alembic_version_{_env_suffix}"

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=_version_table,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=_version_table,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
