"""seed sierra company

Revision ID: c4f0a2d8b9e1
Revises: 1e35a6d3cb28
Create Date: 2026-05-27 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``sierra`` (Ashby) — https://jobs.ashbyhq.com/Sierra

Sits on top of the frozen per-ATS Ashby seed (revision ``a17b7c0ffee500``)
and chains off the current head ``1e35a6d3cb28`` (the exa/roblox seed) so the
alembic chain has a single head. Lands after ``WORKDAY_SEED_REV``, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

``board_token`` uses the exact URL-path casing ``Sierra`` because Ashby's
posting API is case-sensitive.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``sierra`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f0a2d8b9e1'
down_revision: Union[str, None] = '1e35a6d3cb28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'sierra', 'display_name': 'Sierra', 'ats': 'ashby', 'board_token': 'Sierra'},
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
    op.execute("DELETE FROM companies WHERE id = 'sierra'")
