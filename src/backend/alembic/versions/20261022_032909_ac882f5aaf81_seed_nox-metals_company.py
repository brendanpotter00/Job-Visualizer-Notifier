"""seed nox-metals company

Revision ID: ac882f5aaf81
Revises: b9d3ecaab672
Create Date: 2026-10-22 03:29:09.505707+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``nox-metals`` (ashby) — board_token ``nox-metals``

Chains off the current head ``b9d3ecaab672`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``nox-metals`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ac882f5aaf81'
down_revision: Union[str, None] = 'b9d3ecaab672'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'nox-metals', 'display_name': 'Nox Metals', 'ats': 'ashby', 'board_token': 'nox-metals'},
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
    op.execute("DELETE FROM companies WHERE id = 'nox-metals'")
