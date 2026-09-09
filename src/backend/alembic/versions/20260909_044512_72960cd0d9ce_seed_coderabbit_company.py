"""seed coderabbit company

Revision ID: 72960cd0d9ce
Revises: e989e79d16fc
Create Date: 2026-09-09 04:45:12.287014+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``coderabbit`` (ashby) — board_token ``coderabbit``

Chains off the current head ``e989e79d16fc`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``coderabbit`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '72960cd0d9ce'
down_revision: Union[str, None] = 'e989e79d16fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'coderabbit', 'display_name': 'CodeRabbit', 'ats': 'ashby', 'board_token': 'coderabbit'},
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
    op.execute("DELETE FROM companies WHERE id = 'coderabbit'")
