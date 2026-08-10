"""Procrastinate task: run ONE-TIME discovery for a non-ATS careers URL — E7 3b.

Enqueued by the add-flow (``routers/user_companies.add_company``) when a pasted
URL resolves to no supported ATS and the ``custom_company_discovery_enabled`` flag
is on. It runs the agentic :func:`api.services.discovery.discover` (local browser
+ one Sonnet call, ≤2 attempts), then:

* **accept** → :func:`custom_companies_service.add_discovered_company` writes the
  four rows (multi-primitive script, ``transport``, real ``oracle_kind``); the
  existing nightly ``fetch_custom_company`` leaf task replays it agent-free, and
* **refuse** → :func:`custom_companies_service.record_discovery_refusal` writes a
  disabled ``health_state='refused'`` row + a ``company_add_attempts`` row, so the
  user sees "we can't reliably track this site" and nothing is ever scraped.

Runs on its OWN queue (``custom_discovery``) so a slow browser/LLM run never
starves the nightly ``custom_ats_fetch`` harvest queue. This module — and ONLY
this module among ``tasks/`` — imports the discovery package (and thus
``anthropic``); ``fetch_custom_company`` never imports it, so the replay path's
import-guard closure stays clean.
"""

from __future__ import annotations

import asyncio
import logging

import psycopg2
from procrastinate import RetryStrategy

from scripts.shared import database as db

from ..config import settings
from ..services import custom_companies_service as ccs
from ..services.discovery import discover
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# Discovery is a live browser + LLM run; give it a generous wall-clock cap.
_TASK_TIMEOUT_S: float = 240.0


@procrastinate_app.task(
    queue="custom_discovery",
    name="discover_custom_company",
    # Discovery spends money; do NOT auto-retry a whole run. One attempt — the
    # ≤2-authoring-attempts budget lives INSIDE discover(). A transient infra
    # failure surfaces as a refusal via the loop, not a Procrastinate retry storm.
    retry=RetryStrategy(max_attempts=1),
)
async def discover_custom_company(
    user_id: str,
    submitted_url: str,
    normalized_url: str,
    display_name: str,
) -> None:
    """Discover ``normalized_url`` and persist the result (accept or refuse)."""
    if not settings.custom_company_discovery_enabled:
        # Defense in depth: the flag is checked at enqueue time too, but never run
        # a paid discovery if the flag was flipped off after the task was queued.
        logger.info(
            "discover_custom_company: flag off; skipping discovery for %s", normalized_url
        )
        return

    try:
        outcome = await asyncio.wait_for(
            discover(normalized_url), timeout=_TASK_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        logger.error("discover_custom_company timed out for %s", normalized_url)
        outcome = None

    conn = await asyncio.to_thread(
        db.get_connection, settings.database_url, application_name="task_discover_custom"
    )
    try:
        if outcome is not None and outcome.ok and outcome.script is not None:
            assert outcome.transport is not None and outcome.oracle_kind is not None
            created = await asyncio.to_thread(
                ccs.add_discovered_company,
                conn,
                user_id=user_id,
                submitted_url=submitted_url,
                normalized_url=normalized_url,
                display_name=display_name,
                script=outcome.script,
                transport=outcome.transport,
                oracle_kind=outcome.oracle_kind,
            )
            logger.info(
                "discover_custom_company: tracking %s as %s (transport=%s oracle=%s)",
                normalized_url, created["id"], outcome.transport, outcome.oracle_kind,
            )
        else:
            reason = (
                outcome.refuse_reason if outcome is not None else "discovery timed out"
            ) or "discovery could not read this site"
            company_id = await asyncio.to_thread(
                ccs.record_discovery_refusal,
                conn,
                user_id=user_id,
                submitted_url=submitted_url,
                normalized_url=normalized_url,
                display_name=display_name,
                reason=reason[:2000],
            )
            logger.info(
                "discover_custom_company: REFUSED %s (company %s): %s",
                normalized_url, company_id, reason,
            )
    except (psycopg2.Error, RuntimeError):
        logger.exception(
            "discover_custom_company: failed to persist outcome for %s", normalized_url
        )
        raise
    finally:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing discovery task connection (potential leak)", exc_info=True
            )
