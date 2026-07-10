"""seed brainco company

Revision ID: aa83cd49e4c0
Revises: 288764e337a4
Create Date: 2026-07-10 13:46:05.246901+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``brainco`` (ashby) — board_token ``brainco``

Chains off the current head ``288764e337a4`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``brainco`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa83cd49e4c0'
down_revision: Union[str, None] = '288764e337a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'brainco', 'display_name': 'Brain Co.', 'ats': 'ashby', 'board_token': 'brainco'},
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
    op.execute("DELETE FROM companies WHERE id = 'brainco'")
