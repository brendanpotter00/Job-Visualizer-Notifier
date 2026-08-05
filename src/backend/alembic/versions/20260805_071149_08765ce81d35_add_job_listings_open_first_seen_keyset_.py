"""add job_listings open first_seen keyset index

Revision ID: 08765ce81d35
Revises: 18fe9c20a8fd
Create Date: 2026-08-05 07:11:49.992640+00:00

Backing index for keyset pagination on ``GET /api/jobs`` (ticket 1.3, PR-A).
Companion reading: ``docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md``
(the unimplemented lesson this ticket closes) and
``docs/incidents/2026-07-13-api-jobs-outage.md``.

WHY
---
Every Recent-Jobs page load fires three batched
``GET /api/jobs?companies=<~50 csv>&status=OPEN&limit=50000`` calls. There is no
recency bound in the SQL, so each one materializes and sorts every OPEN row the
user's companies own — ~29.5 k rows at today's scale — and ships the lot to the
browser, which then filters to 90 days client-side. The 2026-05-17 postmortem's
open action item is exactly this: *"push the time/recency filter into SQL so the
result set bounds itself."*

PR-A adds the bounded, cursor-paged server path (``?since=`` / ``?cursor=``,
``X-Next-Cursor`` response header). Its ordering is
``(first_seen_at DESC, source_id DESC, id DESC)`` — immutable sort column, made
unique by the composite-PK tiebreak — and its page boundary is a row-value
predicate on that same tuple. This index is the structure that makes both a seek
instead of a sort.

MEASUREMENTS
------------
Local prod-scale fixture: 67,650 ``job_listings`` / 29,500 OPEN / TOAST-heavy
``details`` / 50 companies / ``first_seen_at`` spread over 2 years with 3 rows
per distinct timestamp (so the tiebreak columns are genuinely exercised).
``EXPLAIN (ANALYZE, BUFFERS)`` of the real router query, 90-day ``since``:

======================================== =============================== ========== =========
query                                    plan                            buffers    time
======================================== =============================== ========== =========
page 1, ``since`` only, LIMIT 50         Index Scan Backward using this  311        0.40 ms
(WITH this index)                        index, **no Sort node**
mid-walk, ``since`` + ``cursor``,        same backward scan; the row-     313        0.44 ms
LIMIT 50 (WITH this index)               value predicate lands as an
                                         **Index Cond**, not a Filter
page 1, ``since`` only, LIMIT 50         Index Scan on                   2,001      28.1 ms
(WITHOUT this index)                     idx_job_listings_status, 8,454
                                         rows kept / 21,046 filtered,
                                         then **top-N heapsort**
TODAY'S PROD SHAPE: legacy,              Nested Loop + **external merge   61,532     588.6 ms
``limit=50000``, no bound                sort, Disk: 4,704 kB**,          (+588 temp
(unchanged by this PR)                   29,500 rows returned            blocks)
======================================== =============================== ========== =========

So: the index removes the Sort node (28.1 ms -> 0.40 ms, 6.4x fewer buffers), and
the paged path as a whole replaces a 588 ms disk-spilling 29.5 k-row scan with a
0.4 ms 50-row seek. Index size on the fixture: **1,560 kB**.

The mid-walk row is the one that matters for correctness-under-load: Postgres
turned ``ROW(first_seen_at, source_id, id) < ROW(...)`` into an ``Index Cond``,
meaning the cursor is a true index seek. A hand-expanded ``a < ca OR (a = ca AND
...)`` form does not reliably get that, which is half of why the query builder
uses the row-value form (the other half is that the expansion is where tiebreaks
get dropped and rows silently vanish).

DESIGN NOTES
------------
* **Plain ASC columns, not explicit DESC ops.** The query orders all three columns
  DESC; Postgres serves that from an all-ASC composite btree with a BACKWARD index
  scan, which the plans above confirm (``Index Scan Backward``, no Sort). ASC is
  also the autogenerate-friendly shape — ``sa.Index`` with ``.desc()`` ops does not
  round-trip through Alembic's reflection, so a DESC index would make every future
  autogenerate emit spurious drop/create churn for this index. If a future planner
  ever refuses the backward scan at scale, switch to explicit DESC ops and accept
  the autogenerate noise; today it demonstrably does not need to.
* **PARTIAL on ``status = 'OPEN'``.** Mirrors every real caller of the paged path
  (Recent Jobs fetches ``?status=OPEN`` exclusively) and follows the
  ``idx_job_listings_open_id`` precedent on this table. It keeps the index to the
  ~44 % of rows that are OPEN — which matters for steady-state disk and, because
  this table's whole 2026 history is about index bloat, for how much dead weight a
  future churn pattern could accumulate here. Any request that does NOT filter to
  OPEN — including one that simply omits ``status``, not just ``status=CLOSED`` —
  falls off this index and sorts: still correct, just unindexed, and no real caller
  does it.
* **Columns ordered ``(first_seen_at, source_id, id)``** — identical to the
  ORDER BY tuple and the row-value predicate. A keyset seek is only an index seek
  when the index key IS the sort key; any other column order degrades to a sort.

DEPLOY CONTEXT
--------------
Applied by ``alembic upgrade head`` from the FastAPI lifespan hook on Railway
startup (``src/backend/api/migrations.py``); no operator action. ``alembic.ini``
sets ``transaction_per_migration = true``, so this is one all-or-nothing
transaction.

Cost review per ``docs/implementations/alembicMigration/DEPLOY.md``:

* **``SET LOCAL lock_timeout = '5s'`` is the first statement.** ``CREATE INDEX``
  takes only SHARE (it blocks writers, not readers), so this is a milder case than
  the ACCESS EXCLUSIVE migrations in this series — but prod runs with
  ``lock_timeout = 0`` and ``statement_timeout = 0``, i.e. no bound at all. If an
  in-flight scraper write from the OLD container holds a conflicting ROW EXCLUSIVE
  lock (those statements run with a 60 s timeout, see
  ``api/tasks/fetch_greenhouse_company.py:97``), an unbounded wait would park every
  subsequent writer behind us in Postgres's FIFO lock queue and stall container
  startup. Failing fast and letting the container restart against an idle table is
  the correct behaviour. Same line, same reason, as ``01fef5c9c582``,
  ``a3c32c2aa4d3`` and ``18fe9c20a8fd``.
* **Disk cost: ~+1.6 MB** (measured on the 67,650-row fixture above; prod is the
  same order). Nowhere near the 25 %-of-volume threshold that would require a
  volume upgrade first. This is a pure ADD — no rewrite, no temp copy, no
  ``ALTER TABLE`` (so the combined-ALTER rule does not apply here).
* **NOT ``CONCURRENTLY``**, deliberately, and for the same reason as
  ``18fe9c20a8fd``'s ``idx_job_listings_problem_jobs``. Be precise about the build
  cost rather than hand-waving it: ``CREATE INDEX`` scans ``job_listings`` once —
  the partial predicate does NOT reduce that scan, since every row must be examined
  to decide whether it qualifies — but it reads only the four columns involved
  (``status``, ``first_seen_at``, ``source_id``, ``id``), never detoasting the wide
  ``details`` JSONB, and it sorts and writes only the ~29.5 k qualifying entries.
  One narrow heap scan plus a 1.6 MB sort is sub-second at this table's size, which
  is what makes the plain (non-concurrent) form fine. Meanwhile ``CREATE INDEX
  CONCURRENTLY`` cannot run inside a transaction and would need
  ``op.get_context().autocommit_block()``, forfeiting the all-or-nothing guarantee
  *and* putting the build outside the ``lock_timeout`` guard above. The
  CONCURRENTLY-via-autocommit_block pattern is right for a large index on a big
  table; it is not worth the split transaction here.

DOWNGRADE
---------
A plain ``DROP INDEX`` — genuinely cheap and lossless here, unlike the downgrades
in the freshness-sidecar series. The paged read path keeps working after a
downgrade; it just sorts instead of seeking (the 28.1 ms plan above). A full
rollback is a code revert of this PR plus this downgrade, in either order.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08765ce81d35'
down_revision: Union[str, None] = '18fe9c20a8fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MUST be first — see "DEPLOY CONTEXT" above. Prod has no lock_timeout, so
    # without this a SHARE-lock wait behind an in-flight scraper write parks every
    # subsequent writer behind us in the FIFO lock queue.
    op.execute("SET LOCAL lock_timeout = '5s'")

    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index(
        'idx_job_listings_open_first_seen_keyset',
        'job_listings',
        ['first_seen_at', 'source_id', 'id'],
        unique=False,
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # Mirrors upgrade(): DROP INDEX needs ACCESS EXCLUSIVE, and prod still has no
    # lock_timeout of its own.
    op.execute("SET LOCAL lock_timeout = '5s'")

    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        'idx_job_listings_open_first_seen_keyset',
        table_name='job_listings',
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    # ### end Alembic commands ###
