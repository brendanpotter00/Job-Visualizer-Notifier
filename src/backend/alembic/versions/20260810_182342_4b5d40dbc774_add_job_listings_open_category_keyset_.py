"""add job_listings open category keyset index

Revision ID: 4b5d40dbc774
Revises: c7a41b93e5d2
Create Date: 2026-08-10 18:23:42.567022+00:00

Serves the filtered keyset walk behind ``GET /api/jobs/search``, which moved the
Recent Jobs page's filtering from the browser into SQL.

WHAT THE QUERY LOOKS LIKE
-------------------------
    SELECT ... FROM job_listings JOIN job_freshness f ON ...
    WHERE status = 'OPEN'
      AND enrichment_category = 'software_engineering'
      AND enrichment_level = ANY('{entry,new_grad}')
      AND first_seen_at >= $since
      AND (first_seen_at, source_id, id) < ($cursor_ts, $cursor_src, $cursor_id)
    ORDER BY first_seen_at DESC, source_id DESC, id DESC
    LIMIT 100

WHY A NEW INDEX
---------------
The existing ``idx_job_listings_open_first_seen_keyset`` (first_seen_at,
source_id, id) WHERE status='OPEN' is the only index whose key IS the sort key,
so the planner picks it — but the enrichment predicates then become a heap
``Filter``. Roughly 65% of OPEN rows are unenriched and most of the rest are
other categories, so a narrow filter has to walk and heap-probe nearly the whole
corpus before ``LIMIT`` is satisfied. ``software_engineering + intern`` is 129 of
~31,200 OPEN rows in prod: 99.6% of the scan is discarded work, and every
discarded entry costs a heap fetch.

The two existing enrichment indexes ((status, enrichment_category) and
(status, enrichment_level)) cannot help: neither carries the sort tuple, so
choosing one means a bitmap scan plus a full Sort of the matching set — which
loses to the ordered path on estimated cost, and would forfeit the LIMIT-friendly
plan the whole keyset design exists to get.

COLUMN ORDER
------------
Equality predicate first, then the ORDER BY tuple verbatim: that is what turns
the category into an index seek and leaves the remaining entries already in sort
order. Same rationale as ``08765ce81d35``.

FOUR columns, not five — ``enrichment_level`` is deliberately NOT wedged in
between. Doing so would order entries by level *within* a category, destroying
the usable ordering for a category-only query (the common case: the user picks
"Software Engineering" and no level). It would buy little even for
category+level, since the flagship ``entry`` selection expands to
``= ANY('{entry,new_grad}')``, which cannot ordered-seek a non-leading column.
Level rides along as a heap filter on rows that are fetched anyway.

No level-leading twin index for the same reason, plus: level-only queries fall
back to a bitmap on ``idx_job_listings_status_level`` and a top-N sort of a
few-thousand-row set — milliseconds at this scale, and not worth a third
enrichment index on the table whose entire 2026 history is index-bloat
management.

COST REVIEW
-----------
* **Disk:** ~31,200 OPEN entries x ~85 B (nullable text category + 8 B timestamp
  + source_id + id + item overhead) = **~3 MB**, the same order as
  ``idx_job_listings_open_first_seen_keyset`` (1.6 MB measured for its 3 columns).
* **Build:** one heap scan evaluating ``status = 'OPEN'``, reading four narrow
  columns. It never touches ``details``, so no TOAST reads (the 2026-07-13
  outage's failure mode). Sub-second at prod scale.
* **Write amplification:** one more index to maintain on INSERT and on any UPDATE
  touching an indexed column. ``enrichment_category`` is written once per row by
  the enricher write-back; ``first_seen_at`` is immutable. Negligible.
* **Lock class:** ``SHARE`` for the duration of the build (blocks writes, not
  reads). Bounded by the ``lock_timeout`` below.

Plain ``CREATE INDEX``, not ``CONCURRENTLY``: the build is sub-second, and
CONCURRENTLY would require an ``autocommit_block`` that forfeits
``transaction_per_migration`` (alembic.ini) and escapes the lock_timeout guard —
the same trade-off ``08765ce81d35`` documents.

``SET LOCAL lock_timeout`` is the FIRST statement in both directions: prod runs
with ``lock_timeout = 0``, so a DDL statement that cannot get its lock waits
forever AND queues every subsequent reader behind it. Five seconds turns a
contended deploy into a failed migration (visible, retryable) instead of an
outage.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b5d40dbc774'
down_revision: Union[str, None] = 'c7a41b93e5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_index(
        'idx_job_listings_open_category_keyset',
        'job_listings',
        ['enrichment_category', 'first_seen_at', 'source_id', 'id'],
        unique=False,
        postgresql_where=sa.text("status = 'OPEN'"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(
        'idx_job_listings_open_category_keyset',
        table_name='job_listings',
        postgresql_where=sa.text("status = 'OPEN'"),
    )
