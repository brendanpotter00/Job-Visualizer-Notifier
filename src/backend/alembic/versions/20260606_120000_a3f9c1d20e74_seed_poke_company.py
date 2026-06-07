"""seed poke company

Revision ID: a3f9c1d20e74
Revises: 721c47a02fc8
Create Date: 2026-06-06 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``poke`` (Ashby) — The Interaction Company of California, makers of Poke.
  Board slug (board_token) is ``interaction`` — note this differs from the
  ``id``, the same id-vs-board_token override pattern used for distyl/Distyl
  and gigaml/GigaML in the original Ashby seed. Verified live at
  https://api.ashbyhq.com/posting-api/job-board/interaction

Sits on top of the posthog seed (``721c47a02fc8``); the per-ATS counts asserted
in ``test_migration_companies.py`` are unaffected because that test stops at
``WORKDAY_SEED_REV``, before these single-company seed revisions.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``poke`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f9c1d20e74'
down_revision: Union[str, None] = '721c47a02fc8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'poke', 'display_name': 'Poke', 'ats': 'ashby', 'board_token': 'interaction'},
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
    op.execute("DELETE FROM companies WHERE id IN ('poke')")
