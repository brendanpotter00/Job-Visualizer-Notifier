"""Internal enrichment endpoints — the pull integration with job-enricher.

Mounted at /api/internal/enrichment and protected by the global
require_internal_key middleware (X-Internal-Key), so no per-route auth here. The
laptop makes only OUTBOUND calls to these routes:

    GET  /pending?limit=N   claim a batch of unenriched OPEN jobs (server-side
                            claim so concurrent polls never hand out the same rows)
    POST /results           idempotent per-row upsert of enrichment results
    GET  /sample?n=&...     stratified raw sample for the eval golden set
    GET  /health            enrichment_status counts + stale/needs_human + metrics
    POST /metrics           per-tick pipeline snapshot push (idempotent on tick_uuid)
    GET  /corrections       human-correction feed (for the enricher's golden-merge)

Only /pending's CLAIM is gated by settings.enrichment_use_external: OFF -> no
jobs are handed out, so the cloud-Haiku location pipeline stays the sole floor.
The stale-claim RECLAIM inside /pending runs regardless of the flag — the kill
switch's contract is "claimed rows auto-reclaim after the TTL", which must hold
precisely when the flag was just turned off (otherwise in-flight rows strand at
'claimed' forever). /results, /sample, /health, /metrics and /corrections all
run regardless of the flag.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as Connection

from ..config import settings
from ..dependencies import get_db
from ..models import EnrichmentMetricsBody, EnrichmentResultItem, EnrichmentResultsBody
from ..services.enrichment_monitor import (
    DESCRIPTION_SQL,
    list_corrections_since,
    record_tick,
)
from ..services.enrichment_writer import apply_result

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard cap on /results batch size: bounds one internal-key call's write
# amplification (each row fans out to job_listings + job_enrichment + job_tags
# + locations). The enricher batches well below this; a bigger payload is a bug
# or abuse, and 413 is a clearer signal than a multi-minute transaction.
MAX_RESULTS_PER_BATCH = 500

# RETURNING/SELECT projection shared by /pending and /sample. The description
# COALESCEs across the real per-ATS storage shapes (Ashby/Lever:
# description_html, Greenhouse: content, custom scrapers: description) — see
# enrichment_monitor.DESCRIPTION_SQL; without it only ~17% of OPEN prod rows
# were claimable and the rest were invisible to the enricher forever.
_JOB_PROJECTION = (
    "id, source_id, title, company, location, "
    f"{DESCRIPTION_SQL} AS description_html, "
    "jsonb_build_object("
    "  'department', details->'department', "
    "  'experience_level', details->'experience_level'"
    ") AS details"
)


def _to_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["id"],
        "source_id": row["source_id"],
        "title": row["title"],
        "company": row["company"],
        "location": row["location"],
        "description_html": row["description_html"],
        "details": row["details"],
    }


@router.get("/pending")
def pending(
    conn: Connection = Depends(get_db),
    limit: int = Query(default=60, ge=1, le=500),
) -> dict[str, Any]:
    cur = conn.cursor()
    try:
        # Reclaim claims older than the TTL (a laptop that died mid-batch).
        # Runs BEFORE the flag gate: the kill switch's contract is that flipping
        # the flag off lets in-flight 'claimed' rows drain back to NULL after
        # the TTL — gating the reclaim would strand them at 'claimed' forever
        # exactly when the operator hit the kill switch.
        # Bounded + FOR UPDATE SKIP LOCKED (mirrors the claim below) so concurrent
        # /pending polls never contend on the same stale rows; at most `limit`
        # per tick, which self-heals over subsequent polls.
        cur.execute(
            "UPDATE job_listings SET enrichment_status = NULL, enrichment_claimed_at = NULL "
            "WHERE (source_id, id) IN ("
            "  SELECT source_id, id FROM job_listings "
            "  WHERE enrichment_status = 'claimed' "
            "  AND enrichment_claimed_at < now() - make_interval(mins => %s) "
            "  ORDER BY enrichment_claimed_at "
            "  LIMIT %s FOR UPDATE SKIP LOCKED"
            ")",
            (settings.enrichment_claim_ttl_minutes, limit),
        )

        if not settings.enrichment_use_external:
            conn.commit()  # persist the reclaim even when handing out nothing
            return {"jobs": [], "enabled": False}

        # Mirror /sample's guard: never claim a description-less row (nothing to
        # classify) — it could never leave 'claimed' and would poison a claim slot.
        #
        # Claim the freshest jobs first: ORDER BY first_seen_at DESC — the date the
        # scraper FIRST saw this listing, which is our reliable recency signal.
        # This matters most behind a low-throughput local model: the claimable
        # backlog is deep (~19k OPEN unenriched rows in prod) and only ~limit are
        # drained per tick, so ordering decides which jobs get labelled while fresh.
        #
        # Why first_seen_at and not the alternatives (see docs/database-schema.md
        # "recency fields", which this MUST stay in sync with):
        #   - posted_on is the ATS-supplied posting date and is UNRELIABLE: companies
        #     reuse/repost old listings, so ~8.6% of OPEN rows carry a posted_on >180d
        #     (some >16y) before we ever saw them. Ordering by it buries freshly
        #     re-listed jobs — the exact opposite of the goal.
        #   - last_seen_at is bumped to now() on every scrape a job is still OPEN, so
        #     it clusters at ~now across the whole active backlog and cannot rank a
        #     job posted today above one open for months.
        # first_seen_at is set once at discovery and preserved across close/reopen,
        # so DESC cleanly floats the newest arrivals to the front.
        claim_sql = (
            "UPDATE job_listings SET enrichment_status = 'claimed', enrichment_claimed_at = now() "
            "WHERE (source_id, id) IN ("
            "  SELECT source_id, id FROM job_listings "
            "  WHERE enrichment_status IS NULL AND status = 'OPEN' "
            f"  AND {DESCRIPTION_SQL} IS NOT NULL "
            "  ORDER BY first_seen_at DESC "
            "  LIMIT %s FOR UPDATE SKIP LOCKED"
            f") RETURNING {_JOB_PROJECTION}"
        )
        cur.execute(claim_sql, (limit,))
        rows = cur.fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return {"jobs": [_to_job(r) for r in rows], "enabled": True}


def _item_ident(raw_item: Any) -> str:
    """Best-effort identifier for a raw /results element, for logging a failure
    whose item never validated (so we have no parsed job_listing_id)."""
    if isinstance(raw_item, dict):
        jid = raw_item.get("job_listing_id")
        if jid is not None:
            return str(jid)
        return f"keys={sorted(raw_item.keys())}"
    return f"type={type(raw_item).__name__}"


@router.post("/results")
def results(
    payload: EnrichmentResultsBody,
    conn: Connection = Depends(get_db),
) -> dict[str, Any]:
    # Only the ENVELOPE ({"results": [...]}) is validated by FastAPI. Each ITEM is
    # validated into an EnrichmentResultItem INSIDE the per-row SAVEPOINT below,
    # so a null / non-dict / schema-invalid element lands in `failed[]` instead of
    # 422/500-ing the whole batch (per-row isolation contract).
    if len(payload.results) > MAX_RESULTS_PER_BATCH:
        raise HTTPException(
            status_code=413,
            detail=f"results batch exceeds {MAX_RESULTS_PER_BATCH} items",
        )
    written = 0
    failed: list[dict[str, Any]] = []
    # Per-row degradation feedback (facets nulled, tags truncated, human-
    # correction skip). Echoed to the enricher so laptop-side drift is VISIBLE
    # in its logs/metrics instead of silently degrading for weeks.
    row_warnings: list[dict[str, Any]] = []
    cur = conn.cursor()
    try:
        for index, raw_item in enumerate(payload.results):
            # Best-effort ids captured BEFORE validation so a failed row still
            # reports which job it was (they survive even a failed validation).
            fallback_id = (
                raw_item.get("job_listing_id") if isinstance(raw_item, dict) else None
            )
            fallback_source = (
                raw_item.get("source_id") if isinstance(raw_item, dict) else None
            )
            try:
                cur.execute("SAVEPOINT enr_row")
                item = EnrichmentResultItem.model_validate(raw_item)
                warnings = apply_result(
                    conn,
                    item.model_dump(),
                    require_judge_pass=settings.enrichment_require_judge_pass,
                )
                cur.execute("RELEASE SAVEPOINT enr_row")
                written += 1
                if warnings:
                    row_warnings.append(
                        {
                            "job_listing_id": item.job_listing_id,
                            "source_id": item.source_id,
                            "warnings": warnings,
                        }
                    )
            except Exception as exc:  # noqa: BLE001 — one bad row must not fail the batch
                cur.execute("ROLLBACK TO SAVEPOINT enr_row")
                # exc_info=True captures the traceback: most failures here are
                # benign per-row ValidationErrors, but an unexpected psycopg2 /
                # programming error hiding in the same subset must be debuggable,
                # even though the row still lands in failed[] either way.
                logger.warning(
                    "enrichment /results: item %d (%s) failed: %s",
                    index, fallback_id or _item_ident(raw_item), exc,
                    exc_info=True,
                )
                # source_id included so the enricher can match the failure to
                # its composite-keyed local row (id alone is ambiguous across
                # sources).
                failed.append(
                    {
                        "job_listing_id": fallback_id,
                        "source_id": fallback_source,
                        "error": str(exc),
                    }
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return {"written": written, "failed": failed, "warnings": row_warnings}


@router.get("/sample")
def sample(
    conn: Connection = Depends(get_db),
    n: int = Query(default=150, ge=1, le=1000),
    stratify: str = Query(default="company"),
) -> dict[str, Any]:
    """Return a raw job sample for the eval golden set. `stratify=company` caps
    a few per company so one company's phrasing can't dominate the golden set."""
    cur = conn.cursor()
    try:
        if stratify == "company":
            cur.execute(
                f"SELECT {_JOB_PROJECTION} FROM ("
                "  SELECT *, row_number() OVER (PARTITION BY company ORDER BY random()) AS _rn "
                "  FROM job_listings "
                f"  WHERE status = 'OPEN' AND {DESCRIPTION_SQL} IS NOT NULL"
                ") job_listings WHERE _rn <= 3 ORDER BY random() LIMIT %s",
                (n,),
            )
        else:
            cur.execute(
                f"SELECT {_JOB_PROJECTION} FROM job_listings "
                f"WHERE status = 'OPEN' AND {DESCRIPTION_SQL} IS NOT NULL "
                "ORDER BY random() LIMIT %s",
                (n,),
            )
        rows = cur.fetchall()
    finally:
        cur.close()
    return {"jobs": [_to_job(r) for r in rows]}


@router.get("/health")
def health(conn: Connection = Depends(get_db)) -> dict[str, Any]:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COALESCE(enrichment_status, 'unenriched') AS status, COUNT(*) AS n "
            "FROM job_listings WHERE status = 'OPEN' GROUP BY 1"
        )
        status_counts = {r["status"]: r["n"] for r in cur.fetchall()}

        # 'unenriched' above includes rows /pending can never hand out (no
        # description under any known key). Surface the CLAIMABLE count
        # separately so a drained-but-capped pipeline is distinguishable from
        # a genuinely idle one.
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_listings "
            "WHERE enrichment_status IS NULL AND status = 'OPEN' "
            f"AND {DESCRIPTION_SQL} IS NOT NULL"
        )
        eligible_unenriched = cur.fetchone()["n"]

        cur.execute(
            "SELECT COUNT(*) AS n FROM job_listings "
            "WHERE enrichment_status = 'claimed' "
            "AND enrichment_claimed_at < now() - make_interval(mins => %s)",
            (settings.enrichment_claim_ttl_minutes,),
        )
        stale_claims = cur.fetchone()["n"]

        cur.execute("SELECT COUNT(*) AS n FROM job_enrichment WHERE needs_human")
        needs_human = cur.fetchone()["n"]

        # The ACTIONABLE queue depth (OPEN jobs, not yet human-corrected) —
        # the raw needs_human count above includes CLOSED jobs and corrected
        # rows, so it only ever grows; kept for backward compat.
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_enrichment je "
            "JOIN job_listings jl ON jl.source_id = je.source_id "
            "AND jl.id = je.job_listing_id "
            "WHERE je.needs_human AND je.human_corrected_at IS NULL "
            "AND jl.status = 'OPEN'"
        )
        needs_human_open = cur.fetchone()["n"]

        cur.execute(
            "SELECT MAX(enriched_at) AS last, "
            "EXTRACT(EPOCH FROM now() - MAX(enriched_at))::bigint AS age_s "
            "FROM job_enrichment"
        )
        last_row = cur.fetchone()
    finally:
        cur.close()
    return {
        "enabled": settings.enrichment_use_external,
        "open_by_status": status_counts,
        "eligible_unenriched": eligible_unenriched,
        "stale_claims": stale_claims,
        "needs_human": needs_human,
        "needs_human_open": needs_human_open,
        "last_enriched_at": last_row["last"].isoformat() if last_row["last"] else None,
        "last_enriched_age_s": last_row["age_s"],
        "claim_ttl_minutes": settings.enrichment_claim_ttl_minutes,
    }


@router.post("/metrics")
def metrics(
    payload: EnrichmentMetricsBody,
    conn: Connection = Depends(get_db),
) -> dict[str, Any]:
    """Per-tick pipeline snapshot from the enricher (see ``cli metrics-push``).
    Idempotent on ``tick_uuid`` — a re-push (running → ok, or a retry) upserts.
    This is the only channel carrying laptop-side observability (per-stage
    latency, heartbeat, knobs, eval scorecards) into JVN; job-level provenance
    already arrives via /results."""
    record_tick(conn, payload.model_dump())
    return {"ok": True}


@router.get("/corrections")
def corrections(
    conn: Connection = Depends(get_db),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    """Human-review feed (admin needs-human queue output). Consumed by the
    enricher's ``cli golden-merge`` to upgrade matching golden-set rows to
    ``label_source='human'`` — the loop that turns admin triage into real gold
    labels for the eval gate. Each row's ``decision`` ('corrected' |
    'confirmed_correct') lets the consumer tell a human fix from a
    flagged-but-validated label (the raised-yet-correct signal)."""
    rows = list_corrections_since(conn, since=since, limit=limit)
    return {
        "corrections": [
            {
                "job_listing_id": r["job_listing_id"],
                "source_id": r["source_id"],
                "title": r["title"],
                "company": r["company"],
                "category": r["category"],
                "level": r["level"],
                "tags": r["tags"],
                "decision": r["decision"],
                "corrected_at": r["corrected_at"].isoformat() if r["corrected_at"] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }
