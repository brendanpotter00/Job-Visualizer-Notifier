"""Procrastinate task: run ONE-TIME capture discovery for a non-ATS careers URL — E7.

Enqueued by the add-flow (``routers/user_companies.add_company``) when a pasted URL
resolves to no supported ATS and the ``custom_company_discovery_enabled`` flag is on.
It runs :func:`api.services.capture.discover` — open the page in ONE browser session,
record its network traffic, ONE Claude Haiku call to pick + map the jobs request,
synthesize a deterministic recipe, and prove it replays from our production path — then:

* **accept** → :func:`custom_companies_service.add_discovered_company` flips the
  provisional ``health_state='discovering'`` row to tracked and writes the recipe with
  ``transport='http_json'`` (replays for $0) or ``transport='browser_fetch'`` (replays
  in our own Chromium); the FIRST ``fetch_custom_company`` is then enqueued immediately
  (:func:`claim_custom_companies.start_first_harvest`, the same helper the ATS add path
  calls) and the nightly claim tick takes over from there — all
  replays deterministic, no LLM at runtime, ever — and
* **refuse** → :func:`custom_companies_service.record_discovery_refusal` flips that row
  to a disabled ``health_state='refused'`` + a ``company_add_attempts`` row carrying the
  NAMED STEP that failed ("verifying we can read it: …"), so the user sees why we can't
  track this site and nothing is ever scraped.

A board with no capturable API is refused by design (the deterministic-only principle):
there is no DOM/agent tier to fall back to, because such a tier could silently drift and
burn resources daily. That is the whole reason the Stagehand path was retired.

WHY THE FIRST HARVEST IS ENQUEUED HERE and not left to the 15-minute claim tick: the
accept flips the row to tracked with all its discovery steps green, and until a harvest
lands the company genuinely has ZERO jobs. A finished checklist over "0 open jobs" reads
as "we looked and your board is empty", which is the single most confusing thing this
feature did. Enqueuing here collapses that window from up to ~15 minutes to the length
of one harvest. The helper itself lives in ``claim_custom_companies`` beside the two
primitives it composes, because the ATS fast path had the identical bug and must not
grow a second enqueue path to fix it.

Runs on its OWN queue (``custom_discovery``) so a slow browser run never starves the
nightly ``custom_ats_fetch`` harvest queue. The capture drives its Chromium OUT OF
PROCESS (``capture/_capture_main``), so importing this task never makes ``playwright``
resident — the replay path's import-guard closure stays clean.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import psycopg2
from procrastinate import RetryStrategy
from psycopg2.extensions import connection as Connection

from scripts.shared import database as db

from ..config import settings
from ..services import custom_companies_service as ccs
from ..services.capture import DiscoveryOutcome, discover
from .claim_custom_companies import start_first_harvest
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# Discovery is a live browser capture + an LLM call + up to two acceptance replays;
# give it a generous wall-clock cap. It MUST stay above
# ``network_capture._SUBPROCESS_TIMEOUT_S`` (120s) so a capture that overruns is
# reported as a capture timeout rather than killing the whole task.
_TASK_TIMEOUT_S: float = 240.0


def _progress_writer(
    user_id: str, normalized_url: str
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Build the live-checklist callback handed to :func:`discover` as ``emit``.

    EACH WRITE OPENS ITS OWN SHORT-LIVED CONNECTION, deliberately. The persist below
    opens its connection only AFTER the browser run finishes, precisely so no pool
    connection is held across a 240-second paid session — reusing that connection for
    progress would undo the whole point, and holding a second one for the duration
    would be the same mistake twice. Four or five connect/commit/close cycles over a
    four-minute run is nothing next to a held connection.

    NEVER RAISES into the caller: ``discover``'s ``_publish`` also swallows, but a
    connection failure is exactly the case where the narration must not become the
    outcome. A run whose progress writes all fail still tracks or refuses the board
    correctly; the user simply sees the terminal checklist instead of a live one.
    """
    async def _emit(snapshot: dict[str, Any]) -> None:
        def _write() -> None:
            conn: Connection = db.get_connection(
                settings.database_url, application_name="task_discover_progress"
            )
            try:
                ccs.record_discovery_progress(
                    conn,
                    user_id=user_id,
                    normalized_url=normalized_url,
                    progress=snapshot,
                )
            finally:
                conn.close()

        try:
            await asyncio.to_thread(_write)
        except Exception:  # noqa: BLE001
            # Belt and braces with ``discover``'s own ``_publish`` guard: this seam is
            # also reachable from an injected caller, and there is no version of "the
            # progress connection failed" that should decide whether we track a board.
            logger.warning(
                "discovery progress write failed for %s (continuing)",
                normalized_url, exc_info=True,
            )

    return _emit


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
    outcome: DiscoveryOutcome | None = None
    # A refusal reason that PRE-EMPTS the run, set when we decline to start at all. It
    # exists so the flag-off branch below can REFUSE rather than ``return``: see there.
    preempt_reason: str | None = None

    if not settings.custom_company_discovery_enabled:
        # Defence in depth: the router gates on this same single flag at enqueue time,
        # but never open a browser or spend an LLM call if it was flipped off after the
        # task was queued. ONE flag on purpose — the retired two-flag arrangement made
        # "discovery is off" indistinguishable from "this board is unsupported".
        #
        # THIS IS A REFUSAL, NOT A ``return``. The router already inserted the
        # provisional ``health_state='discovering'`` row before deferring this task, so
        # returning here left that row spinning with nothing in flight behind it —
        # ended only by ``reconcile_discovering``'s 30-minute sweep. A half-hour silent
        # spinner is not a definite state, and the sweep's verdict is the one we can
        # reach right now for free: the flag is off, so this run is never happening.
        logger.info(
            "discover_custom_company: custom_company_discovery_enabled off; refusing %s",
            normalized_url,
        )
        preempt_reason = (
            "adding boards outside the supported job platforms is turned off right now"
        )
    else:
        try:
            outcome = await asyncio.wait_for(
                discover(normalized_url, emit=_progress_writer(user_id, normalized_url)),
                timeout=_TASK_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.error("discover_custom_company timed out for %s", normalized_url)
            outcome = None

    # WEDGED-ROW CAVEAT (now reconciled, not merely documented): the provisional
    # companies row created on the 202 add sits at health_state='discovering' until the
    # persist below flips it to tracked or refused. Because this task is retry=1 (it
    # spends money — never retried), a HARD failure between the ``wait_for`` above and
    # the persist below (a SIGKILL / worker OOM, not a caught exception — ``discover``
    # never raises, and a timeout becomes a REFUSE via ``outcome=None``) leaves that row
    # stuck at 'discovering' with nothing left to move it. So does a queue nothing
    # drains. (The flag being flipped off mid-flight USED to belong on that list; it
    # now takes the ordinary refusal path above, because that is a case this task can
    # settle itself and a 30-minute sweep is not "ending cleanly".)
    # :mod:`api.tasks.reconcile_discovering` sweeps the rows that remain
    # onto the ordinary refusal state — see it for how a stalled run is told apart from
    # a slow one, and why it deliberately rides the BULK lane rather than this one.

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
                # The terminal checklist (four ticks + the job preview) lands in the
                # SAME statement that flips the row to tracked, so the two can never
                # disagree and no straggler write can reopen a settled board.
                progress=outcome.progress,
            )
            if created is None:
                # THE USER REMOVED THE BOARD WHILE WE WERE READING IT. The service
                # refuses to re-create a row whose placeholder is gone, so there is
                # nothing to track and — crucially — no first harvest to start: a
                # harvest here would write job_listings under a ``custom:<id>``
                # namespace nobody owns, which is precisely the resurrection this
                # whole path exists to prevent.
                logger.info(
                    "discover_custom_company: %s was removed while discovery ran; "
                    "discarding the accepted recipe", normalized_url,
                )
                return
            logger.info(
                "discover_custom_company: tracking %s as %s (transport=%s oracle=%s)",
                normalized_url, created["id"], outcome.transport, outcome.oracle_kind,
            )
            # The board is tracked and has a proven recipe but ZERO jobs — read it NOW.
            # This is the last thing the accept does, after the row and script are
            # committed, so the harvest the worker picks up can never see a half-written
            # company.
            await start_first_harvest(
                conn, company_id=str(created["id"]), transport=outcome.transport,
            )
        else:
            reason = (
                preempt_reason
                or (
                    outcome.refuse_reason
                    if outcome is not None
                    else "discovery timed out"
                )
            ) or "discovery could not read this site"
            company_id = await asyncio.to_thread(
                ccs.record_discovery_refusal,
                conn,
                user_id=user_id,
                submitted_url=submitted_url,
                normalized_url=normalized_url,
                display_name=display_name,
                reason=reason[:2000],
                # Carries the NAMED STEP that failed onto the refused row. Without it
                # the only record of "which step" is the append-only attempts audit,
                # which no endpoint reads back — so the user would get "Not trackable"
                # and nothing to act on. ``None`` on the TIMEOUT path (there is no
                # outcome to carry a checklist), which LEAVES the last live snapshot in
                # place: "opened the careers page ✓ · finding the jobs feed…" on a
                # refused row is exactly the how-far-did-we-get the user wants.
                progress=outcome.progress if outcome is not None else None,
            )
            if company_id is None:
                logger.info(
                    "discover_custom_company: %s was removed while discovery ran; "
                    "not recording the refusal", normalized_url,
                )
                return
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
