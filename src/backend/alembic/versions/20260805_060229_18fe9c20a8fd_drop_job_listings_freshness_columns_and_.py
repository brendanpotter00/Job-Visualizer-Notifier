"""drop job_listings freshness columns and index, add normalization_failed partial index

Revision ID: 18fe9c20a8fd
Revises: a3c32c2aa4d3
Create Date: 2026-08-05 06:02:29.913182+00:00

Unit 4 — the CONTRACT step of the ``job_freshness`` expand -> migrate -> contract
sequence. Full background: ``docs/incidents/2026-07-13-api-jobs-outage.md`` and
``src/backend/docs/job-listings-bloat.md``.

WHY
---
``job_listings.last_seen_at`` was re-stamped on every OPEN row on every hourly
scrape cycle. Because it was INDEXED, every one of those ~182 M lifetime updates
was a non-HOT update: it appended a dead btree entry at the high end of
``idx_job_listings_last_seen`` — exactly where an ``ORDER BY last_seen_at DESC``
scan enters. The index reached 46,800,896 B (44.6 MiB) / 691.8 bytes-per-row for
67,648 rows, against 1,851,392 B (1.8 MiB) / 27.4 bytes-per-row for the
apples-to-apples ``idx_job_freshness_last_seen`` (same type, same row count).

Units 1–3 fixed that by moving the two churny columns onto the narrow
``job_freshness`` sidecar: ``01fef5c9c582`` created the table + the AFTER INSERT
trigger + the backfill, ``a3c32c2aa4d3`` re-synced it, and PR #224 repointed both
the write path (``scripts/shared/database.py``) and the read paths
(``api/services/database.py``, ``api/services/location_admin.py``) at the
sidecar. That cutover went live 2026-08-05 04:39 UTC.

Since the cutover **nothing writes and nothing reads these two columns** — they
are dead weight that still costs disk and still drags the index along. Verified
read-only against prod before authoring this revision: zero pre-cutover
``job_listings`` freshness re-stamps since the cutover, ``job_listings`` HOT
update rate flipped 0.115 % -> ~91 %, both ``job_listings ⟕ job_freshness``
anti-joins are 0 (so the read-side INNER JOIN is lossless), and the resync is
fully applied (``freshness_behind = 0``).

The AFTER INSERT trigger ``job_freshness_sync()`` seeds the sidecar from
``NEW.first_seen_at`` and a literal ``0`` — it never referenced
``NEW.last_seen_at`` / ``NEW.consecutive_misses`` — so dropping these columns
does not touch it. The trigger, the function, and the sidecar's fillfactor /
autovacuum reloptions are all deliberately left alone here.

Per the 2026-08-04 disposition in the postmortem, this revision sets **no**
storage parameters on ``job_listings``: autovacuum tuning was refuted as a fix
for this table, and ticket 1.2 requires ``job_listings.reloptions`` stay NULL.

ALSO: a partial index for the admin problem-jobs queue
-----------------------------------------------------
``location_admin.list_problem_jobs`` runs two statements: a paged query and a
bounded ``count(*)``. Both filter ``normalization_status = 'failed' AND location
IS NOT NULL AND btrim(location) <> ''``, and both used to reach their rows via a
backward scan of ``idx_job_listings_last_seen``. Unit 3 moved the ORDER BY onto
the sidecar, which left the count with no usable index at all — prod plans it as
a full ``Seq Scan on job_listings`` (cost 14,627.94) over the wide parent, the
bulk of the 13.6 ms -> 206 ms regression. ``idx_job_listings_problem_jobs`` fixes
that half.

Its predicate mirrors the query's WHERE clause EXACTLY, all three clauses
including the ``btrim`` form. That is a correctness requirement, not tidiness:
Postgres uses a partial index only when the query predicate *implies* the index
predicate, and for a function expression that needs a structurally identical
clause. Measured on a prod-like fixture (67,650 rows / 6,765 failed / 182 with a
non-blank location / TOAST-heavy ``details``), ``count(*)``:

===================================== ================ =========
index                                 plan             time
===================================== ================ =========
none                                  Seq Scan,        7.59 ms
                                      67,468 filtered
``WHERE normalization_status =        Bitmap: 6,765    3.24 ms
'failed'`` only                       scanned, 6,583
                                      recheck-dropped,
                                      1,989 heap blks
this predicate (all three clauses)    Bitmap Index     0.05 ms
                                      Scan, 182
                                      entries, no
                                      recheck
===================================== ================ =========

Prod distribution makes the difference stark: 6,709 of 67,654 rows are
``failed`` (9.9 %), but only **182** of those have a non-blank location. The
equality-only predicate would index 37x more rows than any query wants and throw
~97 % of them away on the heap recheck.

SCOPE — the PAGED query is NOT fixed by this index, and is not made worse.
It keeps its ``Nested Loop`` driven by ``idx_job_freshness_last_seen`` (prod cost
751 for LIMIT 50) either way, because the planner estimates 6,137 matching rows —
it cannot know the selectivity of ``btrim(location) <> ''`` (actual ~182) — so
the LIMIT-friendly ordered path always wins on estimated cost. Forcing the better
plan (12.5 ms / 750 buffers vs 53.8 ms / 99,463 measured locally) would need
expression statistics on ``btrim(location)``. Deliberately out of scope here.

DEPLOY CONTEXT
--------------
Applied by ``alembic upgrade head`` from the FastAPI lifespan hook on Railway
startup (``src/backend/api/migrations.py``); no operator action. ``alembic.ini``
sets ``transaction_per_migration = true``, so everything below is one
all-or-nothing transaction.

**``SET LOCAL lock_timeout = '5s'`` is the first statement, and it is
load-bearing.** Prod runs with ``lock_timeout = 0`` and ``statement_timeout = 0``
— no bound at all. ``DROP INDEX`` and ``ALTER TABLE`` both need ACCESS EXCLUSIVE
on ``job_listings``; if an in-flight scraper write from the OLD container holds a
conflicting lock (those statements run with a 60 s timeout, see
``api/tasks/fetch_greenhouse_company.py:97``), the unbounded wait would park
EVERY subsequent reader behind us in Postgres's FIFO lock queue — an unbounded
startup stall AND an ``/api/jobs`` outage, from a migration that is otherwise
instant. Failing fast and letting the container restart is the correct behaviour;
the next attempt hits an idle table. Same line, same reason, as ``01fef5c9c582``
and ``a3c32c2aa4d3``.

Cost review per ``docs/implementations/alembicMigration/DEPLOY.md``:

* **The two DROP COLUMNs are ONE combined ``ALTER TABLE``** (Rule 2 / the
  2026-04-18 volume incident), following the ``5ee285a3c724`` precedent of a raw
  ``op.execute`` rather than two ``op.drop_column`` calls. Postgres ``DROP
  COLUMN`` is catalog-only anyway (the attribute is marked dropped; no heap
  rewrite, no temp copy), so the disk-cost estimate is ~0 either way — the
  combined form is kept because the review rule is the review rule.
* **``DROP INDEX idx_job_listings_last_seen`` FREES ~46 MB.** It is the one
  statement here that changes disk usage, and it changes it downward.
* **Writes to ``job_listings`` are blocked for the WHOLE migration**, not just
  for one statement. The first ``DROP INDEX`` takes ACCESS EXCLUSIVE and, being
  inside a transaction, holds it until COMMIT. Every statement below therefore
  runs behind that same lock. This is acceptable only because the total work is
  metadata plus a 16 kB index build — but state it plainly rather than reasoning
  per-statement.
* **``CREATE INDEX idx_job_listings_problem_jobs`` is NOT CONCURRENT**,
  deliberately. The predicate restricts it to 182 rows of ~67k, so the build is
  sub-second — and it is already inside the ACCESS EXCLUSIVE window above, so
  CONCURRENTLY would buy nothing here anyway. ``CREATE INDEX CONCURRENTLY``
  cannot run inside a transaction, so using it would mean an
  ``op.get_context().autocommit_block()`` — which would forfeit the
  all-or-nothing guarantee for a migration whose other statements are
  destructive, and would put the index build outside the lock_timeout guard
  above. (The CONCURRENTLY-via-autocommit_block pattern is the right call for a
  large index on a big table; it is not worth the split transaction here.)

DOWNGRADE CAVEAT — READ BEFORE RUNNING IT
-----------------------------------------
``downgrade()`` restores the **schema**, not the data-from-thin-air. The values
are re-hydrated from ``job_freshness`` (the authoritative source since the
cutover), which is why the downgrade is not a plain ``add_column``: autogenerate
emitted ``ADD COLUMN last_seen_at ... NOT NULL`` with no default, which would
fail outright on a non-empty table. The backfill ``UPDATE`` rewrites every
``job_listings`` row — the exact write amplification this whole sequence exists
to avoid — so treat downgrade as a real maintenance operation, not a cheap undo.

And note that a downgrade alone does not restore the old behaviour: the write
path no longer stamps these columns, so once restored they immediately start
going stale. A true rollback is a code revert of PR #224 + this PR, then this
downgrade.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '18fe9c20a8fd'
down_revision: Union[str, None] = 'a3c32c2aa4d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MUST be first — see "DEPLOY CONTEXT" above. Prod has no lock_timeout, so
    # without this an ACCESS EXCLUSIVE wait behind an in-flight scraper write
    # parks every reader behind us in the FIFO lock queue.
    op.execute("SET LOCAL lock_timeout = '5s'")

    # Drop the bloated index FIRST: dropping the column would drop it implicitly,
    # but doing it explicitly keeps the ~46 MB reclaim visible in the revision.
    # This takes the ACCESS EXCLUSIVE lock that every statement below inherits
    # until COMMIT.
    op.drop_index(op.f('idx_job_listings_last_seen'), table_name='job_listings')

    # One combined, catalog-only ALTER TABLE (Postgres DROP COLUMN does not
    # rewrite the heap) — see the combined-ALTER rule in
    # docs/implementations/alembicMigration/DEPLOY.md.
    op.execute(
        """
        ALTER TABLE job_listings
            DROP COLUMN last_seen_at,
            DROP COLUMN consecutive_misses
        """
    )

    # Partial index for the admin problem-jobs count (see module docstring).
    # The predicate must stay structurally identical to list_problem_jobs' WHERE
    # clause or the planner will not use it.
    op.create_index(
        'idx_job_listings_problem_jobs',
        'job_listings',
        ['normalization_status'],
        unique=False,
        postgresql_where=sa.text(
            "normalization_status = 'failed' AND location IS NOT NULL "
            "AND btrim(location) <> ''"
        ),
    )


def downgrade() -> None:
    # Mirrors upgrade(): the backfill below needs ACCESS EXCLUSIVE just as much,
    # and prod still has no lock_timeout of its own.
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.drop_index(
        'idx_job_listings_problem_jobs',
        table_name='job_listings',
        postgresql_where=sa.text(
            "normalization_status = 'failed' AND location IS NOT NULL "
            "AND btrim(location) <> ''"
        ),
    )

    # Add both columns NULLABLE in one combined ALTER. `last_seen_at` cannot come
    # back as NOT NULL directly (no default, non-empty table); it is tightened
    # after the backfill below. `DEFAULT 0` on an integer column is a non-volatile
    # default, so PG 11+ stores it in the catalog without rewriting the table.
    op.execute(
        """
        ALTER TABLE job_listings
            ADD COLUMN last_seen_at       TIMESTAMP WITH TIME ZONE,
            ADD COLUMN consecutive_misses INTEGER DEFAULT 0
        """
    )

    # Re-hydrate from the sidecar — the authoritative source since the cutover.
    # The composite FK + AFTER INSERT trigger guarantee one job_freshness row per
    # listing, so this covers every row. This UPDATE rewrites the whole table.
    op.execute(
        """
        UPDATE job_listings jl
           SET last_seen_at       = f.last_seen_at,
               consecutive_misses = f.consecutive_misses
          FROM job_freshness f
         WHERE f.source_id = jl.source_id
           AND f.id        = jl.id
        """
    )

    # Belt and braces: if the invariant above were ever violated, fall back to
    # first_seen_at rather than failing the SET NOT NULL with an opaque error.
    op.execute(
        "UPDATE job_listings SET last_seen_at = first_seen_at "
        "WHERE last_seen_at IS NULL"
    )

    op.execute(
        "ALTER TABLE job_listings ALTER COLUMN last_seen_at SET NOT NULL"
    )

    op.create_index(
        op.f('idx_job_listings_last_seen'),
        'job_listings',
        ['last_seen_at'],
        unique=False,
    )
