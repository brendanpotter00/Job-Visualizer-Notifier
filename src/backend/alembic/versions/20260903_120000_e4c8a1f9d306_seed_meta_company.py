"""seed meta company

Revision ID: e4c8a1f9d306
Revises: d7b3c9e15af2
Create Date: 2026-09-03 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the
autogenerate-only rule). Adds one company to the ``companies`` table:

- ``meta`` (script) — scraped by ``scripts/meta_jobs_scraper``

Chains off ``d7b3c9e15af2`` (``seed_easy_batch2_companies``), which is the
single head on ``main`` as of this rebase. That head was computed FRESH with a
tuple-aware DAG parse of ``alembic/versions/`` (the head is the revision that
appears as no other migration's ``down_revision``, counting hex ids inside
tuple ``down_revision``s too). Do NOT trust
``.claude/skills/add-company/scripts/current_head.py`` here: two merge
migrations use tuple ``down_revision``s its regex cannot parse
(``a5cf3aed5f15`` → ``('fb8467065dfc', '1d2d6c17acfc')`` and
``2633dd6348e4`` → ``('a5cf3aed5f15', '9d2f7ae5c1b4')``), so it mis-reports four
heads. Re-verify the single head before merging if ``main`` gains another
migration in the meantime — chaining off the wrong revision creates a multi-head
and crash-loops the backend on boot.

Why a migration rather than ``company_profiles.json``:
``services/companies_seed.py`` inserts a row for any profile carrying an
``ats`` key, but hardcodes ``created_at`` to ``_BACKFILL_CREATED_AT``
(2020-01-01) so the legacy script companies would not force-enroll existing
users. A newly added company *should* auto-enroll — the behaviour every
ATS-backed company gets — so the row is created here with a real
``created_at``. ``user_preferences_service`` enrolls on
``c.created_at > u.company_enroll_watermark``.

The boot seeder still runs after this migration; its INSERT is
``ON CONFLICT (id) DO NOTHING`` so it defers to this row, while its second phase
still upserts the blurb/accomplishment from ``company_profiles.json``. The Meta
profile deliberately carries no ``ats`` key so ``script_inserted`` stays
unchanged and the existing ``test_companies_seed.py`` contract is untouched.

Source of truth for the frontend entry:
  src/frontend/src/config/companies.ts (``meta`` row)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4c8a1f9d306'
down_revision: Union[str, None] = 'd7b3c9e15af2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    # board_token is meaningless for a script company (no vendor board behind
    # it) but the column is NOT NULL, so it mirrors the id — same as the
    # google/apple/microsoft/tiktok rows. provider_config is omitted from the
    # INSERT: the column is NOT NULL DEFAULT '{}'::jsonb, so it defaults to {}.
    {'id': 'meta', 'display_name': 'Meta', 'ats': 'script', 'board_token': 'meta'},
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
    op.execute("DELETE FROM companies WHERE id = 'meta'")
