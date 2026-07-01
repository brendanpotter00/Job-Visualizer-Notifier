"""Internal enrichment endpoints — the pull integration with job-enricher.

Mounted at /api/internal/enrichment and protected by the global
require_internal_key middleware (X-Internal-Key), so no per-route auth here. The
laptop makes only OUTBOUND calls to these routes:

    GET  /pending?limit=N   claim a batch of unenriched OPEN jobs (server-side
                            claim so concurrent polls never hand out the same rows)
    POST /results           idempotent per-row upsert of enrichment results
    GET  /sample?n=&...     stratified raw sample for the eval golden set
    GET  /health            enrichment_status counts + stale/needs_human + metrics

Only /pending is gated by settings.enrichment_use_external: OFF -> /pending
returns nothing (no jobs are claimed), so the cloud-Haiku location pipeline stays
the sole floor. /results, /sample and /health all run REGARDLESS of the flag.
/results and /health are inert in practice only because nothing gets claimed to
enrich while /pending is off. /sample is INDEPENDENT of the flag: it serves raw
OPEN job samples for the eval golden set unconditionally (it neither claims nor
depends on any enrichment state).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from psycopg2.extensions import connection as Connection

from ..config import settings
from ..dependencies import get_db
from ..models import EnrichmentResultItem, EnrichmentResultsBody
from ..services.enrichment_writer import apply_result

logger = logging.getLogger(__name__)

router = APIRouter()

# RETURNING/SELECT projection shared by /pending and /sample.
_JOB_PROJECTION = (
    "id, source_id, title, company, location, "
    "details->>'description_html' AS description_html, "
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
    if not settings.enrichment_use_external:
        return {"jobs": [], "enabled": False}

    allowlist = settings.enrichment_company_allowlist_list
    cur = conn.cursor()
    try:
        # Reclaim claims older than the TTL (a laptop that died mid-batch).
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

        company_filter = "AND company = ANY(%s::text[]) " if allowlist else ""
        # Mirror /sample's guard: never claim a description-less row (nothing to
        # classify) — it could never leave 'claimed' and would poison a claim slot.
        claim_sql = (
            "UPDATE job_listings SET enrichment_status = 'claimed', enrichment_claimed_at = now() "
            "WHERE (source_id, id) IN ("
            "  SELECT source_id, id FROM job_listings "
            "  WHERE enrichment_status IS NULL AND status = 'OPEN' "
            "  AND details->>'description_html' IS NOT NULL "
            f"  {company_filter}"
            "  ORDER BY details_scraped DESC, last_seen_at DESC "
            "  LIMIT %s FOR UPDATE SKIP LOCKED"
            f") RETURNING {_JOB_PROJECTION}"
        )
        params: tuple[Any, ...] = (allowlist, limit) if allowlist else (limit,)
        cur.execute(claim_sql, params)
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
    written = 0
    failed: list[dict[str, Any]] = []
    cur = conn.cursor()
    try:
        for index, raw_item in enumerate(payload.results):
            # Best-effort id captured BEFORE validation so a failed row still
            # reports which job it was (the id survives even a missing source_id).
            fallback_id = (
                raw_item.get("job_listing_id") if isinstance(raw_item, dict) else None
            )
            try:
                cur.execute("SAVEPOINT enr_row")
                item = EnrichmentResultItem.model_validate(raw_item)
                apply_result(
                    conn,
                    item.model_dump(),
                    require_judge_pass=settings.enrichment_require_judge_pass,
                )
                cur.execute("RELEASE SAVEPOINT enr_row")
                written += 1
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
                failed.append({"job_listing_id": fallback_id, "error": str(exc)})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return {"written": written, "failed": failed}


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
                "  WHERE status = 'OPEN' AND details->>'description_html' IS NOT NULL"
                ") job_listings WHERE _rn <= 3 ORDER BY random() LIMIT %s",
                (n,),
            )
        else:
            cur.execute(
                f"SELECT {_JOB_PROJECTION} FROM job_listings "
                "WHERE status = 'OPEN' AND details->>'description_html' IS NOT NULL "
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

        cur.execute(
            "SELECT COUNT(*) AS n FROM job_listings "
            "WHERE enrichment_status = 'claimed' "
            "AND enrichment_claimed_at < now() - make_interval(mins => %s)",
            (settings.enrichment_claim_ttl_minutes,),
        )
        stale_claims = cur.fetchone()["n"]

        cur.execute("SELECT COUNT(*) AS n FROM job_enrichment WHERE needs_human")
        needs_human = cur.fetchone()["n"]

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
        "stale_claims": stale_claims,
        "needs_human": needs_human,
        "last_enriched_at": last_row["last"].isoformat() if last_row["last"] else None,
        "last_enriched_age_s": last_row["age_s"],
        "claim_ttl_minutes": settings.enrichment_claim_ttl_minutes,
    }
