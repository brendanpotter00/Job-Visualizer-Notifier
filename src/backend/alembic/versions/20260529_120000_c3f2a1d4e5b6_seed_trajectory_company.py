"""seed trajectory company

Revision ID: c3f2a1d4e5b6
Revises: 1e35a6d3cb28
Create Date: 2026-05-29 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``trajectory`` (Ashby) — https://jobs.ashbyhq.com/trajectory

Sits on top of the frozen per-ATS seeds (Ashby revision
``a17b7c0ffee500``) and the exa+roblox seed (``1e35a6d3cb28``); the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected
because that test stops at ``WORKDAY_SEED_REV``, before these revisions.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``trajectory`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3f2a1d4e5b6'
down_revision: Union[str, None] = '1e35a6d3cb28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'trajectory', 'display_name': 'Trajectory', 'ats': 'ashby', 'board_token': 'trajectory'},
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
    op.execute("DELETE FROM companies WHERE id IN ('trajectory')")
