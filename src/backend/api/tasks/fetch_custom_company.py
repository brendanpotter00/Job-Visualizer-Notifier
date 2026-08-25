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
from ..services import recipe_runner
from ..services.custom_baseline import compute_baseline
from ..services.guarded_client import guarded_sync_client
from ..services.harvest_meta import HarvestEvidence
from ..services.recipe_rows import recipe_rows_to_job_listings
from ..services.harvest_verification import (
    FAILED,
    VERIFIED,
    HarvestGateError,
    effective_oracle_kind,
    run_gate,
    verify_harvest,
)
from .normalize_location import normalize_location
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# A ``self_consistent`` company (no trusted total) may only CLOSE once it has
# demonstrated this many consecutive VERIFIED harvests — the extra caution the
# self-consistency oracle carries over ``declared_probed``. Counted INCLUDING the
# in-flight run (whose harvest row is not written until the finally block).
_SELF_CONSISTENT_STREAK_REQUIRED = 3

# CHURN GUARD (E7). A ``self_consistent`` board publishes no
# trusted total, so if MORE THAN this fraction of its prior-OPEN ids disappear in
# a single run there is nothing to corroborate the drop — it is far more likely a
# churning ``id_field`` (a per-load session token / DOM position that changes every
# night) than a real board that shed half its jobs overnight. On such a run NOTHING
# closes (``guard_reason='id_churn_suspected'``). ``declared_probed`` is EXCLUDED:
# its trusted total already corroborates a genuine drop, so it closes normally.
_ID_CHURN_CLOSE_THRESHOLD = 0.5

# Per-task wall-clock cap. Hitting this raises asyncio.TimeoutError → a recorded FAILED
# run (nothing written, nothing closed, NOT a miss). Tests monkeypatch it low.
#
# WAS 120s, matching the six public ATS leaf tasks, and that number was quietly deciding
# how much of a board we were allowed to see: the stored page budget was capped at 100
# pages purely so a full sweep would fit inside it. Microsoft's board is 10 jobs/page and
# 2,111 jobs — 212 pages, ~55s of requests — so under the old cap it could not even be
# ATTEMPTED, let alone finish. The budget is the thing that should be sized to the board,
# so the timeout is now sized to the budget instead of the other way round:
#
#     600s  recipe_runner.HARVEST_TIME_BUDGET_S — the sweep's own mid-flight clock
#   +  30s  guarded_client._DEFAULT_TIMEOUT_S — the one request that can still be
#           in flight when the sweep's clock runs out (the budget is checked BETWEEN
#           pages, so it is exceeded by at most one request)
#   + 270s  the destructive tail: baseline read, the upsert (up to
#           MAX_HARVEST_RECORDS rows at a 60s statement timeout), the miss increment
#           and the close
#   = 900s
#
# For scale, measured end to end on this machine: amazon.jobs — 100 pages of ~1 MB plus
# a 10,000-row upsert — is 90.1s for the WHOLE task, and Microsoft's 212-page sweep plus
# its 2,107-row upsert is 61.4s. Amazon at 90.1s was already 75% of the old 120s cap,
# which is how thin the headroom had become before any budget moved.
#
# It is safe because it is a BACKSTOP, not a budget: the sweep's own clock stops at 600s,
# so a healthy run never approaches this. What it costs when it does fire is one of the
# worker's five concurrency slots (``main.py``: one in-process Procrastinate worker,
# ``concurrency=5``, shared with the six public ATS fan-outs, discovery, normalize_location
# and the heartbeat) held for 15 minutes instead of 2. That is affordable because the
# harvest runs in ``asyncio.to_thread`` — the API's event loop is never blocked by it —
# and because ``retry=RetryStrategy(max_attempts=1)`` means a wedged board burns the slot
# once a night, not five times. The ordering that IS load-bearing stays intact and gets
# more headroom, not less: ``browser_fetch.runner._SUBPROCESS_TIMEOUT_S`` (90s) must
# remain strictly below this, or a cancelled coroutine leaves a Chromium parked.
_TASK_TIMEOUT_S: float = 900.0

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
) -> tuple[list[JobListing], HarvestEvidence]:
    """Run script primitive #1 — the ATS client for ``provider`` — AND capture
    the completeness evidence the gate needs.

    Dispatches to the same clients the public fan-outs use, so a custom company
    is harvested by identical, already-tested code. The three ATSs that carry a
    trusted total / cap (Greenhouse, Workday, Eightfold) use ``fetch_jobs_with_meta``
    so the gate can read ``declared_total`` / ``cap_hit`` / ``page_advance_ok``;
    the single-shot no-total ATSs (Ashby/Lever/Gem) use plain ``fetch_jobs`` and
    synthesize ``HarvestEvidence.single_shot(None)``. References the client
    MODULES so a test can monkeypatch one client and drive this task.
    """
    if provider == "greenhouse":
        raw, evidence = await greenhouse_client.fetch_jobs_with_meta(board_token, http)
        return greenhouse_client.transform_to_job_listings(company_id, raw), evidence
    if provider == "ashby":
        raw = await ashby_client.fetch_jobs(board_token, http)
        return (
            ashby_client.transform_to_job_listings(company_id, raw),
            HarvestEvidence.single_shot(declared_total=None),
        )
    if provider == "lever":
        raw = await lever_client.fetch_jobs(board_token, http)
        return (
            lever_client.transform_to_job_listings(company_id, raw),
            HarvestEvidence.single_shot(declared_total=None),
        )
    if provider == "gem":
        raw = await gem_client.fetch_jobs(board_token, http)
        return (
            gem_client.transform_to_job_listings(company_id, raw),
            HarvestEvidence.single_shot(declared_total=None),
        )
    if provider == "workday":
        workday_client._validate_provider_config(provider_config)
        raw, evidence = await workday_client.fetch_jobs_with_meta(provider_config, http)
        return (
            workday_client.transform_to_job_listings(company_id, raw, provider_config),
            evidence,
        )
    if provider == "eightfold":
        tenant_host = provider_config.get("tenant_host", "")
        domain = provider_config.get("domain", "")
        if not tenant_host or not domain:
            raise ValueError("eightfold provider_config missing tenant_host/domain")
        # confirm_terminus=True: for the self_consistent completeness proof, a
        # full-page count-break must be confirmed with one extra page (Finding 5)
        # — Eightfold's `count` may under-report. The public cron does NOT set
        # this, so its fetch_jobs stays byte-identical.
        raw, evidence = await eightfold_client.fetch_jobs_with_meta(
            tenant_host, domain, http, confirm_terminus=True
        )
        return eightfold_client.transform_to_job_listings(company_id, raw), evidence
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


