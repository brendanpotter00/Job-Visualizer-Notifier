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
    # Both overrides must be set together. A single one (typo on the other
    # name, half-completed deploy config) previously fell through to dev/docker
    # auto-discovery silently — the operator would see "it worked" and never
    # learn their override was ignored. Raise so the misconfig surfaces loudly.
    if ini_override or script_override:
        missing = "ALEMBIC_SCRIPT_LOCATION" if ini_override else "ALEMBIC_INI_PATH"
        set_var = "ALEMBIC_INI_PATH" if ini_override else "ALEMBIC_SCRIPT_LOCATION"
        raise ValueError(
            f"Partial Alembic path override: {set_var} is set but {missing} is not. "
            f"Both must be set together, or neither (to use layout auto-discovery)."
        )

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
logger.info(
    "Alembic paths resolved: ini=%s script_location=%s",
    _ALEMBIC_INI,
    _SCRIPT_LOCATION,
)


def apply_alembic_migrations(database_url: str, env: str) -> None:
    """Run `alembic upgrade head` against the given database URL.

    The caller MUST ensure `env` matches what Alembic's env.py will compute
    as the version-table suffix. env.py reads `api.config.settings.scraper_environment`,
    which is a pydantic module-level singleton bound at import time from
    SCRAPER_ENVIRONMENT (default "local" if unset). If the caller passes
    env="prod" while settings.scraper_environment is "local" (because
    SCRAPER_ENVIRONMENT was unset), Alembic would silently target
    alembic_version_local against a prod database — invisible at deploy
    time, catastrophic later. Comparing against the settings singleton (not
    os.environ) catches the "unset env var → default local" case that a
    plain env-var check misses.

    Raises RuntimeError on mismatch. Does NOT mutate settings or process env —
    the caller owns those.
    """
    # Import inside the function to avoid a hard dependency on Settings() at
    # module import time (some test paths reload api.config between imports).
    from .config import settings as _settings

    if _settings.scraper_environment != env:
        raise RuntimeError(
            f"scraper_environment mismatch: api.config.settings.scraper_environment="
            f"{_settings.scraper_environment!r} but migration target env={env!r}. "
            f"Alembic env.py would target alembic_version_{_settings.scraper_environment} "
            f"against a DB intended for {env}. Set SCRAPER_ENVIRONMENT={env} (and "
            f"ensure api.config.settings is rebuilt if it was imported earlier) before "
            f"invoking apply_alembic_migrations."
        )

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
