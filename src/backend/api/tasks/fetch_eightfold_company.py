"""Procrastinate task: fetch a single Eightfold company's job board.

Per-company unit of work for the eightfold fan-out cron (see Unit 5).
Fetches the live Eightfold Job Board API for one company, upserts rows
into ``job_listings``, advances the consecutive-misses lifecycle, marks
jobs CLOSED once misses exceed ``MISSED_RUN_THRESHOLD``, and records a
single ``scrape_runs`` row.

Structurally identical to ``fetch_ashby_company.py`` (and so to
``fetch_greenhouse_company.py``); the only Eightfold-specific behavior
is the per-task early validation of ``provider_config``:

1. ``tenant_host`` and ``domain`` must be present and non-empty.
2. ``tenant_host`` must be on the SSRF allowlist
   (``_is_allowed_eightfold_host``).

These three checks are the **third layer of the SSRF defense**:

  L1 (build-time)   — the seed migration ships a known-good tenant_host
  L2 (queue-time)   — the fan-out task re-validates before deferring
  L3 (task-entry)   — this task re-validates one more time, so a
                      hand-crafted defer (operator or buggy admin
                      endpoint) can't bypass L2

A failure at L3 raises ``ValueError`` immediately (no HTTP, no DB writes,
no scrape_run row), Procrastinate records the failure and the next retry
will hit the same failure (deterministic, not transient) — the retry
count then exhausts and operations gets a clear failure signal.

Concurrency model and safety guard follow the Ashby task verbatim — see
that file's docstring for details.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Set

import httpx
import psycopg2
from procrastinate import RetryStrategy

from scripts.shared import database as db
from scripts.shared.incremental import (
    MISSED_RUN_THRESHOLD,
    SAFETY_GUARD_RATIO,
)
from scripts.shared.models import ScrapeRun
from scripts.shared.utils import get_iso_timestamp

from ..config import settings
from ..services.eightfold_client import (
    SOURCE_ID,
    _is_allowed_eightfold_host,
    fetch_jobs,
    transform_to_job_listings,
)
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)


def _validate_provider_config(
    company_id: str, provider_config: Any
) -> tuple[str, str]:
    """Return ``(tenant_host, domain)`` after L3 validation.

    Raises ``ValueError`` if anything is wrong. Called at task entry; the
    early raise means we don't burn HTTP or DB cycles on a broken row.
    """
    if not isinstance(provider_config, dict):
        raise ValueError(
            f"fetch_eightfold_company({company_id!r}): provider_config must "
            f"be a dict, got {type(provider_config).__name__}"
        )
    tenant_host = provider_config.get("tenant_host")
    domain = provider_config.get("domain")
    if not tenant_host or not isinstance(tenant_host, str):
        raise ValueError(
            f"fetch_eightfold_company({company_id!r}): missing/non-string "
            f"tenant_host in provider_config"
        )
    if not domain or not isinstance(domain, str):
        raise ValueError(
            f"fetch_eightfold_company({company_id!r}): missing/non-string "
            f"domain in provider_config"
        )
    if not _is_allowed_eightfold_host(tenant_host):
        # Match the wording of the eightfold_client's ValueError so log
        # consumers can grep one phrase.
        raise ValueError(
            f"fetch_eightfold_company({company_id!r}): tenant_host "
            f"{tenant_host!r} is not on the SSRF allowlist"
        )
    return tenant_host, domain


# Per-task wall-clock cap. Slowest observed prod task is Workday ~43s; 120s
# leaves ~3x headroom. Hitting this raises asyncio.TimeoutError → Procrastinate
# retries via RetryStrategy. Tests monkeypatch this to a low value to
# exercise the timeout path without sleeping for two minutes.
_TASK_TIMEOUT_S: float = 120.0


@procrastinate_app.task(
    queue="eightfold_fetch",
    name="fetch_eightfold_company",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def fetch_eightfold_company(
    company_id: str,
    board_token: str,
    provider_config: dict,
) -> None:
    """Fetch one Eightfold company, upsert jobs, advance lifecycle.

    ``board_token`` is accepted for parity with the other ATS tasks
    (Greenhouse, Ashby) and is currently equal to ``company_id`` in the
    seed migration. It is not used in the HTTP call (Eightfold uses
    ``tenant_host`` / ``domain`` from ``provider_config`` for that) but
    kept in the signature so the queue payload shape is uniform.
    """
    # L3 SSRF validation — before any HTTP or DB work.
    tenant_host, domain = _validate_provider_config(company_id, provider_config)

    run_id = str(uuid.uuid4())
    started_at = get_iso_timestamp()
    jobs_seen = 0
    new_jobs_count = 0
    closed_jobs_count = 0
    error_count = 0
    scrape_error: BaseException | None = None

    # Acquire a sync psycopg2 connection in a thread. libpq connect_timeout=10
    # (set by augment_db_url) bounds the handshake; no shield — task-level
    # cancellation (Procrastinate shutdown / SIGTERM) must propagate so the
    # worker slot frees cleanly. The wait_for below wraps `_work()` only;
    # this acquire runs to completion first.
    conn = await asyncio.to_thread(
        db.get_connection,
        settings.database_url,
        application_name="task_fetch_eightfold",
        statement_timeout_ms=60_000,
    )
    try:
        try:
            async def _work() -> None:
                nonlocal jobs_seen, new_jobs_count, closed_jobs_count, error_count
                async with httpx.AsyncClient() as http:
                    raw_jobs = await fetch_jobs(tenant_host, domain, http)
                jobs = transform_to_job_listings(company_id, raw_jobs)
                jobs_seen = len(jobs)

                active_count = await asyncio.to_thread(
                    db.count_active_jobs, conn, SOURCE_ID, company_id
                )

                if active_count > 0 and jobs_seen < SAFETY_GUARD_RATIO * active_count:
                    # ERROR routes to stderr → Railway @level:error queries.
                    logger.error(
                        "SAFETY GUARD for %s: returned %d jobs but %d active in "
                        "DB (threshold %.0f%% = %.0f). Skipping update/close phases.",
                        company_id, jobs_seen, active_count,
                        SAFETY_GUARD_RATIO * 100, SAFETY_GUARD_RATIO * active_count,
                    )
                    error_count = 1
                    return

                timestamp = get_iso_timestamp()
                seen_ids: Set[str] = {j.id for j in jobs}

                pre_upsert_active = await asyncio.to_thread(
                    db.get_active_job_ids, conn, SOURCE_ID, company_id
                )

                # Per-step auto-commit + retry idempotency: the order below is
                # what makes a partially-applied state converge on retry. See
                # the long comment in fetch_ashby_company.py for the full
                # analysis.
                if jobs:
                    await asyncio.to_thread(db.upsert_jobs_batch, conn, jobs)

                if seen_ids:
                    await asyncio.to_thread(
                        db.update_last_seen, conn, SOURCE_ID, list(seen_ids), timestamp,
                    )

                new_jobs_count = len(seen_ids - pre_upsert_active)

                post_upsert_active = await asyncio.to_thread(
                    db.get_active_job_ids, conn, SOURCE_ID, company_id
                )
                missing_ids = post_upsert_active - seen_ids

                if missing_ids:
                    await asyncio.to_thread(
                        db.increment_consecutive_misses, conn, SOURCE_ID, list(missing_ids),
                    )
                    to_close = await asyncio.to_thread(
                        db.get_jobs_exceeding_miss_threshold,
                        conn,
                        SOURCE_ID,
                        list(missing_ids),
                        MISSED_RUN_THRESHOLD,
                    )
                    if to_close:
                        await asyncio.to_thread(
                            db.mark_jobs_closed, conn, SOURCE_ID, list(to_close), timestamp,
                        )
                        closed_jobs_count = len(to_close)

                logger.info(
                    "fetch_eightfold_company %s: seen=%d new=%d closed=%d",
                    company_id, jobs_seen, new_jobs_count, closed_jobs_count,
                )
            await asyncio.wait_for(_work(), timeout=_TASK_TIMEOUT_S)
        except asyncio.TimeoutError as e:
            logger.error(
                "fetch_eightfold_company exceeded %ss for %s — Procrastinate will retry",
                _TASK_TIMEOUT_S,
                company_id,
            )
            error_count = 1
            scrape_error = e
        except (httpx.HTTPError, ValueError, psycopg2.Error) as e:
            # Narrow: programmer errors (Attribute/Type/NameError) propagate
            # so Procrastinate marks the task failed immediately rather than
            # burning all 5 retries on a deterministic bug. Mirrors
            # fetch_ashby_company.
            logger.error(
                "fetch_eightfold_company failed for %s: %s",
                company_id, e, exc_info=True,
            )
            error_count = 1
            scrape_error = e
    finally:
        run_record = ScrapeRun(
            run_id=run_id,
            company=company_id,
            started_at=started_at,
            completed_at=get_iso_timestamp(),
            mode="full",
            jobs_seen=jobs_seen,
            new_jobs=new_jobs_count,
            closed_jobs=closed_jobs_count,
            details_fetched=0,
            error_count=error_count,
        )
        try:
            await asyncio.to_thread(db.record_scrape_run, conn, run_record)
        except Exception:
            logger.exception(
                "Failed to record scrape run %s on primary connection; "
                "retrying on fresh connection",
                run_id,
            )
            try:
                fallback_conn = await asyncio.to_thread(
                    db.get_connection,
                    settings.database_url,
                    application_name="task_fetch_eightfold_fallback",
                    statement_timeout_ms=60_000,
                )
                try:
                    await asyncio.to_thread(
                        db.record_scrape_run, fallback_conn, run_record,
                    )
                finally:
                    try:
                        await asyncio.to_thread(fallback_conn.close)
                    except Exception:
                        logger.error(
                            "Fallback record_scrape_run connection close "
                            "failed for %s (potential connection leak)",
                            run_id,
                            exc_info=True,
                        )
            except Exception:
                logger.exception(
                    "Fallback record_scrape_run also failed for %s",
                    run_id,
                )

        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing task connection (potential connection leak)",
                exc_info=True,
            )

    if scrape_error is not None:
        raise scrape_error
