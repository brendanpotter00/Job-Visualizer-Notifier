"""seed workweave company

Revision ID: d5e1a9c30f72
Revises: f7a2b9c4d1e3
Create Date: 2026-06-12 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``workweave`` (Ashby) — https://jobs.ashbyhq.com/workweave

Chains off the current head ``f7a2b9c4d1e3`` (the quant-firm seed) so the
alembic chain keeps a single head. Lands after the frozen per-ATS Ashby seed
(``a17b7c0ffee500``), so the per-ATS counts asserted in
``test_migration_companies.py`` are unaffected.

``board_token`` uses the lowercase URL-path token ``workweave`` because Ashby's
posting API is case-sensitive.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``workweave`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e1a9c30f72'
down_revision: Union[str, None] = 'f7a2b9c4d1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'workweave', 'display_name': 'Workweave', 'ats': 'ashby', 'board_token': 'workweave'},
]


def upgrade() -> None:
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token) "
        "VALUES (:id, :display_name, :ats, :board_token) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in SEED_ROWS:
        bind.execute(insert_sql, row)


def downgrade() -> None:
    op.execute("DELETE FROM companies WHERE id = 'workweave'")
