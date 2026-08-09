"""seed tiktok company

Revision ID: d8b52c04f6e3
Revises: c7a41b93e5d2
Create Date: 2026-08-09 12:30:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``tiktok`` (script) — scraped by ``scripts/tiktok_jobs_scraper``

Chains off ``c7a41b93e5d2`` (the Amazon seed migration), which is the single
head on ``main`` as of this rebase. This branch was originally cut off
``b4e1c9d77a02``; the sibling Amazon PR (#245) merged first and took that slot,
so this migration was re-pointed at Amazon's revision during the rebase.
Leaving it on ``b4e1c9d77a02`` would give the chain two heads and crash-loop the
backend on boot. Re-run ``.claude/skills/add-company/scripts/current_head.py``
before merging if ``main`` gains another migration in the meantime.

Why a migration rather than ``company_profiles.json``:
``services/companies_seed.py`` inserts a row for any profile carrying an
``ats`` key, but hardcodes ``created_at`` to ``_BACKFILL_CREATED_AT``
(2020-01-01) so the legacy script companies would not force-enroll existing
users. A newly added company *should* auto-enroll — the behaviour every
ATS-backed company gets — so the row is created here with a real
``created_at``. ``user_preferences_service`` enrolls on
``c.created_at > u.company_enroll_watermark``.

The boot seeder still runs after this migration (main.py applies migrations at
line 129 and seeds at line 166); its INSERT is ``ON CONFLICT (id) DO NOTHING``
so it defers to this row, while its second phase still upserts the
blurb/accomplishment from ``company_profiles.json``. The TikTok profile
deliberately carries no ``ats`` key so ``script_inserted`` stays at 3 and the
existing ``test_companies_seed.py`` contract is untouched.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``tiktok`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8b52c04f6e3'
down_revision: Union[str, None] = 'c7a41b93e5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    # board_token is meaningless for a script company (no vendor board behind
    # it) but the column is NOT NULL, so it mirrors the id — same as the
    # google/apple/microsoft rows the boot seeder writes.
    {'id': 'tiktok', 'display_name': 'TikTok', 'ats': 'script', 'board_token': 'tiktok'},
]


def upgrade() -> None:
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, created_at) "
        "VALUES (:id, :display_name, :ats, :board_token, TRUE, now()) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in SEED_ROWS:
        bind.execute(insert_sql, row)


def downgrade() -> None:
    op.execute("DELETE FROM companies WHERE id = 'tiktok'")
