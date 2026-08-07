"""add user-submitted companies

Adds the schema backing the "add your own company by careers-page URL" flow:

* ``companies.listed`` (bool, default true) — curated rows stay listed; runtime
  user-added rows are unlisted so they never appear in the public
  ``GET /api/companies`` directory (they are still scraped and visible in the
  jobs UI to users who track them).
* ``companies.added_by_user_id`` (nullable FK ``users.id`` ON DELETE SET NULL) —
  attribution / abuse accounting; NULL for curated rows.
* ``companies.health_status`` (text, default 'ok') — scrape health for runtime
  sources; the fetch task flips it to 'degraded' when the low-yield safety guard
  trips.
* ``company_submissions`` — async onboarding + audit + rate-limit source for the
  add-company flow.

The three ``companies`` columns are added in a **single** ``ALTER TABLE`` (one
table pass) per the combined-ALTER rule — see
``docs/incidents/2026-04-18-migration-filled-postgres-volume/``. All three are
NOT NULL with a server default, so existing rows backfill with no separate DML.

Revision ID: 5b6a9e76b31e
Revises: 5ee285a3c724
Create Date: 2026-07-25 16:14:49.876866+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b6a9e76b31e'
down_revision: Union[str, None] = '5ee285a3c724'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_NAME = "fk_companies_added_by_user_id_users"


def upgrade() -> None:
    op.create_table(
        'company_submissions',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column(
            'status', sa.Text(), server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column('company_id', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_company_submissions_user_created', 'company_submissions',
        ['user_id', 'created_at'], unique=False,
    )

    # Single ALTER TABLE for all three new columns + the FK (combined-ALTER
    # rule — one table pass, avoids repeated rewrites on the large table).
    op.execute(
        sa.text(
            "ALTER TABLE companies "
            "ADD COLUMN listed BOOLEAN NOT NULL DEFAULT true, "
            "ADD COLUMN added_by_user_id TEXT, "
            "ADD COLUMN health_status TEXT NOT NULL DEFAULT 'ok', "
            f"ADD CONSTRAINT {_FK_NAME} "
            "FOREIGN KEY (added_by_user_id) REFERENCES users (id) "
            "ON DELETE SET NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE companies "
            f"DROP CONSTRAINT IF EXISTS {_FK_NAME}, "
            "DROP COLUMN IF EXISTS health_status, "
            "DROP COLUMN IF EXISTS added_by_user_id, "
            "DROP COLUMN IF EXISTS listed"
        )
    )
    op.drop_index(
        'ix_company_submissions_user_created',
        table_name='company_submissions',
    )
    op.drop_table('company_submissions')
