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

# EXPLICIT pool sizing, because the default is a trap once there is more than
# one worker. ``psycopg_pool.AsyncConnectionPool`` defaults to ``min_size=4``
# and ``max_size=None``, and ``_check_size`` turns ``None`` into ``min_size``
# — four connections, total, for the whole app. Each ``run_worker_async``
# instance pins ONE of them permanently for its LISTEN/NOTIFY listener, so the
# two lanes started by ``api.main``'s lifespan (bulk + interactive) would leave
# just two connections to serve every fetch_job/finish_job across 7 concurrent
# job slots. That is a pool-exhaustion hang waiting to happen, and it would
# present as "the worker stopped draining" — indistinguishable, from the
# outside, from the signal-handler bug this sizing was added alongside.
#
# 12 = 2 listeners + 7 job slots (5 bulk + 2 interactive) + 3 slack for the
# periodic deferrers and the API's own defer_async calls.
_CONNECTOR_POOL_MIN_SIZE = 4
_CONNECTOR_POOL_MAX_SIZE = 12

# The add-time FIRST harvest of a just-tracked custom company rides this queue
# instead of ``custom_ats_fetch``. Same task (``fetch_custom_company``), same
# per-company queueing lock — only the queue differs, chosen by the deferrer in
# ``tasks.claim_custom_companies.start_first_harvest``. It lives HERE, not in
# ``api.main`` next to the lane lists, because a task module importing
# ``api.main`` would be circular (main imports the task modules). ``api.main``
# imports it into ``_INTERACTIVE_QUEUES`` so the deferrer and the worker that
# drains it can never drift apart.
CUSTOM_ATS_FIRST_FETCH_QUEUE = "custom_ats_first_fetch"

# Single source of truth for the worker app. Other task modules attach
# themselves to this instance.
procrastinate_app: App = App(
    connector=PsycopgConnector(
        conninfo=augment_db_url(
            settings.database_url,
            application_name="procrastinate_worker",
            statement_timeout_ms=_WORKER_STATEMENT_TIMEOUT_MS,
        ),
        min_size=_CONNECTOR_POOL_MIN_SIZE,
        max_size=_CONNECTOR_POOL_MAX_SIZE,
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
