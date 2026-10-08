"""seed siena company

Revision ID: edfc1086472a
Revises: 33ff7e590a46
Create Date: 2026-10-08 02:10:35.815952+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``siena`` (ashby) — board_token ``siena``

Chains off the current head ``33ff7e590a46`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``siena`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'edfc1086472a'
down_revision: Union[str, None] = '33ff7e590a46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'siena', 'display_name': 'Siena', 'ats': 'ashby', 'board_token': 'siena'},
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
    op.execute("DELETE FROM companies WHERE id = 'siena'")
