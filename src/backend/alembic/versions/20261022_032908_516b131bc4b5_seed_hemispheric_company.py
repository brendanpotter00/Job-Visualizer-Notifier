"""seed hemispheric company

Revision ID: 516b131bc4b5
Revises: f6c58474e821
Create Date: 2026-10-22 03:29:08.902305+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``hemispheric`` (greenhouse) — board_token ``hemispheric``

Chains off the current head ``f6c58474e821`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``hemispheric`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '516b131bc4b5'
down_revision: Union[str, None] = 'f6c58474e821'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'hemispheric', 'display_name': 'Hemispheric', 'ats': 'greenhouse', 'board_token': 'hemispheric'},
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
    op.execute("DELETE FROM companies WHERE id = 'hemispheric'")
