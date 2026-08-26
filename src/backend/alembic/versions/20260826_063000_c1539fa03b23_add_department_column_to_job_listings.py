"""add denormalized department column to job_listings

Revision ID: c1539fa03b23
Revises: 7a4c1e93b6d8
Create Date: 2026-08-26 06:30:00.000000+00:00

``Job.department`` reached no screen. The frontend transformer reads
``details.department``, but ``/api/jobs`` builds its ``details`` payload from a
two-key ``jsonb_build_object('experience_level', …, 'is_remote_eligible', …)``
(``api/services/database.py``), so ``department`` was never in the response at
all: ``selectAvailableDepartments`` returned ``[]`` and ``GraphFilters`` hid the
Department control entirely.

**Why a third denormalized column and not ``details->>'department'``.** Adding a
JSONB key access to that projection is precisely the TOAST detox that took
``/api/jobs`` down on 2026-07-13 — extracting one key forces Postgres to detoast
the whole ~10 KB ``details`` value per row, and on the batched list query that is
~100 MB of TOAST reads inside a 30 s statement timeout. ``experience_level`` and
``is_remote_eligible`` are already denormalized for exactly this reason
(5ee285a3c724); ``department`` joins them and the read path still never touches
``details``.

**The ADD is catalog-only.** One nullable column, no default -> a metadata-only
change on PG 17, no table rewrite regardless of the 78 k rows
(docs/incidents/2026-04-18-migration-filled-postgres-volume/).

**Unlike 5ee285a3c724 this one DOES backfill**, because the situations differ.
When the two columns above were added, the API had never served those values, so
"populated by the next scrape" cost nothing anyone could see. Here the fix is
user-visible the moment the column has data and invisible until it does: with no
backfill the Department control stays hidden for a full scrape cycle after
deploy, and stays hidden **indefinitely** for any company whose scraper is
currently failing. So the backfill is the difference between shipping the fix and
shipping the plumbing for it.

Backfill cost, measured — not estimated. Prod today: 78 307 rows, 40 024 with a
non-empty ``details->>'department'``, 105 MB heap / 32 MB indexes / 705 MB TOAST.

* **Read.** Every chunk must detoast ``details`` to read one key; there is no way
  around that, which is exactly why the read path must never do it. Sampled on
  prod with ``EXPLAIN (ANALYZE, BUFFERS)``, 2 000 rows detoast in **94 ms**, so
  the whole table is ~4 s of read work warm. Call it ~15 s cold.
* **Write.** Only rows that actually have a department are touched, and only
  while ``department IS NULL``. On a 78 306-row replica of this shape the
  backfill grew the heap 25 -> 37 MB and the indexes 11 -> 14 MB, and left TOAST
  **unchanged at 309 MB** — an UPDATE that does not modify a toasted column
  copies the TOAST pointer rather than rewriting the value. Scaled to prod's
  4x wider heap that is ~50 MB of heap churn + ~10 MB of index churn, plus
  comparable WAL, against a 1 711 MB database. Nowhere near the 2026-04-18
  volume incident's class of cost.
* **Wall clock.** 2.9 s on the 78 306-row synthetic replica and **1.9-2.9 s on a
  restored copy of the real dev database** (50 936 rows, 31 701 with a
  department, whole chain replayed). Prod has ~2x the TOAST and slower disk, so
  budget ~5-15 s. Migrations run in-process at backend boot on a connection with
  **no** statement timeout (``migrations.py`` augments the URL with
  ``statement_timeout_ms=None``) and ``railway.toml``'s healthcheckTimeout is
  600 s, so this fits the boot budget with a wide margin. Chunked at 2 000 rows
  regardless, so no single statement is long-running.

**Lock window (the one real cost, stated plainly).** ``ADD COLUMN`` takes an
ACCESS EXCLUSIVE lock on ``job_listings``, and Alembic runs a revision inside a
single transaction, so the lock is held for the backfill as well — roughly 5-15 s
during which ``/api/jobs`` reads and scraper writes on the still-serving old
container block. Splitting the transaction (commit the ADD, then backfill under
a mere ROW EXCLUSIVE lock) was tried and **rejected**: a mid-revision
``conn.commit()`` on Alembic's bind makes ``context.begin_transaction()``'s
version-table UPDATE a no-op, and the run finishes with the data migrated but
``alembic_version`` still on the PREVIOUS revision — verified against a copy of
the dev database, where head stayed at ``7a4c1e93b6d8``. That is the same
transaction-nesting trap ``alembic/env.py::_cutover_legacy_alembic_version``
documents. A stuck version tracker is a far worse failure than a brief lock, so
this stays one transaction. If the window ever needs to go away, the answer is a
separate one-shot operational script, not a split revision.

The chunked UPDATE is restartable: it only ever writes rows where
``department IS NULL``, so a re-run skips everything already done and never
clobbers a value a concurrent scrape wrote in between. That matters because the
single transaction means a failure rolls the whole revision back — but a
*subsequent* revision, or a manual partial fill, still leaves rows this can
safely finish.

The matching ``create_all`` DDL in ``api/db_models.py`` changes in lockstep — the
test databases build their schema from that, not from this migration body.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1539fa03b23'
down_revision: Union[str, None] = '7a4c1e93b6d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Rows per backfill statement. Small enough that one UPDATE stays sub-second even
# when every row in the chunk has to be detoasted and rewritten; large enough
# that the whole table is ~40 statements, not thousands of round trips.
_CHUNK_ROWS = 2000

# Walk the table in primary-key order — job_listings' PK is the composite
# (source_id, id), and a row-value comparison against it is a plain index range
# scan. ``OFFSET :off LIMIT 1`` returns the LAST key of the next chunk, or no row
# at all once fewer than a chunk remains (which is how the loop terminates).
_NEXT_CHUNK_BOUND = sa.text(
    "SELECT source_id, id FROM job_listings"
    " WHERE (source_id, id) > (:last_source_id, :last_id)"
    " ORDER BY source_id, id"
    " OFFSET :offset LIMIT 1"
)

# ``department IS NULL`` is what makes this restartable AND cheap: rows already
# filled (by a previous partial run, or by a scrape that landed mid-backfill)
# are skipped, so no row is written twice and no fresher value is clobbered.
# ``nullif(..., '')`` keeps an empty-string department out of the column, so the
# frontend's ``Boolean(details.department)`` checks agree with the DB.
_BACKFILL_SET = (
    "UPDATE job_listings SET department = nullif(details->>'department', '')"
    " WHERE (source_id, id) > (:last_source_id, :last_id)"
)
_BACKFILL_ONLY_EMPTY = (
    " AND department IS NULL"
    " AND nullif(details->>'department', '') IS NOT NULL"
)
_BACKFILL_CHUNK = sa.text(
    _BACKFILL_SET
    + " AND (source_id, id) <= (:end_source_id, :end_id)"
    + _BACKFILL_ONLY_EMPTY
)
# The final chunk has no upper bound — fewer than _CHUNK_ROWS keys remain, so it
# runs to the end of the table. Spelled as its own statement rather than a
# nullable-bound branch inside the one above, which reads clearer and keeps both
# statements index-range-scannable.
_BACKFILL_TAIL = sa.text(_BACKFILL_SET + _BACKFILL_ONLY_EMPTY)


def _backfill_department(conn) -> int:
    """Copy ``details->>'department'`` into the new column, chunk by chunk.

    Returns the number of rows written. Bounded by construction: each statement
    covers at most ``_CHUNK_ROWS`` primary keys, and the walk advances strictly
    forward through the PK order, so it terminates even if rows are inserted
    behind it while it runs.
    """
    last_source_id, last_id = "", ""
    written = 0
    while True:
        bound = conn.execute(
            _NEXT_CHUNK_BOUND,
            {
                "last_source_id": last_source_id,
                "last_id": last_id,
                "offset": _CHUNK_ROWS - 1,
            },
        ).fetchone()
        end_source_id, end_id = (bound[0], bound[1]) if bound else (None, None)

        params = {"last_source_id": last_source_id, "last_id": last_id}
        if bound is None:
            result = conn.execute(_BACKFILL_TAIL, params)
        else:
            result = conn.execute(
                _BACKFILL_CHUNK,
                {**params, "end_source_id": end_source_id, "end_id": end_id},
            )
        written += result.rowcount or 0

        if bound is None:
            # No key sat _CHUNK_ROWS ahead, so that chunk ran open-ended to the
            # end of the table and there is nothing left to walk.
            return written
        last_source_id, last_id = end_source_id, end_id


def upgrade() -> None:
    # Catalog-only: nullable, no default -> no table rewrite, whatever the row
    # count. It does take an ACCESS EXCLUSIVE lock on job_listings, and Alembic
    # runs the whole revision in one transaction, so that lock is held across the
    # backfill too — see the "lock window" note in the module docstring for why
    # that is accepted rather than engineered away.
    op.execute("ALTER TABLE job_listings ADD COLUMN department TEXT")
    _backfill_department(op.get_bind())


def downgrade() -> None:
    op.execute("ALTER TABLE job_listings DROP COLUMN department")
