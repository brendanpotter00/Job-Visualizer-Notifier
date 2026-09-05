#!/usr/bin/env python3
"""Perf Wave 2 backfill — populate job_listings.primary_country + search_text.

Companion reading: ``docs/implementations/performance-audit/WAVE2-PLAN.md`` §2/§3.

WHY THIS IS A SEPARATE, POST-DEPLOY SCRIPT (not an in-migration UPDATE)
----------------------------------------------------------------------
Migration ``e3b1a4c9d7f2`` adds ``primary_country`` and ``search_text`` as
catalog-only nullable columns (no default, no backfill) so the ADD cannot rewrite
the ~859 MB table (the 2026-04-18 volume incident). The columns therefore start
all-NULL, and the ``/api/jobs/search`` predicates keep the ORIGINAL cross-table
``EXISTS`` / 4-way ``OR`` as a fallback for rows whose denormalized value ``IS
NULL`` — so a not-yet-filled value is never a wrong answer (WAVE2-PLAN.md §0/§5).

That correctness-under-NULL is what lets this backfill run at leisure AFTER the
deploy, in bounded batches, with no gating flag and no coordination: as NULLs
drain, the fallback fires less and the fast index path takes over. It is
idempotent and re-runnable — kill it and rerun any time.

HOW THE LOOP TERMINATES (refinement (i) from WAVE2-PLAN.md §2)
-------------------------------------------------------------
The loop is driven off ``search_text IS NULL`` ALONE, and sets BOTH columns in the
same UPDATE. Every row gets a non-NULL ``search_text`` (it is built from
``coalesce(...)`` so it is never NULL), so once a row is touched it is never
re-selected — even when its ``primary_country`` is *legitimately* NULL
(remote-only, multi-country, or no country tag). Driving the loop off
``primary_country IS NULL`` instead would re-select those rows forever. New writes
and the normalization writer keep both columns current after this initial drain.

``FOR UPDATE SKIP LOCKED`` means the backfill never fights a live scrape upsert:
a row another transaction holds is skipped this batch and picked up later. Each
batch commits on its own; ``--sleep`` between batches bounds WAL / lock pressure
(POSTGRES-PRINCIPLES §7).

DERIVATION (WAVE2-PLAN.md §3 — keep in lockstep with the write-path constants
that scripts/shared/database.py will own)
-----------------------------------------------------------------------------
* ``primary_country`` = the job's SINGLE distinct non-remote ISO country, or NULL
  when a scalar can't answer (0 non-remote countries, OR ≥2 distinct → NULL). Not
  tied to ``is_primary``: a job whose primary tag is remote but which has a
  non-remote secondary tag still resolves to that country. ``upper()`` matches
  the country-tier predicate's ``upper(l.country)``.
* ``search_text`` = ``lower(title ‖ RAW location ‖ company ‖ tags)`` — the same
  haystack the client ``matchesSearchTags`` builds, plus company. Recomputed from
  scratch (never appended-to) so edits/tag-deletes can't leave stale text.

USAGE
-----
    PYTHONPATH=. .venv/bin/python scripts/backfill_wave2_denorm.py
    PYTHONPATH=. .venv/bin/python scripts/backfill_wave2_denorm.py \
        --db-url postgresql://postgres:postgres@localhost:5432/jobscraper \
        --batch-size 2000 --sleep 0.1 -v
    # Also drain CLOSED rows (low priority — the hot indexes are partial on OPEN):
    PYTHONPATH=. .venv/bin/python scripts/backfill_wave2_denorm.py --include-closed
    # Preview only, touch nothing:
    PYTHONPATH=. .venv/bin/python scripts/backfill_wave2_denorm.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Allow ``python scripts/backfill_wave2_denorm.py`` from the repo root without
# PYTHONPATH, mirroring run_scraper.py's path setup.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.shared import database as db  # noqa: E402

logger = logging.getLogger("backfill_wave2_denorm")

_DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/jobscraper"

# --- Derivation SQL (WAVE2-PLAN.md §3). ``jl`` is the alias of the UPDATE target.
# NOTE: this MUST stay identical to the shared write-path expressions the
# write-path stage adds to scripts/shared/database.py — if they drift, a
# backfilled row and a freshly-written row can disagree. Kept inline here so the
# backfill is a self-contained, runnable script.
_PRIMARY_COUNTRY_EXPR = """
(SELECT CASE WHEN count(DISTINCT upper(l.country)) = 1
             THEN max(upper(l.country)) END
   FROM job_locations j2
   JOIN locations l ON l.id = j2.normalized_location_id
  WHERE j2.job_listing_id = jl.id
    AND l.kind <> 'remote' AND l.country IS NOT NULL)
