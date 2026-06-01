"""seed krea company

Revision ID: d4e5b6c3f2a1
Revises: c3f2a1d4e5b6
Create Date: 2026-05-30 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``krea`` (Ashby) — https://jobs.ashbyhq.com/krea

Sits on top of the frozen per-ATS seeds (Ashby revision
``a17b7c0ffee500``) and the later single-company seeds (``1e35a6d3cb28``
exa+roblox, ``c3f2a1d4e5b6`` trajectory); the per-ATS counts asserted in
``test_migration_companies.py`` are unaffected because that test stops at
``WORKDAY_SEED_REV``, before these revisions.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``krea`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5b6c3f2a1'
down_revision: Union[str, None] = 'c3f2a1d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'krea', 'display_name': 'Krea', 'ats': 'ashby', 'board_token': 'krea'},
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
    op.execute("DELETE FROM companies WHERE id IN ('krea')")
