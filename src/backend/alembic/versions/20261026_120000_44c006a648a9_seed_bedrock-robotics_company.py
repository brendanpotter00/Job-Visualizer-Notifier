"""seed bedrock-robotics company

Revision ID: 44c006a648a9
Revises: 4d38e3c2c324
Create Date: 2026-10-26 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds one company to the ``companies`` table:

- ``bedrock-robotics`` (ashby) — board_token ``bedrock-robotics``

Chains off the current head ``4d38e3c2c324`` so the alembic chain keeps a single
head. Single-company seeds land after the frozen per-ATS seed migrations, so the
per-ATS counts asserted in ``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``bedrock-robotics`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '44c006a648a9'
down_revision: Union[str, None] = '4d38e3c2c324'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'bedrock-robotics', 'display_name': 'Bedrock Robotics', 'ats': 'ashby', 'board_token': 'bedrock-robotics'},
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
    op.execute("DELETE FROM companies WHERE id = 'bedrock-robotics'")
