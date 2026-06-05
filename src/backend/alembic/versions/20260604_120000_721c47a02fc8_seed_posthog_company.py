"""seed posthog company

Revision ID: 721c47a02fc8
Revises: f6c3a1d4e5b2
Create Date: 2026-06-04 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``posthog`` (Ashby) — https://jobs.ashbyhq.com/posthog
  (board token ``posthog``; verified live at
  https://api.ashbyhq.com/posting-api/job-board/posthog)

Sits on top of the frozen per-ATS seeds (Ashby revision
``a17b7c0ffee500``) and the later single-company seeds (``1e35a6d3cb28``
exa+roblox, ``c3f2a1d4e5b6`` trajectory, ``d4e5b6c3f2a1`` krea,
``e5b6c3f2a1d4`` vizcom, ``f6c3a1d4e5b2`` fal); the per-ATS counts asserted
in ``test_migration_companies.py`` are unaffected because that test stops at
``WORKDAY_SEED_REV``, before these revisions.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``posthog`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '721c47a02fc8'
down_revision: Union[str, None] = 'f6c3a1d4e5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    {'id': 'posthog', 'display_name': 'PostHog', 'ats': 'ashby', 'board_token': 'posthog'},
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
    op.execute("DELETE FROM companies WHERE id IN ('posthog')")
