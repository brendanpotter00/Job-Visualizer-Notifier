"""seed aiuc company

Revision ID: 259e1ef63540
Revises: adebe6d46383
Create Date: 2026-09-09 04:45:10.752702+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``aiuc`` (ashby) — board_token ``aiuc``

Chains off the current head ``adebe6d46383`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``aiuc`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '259e1ef63540'
down_revision: Union[str, None] = 'adebe6d46383'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'aiuc', 'display_name': 'AIUC', 'ats': 'ashby', 'board_token': 'aiuc'},
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
    op.execute("DELETE FROM companies WHERE id = 'aiuc'")
