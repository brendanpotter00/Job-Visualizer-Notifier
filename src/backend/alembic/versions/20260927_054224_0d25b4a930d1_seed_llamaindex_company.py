"""seed llamaindex company

Revision ID: 0d25b4a930d1
Revises: 7e81b9662cf0
Create Date: 2026-09-27 05:42:24.348850+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``llamaindex`` (ashby) — board_token ``llamaindex``

Chains off the current head ``7e81b9662cf0`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``llamaindex`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0d25b4a930d1'
down_revision: Union[str, None] = '7e81b9662cf0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'llamaindex', 'display_name': 'LlamaIndex', 'ats': 'ashby', 'board_token': 'llamaindex'},
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
    op.execute("DELETE FROM companies WHERE id = 'llamaindex'")
