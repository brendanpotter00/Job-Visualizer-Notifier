"""Runs Alembic migrations in-process during backend startup.

Replaces the old hand-rolled migration runner that lived in `scripts/shared/migrations/`
(deleted in the Alembic migration PR).
See `docs/implementations/alembicMigration/PLAN.md` for the migration story and
`docs/incidents/2026-04-18-migration-filled-postgres-volume/` for why each new
schema change MUST be an Alembic autogenerate revision (frozen after the 2026-04-19
production incident).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

# Path resolution has three modes:
#   1. ALEMBIC_INI_PATH / ALEMBIC_SCRIPT_LOCATION env vars (explicit override).
#   2. Dev layout: migrations.py lives at src/backend/api/migrations.py;
#      parents[3] is the repo root, which holds alembic.ini and src/backend/alembic.
#   3. Docker layout: migrations.py lives at /app/api/migrations.py; the Dockerfile
#      COPYs alembic.ini and alembic/ into /app, so parents[1] is the alembic root.
_HERE = Path(__file__).resolve()


def _resolve_alembic_paths() -> tuple[Path, Path]:
    ini_override = os.environ.get("ALEMBIC_INI_PATH")
    script_override = os.environ.get("ALEMBIC_SCRIPT_LOCATION")
    if ini_override and script_override:
        return Path(ini_override), Path(script_override)

    dev_root = _HERE.parents[3] if len(_HERE.parents) > 3 else None
    if dev_root is not None:
        dev_ini = dev_root / "alembic.ini"
        dev_scripts = dev_root / "src" / "backend" / "alembic"
        if dev_ini.exists() and dev_scripts.is_dir():
            return dev_ini, dev_scripts

    # Docker layout: migrations.py is /app/api/migrations.py; /app holds
    # alembic.ini and alembic/ thanks to Dockerfile COPYs.
    docker_root = _HERE.parents[1]
    docker_ini = docker_root / "alembic.ini"
    docker_scripts = docker_root / "alembic"
    if docker_ini.exists() and docker_scripts.is_dir():
        return docker_ini, docker_scripts

    raise FileNotFoundError(
        f"Could not locate alembic.ini / alembic script directory. "
        f"Searched: {dev_root / 'alembic.ini' if dev_root else '(no dev root)'}, "
        f"{docker_ini}. Set ALEMBIC_INI_PATH and ALEMBIC_SCRIPT_LOCATION to override."
    )


_ALEMBIC_INI, _SCRIPT_LOCATION = _resolve_alembic_paths()


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
