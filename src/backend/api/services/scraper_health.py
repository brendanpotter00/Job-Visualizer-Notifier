"""Staleness probe for every enabled company's scraper.

Why this exists
---------------
Four scrapers were 100% dead in production and nothing noticed:
``appliedintuition`` (56 days dead, 16,913 consecutive failed runs),
``unity3d`` (28 days), ``fal`` (19 days) and ``merge``. Between them they
left ~460 phantom OPEN jobs in the UI. There was no alerting of any kind,
and ``/health/worker`` only inspects the Procrastinate tables — so a leaf
task that 404s forever still leaves that probe green.

Why ``job_listings.last_seen_at`` and NOT ``scrape_runs``
---------------------------------------------------------
A ``scrape_runs`` row proves only that the task *ran*. Several of the dead
scrapers were writing perfectly healthy-looking run rows while writing zero
jobs (a 404 board returns an empty list, which — on a company whose rows
have already been closed out — trips no guard). ``last_seen_at`` is the
write-side evidence: it advances only when a scrape actually observed a
job. So this catches both "the task stopped running" AND "the task reports
success but writes nothing."

Cost — read this before calling it more often
---------------------------------------------
One query, but not a cheap one. Prod ``EXPLAIN`` shows **Seq Scan on
job_listings** -> Hash Right Join -> HashAggregate (cost ~11,472; ~64k
rows / ~812 MB at time of writing). ``idx_job_listings_company`` exists
but is NOT used and could not be: the query aggregates over EVERY row —
there is no selective predicate for an index to satisfy, so a full scan is
the correct plan, and adding an index would not change it.

No new index is required — but the reason is "an index cannot help this
shape", not "an index already covers it". An earlier version of this
docstring claimed the latter, which would have misled anyone deciding
whether this is safe to call more frequently.

Practical consequence: this is sized for the ONCE-DAILY scheduled check
(.github/workflows/scraper-health.yml). It is not safe as a per-request or
polled endpoint — each call is a full-table aggregate holding a pooled
backend connection for its duration; cf.
``docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md``.

Reachability
------------
The route in front of this (``GET /api/jobs-qa/scraper-health``) carries
NO ``require_admin`` — the scheduled GitHub Action can present a static
header but cannot mint an admin JWT — so ``require_internal_key`` is its
only gate, and the public Vercel proxy holds that key unconditionally.

The proxy therefore refuses to route this path at all: ``scraper-health``
is in ``NOT_PROXIED_PATHS`` in ``api/jobs-qa.ts`` and returns 404 from the
public internet regardless of credentials. Reaching this endpoint means
talking to Railway directly with ``X-Internal-Key``.

Do NOT read that as "the proxy authenticates callers". It cannot: an
earlier attempt only checked that an ``Authorization`` header was
*present*, which ``curl -H "Authorization: x"`` trivially satisfied.
``test_proxy_denies_non_admin_jobs_qa_routes`` (in
``api/tests/test_scraper_health.py``) is what keeps the denylist in sync
with the routes that lack ``require_admin``.

Connection contract (SELECT-only): the single statement is a ``SELECT`` and
this module never commits. ``conn.rollback()`` runs in a ``finally`` so the
caller's connection is never left mid-transaction (same contract as
``location_monitor.py``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)


# One query, deliberately.
#
# * ``companies`` is NOT filtered by ``ats`` — the three script-scraped
#   companies (google/apple/microsoft, seeded with the sentinel
#   ``ats='script'``) are exactly the ones a fan-out-shaped query would
#   silently drop, and Apple is the company this whole change is about.
#   ``test_scraper_health.py`` pins that as a regression guard.
# * LEFT JOIN (not INNER) so a company with zero ``job_listings`` rows at
#   all still produces a row, with ``last_seen_at IS NULL`` — the most
#   broken state there is, and the one an INNER JOIN would hide.
# * ``hours_stale`` is computed in Postgres from ``now()`` rather than in
#   Python. Both sides of the subtraction are ``timestamptz``, so there is
#   no naive/aware mix-up and no client-clock dependency.
_STALE_QUERY = """
    SELECT
        c.id  AS company,
        c.ats AS ats,
        MAX(j.last_seen_at) AS last_seen_at,
        EXTRACT(EPOCH FROM (now() - MAX(j.last_seen_at))) / 3600.0
            AS hours_stale,
        COUNT(*) FILTER (WHERE j.status = 'OPEN') AS open_jobs
    FROM companies c
    LEFT JOIN job_listings j ON j.company = c.id
    WHERE c.enabled
    GROUP BY c.id, c.ats
    ORDER BY c.id
"""


def get_stale_companies(conn: Connection, threshold_hours: int = 24) -> dict[str, Any]:
    """Report every enabled company whose jobs have not been seen recently.

    Args:
        conn: Database connection (used read-only).
        threshold_hours: A company is stale when its most recent
            ``last_seen_at`` is older than this many hours. A company with
            no ``job_listings`` rows at all is ALWAYS stale, regardless of
            the threshold.

    Returns:
        ``{checkedAt, thresholdHours, staleCount, okCount, stale: [...]}``
        with camelCase keys (this dict is serialized straight to JSON by
        the ``/api/jobs-qa/scraper-health`` route). Each ``stale`` entry is
        ``{company, ats, lastSeenAt, hoursStale, openJobs}``;
        ``lastSeenAt``/``hoursStale`` are ``None`` for a company that has
        never had a job row.

        ``openJobs`` is the phantom-listing blast radius: rows still shown
        as OPEN in the UI that nothing has confirmed in ``hoursStale``
        hours.
    """
    try:
        with conn.cursor() as cursor:
            cursor.execute(_STALE_QUERY)
            rows = cursor.fetchall()
    finally:
        # Never leave the caller's pooled connection inside an open
        # transaction — an idle-in-transaction connection pins the xmin
        # horizon and blocks vacuum.
        conn.rollback()

    stale: list[dict[str, Any]] = []
    ok_count = 0

    for row in rows:
        last_seen = row["last_seen_at"]
        hours_stale = (
            None if row["hours_stale"] is None else float(row["hours_stale"])
        )
        # No rows at all => never scraped (or fully wiped) => stale by
        # definition; the threshold comparison can't express that.
        is_stale = last_seen is None or (
            hours_stale is not None and hours_stale > threshold_hours
        )
        if not is_stale:
            ok_count += 1
            continue

        stale.append(
            {
                "company": row["company"],
                "ats": row["ats"],
                "lastSeenAt": last_seen.isoformat() if last_seen is not None else None,
                "hoursStale": None if hours_stale is None else round(hours_stale, 2),
                "openJobs": int(row["open_jobs"] or 0),
            }
        )

    # Worst first: never-seen companies (None) sort ahead of the merely
    # overdue, then most-stale down to least.
    stale.sort(key=lambda e: (e["hoursStale"] is not None, -(e["hoursStale"] or 0.0)))

    if stale:
        logger.warning(
            "scraper-health: %d/%d enabled companies stale (>%dh): %s",
            len(stale),
            len(stale) + ok_count,
            threshold_hours,
            ", ".join(e["company"] for e in stale),
        )

    return {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "thresholdHours": threshold_hours,
        "staleCount": len(stale),
        "okCount": ok_count,
        "stale": stale,
    }


__all__ = ["get_stale_companies"]