# SSRF-guarded sync client for the discovered-script (http_json/http_html)
# transport. Module-level so a test injects a fake validator + MockTransport inner
# (see ``services/guarded_client``). Every request — the entrypoint fetch, each
# pagination page, the facet probe, the sitemap oracle GET — is validated,
# host-pinned, and IP-pinned before a socket opens.
def _recipe_http_client() -> httpx.Client:
    return guarded_sync_client()


async def _run_discovered_script(
    script: dict[str, Any],
    company_id: str,
    *,
    transport: str,
    oracle_kind: str,
) -> tuple[list[JobListing], HarvestEvidence]:
    """Replay a DISCOVERED company's stored multi-primitive script (E7 Phase 3b).

    ``recipe_runner.run_recipe`` is sync + agent-free (it re-validates the stored
    script — including the ``transport``/``oracle_kind`` column-equality check so a
    JSONB-vs-column drift is caught on read — asserts no browser/agent driver is
    resident, then replays it over the SSRF-guarded client) and returns the SAME
    ``HarvestEvidence`` the ATS path yields, so the gate/verdict/upsert tail below
    is byte-identical. Run in a thread so the blocking client (guarded DNS +
    sockets) never stalls the worker's event loop. A ``RecipeExecutionError`` — the
    SSRF guard raises one too — propagates to the leaf task's narrow ``except`` → a
    recorded FAILED run.
    """
    def _run() -> tuple[list[JobListing], HarvestEvidence]:
        http = _recipe_http_client()
        try:
            rows, evidence = recipe_runner.run_recipe(
                script, http, transport=transport, oracle_kind=oracle_kind
            )
        finally:
            http.close()
        return recipe_rows_to_job_listings(company_id, rows), evidence

    return await asyncio.to_thread(_run)


