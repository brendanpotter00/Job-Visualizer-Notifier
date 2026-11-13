"""seed patronus-ai company

Revision ID: 8228e806b0d4
Revises: a6e2bd67da4c
Create Date: 2026-10-22 03:29:09.697576+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``patronus-ai`` (greenhouse) — board_token ``patronusaiinc``

Chains off the current head ``a6e2bd67da4c`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``patronus-ai`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8228e806b0d4'
down_revision: Union[str, None] = 'a6e2bd67da4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'patronus-ai', 'display_name': 'Patronus AI', 'ats': 'greenhouse', 'board_token': 'patronusaiinc'},
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
    op.execute("DELETE FROM companies WHERE id = 'patronus-ai'")
