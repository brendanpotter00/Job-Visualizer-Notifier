"""seed wordsmith-ai company

Revision ID: fbb9bc416470
Revises: d6c18c8c2d3a
Create Date: 2026-10-22 03:29:10.409112+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``wordsmith-ai`` (ashby) — board_token ``wordsmith``

Chains off the current head ``d6c18c8c2d3a`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``wordsmith-ai`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fbb9bc416470'
down_revision: Union[str, None] = 'd6c18c8c2d3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'wordsmith-ai', 'display_name': 'Wordsmith AI', 'ats': 'ashby', 'board_token': 'wordsmith'},
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
    op.execute("DELETE FROM companies WHERE id = 'wordsmith-ai'")
