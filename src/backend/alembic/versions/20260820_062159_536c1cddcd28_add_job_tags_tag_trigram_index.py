"""add job_tags tag trigram index

Revision ID: 536c1cddcd28
Revises: 4b5d40dbc774
Create Date: 2026-08-20 06:21:59.224975+00:00

Makes the keyword filter behind ``GET /api/jobs/search`` stop full-scanning
``job_tags`` once per search term.

WHAT THE QUERY LOOKS LIKE
-------------------------
``_KEYWORD_PREDICATE`` (api/services/job_search.py) expands each term the reader
typed into::

    ( job_listings.title ILIKE '%term%'
      OR COALESCE(job_listings.location, '') ILIKE '%term%'
      OR COALESCE(job_listings.experience_level, '') ILIKE '%term%'
      OR job_listings.company ILIKE '%term%'
      OR EXISTS (SELECT 1 FROM job_tags t
                 WHERE t.source_id = job_listings.source_id
                   AND t.job_listing_id = job_listings.id
                   AND t.tag ILIKE '%term%') )

WHY A NEW INDEX
---------------
``job_tags`` carried exactly two indexes before this migration: ``job_tags_pkey``
and the plain btree ``idx_job_tags_tag`` (migration ``0fa33aca5bda``). A btree
cannot serve a LEADING-wildcard ``ILIKE``, so that ``EXISTS`` had no usable access
path at all.

Worse than it looks. Postgres DE-CORRELATES the ``EXISTS`` into a hashed
``SubPlan``, so it is not "evaluated per candidate row" — it is ONE FULL SCAN of
``job_tags`` per term, executed once (``loops=1``) and then probed. That makes the
cost **independent of LIMIT**: a 50-row page pays exactly the same tag scans as an
un-LIMITed count over the whole corpus. And page 1 runs the whole predicate TWICE
— once for the page query, once for ``get_search_counts``' ``filtered_total``
subquery — on the SAME pooled connection, against prod's ``DB_POOL_MAX=30`` /
``DB_POOL_TIMEOUT=5s``.

GIN + ``gin_trgm_ops`` is the only index class Postgres can consult for a
leading-wildcard ``ILIKE``: it indexes each value's trigrams, so ``'%backend%'``
becomes "find the rows containing the trigrams of `backend`" — a bitmap probe —
instead of an ILIKE evaluated against all 112,880 rows.

MEASURED, at prod scale, on a throwaway local corpus built to match prod
(76,030 ``job_listings`` / 31,941 OPEN / 111,831 ``job_tags`` over 9,982 distinct
tags; prod on 2026-08-20 was 76,030 / 31,941 / 112,880 over 10,488). Both
statements are the ones the endpoint actually issues, rendered through
``search_jobs``/``get_search_counts``' own SQL builders and run with the
endpoint's ``SET LOCAL jit = off`` in force. Figures are the best of 5 warm
executions, interleaved across 5 index-drop/rebuild rounds, ``limit=50``
(``RECENT_SEARCH_PAGE_SIZE``), a 133-company enabled roster, ``since`` = epoch.
Read the RATIOS, not the absolute milliseconds: this ran on PostgreSQL 15.17 in
local Docker while prod is 17.9 on Railway, and round 5's prod numbers for the
same 6-term list were 2.5-4x larger (1.73 s counts / 0.52 s page, unindexed). The
plan SHAPE — which is what this migration changes — is the same on both::

    terms | page before | page after | counts before | counts after |   total before -> after
    ------+-------------+------------+---------------+--------------+--------------------------
        1 |     36.4 ms |     4.0 ms |       80.1 ms |      46.0 ms |   116.5 ms ->   50.0 ms
        6 |    217.7 ms |    12.6 ms |      399.8 ms |     196.1 ms |   617.5 ms ->  208.6 ms
       20 |    715.2 ms |    35.4 ms |     1091.5 ms |     406.5 ms |  1806.6 ms ->  441.9 ms

1 term = "engineer"; 6 terms = the built-in ``SOFTWARE_ENGINEERING_TAGS`` list
verbatim; 20 terms = that list plus 14 keywords a reader plausibly types, i.e.
``_MAX_KEYWORDS``.

The ``job_tags`` half of the work is what moves, and it moves by ~25x. Summing
only the ``job_tags`` plan nodes (the ``loops=1`` hashed SubPlans):

    6 terms, page query:   264.9 ms -> 9.1 ms
    6 terms, counts:       257.2 ms -> 10.3 ms
    20 terms, counts:      700.9 ms -> 29.1 ms

— i.e. ~43 ms per term of full ``Seq Scan on job_tags`` (``Rows Removed by
Filter: 111831`` each) becomes ~1.5 ms per term of ``Bitmap Index Scan on
idx_job_tags_tag_trgm``. What remains in the counts statement is the FOUR
un-indexed ``ILIKE``s per term over the OPEN corpus's ``job_listings`` rows —
untouched by this index, and a separate problem if it ever becomes the binding
one. For reference, the no-keyword floor for the same pair is 13.0 ms (1.0 ms
page + 12.0 ms counts), so six keywords now add ~196 ms to a page-1 load rather
than ~605 ms.

KNOWN BLIND SPOT
----------------
A term shorter than THREE characters contains no complete trigram, so pg_trgm can
extract no index key and the planner correctly keeps the ``Seq Scan``. ``go``,
``ai`` and ``ml`` are all real, high-frequency tags in this corpus, and a reader
typing one of them still gets the ``Seq Scan`` — measured at 110-118 ms of DB
time for that ONE term, against 50 ms for a single 3+ character term with the
index and 13 ms for the no-keyword floor. This index neither helps nor harms
those; it is a ceiling on how much of the keyword cost is recoverable this way,
not a defect in the index.

COST REVIEW
-----------
* **Disk:** 3.9 MB measured at 111,831 rows (vs 1.5 MB for the existing plain
  btree on the same column). GIN stores one posting list per distinct trigram,
  and this column is short — avg 11 chars in prod.
* **Build:** **209-238 ms measured** at prod scale (5 builds, plain
  ``CREATE INDEX``; median 229 ms). It reads one narrow ``text`` column of a
  21 MB table and never touches ``job_listings`` or its TOAST. This runs at BOOT
  — see the transaction note below — so that quarter-second is added to the
  FastAPI lifespan's migration step exactly once, on the deploy that lands it.
* **Write amplification:** the only writer is the enrichment write-back
  (``services/enrichment_writer.py``, ``services/enrichment_monitor.py``), and its
  pattern is ``DELETE FROM job_tags WHERE source_id=… AND job_listing_id=…``
  followed by a row-per-tag ``INSERT`` — the PK is all three columns, so a tag can
  only be replaced, never updated in place. That is a per-JOB churn, not a
  per-CYCLE one: a row is rewritten when it is first enriched, when an admin
  corrects it, and when it is re-enriched, and NOT on the hourly scrape (which
  touches ``job_listings``/``job_freshness``, not this table). Prod rate,
  2026-08-20: 3,672 ``job_enrichment`` rows written in the last 7 days = ~525/day,
  at ~1.5 tags per listing — so on the order of 800 index entries a day against a
  111k-entry index. A very different regime from the ``last_seen_at`` churn that
  produced the 2026-07-13 index-bloat outage (every OPEN row, every hour).
  GIN's pending list (``fastupdate``, on by default) batches
  the insert half; the delete half leaves dead entries that autovacuum reclaims,
  same as it already does for ``idx_job_tags_tag``.
* **Lock class:** ``SHARE`` for the duration of the build — blocks writes to
  ``job_tags``, not reads. Bounded by the ``lock_timeout`` below.

Plain ``CREATE INDEX``, not ``CONCURRENTLY``, and that is FORCED rather than
preferred: migrations run inside a transaction from the FastAPI lifespan hook
(``api/migrations.py`` ``apply_alembic_migrations_with_retry``, with
``transaction_per_migration = true`` in alembic.ini), and
``CREATE INDEX CONCURRENTLY`` cannot run in a transaction block at all. Making it
concurrent would mean an ``autocommit_block`` that forfeits the per-migration
transaction AND escapes the ``lock_timeout`` guard below — the same trade-off
``08765ce81d35`` and ``4b5d40dbc774`` document, and at a ~230 ms build the
trade is not close.

``SET LOCAL lock_timeout`` is the FIRST statement in both directions: prod runs
with ``lock_timeout = 0``, so a DDL statement that cannot get its lock waits
forever AND queues every subsequent reader behind it. Five seconds turns a
contended deploy into a failed migration (visible, retryable) instead of an
outage.

THE EXTENSION IS CREATED HERE AND NEVER DROPPED
-----------------------------------------------
``pg_trgm`` has been a TRUSTED extension since PostgreSQL 13, so
``CREATE EXTENSION`` needs only ``CREATE`` on the database, not superuser. Prod is
PostgreSQL 17.9 with ``pg_trgm`` 1.6 available and marked trusted, and
``pg_extension`` currently holds only ``{plpgsql}`` (all verified read-only,
2026-08-20).

The privilege question was checked rather than assumed, because it is the one way
this migration could fail at boot on prod and nowhere else: prod has exactly two
login roles — ``claude_readonly`` (the analysis MCP, no CREATE anywhere) and
``postgres``, which is the database OWNER and a superuser — and
``pg_stat_activity`` shows the app's own pools (``fastapi_pool``,
``procrastinate_worker``) connected as ``postgres``. So the role that will run this
already has more than the trusted-extension path needs.

``downgrade()`` drops the INDEX but deliberately does NOT drop the EXTENSION.
An extension is a DATABASE-GLOBAL object, not a table-scoped one: any other
object created since — another index, a generated column, a view calling
``similarity()`` — depends on it, so a bare ``DROP EXTENSION`` would either fail
(leaving the downgrade half-applied) or, with ``CASCADE``, silently destroy
objects this migration never created and cannot know about. The asymmetry is
correct rather than sloppy. ``CREATE EXTENSION IF NOT EXISTS`` is idempotent and
costs ~14 ms, so leaving it installed after a downgrade costs a few hundred KB of
catalog and nothing else, while removing it can break unrelated things. Same
reasoning ``api/db_models.py`` records for the pg_trgm ``before_create`` hook.

The index is mirrored in ``api/db_models.py`` (``JobTag.__table_args__``) together
with a ``before_create`` DDL hook that installs the extension, so the
``create_all``-based test/parity bootstrap and this migration produce the same
schema — otherwise ``create_all`` would fail outright on
``operator class "gin_trgm_ops" does not exist``.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '536c1cddcd28'
down_revision: Union[str, None] = '4b5d40dbc774'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # WITH SCHEMA public, explicitly: a bare CREATE EXTENSION lands in the first
    # entry of search_path, which under the tests' PYTEST_SCHEMA isolation is a
    # per-module `test_<hex>` schema that is dropped CASCADE at teardown — taking
    # gin_trgm_ops with it. In prod, public IS the schema.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
    op.create_index(
        'idx_job_tags_tag_trgm',
        'job_tags',
        ['tag'],
        unique=False,
        postgresql_using='gin',
        postgresql_ops={'tag': 'gin_trgm_ops'},
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index('idx_job_tags_tag_trgm', table_name='job_tags')
    # pg_trgm is deliberately NOT dropped — see the module docstring. An
    # extension is database-global; anything else that has come to depend on it
    # would either block this downgrade or be destroyed by a CASCADE.
