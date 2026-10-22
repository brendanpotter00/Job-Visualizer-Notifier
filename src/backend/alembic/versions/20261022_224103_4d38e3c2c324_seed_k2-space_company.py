"""seed k2-space company

Revision ID: 4d38e3c2c324
Revises: 4fed9795468a
Create Date: 2026-10-22 22:41:03.030559+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``k2-space`` (greenhouse) — board_token ``k2spacecorporation``

Chains off the current head ``4fed9795468a`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``k2-space`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4d38e3c2c324'
down_revision: Union[str, None] = '4fed9795468a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'k2-space', 'display_name': 'K2 Space', 'ats': 'greenhouse', 'board_token': 'k2spacecorporation'},
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
    op.execute("DELETE FROM companies WHERE id = 'k2-space'")
