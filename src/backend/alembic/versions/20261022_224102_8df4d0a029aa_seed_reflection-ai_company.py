"""seed reflection-ai company

Revision ID: 8df4d0a029aa
Revises: f3ec7059a801
Create Date: 2026-10-22 22:41:02.253139+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``reflection-ai`` (ashby) — board_token ``reflectionai``

Chains off the current head ``f3ec7059a801`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``reflection-ai`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8df4d0a029aa'
down_revision: Union[str, None] = 'f3ec7059a801'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'reflection-ai', 'display_name': 'Reflection AI', 'ats': 'ashby', 'board_token': 'reflectionai'},
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
    op.execute("DELETE FROM companies WHERE id = 'reflection-ai'")
