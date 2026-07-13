"""resync job_freshness from job_listings

Revision ID: a3c32c2aa4d3
Revises: 01fef5c9c582
Create Date: 2026-07-13 14:23:32.742813+00:00

Data-only migration (no DDL, no schema change) shipped WITH Units 2-3 of the
2026-07-13 ``/api/jobs`` outage fix — the deploy that repoints the write path to
``job_freshness`` and the read path to a ``JOIN job_freshness``.

Why it is needed
----------------
Unit 1 (expand) backfilled ``job_freshness`` from ``job_listings`` at that
migration's time, then left the OLD write path in place: for the entire
Unit-1-only window the scraper kept stamping ``job_listings.last_seen_at`` /
``consecutive_misses`` every cycle while ``job_freshness`` stayed frozen at the
backfill snapshot (the AFTER INSERT trigger only fires for *new* listings). So by
the time this deploy flips the read path onto the sidecar, the sidecar is stale
for every listing re-seen during that window.

This one-shot ``UPDATE`` copies each listing's current ``job_listings`` freshness
into ``job_freshness`` so the sidecar is authoritative and accurate at the exact
moment reads switch to it. Alembic runs in the FastAPI lifespan BEFORE the new
code serves a request, so the correction lands before the first sidecar-backed
read.

The ``IS DISTINCT FROM`` guard updates only rows that actually drifted — no dead
tuples for already-correct rows, which keeps this hot little table's heap/index
tight (the whole point of the sidecar).

Rolling-deploy note: old (Unit-1) instances may still bump
``job_listings.last_seen_at`` for a few seconds after this runs, briefly nudging
the sidecar behind for those ids. That is cosmetic (the frontend re-sorts by
``created_at``) and self-heals on the next scrape, when the new write path stamps
``job_freshness`` directly.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a3c32c2aa4d3'
down_revision: Union[str, None] = '01fef5c9c582'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bound lock acquisition so a long-running scrape writer can't stall startup
    # (mirrors the Unit-1 migration). This UPDATE only touches job_freshness and
    # reads job_listings (ACCESS SHARE) — no rewrite of either table.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        UPDATE job_freshness f
        SET last_seen_at = l.last_seen_at,
            consecutive_misses = COALESCE(l.consecutive_misses, 0)
        FROM job_listings l
        WHERE f.source_id = l.source_id
          AND f.id = l.id
          AND (f.last_seen_at IS DISTINCT FROM l.last_seen_at
               OR f.consecutive_misses IS DISTINCT FROM COALESCE(l.consecutive_misses, 0))
        """
    )


def downgrade() -> None:
    # No-op: this migration only makes job_freshness a more accurate copy of
    # job_listings. Rolling back to Unit-1-only code leaves an accurate sidecar
    # that the old code simply ignores — there is nothing to undo, and the
    # source values it was derived from still live on job_listings until Unit 4.
    pass
