"""seed tools-for-humanity company

Revision ID: a8f9e7d21a94
Revises: 8b4829af0b09
Create Date: 2026-10-22 03:36:27.684412+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``tools-for-humanity`` (ashby) — board_token ``tools for humanity``

Chains off the current head ``8b4829af0b09`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``tools-for-humanity`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8f9e7d21a94'
down_revision: Union[str, None] = '8b4829af0b09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'tools-for-humanity', 'display_name': 'Tools for Humanity', 'ats': 'ashby', 'board_token': 'tools for humanity'},
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
    op.execute("DELETE FROM companies WHERE id = 'tools-for-humanity'")
