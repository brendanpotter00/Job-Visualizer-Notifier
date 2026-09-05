"""add job_listings primary_country + search_text denormalizations (Perf Wave 2)

Revision ID: e3b1a4c9d7f2
Revises: cfa099f2e1e0
Create Date: 2026-09-05 01:00:00.000000+00:00

Perf Wave 2, items C2 + C3. Companion reading:
``docs/implementations/performance-audit/{WAVE2-PLAN,SCHEMA-AUDIT,
ACCESS-PATTERNS-AUDIT,PERF-AUDIT-FINDINGS,POSTGRES-PRINCIPLES}.md``.

WHAT THIS ADDS
--------------
Two denormalized, nullable columns on ``job_listings`` and the two indexes that
make them fast:

* **C2 — ``primary_country``** + ``idx_job_listings_open_country_keyset``
  ``(primary_country, first_seen_at, source_id, id) WHERE status = 'OPEN'``.
  Fixes the #1 slow endpoint, ``location=United States`` (2.08 s): today the
  location filter is one cross-table ``EXISTS`` over ``job_locations`` whose
  selectivity the planner mis-estimates 139x, so it drops the keyset index and
  top-N sorts ~25k rows. With the country denormalized onto the row and this
  category-keyset-shaped index (equality LEADS, sort tuple trailing), a
  single-country selection becomes an ordered backward walk that early-stops at
  the LIMIT.

* **C3 — ``search_text``** + ``idx_job_listings_search_text_trgm`` GIN
  ``(search_text gin_trgm_ops)``. Fixes keyword search: ``_KEYWORD_PREDICATE`` is
  a 4-way OR (title / location / company ``ILIKE`` + a ``job_tags`` ``EXISTS``)
  spanning two tables, which no per-column trigram can serve as one unit.
  ``search_text`` is ``lower(title ‖ raw location ‖ company ‖ tags)`` in one
  column, so ``search_text ILIKE '%term%'`` is a single GIN bitmap probe.

CATALOG-ONLY ADD — no rewrite, no default, no inline backfill
-------------------------------------------------------------
Both columns are ``text`` **nullable with NO default and NO backfill**, so each
``ADD COLUMN`` is a metadata-only catalog change — instant, no table rewrite.
This is the hard rule from the 2026-04-18 "migration filled the Postgres volume"
incident (POSTGRES-PRINCIPLES §10); ``job_listings`` is ~859 MB, so a ``DEFAULT``
or an inline ``UPDATE ... SET`` here would rewrite every row and could fill the
volume. The two ADDs are COMBINED into ONE ``ALTER TABLE`` (§10 combined-ALTER
rule): one catalog bump, not two.

The columns therefore start **all-NULL** and are filled two ways: the write path
(a follow-up change to ``scripts/shared/database.py`` + the enrichment /
normalization writers) sets them on new/changed rows, and a **bounded-batch,
post-deploy** backfill (``scripts/backfill_wave2_denorm.py``, NOT run here) drains
the pre-existing NULLs. The search predicates keep the original cross-table
``EXISTS`` / 4-way ``OR`` as a fallback for rows whose denormalized value ``IS
NULL``, so a not-yet-filled value is never a wrong answer and the backfill can run
at leisure with no gating flag (WAVE2-PLAN.md §0/§5).

INDEXES BUILT CONCURRENTLY, OUTSIDE THE MIGRATION TRANSACTION
------------------------------------------------------------
``job_listings`` is on the scrape write path and is large, and the GIN index in
particular is comparatively heavy to build, so both indexes go up
``CONCURRENTLY`` inside ``op.get_context().autocommit_block()`` — the proven prod
idiom from ``a1f7c9d2e8b4`` (freshness-index drop) and the reasoning
``08765ce81d35`` / ``4b5d40dbc774`` document for when to reach for it. A plain
``CREATE INDEX`` takes a ``SHARE`` lock that blocks writers for the whole build;
``CONCURRENTLY`` takes only ``SHARE UPDATE EXCLUSIVE`` (readers AND writers keep
going) at the cost of two heap passes. ``CONCURRENTLY`` cannot run inside a
transaction and Alembic wraps each migration in one (``transaction_per_migration
= true``), hence the ``autocommit_block``.

``IF NOT EXISTS`` on every statement is load-bearing for RETRY-SAFETY, not
decoration: the ``autocommit_block`` commits the columns and the first index
before the second index is attempted, so a failure partway must be safe to re-run.
``ADD COLUMN IF NOT EXISTS`` keeps the combined ALTER re-runnable after such a
partial apply.

For the index builds ``IF NOT EXISTS`` is necessary but NOT sufficient, and that
gap is closed by ``_drop_invalid_index`` below. A ``CONCURRENTLY`` build that dies
mid-flight leaves an INVALID index of the same name (``pg_index.indisvalid =
false``) — catalog-present, planner-unusable, never finished. On the retry ``IF
NOT EXISTS`` would find that name and SKIP recreation, so the migration would
report success while the index stayed broken and every hot query silently fell
back to the slower indexless plan. So each build is preceded by a probe that drops
ONLY an invalid leftover of that exact name (a valid index is left alone, so a
clean re-run is still a no-op) with a non-transactional ``DROP INDEX
CONCURRENTLY``.

At build time both columns are entirely NULL. The btree country-keyset index
indexes NULLs, so it materializes ~38k OPEN entries (the backfill later moves each
row NULL→country — cheap btree updates). The GIN index does NOT index NULLs, so on
an all-NULL column its concurrent build is trivially fast and it grows only as the
backfill/write path populate ``search_text``.

pg_trgm is already installed in the live chain (``536c1cddcd28`` created it for
``idx_job_tags_tag_trgm``); the ``CREATE EXTENSION IF NOT EXISTS`` below is a
cheap (~14 ms), idempotent guard so this migration is self-contained and the GIN
build cannot fail on a missing operator class. It is created ``WITH SCHEMA
public`` for the same test-isolation reason ``536c1cddcd28`` records.

lock_timeout
------------
``SET LOCAL lock_timeout = '5s'`` is the first statement of the transactional
part, guarding the brief ``ACCESS EXCLUSIVE`` lock the combined ``ALTER TABLE``
takes: prod runs with ``lock_timeout = 0`` (no bound at all), so without it a
wait behind an in-flight scraper write would park every subsequent writer behind
us in Postgres's FIFO lock queue and stall container startup. Failing fast into a
retry is correct. Same first-line, same reason, as ``08765ce81d35`` /
``4b5d40dbc774``. It does NOT (and cannot) cover the ``CONCURRENTLY`` builds —
those run outside the transaction — but ``CONCURRENTLY``'s weaker lock class does
not queue writers the way a plain build would, matching ``a1f7c9d2e8b4``.

DOWNGRADE
---------
Fully reversible SCHEMA-wise: drop both indexes ``CONCURRENTLY IF EXISTS`` in an
``autocommit_block``, then one combined ``ALTER TABLE ... DROP COLUMN IF EXISTS``
under the ``lock_timeout`` guard. ``pg_trgm`` is deliberately NOT dropped — an
extension is database-global and ``idx_job_tags_tag_trgm`` still depends on it;
a bare ``DROP EXTENSION`` would fail and a ``CASCADE`` could destroy unrelated
objects (same asymmetry ``536c1cddcd28`` documents).

DATA IS NOT REVERSIBLE — RE-BACKFILL AFTER ANY downgrade→upgrade. ``downgrade()``
DROPs the columns, discarding every denormalized value the write path + backfill
had populated. A later ``upgrade()`` re-adds them as all-NULL (catalog-only, no
backfill), exactly as on a first deploy. This is SAFE but SLOW, not wrong: the
``services/job_search.py`` predicates keep the original cross-table ``EXISTS`` /
4-way ``OR`` as a fallback for NULL rows, so results stay CORRECT while the columns
are NULL — the hot endpoints just fall back to the slower plans they had before
Wave 2. To restore fast paths, an operator MUST rerun the post-deploy backfill
after the re-upgrade:

    PYTHONPATH=. .venv/bin/python scripts/backfill_wave2_denorm.py

(the write path also refills each row lazily as it is next scraped/enriched, but
the backfill is what drains the pre-existing NULLs promptly). No gating flag and
no coordination are needed — correctness never depends on the backfill's progress.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3b1a4c9d7f2'
down_revision: Union[str, None] = 'cfa099f2e1e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COUNTRY_KEYSET_INDEX = "idx_job_listings_open_country_keyset"
_SEARCH_TRGM_INDEX = "idx_job_listings_search_text_trgm"


def _drop_invalid_index(index_name: str) -> None:
    """Drop ``index_name`` IFF it exists as an INVALID index, clearing the way for
    the retrying ``CREATE INDEX CONCURRENTLY IF NOT EXISTS`` that follows.

    ``CREATE INDEX CONCURRENTLY`` that is killed mid-build (deploy timeout, OOM,
    a cancelled statement) leaves an index of the SAME NAME with
    ``pg_index.indisvalid = false`` — present in the catalog, unusable by the
    planner, never finished. ``IF NOT EXISTS`` then SKIPS recreation on the next
    run, so the migration would report success while the index stays broken. This
    guard removes ONLY that invalid leftover; a VALID index is left untouched, so a
    clean re-run is still a no-op (we do not drop-and-rebuild a good index). The
    drop is ``CONCURRENTLY`` — the non-transactional online drop this
    ``autocommit_block`` permits, matching the create's lock class.

    ``pg_table_is_visible`` scopes the probe to exactly the index the CREATE would
    target on the current ``search_path`` (per-worker test schemas reuse bare
    names), so an unrelated schema's same-named leftover is never touched.
    """
    invalid = op.get_bind().exec_driver_sql(
        "SELECT 1 FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = %s "
        "  AND NOT i.indisvalid "
        "  AND pg_catalog.pg_table_is_visible(c.oid)",
        (index_name,),
    ).fetchone()
    if invalid is not None:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")


def upgrade() -> None:
    # MUST be first — see "lock_timeout" above. Guards the ACCESS EXCLUSIVE lock
    # the combined ALTER takes; prod has no lock_timeout of its own.
    op.execute("SET LOCAL lock_timeout = '5s'")

    # (1) Catalog-only ADD — nullable, NO default, NO backfill (2026-04-18 volume
    # incident). ONE combined ALTER TABLE (POSTGRES-PRINCIPLES §10). IF NOT EXISTS
    # keeps it re-runnable after a partial apply, since the CONCURRENTLY steps
    # below commit outside this transaction.
    op.execute(
        "ALTER TABLE job_listings "
        "ADD COLUMN IF NOT EXISTS primary_country text, "
        "ADD COLUMN IF NOT EXISTS search_text text"
    )

    # (2) pg_trgm — already installed in the live chain by 536c1cddcd28; this is a
    # cheap, idempotent guard so the GIN build below cannot fail on a missing
    # operator class and the migration stays self-contained. WITH SCHEMA public
    # for the same test-isolation reason 536c1cddcd28 records.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")

    # (3) Indexes built CONCURRENTLY, OUTSIDE the migration transaction, because
    # job_listings is large and on the scrape write path. autocommit_block +
    # IF NOT EXISTS + the _drop_invalid_index guard = retry-safe. Same idiom as
    # a1f7c9d2e8b4, hardened for the one gap IF NOT EXISTS alone leaves: a failed
    # CONCURRENTLY build leaves an INVALID index of the same name, which IF NOT
    # EXISTS would then SKIP — "succeeding" with an unusable index. The guard drops
    # that invalid leftover first (see _drop_invalid_index).
    with op.get_context().autocommit_block():
        # C2: partial compound keyset — equality column (primary_country) LEADS,
        # then the (first_seen_at, source_id, id) sort tuple VERBATIM, partial on
        # status='OPEN'. Plain ASC columns served by a BACKWARD scan (same shape
        # and rationale as idx_job_listings_open_category_keyset).
        _drop_invalid_index(_COUNTRY_KEYSET_INDEX)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_COUNTRY_KEYSET_INDEX} "
            "ON job_listings (primary_country, first_seen_at, source_id, id) "
            "WHERE status = 'OPEN'"
        )
        # C3: GIN trigram on the single search haystack. GIN does not index NULLs,
        # so the build on an all-NULL column is trivially fast.
        _drop_invalid_index(_SEARCH_TRGM_INDEX)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_SEARCH_TRGM_INDEX} "
            "ON job_listings USING gin (search_text gin_trgm_ops)"
        )


def downgrade() -> None:
    # Drop the indexes CONCURRENTLY (online), outside the transaction, mirroring
    # upgrade(). IF EXISTS so a retry after a partial drop is safe.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_SEARCH_TRGM_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_COUNTRY_KEYSET_INDEX}")

    # Then drop the columns in one combined ALTER under the lock_timeout guard.
    # pg_trgm is deliberately NOT dropped — it is database-global and
    # idx_job_tags_tag_trgm still depends on it (see 536c1cddcd28).
    #
    # DATA LOSS IS EXPECTED HERE: this discards every populated primary_country /
    # search_text value. A later upgrade() re-adds the columns all-NULL, and the
    # job_search.py EXISTS/4-way-OR fallback keeps results CORRECT (just slower)
    # until the columns are repopulated. After any downgrade→upgrade an operator
    # MUST rerun `scripts/backfill_wave2_denorm.py` to restore the fast paths (the
    # write path also refills lazily on the next scrape/enrich). See "DOWNGRADE"
    # in the module docstring above.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE job_listings "
        "DROP COLUMN IF EXISTS search_text, "
        "DROP COLUMN IF EXISTS primary_country"
    )
