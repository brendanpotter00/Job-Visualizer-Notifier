"""seed tomo-ai company

Revision ID: 1d85b2f9a6d1
Revises: 4c1f8a26d7be
Create Date: 2026-09-10 19:20:48.687749+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``tomo-ai`` (ashby) — board_token ``tomo.ai``

Chains off the current head ``4c1f8a26d7be`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``tomo-ai`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1d85b2f9a6d1'
down_revision: Union[str, None] = '4c1f8a26d7be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'tomo-ai', 'display_name': 'Tomo', 'ats': 'ashby', 'board_token': 'tomo.ai'},
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
    op.execute("DELETE FROM companies WHERE id = 'tomo-ai'")
