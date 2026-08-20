"""Procrastinate task: run ONE-TIME capture discovery for a non-ATS careers URL — E7.

Enqueued by the add-flow (``routers/user_companies.add_company``) when a pasted URL
resolves to no supported ATS and the ``custom_company_discovery_enabled`` flag is on.
It runs :func:`api.services.capture.discover` — open the page in ONE browser session,
record its network traffic, ONE Claude Haiku call to pick + map the jobs request,
synthesize a deterministic recipe, and prove it replays from our production path — then:

* **accept** → :func:`custom_companies_service.add_discovered_company` flips the
  provisional ``health_state='discovering'`` row to tracked and writes the recipe with
  ``transport='http_json'`` (replays for $0) or ``transport='browser_fetch'`` (replays
  in our own Chromium); the existing nightly ``fetch_custom_company`` leaf task replays
  it deterministically — no LLM at runtime, ever — and
* **refuse** → :func:`custom_companies_service.record_discovery_refusal` flips that row
  to a disabled ``health_state='refused'`` + a ``company_add_attempts`` row carrying the
  NAMED STEP that failed ("verifying we can read it: …"), so the user sees why we can't
  track this site and nothing is ever scraped.

A board with no capturable API is refused by design (the deterministic-only principle):
there is no DOM/agent tier to fall back to, because such a tier could silently drift and
burn resources daily. That is the whole reason the Stagehand path was retired.

Runs on its OWN queue (``custom_discovery``) so a slow browser run never starves the
nightly ``custom_ats_fetch`` harvest queue. The capture drives its Chromium OUT OF
PROCESS (``capture/_capture_main``), so importing this task never makes ``playwright``
resident — the replay path's import-guard closure stays clean.
"""

from __future__ import annotations

import asyncio
import logging

import psycopg2
from procrastinate import RetryStrategy

from scripts.shared import database as db

from ..config import settings
from ..services import custom_companies_service as ccs
from ..services.capture import discover
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# Discovery is a live browser capture + an LLM call + up to two acceptance replays;
# give it a generous wall-clock cap. It MUST stay above
# ``network_capture._SUBPROCESS_TIMEOUT_S`` (120s) so a capture that overruns is
# reported as a capture timeout rather than killing the whole task.
_TASK_TIMEOUT_S: float = 240.0


@procrastinate_app.task(
    queue="custom_discovery",
    name="discover_custom_company",
    # Discovery spends money; do NOT auto-retry a whole run. One attempt — the
    # ≤2-candidate-round budget lives INSIDE discover(). A transient infra failure
    # surfaces as a refusal via the ladder, not a Procrastinate retry storm.
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
        # Defence in depth: the router gates on this same single flag at enqueue time,
        # but never open a browser or spend an LLM call if it was flipped off after the
        # task was queued. ONE flag on purpose — the retired two-flag arrangement made
        # "discovery is off" indistinguishable from "this board is unsupported".
        logger.info(
            "discover_custom_company: custom_company_discovery_enabled off; skipping %s",
            normalized_url,
        )
        return

    try:
        outcome = await asyncio.wait_for(
            discover(normalized_url), timeout=_TASK_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        logger.error("discover_custom_company timed out for %s", normalized_url)
        outcome = None

    # WEDGED-ROW CAVEAT: the provisional companies row created on the 202 add sits at
    # health_state='discovering' until the persist below flips it to tracked or refused.
    # Because this task is retry=1 (it spends money — never retried), a HARD failure
    # between the ``wait_for`` above and the persist below (a SIGKILL / worker OOM, not
    # a caught exception — ``discover`` never raises, and a timeout becomes a REFUSE via
    # ``outcome=None``) leaves that row stuck at 'discovering' forever. The user recovers
    # by Removing the row and re-adding. TODO: a server-side reconciler that sweeps
    # 'discovering' rows older than N minutes (and stuck Procrastinate 'doing' jobs) back
    # to a retryable or refused state.

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
