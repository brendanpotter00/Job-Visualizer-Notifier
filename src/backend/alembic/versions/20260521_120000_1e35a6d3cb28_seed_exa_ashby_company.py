"""seed exa ashby company

Revision ID: 1e35a6d3cb28
Revises: b9714f608e21
Create Date: 2026-05-21 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds a single Ashby row for Exa
(https://jobs.ashbyhq.com/exa) on top of the frozen 46-row Ashby seed
in revision a17b7c0ffee500.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (Ashby block, ``exa`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1e35a6d3cb28'
down_revision: Union[str, None] = 'b9714f608e21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token) "
        "VALUES (:id, :display_name, :ats, :board_token) "
        "ON CONFLICT (id) DO NOTHING"
    )
    bind.execute(
        insert_sql,
        {
            'id': 'exa',
            'display_name': 'Exa',
            'ats': 'ashby',
            'board_token': 'exa',
        },
    )


def downgrade() -> None:
    op.execute("DELETE FROM companies WHERE id = 'exa' AND ats = 'ashby'")
