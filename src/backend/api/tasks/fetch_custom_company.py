"""Procrastinate task: harvest ONE custom (user-added, private) company — E7.

Per-company unit of work for the ``custom_ats_fetch`` claim task. It runs the
stored script (Phase 1: a one-primitive ``ats_client`` script — the existing ATS
client IS script primitive #1), runs the **minimal Phase-1 gate**, and — because
no oracle exists yet — lands the harvest **UNVERIFIED** and upserts ONLY. It
NEVER increments misses and NEVER closes a job. That is the load-bearing safety
property of Phase 1, not a gap: *a job is never closed by a run that could not
prove it saw the whole board*, and in Phase 1 no run can prove that.

Cloned from ``fetch_greenhouse_company`` — same connection model, same
``finally``-writes-a-scrape-run bookkeeping, same narrow ``except`` tuple. The
divergence is the destructive tail: it is replaced by the verify-gate, which in
Phase 1 always skips closing.

Concurrency model
-----------------
The task is async; helpers in :mod:`scripts.shared.database` are sync psycopg2.
We acquire a fresh sync connection per task (separate from the FastAPI request
pool) and call helpers via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Set

import httpx
import psycopg2
from procrastinate import RetryStrategy
from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db
from scripts.shared.constants import custom
from scripts.shared.incremental import GuardReason, resolve_safety_guard
from scripts.shared.models import JobListing, ScrapeRun
from scripts.shared.utils import get_iso_timestamp

from ..config import settings
from ..services import (
    ashby_client,
    eightfold_client,
    gem_client,
    greenhouse_client,
    lever_client,
    workday_client,
)
from ..services import custom_companies_service as ccs
from ..services.harvest_verification import (
    FAILED,
    UNVERIFIED,
    HarvestGateError,
    run_minimal_gate,
    verify_harvest,
)
from .normalize_location import normalize_location
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# Per-task wall-clock cap (matches the six ATS leaf tasks). Hitting this raises
# asyncio.TimeoutError → Procrastinate retries. Tests monkeypatch it low.
_TASK_TIMEOUT_S: float = 120.0

# ``details`` JSONB hard cap (§2.2). A large job body (Greenhouse ``content``
# HTML) can blow past this; TOAST/OOM incidents are why it is capped, not
# truncated silently. The read path only needs department + the two denormalized
# sub-fields, so an over-cap body is dropped and flagged.
_DETAILS_MAX_BYTES = 8 * 1024


def _cap_details(details: dict[str, Any]) -> dict[str, Any]:
    """Hard-cap the serialized ``details`` at 8 KB, deterministically.

    First drops the big free-text body (``content``); if still over cap, keeps
    only the structured essentials the read path uses. Always flags a
    ``_details_truncated`` marker so the loss is visible, never silent.
    """
    if len(json.dumps(details).encode("utf-8")) <= _DETAILS_MAX_BYTES:
        return details
    trimmed = {k: v for k, v in details.items() if k != "content"}
    trimmed["content"] = None
    trimmed["_details_truncated"] = True
    if len(json.dumps(trimmed).encode("utf-8")) <= _DETAILS_MAX_BYTES:
        return trimmed
    return {
        "department": details.get("department"),
        "experience_level": details.get("experience_level"),
        "is_remote_eligible": details.get("is_remote_eligible", False),
        "content": None,
        "_details_truncated": True,
    }


def _validated_posted_on(posted_on: str | None, now: datetime) -> str | None:
    """``posted_on`` only if it parses AND lands in [now-365d, now+7d], else None.

    Never synthesize a date. The vendor transformer already normalized to UTC
    ISO; this is the extra sanity window from §2.2 — a posting dated years ago or
    in the future is data corruption and is stored as NULL rather than skewing
    the trend graph.
    """
    if not posted_on:
        return None
    try:
        dt = datetime.fromisoformat(posted_on)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if not (now - timedelta(days=365) <= dt <= now + timedelta(days=7)):
        return None
    return dt.astimezone(timezone.utc).isoformat()


async def _fetch_and_transform(
    provider: str,
    board_token: str,
    provider_config: dict[str, Any],
    company_id: str,
    http: httpx.AsyncClient,
) -> list[JobListing]:
    """Run script primitive #1 — the existing ATS client for ``provider``.

    Dispatches to the same clients the public fan-outs use, so a custom company
    is harvested by identical, already-tested code. References the client
    MODULES (not ``from x import fetch_jobs``) so a test can monkeypatch one
    client's ``fetch_jobs`` and drive this task with controlled rows.
    """
    if provider == "greenhouse":
        raw = await greenhouse_client.fetch_jobs(board_token, http)
        return greenhouse_client.transform_to_job_listings(company_id, raw)
    if provider == "ashby":
        raw = await ashby_client.fetch_jobs(board_token, http)
        return ashby_client.transform_to_job_listings(company_id, raw)
    if provider == "lever":
        raw = await lever_client.fetch_jobs(board_token, http)
        return lever_client.transform_to_job_listings(company_id, raw)
    if provider == "gem":
        raw = await gem_client.fetch_jobs(board_token, http)
        return gem_client.transform_to_job_listings(company_id, raw)
    if provider == "workday":
        workday_client._validate_provider_config(provider_config)
        raw = await workday_client.fetch_jobs(provider_config, http)
        return workday_client.transform_to_job_listings(company_id, raw, provider_config)
    if provider == "eightfold":
        tenant_host = provider_config.get("tenant_host", "")
        domain = provider_config.get("domain", "")
        if not tenant_host or not domain:
            raise ValueError("eightfold provider_config missing tenant_host/domain")
        raw = await eightfold_client.fetch_jobs(tenant_host, domain, http)
        return eightfold_client.transform_to_job_listings(company_id, raw)
    raise ValueError(f"unsupported custom-company provider {provider!r}")


def _remap_for_custom(
    jobs: list[JobListing], company_id: str, source_id: str, now: datetime
) -> list[JobListing]:
    """Re-scope vendor rows to this custom company's namespace (§2.2).

    ``source_id=custom:<id>`` and ``company=<id>`` so the DATABASE enforces
    cross-company isolation; ``details`` capped at 8 KB; ``posted_on`` window-
    validated; the upstream ``id`` kept verbatim (ATS ids are stable).
    Enrichment/normalization stay NULL — those columns are simply not written by
    the upsert path in Phase 1.
    """
    return [
        job.model_copy(
            update={
                "source_id": source_id,
                "company": company_id,
                "posted_on": _validated_posted_on(job.posted_on, now),
                "details": _cap_details(job.details),
            }
        )
        for job in jobs
    ]


@procrastinate_app.task(
    queue="custom_ats_fetch",
    name="fetch_custom_company",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def fetch_custom_company(company_id: str) -> None:
    """Harvest one custom company: run the script, gate it, upsert (never close).

    Procrastinate retries on any unhandled exception per RetryStrategy. The
    transport/parse/gate failure paths convert to a recorded FAILED run and
    re-raise (so Procrastinate retries); a FAILED run writes NOTHING to
    job_listings and is explicitly NOT a miss.
    """
    run_id = str(uuid.uuid4())
    started_at = get_iso_timestamp()
    source_id = custom(company_id)
    jobs_seen = 0
    new_jobs_count = 0
    error_count = 0
    guard_reason: GuardReason | None = None
    verdict = FAILED
    verdict_reason: str | None = "not_run"
    records_harvested = 0
    id_dedup_dropped = 0
    new_ids: Set[str] = set()
    scrape_error: BaseException | None = None

    conn = await asyncio.to_thread(
        db.get_connection,
        settings.database_url,
        application_name="task_fetch_custom",
        statement_timeout_ms=60_000,
    )
    try:
        try:
            async def _work() -> None:
                nonlocal jobs_seen, new_jobs_count, error_count, guard_reason
                nonlocal verdict, verdict_reason, records_harvested, id_dedup_dropped
                nonlocal new_ids

                company = await asyncio.to_thread(
                    ccs.load_custom_company_for_run, conn, company_id
                )
                if company is None:
                    # No company / no script — nothing to do. Leave the run
                    # FAILED-but-empty so it is visible, without retrying forever.
                    verdict_reason = "company_or_script_missing"
                    logger.warning(
                        "fetch_custom_company: no company/script for %s", company_id
                    )
                    return
                if not company["enabled"]:
                    verdict_reason = "company_disabled"
                    logger.info("fetch_custom_company: %s is disabled; skipping", company_id)
                    return

                script = company["script"]
                provider = str(script.get("provider") or company["ats"])
                board_token = str(script.get("token") or company["board_token"])
                provider_config = dict(company["provider_config"] or {})

                async with httpx.AsyncClient() as http:
                    raw_jobs = await _fetch_and_transform(
                        provider, board_token, provider_config, company_id, http
                    )
                jobs = _remap_for_custom(
                    raw_jobs, company_id, source_id, datetime.now(timezone.utc)
                )

                # ===== Minimal Phase-1 gate (checks 1, 2, 7-dedup, 8) =====
                # Raises HarvestGateError on empty/short/dup — a FAILED run.
                gate = run_minimal_gate(jobs)
                jobs = gate.jobs
                jobs_seen = gate.records_harvested
                records_harvested = gate.records_harvested
                id_dedup_dropped = gate.id_dedup_dropped

                # ===== Verdict: oracle_kind='none' ⇒ UNVERIFIED, always =====
                decision = verify_harvest(company, gate, baseline=None)
                verdict = decision.verdict
                verdict_reason = decision.reason

                active_count = await asyncio.to_thread(
                    db.count_active_jobs, conn, source_id, company_id
                )
                # The completeness verdict is ANDed with the existing safety
                # guard (never a replacement). In Phase 1 the destructive path is
                # unreachable (verdict is always UNVERIFIED), so the guard only
                # decides which reason is recorded on the run.
                guard = await asyncio.to_thread(
                    resolve_safety_guard, conn, company_id, jobs_seen, active_count
                )

                timestamp = get_iso_timestamp()
                seen_ids: Set[str] = {j.id for j in jobs}

                pre_upsert_active = await asyncio.to_thread(
                    db.get_active_job_ids, conn, source_id, company_id
                )

                # =================================================================
                # Per-step auto-commit + retry idempotency (load-bearing comment).
                #
                # Each helper below opens its own transaction and commits internally.
                # That means a mid-task failure (worker crash, Procrastinate kill, etc.)
                # can leave the DB in a partially-applied state, and the @retry will
                # re-run the WHOLE handler from the top. The order below is what makes
                # that safe:
                #
                #   1. upsert_jobs_batch       -- INSERT ... ON CONFLICT DO UPDATE.
                #                                 Idempotent: re-running with the same
                #                                 input produces the same row state.
                #   2. update_last_seen        -- Sets last_seen_at AND resets
                #                                 consecutive_misses=0 for any id we
                #                                 saw in *this* run. So spurious
                #                                 increments from a prior partial run
                #                                 get wiped clean for any job that's
                #                                 still on the board.
                #   3. increment_consecutive_misses -- Only run for ids that were
                #                                 active before this fetch and NOT in
                #                                 today's seen_ids. If a previous
                #                                 retry already incremented them and
                #                                 the job is *still* missing on this
                #                                 retry, the increment is correct
                #                                 (the job missed both runs). If the
                #                                 job came back, step 2 reset the
                #                                 counter to 0.
                #   4. mark_jobs_closed        -- Idempotent (status='CLOSED' is a
                #                                 terminal write). Closing twice has
                #                                 no extra effect.
                #
                # Net: any partial failure that's later retried converges to the
                # right state. Do NOT reorder these without re-doing the analysis.
                # =================================================================
                #
                # PHASE 1 DIVERGENCE (E7): the verdict is UNVERIFIED (no oracle
                # exists yet), so ONLY steps 1-2 run. Steps 3-4 — the destructive
                # miss-increment and close — are deliberately NOT executed: an
                # UNVERIFIED run may never close a job. The verbatim ordering above
                # is retained because Phase 2 wires steps 3-4 back on for VERIFIED
                # runs and the order is what makes that close path safe.

                if jobs:
                    await asyncio.to_thread(db.upsert_jobs_batch, conn, jobs)

                if seen_ids:
                    await asyncio.to_thread(
                        db.update_last_seen, conn, source_id, list(seen_ids), timestamp
                    )

                new_ids = seen_ids - pre_upsert_active
                new_jobs_count = len(new_ids)

                # UNVERIFIED never closes. guard_reason records WHY the destructive
                # phase was skipped: the safety guard's own reason wins if it
                # tripped (§4 precedence), otherwise 'unverified_harvest'.
                guard_reason = (
                    guard.reason if guard.reason is not None else "unverified_harvest"
                )

                logger.info(
                    "fetch_custom_company %s: verdict=%s seen=%d new=%d closed=0 "
                    "(guard_reason=%s)",
                    company_id, verdict, jobs_seen, new_jobs_count, guard_reason,
                )

            await asyncio.wait_for(_work(), timeout=_TASK_TIMEOUT_S)

            # Defer normalize_location for new ids, AFTER wait_for (so it isn't
            # charged against the timeout) and only for a run that upserted.
            normalize_deferred = 0
            for job_id in new_ids:
                try:
                    await normalize_location.configure(
                        queueing_lock=f"normalize:{job_id}",
                    ).defer_async(job_id=job_id)
                    normalize_deferred += 1
                except procrastinate_exceptions.AlreadyEnqueued:
                    logger.debug(
                        "normalize_location already enqueued for job %s; skipping",
                        job_id,
                    )
                except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
                    logger.exception(
                        "Failed to defer normalize_location for job %s; continuing",
                        job_id,
                    )
            if new_ids:
                logger.info(
                    "%s: deferred normalize_location for %d/%d new job(s)",
                    company_id, normalize_deferred, len(new_ids),
                )
        except asyncio.TimeoutError as e:
            logger.error(
                "fetch_custom_company exceeded %ss for %s — Procrastinate will retry",
                _TASK_TIMEOUT_S, company_id,
            )
            error_count = 1
            verdict = FAILED
            verdict_reason = "timeout"
            scrape_error = e
        except (HarvestGateError, httpx.HTTPError, ValueError, psycopg2.Error) as e:
            # Narrow on purpose (mirrors the ATS tasks): programmer errors
            # propagate immediately; expected failure modes (a gate check, HTTP
            # transport, malformed payload, DB error) convert to a recorded
            # FAILED run. A FAILED run wrote nothing destructive and is NOT a miss.
            logger.error(
                "fetch_custom_company failed for %s: %s", company_id, e, exc_info=True,
            )
            error_count = 1
            verdict = FAILED
            verdict_reason = str(e) or type(e).__name__
            scrape_error = e
    finally:
        completed_at = get_iso_timestamp()
        success = scrape_error is None and verdict == UNVERIFIED

        # On a SUCCESSFUL (non-FAILED, actually-executed) harvest, stamp
        # companies.last_success_at = now() — same condition as
        # scrape_runs.success below. Without this the "last checked" UI reads
        # "Not yet checked" forever, because in Phase 1 every run is UNVERIFIED
        # and nothing else moves last_success_at. health_state / tracking_started_at
        # are intentionally untouched here (see mark_last_success). A FAILED run
        # (success=False) never updates it. A write failure here must not mask the
        # run bookkeeping below, so it is logged and swallowed.
        if success:
            try:
                await asyncio.to_thread(ccs.mark_last_success, conn, company_id)
            except Exception:
                logger.exception(
                    "Failed to update last_success_at for %s", company_id
                )

        # Per-run evidence — written for every run (UNVERIFIED or FAILED) so a
        # wrong match / silent failure is diagnosable weeks later.
        try:
            await asyncio.to_thread(
                ccs.record_company_harvest,
                conn,
                company_id=company_id,
                run_id=run_id,
                started_at=started_at,
                completed_at=completed_at,
                verdict=verdict,
                verdict_reason=verdict_reason,
                records_harvested=records_harvested,
                oracle_kind="none",
                id_dedup_dropped=id_dedup_dropped,
            )
        except Exception:
            logger.exception("Failed to record company_harvest for %s", run_id)

        run_record = ScrapeRun(
            run_id=run_id,
            company=company_id,
            started_at=started_at,
            completed_at=completed_at,
            mode="full",
            jobs_seen=jobs_seen,
            new_jobs=new_jobs_count,
            closed_jobs=0,  # Phase 1 never closes.
            details_fetched=0,
            error_count=error_count,
            skipped_update=False,
            guard_reason=guard_reason,
            source_id=source_id,
            success=success,
        )
        try:
            await asyncio.to_thread(db.record_scrape_run, conn, run_record)
        except Exception:
            logger.exception(
                "Failed to record scrape run %s on primary connection; "
                "retrying on fresh connection", run_id,
            )
            try:
                fallback_conn = await asyncio.to_thread(
                    db.get_connection,
                    settings.database_url,
                    application_name="task_fetch_custom_fallback",
                    statement_timeout_ms=60_000,
                )
                try:
                    await asyncio.to_thread(db.record_scrape_run, fallback_conn, run_record)
                finally:
                    try:
                        await asyncio.to_thread(fallback_conn.close)
                    except Exception:
                        logger.error(
                            "Fallback record_scrape_run connection close failed "
                            "for %s (potential connection leak)", run_id, exc_info=True,
                        )
            except Exception:
                logger.exception("Fallback record_scrape_run also failed for %s", run_id)

        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing task connection (potential connection leak)",
                exc_info=True,
            )

    if scrape_error is not None:
        raise scrape_error
