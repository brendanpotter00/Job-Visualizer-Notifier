"""remove stainless company

Revision ID: ebe8cd35b4cd
Revises: e015cd4d01a8
Create Date: 2026-06-22 04:16:21.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Fully removes the ``stainlessapi`` company
("Stainless API", an Ashby board) from the application.

Chains off the current head ``e015cd4d01a8`` (the blurb/accomplishment
columns migration) so the alembic chain keeps a single head. Lands AFTER
the frozen per-ATS Ashby seed (``a17b7c0ffee500``, which inserts
``stainlessapi``), so the per-ATS row counts asserted in
``test_migration_companies.py`` are unaffected — those tests upgrade only
to the seed revisions, never to head, so they still observe 46 Ashby rows
at the seed point. We do NOT edit the frozen seed migration; removal is a
new event, expressed as a new migration.

Full purge (no FK constraints reference ``companies``, so nothing
cascades — each table is cleared explicitly):

- ``job_locations``         — per-job location join rows (16 in prod)
- ``job_listings``          — scraped postings           (16 OPEN in prod)
- ``scrape_runs``           — historical scrape log      (~1599 rows in prod)
- ``user_enabled_companies``— per-user enablement rows   (32 users in prod)
- ``companies``             — the registration row       (1 row)

``job_locations`` needs EXPLICIT cleanup and is deleted FIRST:
``job_locations.job_listing_id`` has NO database FK (``job_listings`` has a
composite PK ``(source_id, id)``, so a single-column FK to ``id`` is invalid
Postgres — integrity is enforced at the app layer; see the ``JobLocation``
model in ``src/backend/api/db_models.py``). Because there is no FK, deleting
``job_listings`` neither cascades to nor is blocked by ``job_locations`` — it
would simply orphan the 16 rows. Its delete subquery reads the parent
``job_listings`` rows, so it MUST run before they are deleted.

Delete order is child/leaf first, then parent, so nothing is ever orphaned:
``job_locations`` (grandchild of ``companies`` via ``job_listings``) →
``job_listings`` → ``scrape_runs`` / ``user_enabled_companies`` →
``companies``.

The four operational tables (``job_locations``, ``job_listings``,
``scrape_runs``, ``user_enabled_companies``) are empty when this migration
runs in the full upgrade chain on a fresh DB, so those deletes are no-ops
there. The ``companies`` delete is NOT a no-op on a fresh DB: the frozen
Ashby seed (``a17b7c0ffee500``) inserts ``stainlessapi`` earlier in the same
chain, so this delete removes that freshly-seeded registration row — which is
the whole point of the migration. All deletes are scoped to the single
company id and re-runnable, so the migration is idempotent and safe.

The frontend counterpart (companies.ts entry + COMPANY_IDS enum member),
the curated blurb in ``src/backend/api/data/company_profiles.json``, and
the brand logos under ``src/frontend/public/logos/`` are removed in the
same PR.

Source of truth for the (now removed) frontend entry:
  src/frontend/src/config/companies.ts (``stainlessapi`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ebe8cd35b4cd'
down_revision: Union[str, None] = 'e015cd4d01a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COMPANY_ID = 'stainlessapi'


def upgrade() -> None:
    bind = op.get_bind()
    # Child/leaf data first, then the registration row. Scoped to the single
    # company id and safe to re-run. The four operational tables are empty at
    # this point in a fresh upgrade chain (no-op there); the companies delete is
    # NOT a no-op on a fresh DB — it removes the row the frozen Ashby seed
    # (a17b7c0ffee500) inserted earlier in the same chain.
    #
    # job_locations MUST be deleted FIRST: job_locations.job_listing_id has no
    # DB FK (job_listings has a composite PK, so a single-col FK is impossible —
    # integrity is app-layer), so deleting job_listings would orphan these rows
    # instead of cascading. Its subquery also reads the parent job_listings rows,
    # so it has to run before they are gone.
    bind.execute(
        sa.text(
            "DELETE FROM job_locations "
            "WHERE job_listing_id IN "
            "(SELECT id FROM job_listings WHERE company = :id)"
        ),
        {"id": COMPANY_ID},
    )
    bind.execute(
        sa.text("DELETE FROM job_listings WHERE company = :id"),
        {"id": COMPANY_ID},
    )
    bind.execute(
        sa.text("DELETE FROM scrape_runs WHERE company = :id"),
        {"id": COMPANY_ID},
    )
    bind.execute(
        sa.text("DELETE FROM user_enabled_companies WHERE company_id = :id"),
        {"id": COMPANY_ID},
    )
    bind.execute(
        sa.text("DELETE FROM companies WHERE id = :id"),
        {"id": COMPANY_ID},
    )


def downgrade() -> None:
    # Restore the registration row only (config), mirroring the frozen Ashby
    # seed's INSERT. The purged scrape_runs / job_listings / user_enabled_companies
    # are operational data, not seed data — they are not (and cannot be)
    # reconstructed here; the next scrape repopulates job_listings/scrape_runs,
    # and users re-enable the company themselves. ON CONFLICT DO NOTHING keeps
    # the downgrade idempotent if the row was restored out-of-band.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO companies (id, display_name, ats, board_token) "
            "VALUES (:id, :display_name, :ats, :board_token) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": COMPANY_ID,
            "display_name": "Stainless API",
            "ats": "ashby",
            "board_token": "stainlessapi",
        },
    )
