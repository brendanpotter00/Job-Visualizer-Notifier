"""seed generalist-ai company

Revision ID: 4fed9795468a
Revises: 4535bd7a2515
Create Date: 2026-10-22 22:41:02.854238+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``generalist-ai`` (ashby) — board_token ``generalist``

Chains off the current head ``4535bd7a2515`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``generalist-ai`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4fed9795468a'
down_revision: Union[str, None] = '4535bd7a2515'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'generalist-ai', 'display_name': 'Generalist AI', 'ats': 'ashby', 'board_token': 'generalist'},
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
    op.execute("DELETE FROM companies WHERE id = 'generalist-ai'")
