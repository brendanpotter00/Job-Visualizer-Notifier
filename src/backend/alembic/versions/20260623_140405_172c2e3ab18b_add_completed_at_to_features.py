"""add completed_at to features

Revision ID: 172c2e3ab18b
Revises: 7ccc685e2cd6
Create Date: 2026-06-23 14:04:05.568413+00:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '172c2e3ab18b'
# Chained after main's 7ccc685e2cd6 (add visit_count/last_visit_at) rather than
# directly after 6df9297dcc67: both this PR and #172 branched off 6df9297dcc67,
# so leaving both at that down_revision would create two Alembic heads (backend
# crash-on-boot). Re-pointing keeps a single linear head. The two migrations are
# independent (features.completed_at vs users.visit_count), so order is moot.
down_revision: Union[str, None] = '7ccc685e2cd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Single nullable column, no default -> metadata-only ALTER (no table
    # rewrite), written as one ALTER TABLE per the combined-ALTER-TABLE rule
    # (docs/implementations/alembicMigration/DEPLOY.md + the 2026-04-18
    # postmortem). Autogenerate also surfaced unrelated procrastinate/feedback
    # drift from the local DB; that noise was intentionally dropped — this
    # revision only owns the features.completed_at column.
    op.execute(
        "ALTER TABLE features ADD COLUMN completed_at TIMESTAMP WITH TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE features DROP COLUMN completed_at")
