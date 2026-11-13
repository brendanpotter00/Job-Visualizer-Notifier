"""seed chai-discovery company

Revision ID: b1bcef77cb48
Revises: f8e158fbf640
Create Date: 2026-10-22 03:29:07.873858+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``chai-discovery`` (ashby) — board_token ``chaidiscovery``

Chains off the current head ``f8e158fbf640`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``chai-discovery`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1bcef77cb48'
down_revision: Union[str, None] = 'f8e158fbf640'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'chai-discovery', 'display_name': 'Chai Discovery', 'ats': 'ashby', 'board_token': 'chaidiscovery'},
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
    op.execute("DELETE FROM companies WHERE id = 'chai-discovery'")
