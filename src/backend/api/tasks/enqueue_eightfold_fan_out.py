"""Procrastinate periodic task: fan out per-company Eightfold fetches.

Fires every 30 minutes via Procrastinate's built-in periodic deferrer.
For each enabled Eightfold company, defers one ``fetch_eightfold_company``
job with a per-company queueing lock.

The fan-out **also** re-validates the ``provider_config`` blob before
deferring (L2 of the SSRF defense — see ``fetch_eightfold_company.py``
docstring for the full L1/L2/L3 layered model). If a row's
``provider_config`` is missing required keys, the row is skipped with an
ERROR log; the loop continues with the next company. This ensures one
malformed row can't poison the whole fan-out tick.

Per-company task locks live on the children, not on this fan-out task —
two concurrent fan-out ticks each enqueue per-company tasks, and
Procrastinate's per-company queueing lock dedupes them. The fan-out
itself does not carry a lock because if two ticks race, the second is a
cheap no-op (each per-company defer is either deduped by lock or by the
periodic-defers unique constraint).
"""

from __future__ import annotations

import asyncio
import logging

import psycopg2
from procrastinate import RetryStrategy
from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db

from ..config import settings
from ..services.eightfold_client import _is_allowed_eightfold_host
from .fetch_eightfold_company import fetch_eightfold_company
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)


def _validate_row_provider_config(company_id: str, cfg: object) -> tuple[str, str] | None:
    """Return ``(tenant_host, domain)`` if the row is valid; ``None`` if not.

    Logs ERROR for any failure mode. Distinct from the task-entry validator
    (in ``fetch_eightfold_company``) because at fan-out time we want to
    isolate per-company failures from the broader tick — one bad row
    must not abort the loop and leave alphabetically-later companies
    unprocessed for 30 min.
    """
    if not isinstance(cfg, dict):
        logger.error(
            "enqueue_eightfold_fan_out: company %s has non-dict "
            "provider_config (%r); skipping",
            company_id, type(cfg).__name__,
        )
        return None
    tenant_host = cfg.get("tenant_host")
    domain = cfg.get("domain")
    if not tenant_host or not isinstance(tenant_host, str):
        logger.error(
            "enqueue_eightfold_fan_out: company %s missing tenant_host in "
            "provider_config; skipping",
            company_id,
        )
        return None
    if not domain or not isinstance(domain, str):
        logger.error(
            "enqueue_eightfold_fan_out: company %s missing domain in "
            "provider_config; skipping",
            company_id,
        )
        return None
    if not _is_allowed_eightfold_host(tenant_host):
        # The seed migration's contract: tenant_host is on the allowlist.
        # If this fires in prod, someone bypassed the seed and inserted a
        # bad row out-of-band — surface as ERROR so it's caught fast.
        logger.error(
            "enqueue_eightfold_fan_out: company %s tenant_host %r is NOT "
            "on the SSRF allowlist; skipping (row was likely inserted "
            "out-of-band of the seed migration)",
            company_id, tenant_host,
        )
        return None
    return tenant_host, domain


@procrastinate_app.periodic(
    cron="*/30 * * * *",
    periodic_id="eightfold_fan_out",
)
@procrastinate_app.task(
    queue="eightfold_fetch",
    name="enqueue_eightfold_fan_out",
    # If db.list_enabled_eightfold_companies fails on a transient blip
    # (Railway network blip, momentary connection refusal), the entire
    # 30-min tick would otherwise be lost. Three exponential-wait attempts
    # cover transient connector failures while bounding the worst case.
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def enqueue_eightfold_fan_out(timestamp: int) -> int:
    """Defer one ``fetch_eightfold_company`` per enabled Eightfold company.

    Returns the count of successful deferrals (some may be silently
    skipped because a prior tick's job is still in the queue with the
    same queueing lock — that is the intended dedupe path).
    """
    conn = await asyncio.to_thread(db.get_connection, settings.database_url)
    try:
        companies = await asyncio.to_thread(
            db.list_enabled_eightfold_companies, conn,
        )
    finally:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing fan-out connection (potential connection leak)",
                exc_info=True,
            )

    if not companies:
        logger.info(
            "enqueue_eightfold_fan_out tick %d: no enabled eightfold companies",
            timestamp,
        )
        return 0

    deferred = 0
    failed = 0
    skipped_bad_config = 0
    for c in companies:
        company_id = c["id"]
        board_token = c["board_token"]
        cfg = c.get("provider_config") or {}

        validated = _validate_row_provider_config(company_id, cfg)
        if validated is None:
            skipped_bad_config += 1
            continue

        try:
            await fetch_eightfold_company.configure(
                queueing_lock=f"eightfold:{company_id}",
            ).defer_async(
                company_id=company_id,
                board_token=board_token,
                provider_config=cfg,
            )
            deferred += 1
        except procrastinate_exceptions.AlreadyEnqueued:
            logger.info(
                "fetch_eightfold_company already enqueued for %s; "
                "skipping this tick",
                company_id,
            )
        except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
            # Per-company isolation: a transient connector blip on company N
            # must NOT abort the loop and leave alphabetically-later
            # companies unprocessed for the entire 30-min window.
            # Narrow on purpose — programmer errors propagate.
            failed += 1
            logger.exception(
                "Failed to defer fetch_eightfold_company for %s; "
                "continuing with remaining companies",
                company_id,
            )

    logger.info(
        "enqueue_eightfold_fan_out tick %d: deferred %d / %d companies "
        "(failed=%d, skipped_bad_config=%d)",
        timestamp, deferred, len(companies), failed, skipped_bad_config,
    )
    return deferred
