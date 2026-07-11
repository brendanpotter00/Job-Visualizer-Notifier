"""add open_only location-search indexes

Revision ID: 695acc9f478b
Revises: 74ef55837f12
Create Date: 2026-07-11 04:23:54.241768+00:00

Two additive indexes that let the ``open_only=true`` location-search path
(``saved_filters_service.search_locations``) use indexes instead of full
seq-scans on the ~54k/57k-row join tables:

- ``idx_job_locations_norm_loc`` — standalone btree on
  ``job_locations.normalized_location_id``. The EXISTS semijoin filters
  ``job_locations`` by ``normalized_location_id``, but the table's PK leads with
  ``job_listing_id`` so it can't serve that probe.
- ``idx_job_listings_open_id`` — PARTIAL btree on ``job_listings.id`` WHERE
  ``status = 'OPEN'``. The semijoin probes ``job_listings`` by id restricted to
  OPEN rows; ``job_listings``' PK is the composite ``(source_id, id)`` so there
  is no standalone index on ``id`` alone.

Both are plain (non-CONCURRENT) ``create_index`` calls — Alembic runs migrations
in a transaction, and at current scale (~54k/57k rows) each index builds in ~1s.

Phantom ``procrastinate_*`` autogenerate ops stripped (those tables are owned by
Procrastinate's own schema setup, not ``db_models.py``, so autogenerate always
wants to drop them — same trim as 288764e337a4 / 74ef55837f12).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '695acc9f478b'
down_revision: Union[str, None] = '74ef55837f12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('idx_job_listings_open_id', 'job_listings', ['id'], unique=False, postgresql_where=sa.text("status = 'OPEN'"))
    op.create_index('idx_job_locations_norm_loc', 'job_locations', ['normalized_location_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_job_locations_norm_loc', table_name='job_locations')
    op.drop_index('idx_job_listings_open_id', table_name='job_listings', postgresql_where=sa.text("status = 'OPEN'"))
