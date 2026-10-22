"""seed periodic-labs company

Revision ID: 8b2ca4056a62
Revises: 8228e806b0d4
Create Date: 2026-10-22 03:29:09.762011+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``periodic-labs`` (ashby) — board_token ``periodic-labs``

Chains off the current head ``8228e806b0d4`` so the alembic chain keeps a single head.
Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``periodic-labs`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8b2ca4056a62'
down_revision: Union[str, None] = '8228e806b0d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'periodic-labs', 'display_name': 'Periodic Labs', 'ats': 'ashby', 'board_token': 'periodic-labs'},
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
    op.execute("DELETE FROM companies WHERE id = 'periodic-labs'")
