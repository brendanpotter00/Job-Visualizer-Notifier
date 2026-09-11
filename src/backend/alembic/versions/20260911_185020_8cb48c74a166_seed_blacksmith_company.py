"""seed blacksmith company

Revision ID: 8cb48c74a166
Revises: 5bf63e27b6a2
Create Date: 2026-09-11 18:50:20.900882+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``blacksmith`` (ashby) — board_token ``blacksmith``

Chains off the current head ``5bf63e27b6a2`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``blacksmith`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8cb48c74a166'
down_revision: Union[str, None] = '5bf63e27b6a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'blacksmith', 'display_name': 'Blacksmith', 'ats': 'ashby', 'board_token': 'blacksmith'},
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
    op.execute("DELETE FROM companies WHERE id = 'blacksmith'")
