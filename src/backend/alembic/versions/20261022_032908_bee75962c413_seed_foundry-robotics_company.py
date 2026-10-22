"""seed foundry-robotics company

Revision ID: bee75962c413
Revises: a2d0dde5334d
Create Date: 2026-10-22 03:29:08.579627+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``foundry-robotics`` (ashby) — board_token ``foundry-robotics``

Chains off the current head ``a2d0dde5334d`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``foundry-robotics`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bee75962c413'
down_revision: Union[str, None] = 'a2d0dde5334d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'foundry-robotics', 'display_name': 'Foundry Robotics', 'ats': 'ashby', 'board_token': 'foundry-robotics'},
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
    op.execute("DELETE FROM companies WHERE id = 'foundry-robotics'")
