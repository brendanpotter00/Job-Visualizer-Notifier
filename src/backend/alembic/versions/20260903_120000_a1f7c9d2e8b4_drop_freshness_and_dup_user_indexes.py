"""drop idx_job_freshness_last_seen + duplicate users indexes

Revision ID: a1f7c9d2e8b4
Revises: 776b9dbc68cc
Create Date: 2026-09-03 12:00:00.000000+00:00

Wave-1 performance pass, item C1 + index hygiene. Companion reading:
``docs/implementations/performance-audit/{SCHEMA-AUDIT,ACCESS-PATTERNS-AUDIT,
WAVE1-PLAN}.md`` and ``src/backend/docs/job-listings-bloat.md``.

Three index DROPs, no ADD — this migration only removes dead weight.

WHY — ``idx_job_freshness_last_seen`` (the headline)
----------------------------------------------------
``job_freshness.last_seen_at`` is re-stamped on every OPEN row on every scrape
cycle (~69.5 M lifetime updates at audit time). Indexing that column makes the
UPDATE non-HOT: measured at prod scale, an 8 MB heap carried a **~62 MB** index
— ~30x bloat, 4,615 autovacuums — for a column on **NO hot read path**.

The only ``ORDER BY last_seen_at DESC`` consumers, all cold (verified by grep +
Railway-log review before the drop):
  * ``services/database.py`` ``_LEGACY_ORDER_BY`` — the no-``since``/``cursor``
    ``/api/jobs`` path. WITH a company filter (the trend read) the planner
    already seq-scans ``job_freshness`` and top-N sorts ~2,833 rows and does NOT
    use this index. Only the NO-company shape would, and no live UI caller hits
    it (Recent moved to ``/api/jobs/search``; the trend read always passes a
    company).
  * ``services/location_admin.py::list_problem_jobs`` — admin
    ``/admin/location-normalization`` problem-jobs page. Low-traffic; post-drop
    it does a bounded sort of the WHERE-limited set. Acceptable.
  * ``services/scraper_health.py`` — ``MAX(f.last_seen_at) … GROUP BY company``
    (daily cron); grouping, needs no ordered index.
  * ``api/eval/monitor_prod.py`` — read-only, on-demand storage monitor; its
    ``pg_relation_size(to_regclass('idx_job_freshness_last_seen'))`` gracefully
    returns NULL once the index is gone.

Dropping it makes the re-stamp HOT again and reclaims ~62 MB. ``job_freshness``
is the write-hottest table in the schema, so this DROP runs **CONCURRENTLY**: a
plain ``DROP INDEX`` takes a brief ACCESS EXCLUSIVE lock that would block scrape
writes. CONCURRENTLY cannot run inside a transaction and Alembic wraps each
migration in one, so it goes in an ``op.get_context().autocommit_block()`` (same
idiom as ``b4e1c9d77a02`` / ``08765ce81d35``'s design notes). ``IF EXISTS`` keeps
a retry safe: a CONCURRENTLY drop that fails partway can leave an INVALID index
of the same name, and a bare re-run would otherwise die.

WHY — the two duplicate ``users`` indexes (hygiene, audit Finding 4a)
--------------------------------------------------------------------
``idx_users_auth0_id`` and ``idx_users_email`` each merely DUPLICATE the unique
index Postgres already builds behind a UNIQUE constraint — ``users_auth0_id_key``
(from ``auth0_id``'s column-level ``unique=True``) and ``users_email_key``. Those
backing indexes serve every equality lookup, so the standalone copies are pure
write-amplification. ``users`` is tiny (~345 rows) and rarely written, so a plain
transactional ``DROP INDEX IF EXISTS`` is instant and safe; it is guarded by
``SET LOCAL lock_timeout`` because prod runs with ``lock_timeout = 0`` (see the
DEPLOY CONTEXT note shared with ``08765ce81d35``). ``IF EXISTS`` on the raw
statements keeps the whole migration re-runnable even though the autocommit_block
below commits them before the CONCURRENTLY step.

DOWNGRADE
---------
Fully reversible: recreate all three exactly. The freshness index is rebuilt
CONCURRENTLY (``IF NOT EXISTS``) in its own autocommit_block; the two ``users``
indexes are recreated transactionally. This restores the prior (redundant) state
byte-for-byte.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1f7c9d2e8b4'
down_revision: Union[str, None] = '776b9dbc68cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FRESHNESS_INDEX = "idx_job_freshness_last_seen"


def upgrade() -> None:
    # Duplicate users indexes: tiny table, plain transactional drop is instant.
    # lock_timeout guards the brief ACCESS EXCLUSIVE lock (prod has none of its
    # own). IF EXISTS keeps this re-runnable after a failed CONCURRENTLY below.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP INDEX IF EXISTS idx_users_auth0_id")
    op.execute("DROP INDEX IF EXISTS idx_users_email")

    # Freshness index: online drop, outside the migration transaction, because
    # job_freshness is on the write path of every scrape cycle.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_FRESHNESS_INDEX}")


def downgrade() -> None:
    # Recreate the freshness index CONCURRENTLY (online), matching the original
    # ``Index('idx_job_freshness_last_seen', 'last_seen_at')`` definition.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_FRESHNESS_INDEX} "
            "ON job_freshness (last_seen_at)"
        )

    # Recreate the two duplicate users indexes (tiny table, transactional).
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_auth0_id ON users (auth0_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)")
