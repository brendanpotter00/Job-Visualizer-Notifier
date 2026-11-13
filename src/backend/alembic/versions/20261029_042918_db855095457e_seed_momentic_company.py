"""seed momentic company

Revision ID: db855095457e
Revises: 378acab34dfd
Create Date: 2026-10-29 04:29:18.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``momentic`` (ashby) — board_token ``momentic``

Momentic (YC W24) shipped as part of the Disruptors 60 batch add (PR #349) in
the frontend and backend profile layers, but the corresponding per-ATS seed
migration for the ``companies`` table was never written, so
``GET /api/companies`` has never returned it in production. This migration
closes that gap.

Chains off the current head ``378acab34dfd`` so the alembic chain keeps a
single head. Single-company seeds land after the frozen per-ATS seed
migrations, so the per-ATS counts asserted in
``test_migration_companies.py`` are unaffected.

``board_token`` uses the lowercase URL-path token ``momentic`` because
Ashby's posting API is case-sensitive. Verified live against
https://api.ashbyhq.com/posting-api/job-board/momentic (4 open roles as of
2026-10-29).

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``momentic`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'db855095457e'
down_revision: Union[str, None] = '378acab34dfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'momentic', 'display_name': 'Momentic', 'ats': 'ashby', 'board_token': 'momentic'},
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
    op.execute("DELETE FROM companies WHERE id = 'momentic'")
