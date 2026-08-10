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
import time
from pathlib import Path

import psycopg2
from alembic import command
from alembic.config import Config
from sqlalchemy import exc as sqlalchemy_exc

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


def apply_alembic_migrations(database_url: str) -> None:
    """Run `alembic upgrade head` against the given database URL."""
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
        logger.exception("Failed to apply Alembic migrations")
        raise


_CONNECTIVITY_RETRY_INTERVAL_S = 15.0


def apply_alembic_migrations_with_retry(
    database_url: str, max_wait_seconds: float
) -> None:
    """Run migrations, retrying DB-connectivity failures up to a time budget.

    Why (2026-08-10 incident): when the db_watchdog exits the process during
    a database outage, Railway ON_FAILURE-restarts the container — which
    lands right back here while the DB is still down. Without a retry, boot
    fails within seconds, and a multi-hour DB outage burns through
    railway.toml's restartPolicyMaxRetries long before the DB returns,
    leaving the service permanently down. With the retry, each restart cycle
    holds on for ``max_wait_seconds`` probing for the DB, and boots cleanly
    the moment it comes back.

    Only connectivity errors retry. Anything else — a broken revision, a
    schema conflict — raises immediately: a bad deploy must fail loudly, not
    sit in a retry loop.
    """
    deadline = time.monotonic() + max_wait_seconds
    while True:
        try:
            apply_alembic_migrations(database_url)
            return
        except (psycopg2.OperationalError, sqlalchemy_exc.OperationalError) as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            logger.warning(
                "Database unreachable during startup migrations (%s); "
                "retrying in %.0fs (%.0fs left in boot retry budget)",
                exc,
                _CONNECTIVITY_RETRY_INTERVAL_S,
                remaining,
            )
            time.sleep(_CONNECTIVITY_RETRY_INTERVAL_S)


def stamp_alembic_head(database_url: str) -> None:
    """Mark `alembic_version` at head without running any upgrade body.

    For test fixtures that bootstrap the schema via `Base.metadata.create_all`:
    the ORM metadata already produces the target schema, so running Alembic
    upgrade on top would re-execute every `op.create_table` and fail with a
    DuplicateTable error. Stamping writes only to the version tracker, leaving
    the already-materialized tables alone.
    """
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    cfg.config_file_name = None
    try:
        command.stamp(cfg, "head")
    except Exception:
        logger.exception("Failed to stamp Alembic head")
        raise
