"""Runs Alembic migrations in-process during backend startup.

Replaces the old hand-rolled migration runner (`scripts.shared.database.init_schema`).
See `docs/implementations/alembicMigration/PLAN.md` for the migration story and
`docs/incidents/2026-04-18-migration-filled-postgres-volume/` for why each new
schema change MUST be an Alembic autogenerate revision (frozen after the 2026-04-19
production incident).
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

# src/backend/api/migrations.py → parents[3] resolves to the repo/worktree root
# (where alembic.ini lives).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_SCRIPT_LOCATION = _REPO_ROOT / "src" / "backend" / "alembic"


def apply_alembic_migrations(database_url: str, env: str) -> None:
    """Run `alembic upgrade head` against the given database URL.

    `env` is forwarded only for the failure log line — Alembic's env.py reads
    SCRAPER_ENVIRONMENT from the process environment to compute the
    `alembic_version_<env>` table name, so the caller must have already set
    SCRAPER_ENVIRONMENT (which FastAPI's Settings() does via pydantic BaseSettings).
    """
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    # alembic.ini's script_location is relative ("src/backend/alembic"); when
    # called from a cwd other than the repo root (e.g. backend pytest runs from
    # src/backend/, Railway containers from /app), the relative path doesn't
    # resolve. Override with an absolute path computed from this file's location.
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    # alembic.ini contains [loggers]/[handlers]/[formatters] sections; env.py's
    # default `if config.config_file_name is not None: fileConfig(...)` would
    # destructively reset the root logger and disable existing handlers (caplog
    # in tests, and our basicConfig in main.py). When Alembic is invoked
    # in-process, the calling context owns logging — clear the file name so
    # env.py's fileConfig branch is skipped.
    cfg.config_file_name = None
    try:
        command.upgrade(cfg, "head")
    except Exception:
        logger.exception("Failed to apply Alembic migrations (env=%s)", env)
        raise
