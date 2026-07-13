"""add category/level to user_saved_filters

Revision ID: a1b2c3d4e5f6
Revises: 8e59adfb817a
Create Date: 2026-07-12 18:00:00.000000+00:00

Adds two JSONB array columns — ``category`` and ``level`` — to
``user_saved_filters`` so a signed-in user can persist default enrichment facet
filters (category + level) the same way ``locations`` is persisted. Each is a
JSONB array of facet slugs (e.g. ``["software_engineering"]``, ``["senior"]``),
shared by both the Recent and Trend pages; the empty array means "no filter".

Metadata-only add: the default is a constant (``'[]'::jsonb``), so existing rows
backfill to ``[]`` without a table rewrite. Both ADDs are collapsed into one
``ALTER TABLE`` statement per the combined-ALTER rule from the 2026-04-18
migration/volume incident (multiple separate ``op.add_column`` calls can force
repeated rewrites).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '8e59adfb817a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_saved_filters "
        "ADD COLUMN category JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "ADD COLUMN level JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_saved_filters "
        "DROP COLUMN level, "
        "DROP COLUMN category"
    )
