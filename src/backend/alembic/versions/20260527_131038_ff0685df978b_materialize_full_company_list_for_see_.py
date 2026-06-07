"""materialize full company list for see-all users

Revision ID: ff0685df978b
Revises: 204a7e074899
Create Date: 2026-05-27 13:10:38.722228+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). One-time launch backfill for the auto-enroll feature: every user who
currently has ZERO rows in ``user_enabled_companies`` (the implicit "see all"
state) is given an explicit row for every currently-enabled company, so they
become explicit-list users and the auto-enroll watermark logic applies to them
going forward.

Curated users (≥1 existing row) are left untouched — combined with the
launch-time ``company_enroll_watermark`` set in revision ``204a7e074899``, this
makes the rollout forward-only: only companies added after launch auto-enroll.

Users who sign up AFTER this migration keep the existing "zero rows = see all"
default (this backfill is a one-shot, not a per-signup hook).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'ff0685df978b'
down_revision: Union[str, None] = '204a7e074899'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO user_enabled_companies (user_id, company_id)
        SELECT u.id, c.id
        FROM users u CROSS JOIN companies c
        WHERE c.enabled
          AND NOT EXISTS (
            SELECT 1 FROM user_enabled_companies e WHERE e.user_id = u.id
          )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # Intentional no-op: once materialized, a backfilled row is indistinguishable
    # from a row the user chose themselves, so reversing would delete legitimate
    # user data. Leave the rows in place on downgrade.
    pass
