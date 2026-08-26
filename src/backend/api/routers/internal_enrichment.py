"""Internal enrichment endpoints — the pull integration with job-enricher.

Mounted at /api/internal/enrichment and protected by the global
require_internal_key middleware (X-Internal-Key), so no per-route auth here. The
laptop makes only OUTBOUND calls to these routes:

    GET  /pending?limit=N   claim a batch of unenriched OPEN jobs (server-side
                            claim so concurrent polls never hand out the same rows).
                            Ordered by title-priority tier — entry-level/intern,
                            then software-engineering, then everything else — with
                            newest first_seen_at as the within-tier tie-breaker.
                            The batch is SPLIT: a reserved share (default 10%)
                            goes to custom (user-added) companies, round-robin
                            across them; the rest keeps the published ordering
                            untouched. Either slice absorbs the other's unused
                            budget, so the reservation never idles the enricher.
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

from scripts.shared.constants import CUSTOM_SOURCE_PREFIX

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
    # first_seen_at (the claim's ORDER BY key) is echoed so the enricher can order
    # its own local classify queue newest-first too — otherwise it re-FIFOs by
    # local arrival and buries freshly-posted jobs behind its backlog.
    "first_seen_at, "
    "jsonb_build_object("
    "  'department', details->'department', "
    "  'experience_level', details->'experience_level'"
    ") AS details"
)

# Title-keyword priority tiers for the /pending claim (interpolated into the
# ORDER BY below). Purpose: behind a low-throughput enricher the claimable
# backlog is far deeper than one tick can drain, so we label the roles we care
# about MOST while they're still fresh — entry-level/intern first, then
# software-engineering, then everything else — with recency (first_seen_at DESC)
# as the within-tier tie-breaker.
#
# Matching is whole-word via Postgres word boundaries (\y), mirroring the
# scrapers' shared title_matches_keyword helper (regex \bintern(?:ship)?s?\b) so
# 'internal' / 'international' / 'internet' never false-match 'intern'. NOTE:
# Postgres ARE spells the word boundary \y (\b is backspace). These are trusted
# literal constants (no user input), so f-string interpolation into SQL is safe.
_ENTRY_LEVEL_TITLE_RE = r"\y(intern(ship)?s?|junior|jr|entry[ -]?level|new[ -]?grad(uate)?)\y"
# No trailing \y on the software root so "Software Engineering" / "…Development"
# also match; the acronym is matched whole-word separately.
_SWE_TITLE_RE = r"\ysoftware (engineer|develop)"
_SWE_ACRONYM_RE = r"\yswe\y"

# The tier expression itself, shared verbatim by BOTH claim passes (published and
# custom) so the two slices can never drift into different notions of priority.
_TITLE_TIER_SQL = (
    "CASE "
    f"  WHEN title ~* '{_ENTRY_LEVEL_TITLE_RE}' THEN 0 "
    f"  WHEN title ~* '{_SWE_TITLE_RE}' OR title ~* '{_SWE_ACRONYM_RE}' THEN 1 "
    "  ELSE 2 "
    "END"
)

# LIKE pattern splitting the two slices. Custom (user-added) companies each own a
# `custom:<company_id>` source_id namespace — see scripts.shared.constants.
_CUSTOM_SOURCE_LIKE = CUSTOM_SOURCE_PREFIX + "%"


def _to_job(row: dict[str, Any]) -> dict[str, Any]:
    first_seen = row["first_seen_at"]
    return {
        "job_id": row["id"],
        "source_id": row["source_id"],
        "title": row["title"],
        "company": row["company"],
        "location": row["location"],
        "description_html": row["description_html"],
        "first_seen_at": first_seen.isoformat() if first_seen is not None else None,
        "details": row["details"],
    }


def _custom_budget(limit: int) -> int:
    """Slots of this batch reserved for custom (user-added) companies.

    Floor of the configured share, but never rounded down to zero while the
    share is enabled: at ``limit=1`` a floor would silently hand custom 0 slots
    on every tick forever, which is exactly the starvation this brake exists to
    prevent. The published side is only squeezed by that guard at ``limit=1``
    (below 10 slots it still keeps ``limit - 1``); the real enricher polls 60,
    where the split is an exact 6/54.
    """
    pct = settings.enrichment_custom_share_pct
    if pct <= 0:  # 0 = kill switch: custom rows are never claimed
        return 0
    return max(1, limit * pct // 100)


def _claim_published(cur: Any, budget: int, desc_guard: str) -> list[Any]:
    """Claim up to `budget` rows from the PUBLISHED (curated) slice.

    The historical claim, unchanged, plus one predicate — ``source_id NOT LIKE
    'custom:%'``. Published rows are neither reordered nor re-tiered relative to
    each other; the only thing that changed for them is that custom rows can no
    longer appear in this queue at all (they used to sort straight to the FRONT,
    being the newest rows in the table).
    """
    if budget <= 0:
        return []
    cur.execute(
        "UPDATE job_listings SET enrichment_status = 'claimed', enrichment_claimed_at = now() "
        "WHERE (source_id, id) IN ("
        "  SELECT source_id, id FROM job_listings "
        "  WHERE enrichment_status IS NULL AND status = 'OPEN' "
        "  AND source_id NOT LIKE %s "
        f"{desc_guard}"
        f"  ORDER BY {_TITLE_TIER_SQL}, first_seen_at DESC "
        "  LIMIT %s FOR UPDATE SKIP LOCKED"
        f") RETURNING {_JOB_PROJECTION}",
        (_CUSTOM_SOURCE_LIKE, budget),
    )
    rows: list[Any] = cur.fetchall()
    return rows


def _claim_custom(cur: Any, budget: int, desc_guard: str) -> list[Any]:
    """Claim up to `budget` rows from the CUSTOM slice, round-robin by company.

    Two statements, not one, because Postgres rejects ``FOR UPDATE`` in a query
    level that uses window functions ("FOR UPDATE is not allowed with window
    functions") and a CTE cannot be locked either. So: pick candidates with the
    window query, then re-select exactly those PKs ``FOR UPDATE SKIP LOCKED``
    and re-assert ``enrichment_status IS NULL`` *under the lock*. That keeps the
    published claim's concurrency contract intact — two simultaneous /pending
    polls can still never be handed the same row — at the cost of one extra
    round trip per tick.

    The ordering has two independent jobs, hence two ROW_NUMBERs:

    * ``recency_rank`` (first_seen_at DESC) implements the per-company
      ELIGIBILITY CAP: only a company's newest N unclaimed OPEN rows compete.
      Ranked over UNCLAIMED rows on purpose — the window slides forward as rows
      drain, so a 47k-job board's tail is deferred, never permanently walled
      off (an absolute "newest 500 of all time" cap would strand row 501 for
      good). It also stops a mega-board's deep tier-0 history — thousands of
      old "intern" titles buried 20k rows down — from outranking every other
      company's fresh postings.
    * ``company_slot`` (tier, then recency, within one source_id) is the
      ROUND-ROBIN cursor: ordering the pooled candidates by slot number takes
      every company's #1 before anyone's #2, so one board cannot monopolise even
      the custom slice itself. Ties inside a slot fall back to tier/recency, so
      a company that runs out simply stops consuming slots and the remaining
      budget flows to the boards that still have work.
    """
    if budget <= 0:
        return []
    cur.execute(
        "SELECT source_id, id FROM ("
        "  SELECT source_id, id, tier, first_seen_at, "
        "         ROW_NUMBER() OVER ("
        "           PARTITION BY source_id ORDER BY tier, first_seen_at DESC, id"
        "         ) AS company_slot "
        "  FROM ("
        f"    SELECT source_id, id, {_TITLE_TIER_SQL} AS tier, first_seen_at, "
        "           ROW_NUMBER() OVER ("
        "             PARTITION BY source_id ORDER BY first_seen_at DESC, id"
        "           ) AS recency_rank "
        "    FROM job_listings "
        "    WHERE enrichment_status IS NULL AND status = 'OPEN' "
        "    AND source_id LIKE %s "
        f"{desc_guard}"
        "  ) eligible "
        "  WHERE recency_rank <= %s "
        ") slotted "
        "ORDER BY company_slot, tier, first_seen_at DESC, id "
        "LIMIT %s",
        (
            _CUSTOM_SOURCE_LIKE,
            settings.enrichment_custom_per_company_cap,
            budget,
        ),
    )
    candidates = tuple((r["source_id"], r["id"]) for r in cur.fetchall())
    if not candidates:  # `IN ()` is a syntax error, and there is nothing to lock
        return []
    cur.execute(
        "UPDATE job_listings SET enrichment_status = 'claimed', enrichment_claimed_at = now() "
        "WHERE (source_id, id) IN ("
        "  SELECT source_id, id FROM job_listings "
        "  WHERE (source_id, id) IN %s "
        "  AND enrichment_status IS NULL AND status = 'OPEN' "
        # Deterministic lock order across concurrent pollers.
        "  ORDER BY source_id, id "
        "  LIMIT %s FOR UPDATE SKIP LOCKED"
        f") RETURNING {_JOB_PROJECTION}",
        (candidates, budget),
    )
    rows: list[Any] = cur.fetchall()
    return rows


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
        # EXCEPTION: when enrichment_claim_without_description is ON, drop the guard
        # and claim description-less rows too (workday_api/eightfold_api capture no
        # description) — the enricher labels them title-only at low confidence. The
        # partial index idx_job_listings_enrichment_claim (predicate: enrichment_status
        # IS NULL AND status='OPEN', no description clause) serves BOTH the guarded and
        # unguarded query, so no index change is needed either way.
        desc_guard = (
            "" if settings.enrichment_claim_without_description
            else f"  AND {DESCRIPTION_SQL} IS NOT NULL "
        )
        #
        # Claim order = title-priority TIER first, then recency within the tier.
        # The backlog is far deeper than one tick can drain (~19k OPEN unenriched
        # rows in prod, only ~limit claimed per tick), so ordering decides which
        # jobs get labelled while still fresh. We front-load the roles we care
        # about most (see _ENTRY_LEVEL_TITLE_RE / _SWE_TITLE_RE above):
        #   tier 0 — entry-level / internships (intern, new grad, junior, entry-level)
        #   tier 1 — software-engineering (software engineer/dev, SWE)
        #   tier 2 — everything else
        # An entry-level SWE role (e.g. "Software Engineer Intern") lands in tier 0
        # because tier 0 is tested first — exactly "entry-level before all else".
        #
        # Within each tier we ORDER BY first_seen_at DESC. Two of the three reasons
        # this column was chosen still hold; the third has been overtaken and the
        # ordering is being KEPT anyway. Stated plainly so the next reader is not
        # misled by the argument that used to justify it:
        #
        #   - last_seen_at is bumped to now() on every scrape a job is still OPEN, so
        #     it clusters at ~now across the whole active backlog and cannot rank a
        #     job posted today above one open for months. (Still true.)
        #   - first_seen_at is written once at INSERT and never moves, not even
        #     across close/reopen, so a row cannot change position mid-drain.
        #     (Still true, and it is also why keyset pagination sorts on it.)
        #   - The third reason SAID: "posted_on is the ATS-supplied posting date and
        #     is UNRELIABLE — ~8.6% of OPEN rows carry a posted_on >180d — so
        #     ordering by it buries freshly re-listed jobs." That distinction is
        #     GONE. first_seen_at is now seeded FROM the board's posted date when the
        #     board publishes a real one, so ordering by first_seen_at IS ordering by
        #     posted_on for every row that has one. There is no longer a version of
        #     this query that avoids the burial by sorting on a different column.
        #
        # What that costs, measured on prod: of the rows inserted in the last 30 days,
        # 2.08% (308 of 14,841) carry a posting date more than 180 days old, and those
        # now enter the queue dated months back — i.e. BEHIND a 16,201-row unenriched
        # OPEN backlog which, at one local ollama worker, does not drain. Those rows
        # are not delayed; in practice they are never claimed.
        #
        # This is a deliberate, owner-made trade and it STANDS: first_seen_at is the
        # column every user-visible surface and the keyset walk already sort by, and
        # having the enricher disagree with them would be a second, invisible notion of
        # recency. Do not "fix" this by switching the ORDER BY. If the buried tail
        # matters later, the shape of the answer is a separate small slice for old-dated
        # arrivals — the same move ``enrichment_custom_share_pct`` already makes for
        # custom companies — not a change to this sort.
        #
        # Index note: the partial index idx_job_listings_enrichment_claim still
        # serves the WHERE predicate; the tier CASE makes Postgres sort the matched
        # set (~19k rows) by (tier, first_seen_at) rather than doing a bounded
        # index-only scan. At this row count that sort is trivial (tens of ms) and
        # runs once per tick, so no schema/index change is needed.
        #
        # The custom slice adds two window functions over its own subset. Measured
        # with EXPLAIN ANALYZE on 19k published + 48.6k custom rows (a 47k board
        # plus two small ones): custom candidate pass 27 ms, published pass 39 ms.
        # Note what the per-company cap does and does not do — it bounds the RANKED
        # output (Postgres 15 pushes it down as a window `Run Condition`, so only
        # cap-per-company rows are ever emitted), not the sort INPUT, which is
        # still every unclaimed custom row. At one tick every few minutes that is
        # not worth a migration; if the custom backlog ever dwarfs the published
        # one, the fix is a partial index on (source_id, first_seen_at DESC) —
        # today's index is on first_seen_at alone and cannot serve the per-source
        # ordering.
        #
        # ---- The fairness brake -------------------------------------------
        # Ordering by first_seen_at DESC has a nasty interaction with custom
        # (user-added) companies, and since the posted-date seeding it has TWO,
        # pointing opposite ways — which is why the brake is a reservation (a floor
        # AND a ceiling) rather than a cap:
        #   - a board added today whose jobs are dateless, or dated today, produces
        #     the NEWEST rows in the table and sorts to the FRONT of the queue. With
        #     no source_id filter (and with enrichment_claim_without_description ON
        #     in prod, so the description guard no longer accidentally excludes
        #     them), one user pasting one 47k-job careers URL would hold ~100% of
        #     the claim for years while every published company waits.
        #   - a board that publishes REAL posting dates now inserts rows dated
        #     months back, which sort to the BACK — behind a 16,201-row published
        #     backlog that does not drain. Without the reserved slice those rows
        #     would simply never be claimed.
        # Which of the two a board hits is decided by what dates it happens to
        # publish, i.e. by nothing we control. So the batch is split:
        #
        #   1. custom slice   — at most enrichment_custom_share_pct of `limit`,
        #                       round-robin across custom companies (_claim_custom)
        #   2. published pass — the REST, unchanged ordering (_claim_published)
        #   3. top-up         — whatever neither slice used goes back to custom
        #
        # Neither side can starve the other. Step 2 takes `limit - claimed_custom`,
        # so an idle/empty custom slice costs published NOTHING — the reservation
        # is a ceiling on custom, never a floor that idles the GPU. Step 3 is the
        # mirror image: when the published backlog runs dry, custom takes the
        # leftovers instead of trickling at 10%/tick. And because step 1 always
        # runs first with a non-zero budget, custom work can never be indefinitely
        # buried behind a published backlog that (at one local ollama worker)
        # never drains.
        custom_rows = _claim_custom(cur, _custom_budget(limit), desc_guard)
        published_rows = _claim_published(cur, limit - len(custom_rows), desc_guard)
        rows = custom_rows + published_rows
        leftover = limit - len(rows)
        if leftover > 0:
            # Already-claimed rows are invisible to this second pass (same
            # transaction sees its own writes), so the round-robin simply
            # continues into each company's next slot.
            rows += _claim_custom(cur, leftover, desc_guard)
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
        # a genuinely idle one. Mirror /pending's desc_guard so this stays equal
        # to what /pending actually claims: when title-only claiming is ON,
        # description-less rows ARE claimable and must be counted here too
        # (otherwise a title-only-draining pipeline reads as idle/starved).
        desc_guard = (
            "" if settings.enrichment_claim_without_description
            else f"AND {DESCRIPTION_SQL} IS NOT NULL"
        )
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_listings "
            "WHERE enrichment_status IS NULL AND status = 'OPEN' "
            f"{desc_guard}"
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