"""

_SEARCH_TEXT_EXPR = """
lower(
  coalesce(jl.title, '')    || ' ' ||
  coalesce(jl.location, '') || ' ' ||
  coalesce(jl.company, '')  || ' ' ||
  coalesce((SELECT string_agg(t.tag, ' ' ORDER BY t.tag)
              FROM job_tags t
             WHERE t.source_id = jl.source_id
               AND t.job_listing_id = jl.id), '')
)
"""


def _update_sql(status: str) -> str:
    """One bounded, self-locking batch UPDATE for the given ``status``.

    The inner ``SELECT ... FOR UPDATE SKIP LOCKED`` picks up to ``batch_size``
    not-yet-filled rows that no other transaction holds, ordered freshest-first
    (the hot endpoints read the newest rows first). The outer UPDATE recomputes
    both denormalized columns for exactly those rows.
    """
    return f"""
        UPDATE job_listings jl
           SET primary_country = {_PRIMARY_COUNTRY_EXPR},
               search_text     = {_SEARCH_TEXT_EXPR}
         WHERE (jl.source_id, jl.id) IN (
             SELECT source_id, id
               FROM job_listings
              WHERE status = %(status)s
                AND search_text IS NULL
              ORDER BY first_seen_at DESC
              LIMIT %(batch)s
              FOR UPDATE SKIP LOCKED
         )
    """


_REMAINING_SQL = (
    "SELECT count(*) AS n FROM job_listings "
    "WHERE status = %(status)s AND search_text IS NULL"
)


def _scalar(cur, key: str) -> int:
    """Read a single count from a RealDictCursor row (dict) — driver-agnostic."""
    row = cur.fetchone()
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row[key])
    return int(row[0])


def backfill_status(
    conn,
    *,
    status: str,
    batch_size: int,
    sleep_s: float,
    dry_run: bool,
    max_empty_retries: int,
) -> int:
    """Drain NULL ``search_text`` rows for one ``status``. Returns rows updated."""
    with conn.cursor() as cur:
        cur.execute(_REMAINING_SQL, {"status": status})
        remaining = _scalar(cur, "n")
    logger.info("[%s] %d rows need backfill", status, remaining)
    if remaining == 0:
        return 0

    if dry_run:
        logger.info(
            "[%s] --dry-run: would backfill %d rows in ~%d batches of %d",
            status,
            remaining,
            -(-remaining // batch_size),
            batch_size,
        )
        return 0

    sql = _update_sql(status)
    total = 0
    empty_streak = 0
    while True:
        with conn.cursor() as cur:
            cur.execute(sql, {"status": status, "batch": batch_size})
            n = cur.rowcount
        conn.commit()

        if n > 0:
            total += n
            empty_streak = 0
            logger.info("[%s] +%d (total %d)", status, n, total)
            if sleep_s > 0:
                time.sleep(sleep_s)
            continue

        # n == 0: either done, or every remaining candidate is currently locked
        # by a live scrape (SKIP LOCKED yielded nothing). Distinguish the two so a
        # transient contention burst doesn't declare a premature finish.
        with conn.cursor() as cur:
            cur.execute(_REMAINING_SQL, {"status": status})
            left = _scalar(cur, "n")
        conn.commit()
        if left == 0:
            break
        empty_streak += 1
        if empty_streak > max_empty_retries:
            logger.warning(
                "[%s] gave up after %d contended empty batches with %d rows "
                "still NULL (all locked?). Re-run later to finish.",
                status,
                empty_streak,
                left,
            )
            break
        logger.info(
            "[%s] batch empty but %d rows remain (contended); retry %d/%d",
            status,
            left,
            empty_streak,
            max_empty_retries,
        )
        time.sleep(max(sleep_s, 0.5))

    logger.info("[%s] done: %d rows backfilled", status, total)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill job_listings.primary_country + search_text (Perf Wave 2).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", _DEFAULT_DB_URL),
        help="PostgreSQL URL (default: $DATABASE_URL or the local jobscraper DB).",
    )
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.1,
        help="Seconds to sleep between batches (bounds WAL/lock pressure).",
    )
    parser.add_argument(
        "--include-closed",
        action="store_true",
        help="Also drain CLOSED rows after OPEN (low priority; hot indexes are "
        "partial on OPEN).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows need backfill and exit without writing.",
    )
    parser.add_argument(
        "--max-empty-retries",
        type=int,
        default=50,
        help="Consecutive fully-contended empty batches before giving up on a "
        "status (re-run later to finish).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")

    statuses = ["OPEN"] + (["CLOSED"] if args.include_closed else [])

    # application_name is path-specific so a connection leak is attributable in
    # pg_stat_activity (get_connection's own guidance).
    conn = db.get_connection(args.db_url, application_name="backfill_wave2_denorm")
    grand_total = 0
    try:
        for status in statuses:
            grand_total += backfill_status(
                conn,
                status=status,
                batch_size=args.batch_size,
                sleep_s=args.sleep,
                dry_run=args.dry_run,
                max_empty_retries=args.max_empty_retries,
            )
    finally:
        conn.close()

    logger.info("Backfill complete: %d rows updated across %s", grand_total, statuses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