async def _run_browser_fetch_script(
    script: dict[str, Any],
    company_id: str,
    *,
    transport: str,
    oracle_kind: str,
) -> tuple[list[JobListing], HarvestEvidence]:
    """Replay a DISCOVERED ``browser_fetch`` company's stored recipe (E7 Phase 3c).

    Re-issues the board's captured jobs request inside OUR OWN headless Chromium on
    the board's origin (``run_browser_fetch`` — a subprocess; no Browserbase, no LLM),
    maps its rows via ``recipe_rows_to_job_listings`` and returns the SAME
    ``HarvestEvidence`` the ATS / http paths yield, so the gate/verdict/upsert tail
    below is byte-identical.

    ``run_browser_fetch`` RAISES ``RecipeExecutionError`` on an SSRF-blocked URL, a
    non-2xx or non-JSON page, an over-budget page count, zero rows, or a Chromium
    crash/timeout — the leaf task's narrow ``except`` records that as a FAILED run
    (nothing destructive, NOT a miss). Imported LAZILY (inside this function, i.e.
    only when the ``browser_fetch`` branch runs) so the leaf task's module import
    graph never even references the package — ``playwright`` lives solely in the
    subprocess it spawns, and the import-guard tests hold.
    """
    from ..services.browser_fetch import runner as browser_fetch_runner

    rows, evidence = await browser_fetch_runner.run_browser_fetch(
        script, transport=transport, oracle_kind=oracle_kind
    )
    return recipe_rows_to_job_listings(company_id, rows), evidence


