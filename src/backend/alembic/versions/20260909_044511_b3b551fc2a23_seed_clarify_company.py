"""seed clarify company

Revision ID: b3b551fc2a23
Revises: a2d09f82a08f
Create Date: 2026-09-09 04:45:11.587003+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``clarify`` (ashby) — board_token ``clarify``

Chains off the current head ``a2d09f82a08f`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``clarify`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3b551fc2a23'
down_revision: Union[str, None] = 'a2d09f82a08f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'clarify', 'display_name': 'Clarify', 'ats': 'ashby', 'board_token': 'clarify'},
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
    op.execute("DELETE FROM companies WHERE id = 'clarify'")
