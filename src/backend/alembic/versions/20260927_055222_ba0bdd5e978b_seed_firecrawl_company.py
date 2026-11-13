"""seed firecrawl company

Revision ID: ba0bdd5e978b
Revises: e89b83f0dc05
Create Date: 2026-09-27 05:52:22.605082+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``firecrawl`` (ashby) — board_token ``firecrawl``

Chains off the current head ``e89b83f0dc05`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``firecrawl`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ba0bdd5e978b'
down_revision: Union[str, None] = 'e89b83f0dc05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'firecrawl', 'display_name': 'Firecrawl', 'ats': 'ashby', 'board_token': 'firecrawl'},
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
    op.execute("DELETE FROM companies WHERE id = 'firecrawl'")
