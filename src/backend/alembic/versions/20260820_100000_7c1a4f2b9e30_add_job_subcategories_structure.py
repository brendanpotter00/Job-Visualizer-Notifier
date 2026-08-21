"""Phase 1 of the SWE-subcategories epic: STRUCTURE ONLY, no data.

WHAT THIS ADDS
--------------
1. ``job_subcategories`` — the seeded dimension table, created **EMPTY**.
2. ``job_listings.enrichment_subcategories`` (``TEXT[]``, nullable) and
   ``job_listings.enrichment_subcategory_source`` (``TEXT``, nullable), added in
   ONE combined ``ALTER TABLE``.
3. ``job_enrichment.subcategory_confidence`` (``DOUBLE PRECISION``, nullable),
   mirroring ``classify_confidence``.
4. ``idx_job_listings_open_subcategories_gin`` — a PARTIAL GIN on the array,
   restricted to ``status = 'OPEN'``.

WHY THE TABLE SHIPS EMPTY (the phase-1 / phase-2 split)
-------------------------------------------------------
``job_subcategories``' only consumer is ``get_facets`` -> the public filter
dropdown, and the SPA caches that response for an hour. Seeding the dimension is
therefore a **user-visible publish**, not a schema change: the moment rows exist
the checkboxes appear. If they appear before anything has been labelled, every
one of them returns "No jobs found".

Splitting structure (here) from the seed (SCHEMA-7, phase 2) makes that failure
**structurally impossible rather than flag-dependent** — there is no flag to
mis-set, because the data the UI would render does not exist yet. It also lets
the write path, the backfill and the coverage counters all land and be verified
against a production database while the dropdown is provably unchanged.

WHY THE ARRAY HAS NO FOREIGN KEY
--------------------------------
Postgres cannot FK-check the elements of an array column. That is a real hole and
it is accepted deliberately: cardinality is <= 2, the only query is a membership
probe, and a join table would put a second row-per-job table on the hot list
path. The compensating controls are named so they cannot be forgotten:

* ``TestTaxonomyParity`` / ``test_taxonomy_artifact.py`` — the code, the seed and
  the API must all carry the same slug set;
* the admin health snapshot's ``subcategory_unknown_slugs`` counter, which counts
  persisted slugs absent from the TAXONOMY and **must be permanently 0** — including
  during Phase 1. This table ships EMPTY here and SCHEMA-7 seeds it later, so the
  counter reads against ``enrichment_writer.SUBCATEGORY_SLUGS`` while it is empty and
  against this table the moment it has rows. Comparing against an empty table would
  make every legitimate slug "unknown" and leave the admin warning permanently red
  for the whole labelling window — a control nobody reads is not a control.

Legal values for ``enrichment_subcategory_source`` are
``api.services.enrichment_writer.SUBCATEGORY_SOURCES``. Cited, not re-listed —
that enum has already drifted three different ways across draft documents, and a
fourth copy in a migration docstring would be a fifth thing to keep in sync.
``enrichment_subcategory_source`` exists so a bad automated run can be reversed
in a SCOPED way (NULL every row whose source is 'backfill') without destroying
the human labels the eval gate depends on.

DEPLOY CONTEXT
--------------
Applied by ``alembic upgrade head`` from the FastAPI lifespan hook on Railway
startup (``src/backend/api/migrations.py``). ``alembic.ini`` sets
``transaction_per_migration = true``: one all-or-nothing transaction.

* **``SET LOCAL lock_timeout = '5s'`` is the first statement in BOTH
  directions.** Prod runs with ``lock_timeout = 0``, i.e. no bound at all, so an
  ``ACCESS EXCLUSIVE`` wait behind an in-flight scraper write would park every
  subsequent writer behind us in Postgres's FIFO lock queue and stall container
  startup. Failing fast and letting the container restart against an idle table
  is the correct behaviour. Same line, same reason, as ``08765ce81d35``,
  ``a3c32c2aa4d3`` and ``18fe9c20a8fd``.
* **The two ``job_listings`` columns go in ONE combined ``ALTER``**, exactly as
  ``0fa33aca5bda`` does. Both are nullable with no default, so this is
  catalog-only — no heap rewrite, no temp copy. Two separate ``ALTER``s would
  take the ACCESS EXCLUSIVE lock twice for no benefit. The 2026-04-18 incident
  (``docs/incidents/2026-04-18-migration-filled-postgres-volume/``) is why this
  rule is not optional.
* **The GIN index is NOT ``CONCURRENTLY``.** The column is 100% NULL at this
  point, so the partial index has zero entries to sort or write: the build is one
  narrow heap scan over the OPEN slice. ``CREATE INDEX CONCURRENTLY`` cannot run
  inside a transaction, would need ``autocommit_block()``, and would forfeit the
  all-or-nothing guarantee *and* the ``lock_timeout`` guard above — a bad trade
  for an index that is empty on arrival.

DOWNGRADE
---------
Drops the index, the two columns, the confidence column and the table.
**Lossy by construction**: a plain ``DROP COLUMN`` discards every subcategory
label that has been written since the upgrade. That is why
``POST /api/admin/enrichment/subcategories/reset`` (ADM-15) exists — a scoped,
source-keyed reversal is the reversal you actually want; this downgrade is the
blunt instrument for backing the whole feature out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
#
# down_revision is PR #252's TRUE head (`536c1cddcd28`, the job_tags trigram
# index), NOT `4b5d40dbc774` — that is #252's FIRST revision and already has a
# child, so parenting here would fork the graph into two heads and crash the
# backend in the lifespan. See api/tests/test_alembic_single_head.py for the
# full pinned chain (SCHEMA-0) and the Order-B fallback procedure.
revision: str = '7c1a4f2b9e30'
down_revision: Union[str, None] = '536c1cddcd28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MUST be first — see "DEPLOY CONTEXT" above.
    op.execute("SET LOCAL lock_timeout = '5s'")

    # 1. The dimension table. Created EMPTY on purpose (see the module
    #    docstring); SCHEMA-7 seeds it in phase 2.
    op.create_table(
        'job_subcategories',
        sa.Column('slug', sa.Text(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('parent_slug', sa.Text(), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['parent_slug'], ['job_categories.slug'], ),
        sa.PrimaryKeyConstraint('slug'),
    )

    # 2. ONE combined, catalog-only ALTER on the large table — both columns
    #    nullable with no default, so no rewrite.
    op.execute(
        """
        ALTER TABLE job_listings
            ADD COLUMN enrichment_subcategories      TEXT[],
            ADD COLUMN enrichment_subcategory_source TEXT
        """
    )

    # 3. The confidence sibling on the narrow side table.
    op.add_column(
        'job_enrichment',
        sa.Column('subcategory_confidence', sa.Float(), nullable=True),
    )

    # 4. Partial GIN for the membership probe on the OPEN slice.
    op.create_index(
        'idx_job_listings_open_subcategories_gin',
        'job_listings',
        ['enrichment_subcategories'],
        unique=False,
        postgresql_using='gin',
        postgresql_where=sa.text("status = 'OPEN'"),
    )


def downgrade() -> None:
    # Mirrors upgrade(): DROP INDEX / DROP COLUMN need ACCESS EXCLUSIVE and prod
    # still has no lock_timeout of its own.
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.drop_index(
        'idx_job_listings_open_subcategories_gin',
        table_name='job_listings',
        postgresql_using='gin',
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.drop_column('job_enrichment', 'subcategory_confidence')
    # One combined ALTER on the way down too, for the same lock reason.
    op.execute(
        """
        ALTER TABLE job_listings
            DROP COLUMN enrichment_subcategory_source,
            DROP COLUMN enrichment_subcategories
        """
    )
    op.drop_table('job_subcategories')
