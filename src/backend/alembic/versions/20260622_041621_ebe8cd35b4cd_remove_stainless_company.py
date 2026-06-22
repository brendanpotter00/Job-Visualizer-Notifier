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

- ``scrape_runs``           — historical scrape log     (~1599 rows in prod)
- ``job_listings``          — scraped postings          (16 OPEN in prod)
- ``user_enabled_companies``— per-user enablement rows  (32 users in prod)
- ``companies``             — the registration row      (1 row)

Child rows are deleted before the parent ``companies`` row for clarity
(order is not load-bearing absent FKs). Deletes are scoped to the single
company id and are no-ops on a fresh DB (the tables are empty when this
runs in the full upgrade chain), so the migration is idempotent and safe.

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
    # company id; no-op on a fresh DB (these tables are empty at this point in
    # the upgrade chain) and safe to re-run.
    bind.execute(
        sa.text("DELETE FROM scrape_runs WHERE company = :id"),
        {"id": COMPANY_ID},
    )
    bind.execute(
        sa.text("DELETE FROM job_listings WHERE company = :id"),
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
