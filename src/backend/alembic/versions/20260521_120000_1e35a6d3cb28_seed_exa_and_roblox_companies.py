"""seed exa and roblox companies

Revision ID: 1e35a6d3cb28
Revises: 2aaec46888f4
Create Date: 2026-05-21 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds two companies to the ``companies`` table:

- ``exa`` (Ashby) — https://jobs.ashbyhq.com/exa
- ``roblox`` (Greenhouse) — https://boards.greenhouse.io/roblox

Both sit on top of the frozen per-ATS seeds (Ashby revision
``a17b7c0ffee500``, Greenhouse revision ``939331c99a23``); the per-ATS
counts asserted in ``test_migration_companies.py`` are unaffected because
that test stops at ``WORKDAY_SEED_REV``, before this revision.

Chains off ``2aaec46888f4`` (the worker_heartbeats schema migration from
PR #129) rather than directly off the Workday seed, so the alembic chain
has a single head when this PR is merged into main.

Source of truth for the frontend entries:
  src/frontend/src/config/companies.ts (``exa`` and ``roblox`` rows)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1e35a6d3cb28'
down_revision: Union[str, None] = '2aaec46888f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'exa',    'display_name': 'Exa',    'ats': 'ashby',      'board_token': 'exa'},
    {'id': 'roblox', 'display_name': 'Roblox', 'ats': 'greenhouse', 'board_token': 'roblox'},
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
    op.execute("DELETE FROM companies WHERE id IN ('exa', 'roblox')")
