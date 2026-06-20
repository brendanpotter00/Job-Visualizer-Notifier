"""seed reducto company

Revision ID: c7d2e9f4a1b8
Revises: b38c364cd0c4
Create Date: 2026-06-18 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``reducto`` (Ashby) — https://reducto.ai/careers (board_token ``reducto``)

Chains off the current head ``b38c364cd0c4`` (the feedback-table migration) so
the alembic chain keeps a single head. Lands after the frozen per-ATS Ashby seed
(``a17b7c0ffee500``), so the per-ATS counts asserted in
``test_migration_companies.py`` are unaffected.

``board_token`` uses the lowercase URL-path token ``reducto`` because Ashby's
posting API is case-sensitive. Verified live against
https://api.ashbyhq.com/posting-api/job-board/reducto.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``reducto`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7d2e9f4a1b8'
down_revision: Union[str, None] = 'b38c364cd0c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'reducto', 'display_name': 'Reducto', 'ats': 'ashby', 'board_token': 'reducto'},
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
    op.execute("DELETE FROM companies WHERE id = 'reducto'")
