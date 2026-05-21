"""Procrastinate App singleton + bootstrap no-op task.

We instantiate ``App`` at import time so every task module
(``fetch_greenhouse_company``, ``enqueue_greenhouse_fan_out``, …) can
``from .procrastinate_app import procrastinate_app`` and register tasks via
``@procrastinate_app.task(...)``. The connector is opened/closed by FastAPI's
lifespan (see ``api.main``), NOT here — importing this module must remain
side-effect-free aside from object construction so Alembic env.py and unit
tests that import ``api.db_models`` etc. don't accidentally open a DB
connection.

The connector uses the same ``DATABASE_URL`` the rest of the app uses. That
single source means Alembic migrations and Procrastinate's own schema land in
the same database — and, in tests, in the same per-worker Postgres schema
(``PYTEST_SCHEMA``).
"""

from __future__ import annotations

import logging

from procrastinate import App, PsycopgConnector

from scripts.shared.database import augment_db_url

from ..config import settings

logger = logging.getLogger(__name__)

# 60s statement timeout matches the */30 cron cadence — any single
# Procrastinate-internal query past 60s is broken. Per-task SQL on Workday
# pagination is bounded by the per-task `asyncio.wait_for(_TASK_TIMEOUT_S)`
# wrapper (see `_TASK_TIMEOUT_S` in `tasks/fetch_*_company.py`), not this GUC.
_WORKER_STATEMENT_TIMEOUT_MS = 60_000

# Single source of truth for the worker app. Other task modules attach
# themselves to this instance.
procrastinate_app: App = App(
    connector=PsycopgConnector(
        conninfo=augment_db_url(
            settings.database_url,
            application_name="procrastinate_worker",
            statement_timeout_ms=_WORKER_STATEMENT_TIMEOUT_MS,
        ),
    ),
)


async def ensure_schema_async(app: App) -> None:
    """Idempotently install Procrastinate's schema (procrastinate_jobs, ...).

    Procrastinate 2.x's ``apply_schema_async`` is NOT idempotent on its own —
    the bundled ``schema.sql`` uses ``CREATE TABLE`` and ``CREATE TYPE``
    without ``IF NOT EXISTS``, so running it twice raises ``DuplicateTable``
    or ``DuplicateObject``. We probe for ``procrastinate_jobs`` first and
    only apply the schema when missing. The probe also picks up the active
    ``search_path`` (set by tests via ``PYTEST_SCHEMA``), so in tests this
    correctly returns "missing" for each fresh per-test schema and applies
    the schema there.
    """
    connector = app.connector
    rows = await connector.execute_query_all_async(
        "SELECT to_regclass('procrastinate_jobs') AS exists"
    )
    if rows and rows[0].get("exists") is not None:
        logger.debug("Procrastinate schema already installed; skipping apply_schema_async")
        return
    logger.info("Installing Procrastinate schema")
    await app.schema_manager.apply_schema_async()


# Bootstrap-only no-op task. Used by tests to prove the queue plumbing works
# end-to-end (defer → worker picks up → completes). Real tasks (Units 4–5)
# live in sibling modules.
@procrastinate_app.task(queue="greenhouse_fetch", name="bootstrap_noop")
async def bootstrap_noop(payload: str = "") -> str:
    """Return the payload unchanged. Verifies worker plumbing only."""
    logger.info("bootstrap_noop ran with payload=%r", payload)
    return payload