@procrastinate_app.task(
    queue="custom_ats_fetch",
    name="fetch_custom_company",
    # ONE attempt, no auto-retry (matches the discovery task). A persistently-failing
    # browser_fetch board must NOT burn up to 5 Chromium launches/night on Procrastinate
    # retries; a FAILED run is still recorded + re-raised (the direct contract holds)
    # and the next daily claim re-runs it. The tradeoff — a transient
    # blip on a custom ATS/http board waits until the next daily cadence instead of
    # an in-run retry — is acceptable for a daily-cadence private board.
    retry=RetryStrategy(max_attempts=1),
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
    closed_jobs_count = 0
    error_count = 0
    guard_reason: GuardReason | None = None
    verdict = FAILED
    verdict_reason: str | None = "not_run"
    records_harvested = 0
    id_dedup_dropped = 0
    new_ids: Set[str] = set()
    scrape_error: BaseException | None = None
    # E7 gate evidence, recorded on company_harvests even for a FAILED run.
    oracle_kind_effective = "none"
    declared_total: int | None = None
    oracle_total: int | None = None
    cap_hit = False
    page_advance_ok: bool | None = None
    tolerance_used = 0.0

    conn = await asyncio.to_thread(
        db.get_connection,
        settings.database_url,
        application_name="task_fetch_custom",
        statement_timeout_ms=60_000,
    )
    try:
        try:
            async def _work() -> None:
                nonlocal jobs_seen, new_jobs_count, closed_jobs_count, error_count
                nonlocal guard_reason, verdict, verdict_reason, records_harvested
                nonlocal id_dedup_dropped, new_ids, oracle_kind_effective
                nonlocal declared_total, oracle_total, cap_hit, page_advance_ok
                nonlocal tolerance_used

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
                transport = str(company.get("transport") or "ats_client")
                cadence_hours = float(company.get("cadence_hours") or 24)
                is_first_verified = company.get("tracking_started_at") is None

                if transport == "browser_agent":
                    # RETIRED TRANSPORT (the capture pivot). The Stagehand DOM tier is
                    # gone, but a company discovered under it may still carry a stored
                    # ``transport='browser_agent'`` script. Falling through to the ATS
                    # ``else`` below would try to fetch it as an ATS provider named
                    # 'discovered' and fail with a nonsense message; raising HERE makes
                    # it an explicit, greppable FAILED run — which harvests nothing,
                    # closes NOTHING and is not a miss (invariant #2) — so the row goes
                    # stale in the UI rather than losing its jobs. An operator (or the
                    # user) re-discovers such a board by Removing it and re-adding the
                    # same URL, which runs capture discovery and rewrites the script.
                    raise recipe_runner.RecipeExecutionError(
                        f"transport 'browser_agent' was retired with the Stagehand tier; "
                        f"company {company_id} must be re-discovered (remove + re-add the "
                        f"careers URL) — refusing to harvest, closing nothing"
                    )
                elif transport == "browser_fetch":
                    # KILL-SWITCH: ``custom_company_discovery_enabled``, the single
                    # discovery flag. Rationale: discovery is the ONLY thing
                    # that ever creates a browser_fetch company, so with the flag off
                    # the tier is dormant end-to-end, and flipping it off is a
                    # fleet-wide stop for the whole own-Chromium surface if its SSRF
                    # posture ever needs one. The cost of that choice, stated plainly:
                    # turning discovery off ALSO stops re-harvesting boards that were
                    # already discovered — they go stale rather than partially
                    # harvested. That is the safe direction (a no-op skip harvests
                    # nothing, closes nothing, accrues no miss — identical to the
                    # disabled-company path), and per-company ``enabled=FALSE`` remains
                    # the single-board switch.
                    if not settings.custom_company_discovery_enabled:
                        verdict_reason = "browser_fetch_disabled"
                        logger.info(
                            "fetch_custom_company: custom_company_discovery_enabled off; "
                            "skipping browser_fetch harvest for %s", company_id,
                        )
                        return
                    # DISCOVERED browser_fetch company — replay the captured request
                    # inside our own Chromium. Use the STORED oracle_kind for the same
                    # reason the http branch does: a discovered company has no ATS
                    # provider, so ``effective_oracle_kind`` does not apply.
                    oracle_kind_effective = str(company.get("oracle_kind") or "none")
                    raw_jobs, evidence = await _run_browser_fetch_script(
                        script, company_id,
                        transport=transport, oracle_kind=oracle_kind_effective,
                    )
                elif transport in ("http_json", "http_html"):
                    # DISCOVERED (non-ATS) company — E7 Phase 3b. Replay the stored
                    # multi-primitive script agent-free, and use the STORED
                    # oracle_kind: a discovered company has no ATS provider, so
                    # ``effective_oracle_kind`` (provider-derived) does not apply.
                    oracle_kind_effective = str(company.get("oracle_kind") or "none")
                    raw_jobs, evidence = await _run_discovered_script(
                        script, company_id,
                        transport=transport, oracle_kind=oracle_kind_effective,
                    )
                else:
                    provider = str(script.get("provider") or company["ats"])
                    board_token = str(script.get("token") or company["board_token"])
                    provider_config = dict(company["provider_config"] or {})
                    # DECISION D2: derive the effective oracle from the ATS provider,
                    # NOT from the stored oracle_kind — so a Phase-1 row seeded 'none'
                    # graduates with no backfill.
                    oracle_kind_effective = effective_oracle_kind(provider)
                    async with httpx.AsyncClient() as http:
                        raw_jobs, evidence = await _fetch_and_transform(
                            provider, board_token, provider_config, company_id, http
                        )
                jobs = _remap_for_custom(
                    raw_jobs, company_id, source_id, datetime.now(timezone.utc)
                )
                # Record the raw evidence now, so even a gate-raised FAILED run
                # captures it on company_harvests.
                declared_total = evidence.declared_total
                cap_hit = evidence.cap_hit
                page_advance_ok = evidence.page_advance_ok

                # ===== Structural gate (checks 2 zero-aware, 3, 7-dedup, 8) =====
                # Raises HarvestGateError only on a genuinely broken run → FAILED.
                gate = run_gate(jobs, evidence, oracle_kind=oracle_kind_effective)
                jobs = gate.jobs
                jobs_seen = gate.records_harvested
                records_harvested = gate.records_harvested
                id_dedup_dropped = gate.id_dedup_dropped

                # ===== Verdict (checks 5, 6, 7-vs-total, 9, 10, 11, 12) =====
                baseline = await asyncio.to_thread(compute_baseline, conn, company_id)
                decision = verify_harvest(
                    oracle_kind_effective, gate, evidence, baseline
                )
                verdict = decision.verdict
                verdict_reason = decision.reason
                tolerance_used = decision.tolerance_used
                oracle_total = decision.oracle_total
                if decision.declared_total is not None:
                    declared_total = decision.declared_total
                cap_hit = decision.cap_hit or cap_hit
                if decision.page_advance_ok is not None:
                    page_advance_ok = decision.page_advance_ok

                active_count = await asyncio.to_thread(
                    db.count_active_jobs, conn, source_id, company_id
                )
                # The completeness verdict is ANDed with the existing safety guard
                # (never a replacement). Custom companies pass their learned
                # per-company min_ratio (the 0.5 floor until calibrated); the six
                # public crons keep the global 0.85 (min_ratio defaults to None).
                guard = await asyncio.to_thread(
                    resolve_safety_guard, conn, company_id, jobs_seen, active_count,
                    min_ratio=baseline.min_ratio,
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
                # PHASE 2 (E7): steps 1-2 run under EVERY non-FAILED verdict
                # (UNVERIFIED still upserts + refreshes last_seen — writing the rows
                # we DID get can only move jobs away from closure). Steps 3-4 — the
                # destructive miss-increment and close — run ONLY on a VERIFIED run
                # that also clears every safety gate below. An UNVERIFIED run may
                # never close a job; that is the load-bearing invariant.

                if jobs:
                    await asyncio.to_thread(db.upsert_jobs_batch, conn, jobs)

                if seen_ids:
                    await asyncio.to_thread(
                        db.update_last_seen, conn, source_id, list(seen_ids), timestamp
                    )

                new_ids = seen_ids - pre_upsert_active
                new_jobs_count = len(new_ids)

                # A VERIFIED run PROVED it saw the whole board → the company is
                # healthy; the FIRST VERIFIED run also stamps tracking_started_at.
                if verdict == VERIFIED:
                    await asyncio.to_thread(
                        ccs.mark_verified, conn, company_id,
                        set_tracking=is_first_verified,
                    )

                # ---- close-eligibility precedence (verdict-FIRST; DECISION D1) --
                # guard_reason records WHY the destructive close was skipped (None
                # = a clean VERIFIED close-eligible run). ``increment_misses`` and
                # ``close_eligible`` split the two destructive sub-steps: a
                # streak-building self_consistent run accrues misses but may not
                # close yet (so the accrued misses close it the moment the streak
                # completes), while every non-VERIFIED / guarded / first-run /
                # fleet-outage case does NEITHER.
                increment_misses = False
                close_eligible = False
                if verdict != VERIFIED:
                    guard_reason = "unverified_harvest"
                elif guard.reason is not None:
                    guard_reason = guard.reason
                elif tolerance_used > 0:
                    guard_reason = "approximate_no_close"
                elif await asyncio.to_thread(ccs.fleet_breaker_tripped, conn):
                    guard_reason = "fleet_breaker"
                elif is_first_verified:
                    guard_reason = "first_verified_run"
                elif await asyncio.to_thread(
                    ccs.script_changed_since_last, conn, company_id
                ):
                    guard_reason = "script_changed"
                elif oracle_kind_effective == "self_consistent" and (
                    len(pre_upsert_active) > 0
                    and len(pre_upsert_active - seen_ids) / len(pre_upsert_active)
                    > _ID_CHURN_CLOSE_THRESHOLD
                ):
                    # CHURN GUARD (self_consistent only): >50% of prior-OPEN ids
                    # vanished this run with no trusted total to corroborate the
                    # drop — treat it as a churning id_field, not a real board
                    # shrink. Keep every job OPEN and accrue NO misses (so a
                    # steadily-churning board never latches toward a close). This is
                    # the fix for a browser-agent board whose per-load url id churns
                    # each night: a steady count but a fresh id set would otherwise
                    # close still-live jobs after the 3-run streak.
                    guard_reason = "id_churn_suspected"
                elif oracle_kind_effective == "self_consistent" and (
                    await asyncio.to_thread(ccs.consecutive_verified, conn, company_id)
                    + 1 < _SELF_CONSISTENT_STREAK_REQUIRED
                ):
                    # Streak still building: accrue misses so the run that finally
                    # completes the streak can act on them, but do not close yet.
                    guard_reason = "streak_too_short"
                    increment_misses = True
                else:
                    guard_reason = None
                    increment_misses = True
                    close_eligible = True

                if increment_misses:
                    post_upsert_active = await asyncio.to_thread(
                        db.get_active_job_ids, conn, source_id, company_id
                    )
                    missing_ids = post_upsert_active - seen_ids
                    if missing_ids:
                        # KNOWN GAP (review Finding 1 — deferred to the fleet-
                        # hardening pass in STACK-ORCHESTRATION.md): this
                        # increment + the threshold read + close below are three
                        # separately-committed steps, not one transaction. A
                        # Procrastinate retry re-runs the whole handler with a
                        # fresh run_id, so a job still missing on the retry can be
                        # incremented twice — letting an already-gone, >36h-stale
                        # job close up to one logical run early. NOT a wrong close:
                        # only a VERIFIED run reaches here (the job is proven gone)
                        # and the 36h floor is on the real last_seen_at, which a
                        # retry does not move. TODO: fold increment + threshold-read
                        # + close into one transaction to make it idempotent per
                        # logical run.
                        await asyncio.to_thread(
                            db.increment_consecutive_misses,
                            conn, source_id, list(missing_ids),
                        )
                        if close_eligible:
                            # 36h wall-clock floor (§4.2) — on last_seen_at, NOT
                            # the miss counter, so a scheduler double-fire / manual
                            # rerun cannot shortcut it. guard.miss_threshold (not a
                            # bare 2) so an auto-released run closes one miss later.
                            to_close = await asyncio.to_thread(
                                db.get_jobs_exceeding_miss_threshold,
                                conn, source_id, list(missing_ids),
                                guard.miss_threshold,
                                min_seen_age_hours=1.5 * cadence_hours,
                            )
                            if to_close:
                                await asyncio.to_thread(
                                    db.mark_jobs_closed,
                                    conn, source_id, list(to_close), timestamp,
                                )
                                closed_jobs_count = len(to_close)

                logger.info(
                    "fetch_custom_company %s: verdict=%s seen=%d new=%d closed=%d "
                    "(oracle=%s guard_reason=%s)",
                    company_id, verdict, jobs_seen, new_jobs_count,
                    closed_jobs_count, oracle_kind_effective, guard_reason,
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
        except (
            HarvestGateError,
            httpx.HTTPError,
            recipe_runner.RecipeExecutionError,
            ValueError,
            psycopg2.Error,
        ) as e:
            # Narrow on purpose (mirrors the ATS tasks): programmer errors
            # propagate immediately; expected failure modes (a gate check, HTTP
            # transport, a discovered-script replay raise, malformed payload, DB
            # error) convert to a recorded FAILED run. A FAILED run wrote nothing
            # destructive and is NOT a miss.
            logger.error(
                "fetch_custom_company failed for %s: %s", company_id, e, exc_info=True,
            )
            error_count = 1
            verdict = FAILED
            verdict_reason = str(e) or type(e).__name__
            scrape_error = e
    finally:
        completed_at = get_iso_timestamp()
        # A SUCCESSFUL run is any executed, non-FAILED harvest — VERIFIED OR
        # UNVERIFIED. (Phase 1 gated this on ==UNVERIFIED; Phase 2 adds VERIFIED.)
        success = scrape_error is None and verdict != FAILED

        # On a SUCCESSFUL harvest, stamp companies.last_success_at = now() so the
        # "last checked" UI stops reading "Not yet checked". health_state /
        # tracking_started_at are moved by mark_verified inside _work (VERIFIED
        # runs only), not here. A FAILED run (success=False) never updates it. A
        # write failure here must not mask the run bookkeeping below.
        if success:
            try:
                await asyncio.to_thread(ccs.mark_last_success, conn, company_id)
            except Exception:
                logger.exception(
                    "Failed to update last_success_at for %s", company_id
                )

        # THE FIFTH RUNG on a discovered company's setup checklist (see
        # ``services/discovery/progress``). Discovery ends by proving it can read the
        # board and enqueuing THIS run; the row is tracked, green all the way down, and
        # holding zero jobs until we land. So the run that lands says so — a ✓ carrying
        # the count, or an ✕ carrying why — and a user watching "0 open jobs" has an
        # answer instead of a finished-looking checklist.
        #
        # DISPLAY-ONLY, and guarded like it: a no-op for any company without a discovery
        # blob, and any failure is swallowed with a log. Nothing about closing, missing
        # or verifying reads this blob, so it must never be able to fail a harvest — the
        # same stance ``record_company_harvest`` and ``mark_last_success`` take here.
        try:
            await asyncio.to_thread(
                ccs.record_first_scan,
                conn,
                company_id,
                ok=success,
                detail=(
                    f"read {jobs_seen} job(s) from the board"
                    if success
                    # The reason is RENDERED on the ✕, and it is the only thing that
                    # distinguishes "we will retry tonight" from "this board changed".
                    else "we could not read the board on this run "
                         f"({verdict_reason or 'unknown error'}) — we will try again"
                ),
            )
        except Exception:
            logger.exception(
                "Failed to record the first-scan checklist rung for %s", company_id
            )

        # Per-run evidence — written for every run (VERIFIED/UNVERIFIED/FAILED) so
        # a wrong match / silent failure is diagnosable weeks later. oracle_kind is
        # the EFFECTIVE oracle (D2), and the completeness signals ride along.
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
                oracle_kind=oracle_kind_effective,
                id_dedup_dropped=id_dedup_dropped,
                declared_total=declared_total,
                oracle_total=oracle_total,
                cap_hit=cap_hit,
                page_advance_ok=page_advance_ok,
                tolerance_used=tolerance_used,
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
            closed_jobs=closed_jobs_count,  # real count (VERIFIED runs may close)
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
