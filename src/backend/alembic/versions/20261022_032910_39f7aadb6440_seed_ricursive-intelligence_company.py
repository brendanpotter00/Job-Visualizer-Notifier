"""seed ricursive-intelligence company

Revision ID: 39f7aadb6440
Revises: b84598746f2b
Create Date: 2026-10-22 03:29:10.020155+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``ricursive-intelligence`` (ashby) — board_token ``ricursive intelligence``

Chains off the current head ``b84598746f2b`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``ricursive-intelligence`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '39f7aadb6440'
down_revision: Union[str, None] = 'b84598746f2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'ricursive-intelligence', 'display_name': 'Ricursive Intelligence', 'ats': 'ashby', 'board_token': 'ricursive intelligence'},
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
    op.execute("DELETE FROM companies WHERE id = 'ricursive-intelligence'")
