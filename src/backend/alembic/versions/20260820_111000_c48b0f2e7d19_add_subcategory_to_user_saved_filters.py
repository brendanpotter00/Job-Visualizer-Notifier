"""add subcategory to user_saved_filters

Revision ID: c48b0f2e7d19
Revises: 5a7d3e9c1b46
Create Date: 2026-08-20 11:10:00.000000+00:00

Adds one JSONB array column — ``subcategory`` — to ``user_saved_filters`` so a
signed-in user can persist a default SWE-subcategory selection the same way
``category`` and ``level`` are persisted. SINGULAR, matching those two sibling
columns: the plural ``subcategories`` is the JOB-side field on ``job_listings``,
and the two must not be confused.

Modelled verbatim on ``a1b2c3d4e5f6`` (the category/level add), including the
single combined ``op.execute("ALTER TABLE …")`` and the mirrored DROP.

**Metadata-only**: the default is a constant (``'[]'::jsonb``), so existing rows
backfill to ``[]`` without a table rewrite. That matters because the frontend
sends the WHOLE saved-filters object on every PUT and the request model is
``extra='forbid'`` — this column must exist server-side BEFORE the SPA starts
sending the field, or the entire PUT 422s and the user loses their other
selections too. Railway before Vercel.

``SET LOCAL lock_timeout = '5s'`` first in both directions: prod runs with no
``lock_timeout`` at all, and this ``ALTER`` takes ACCESS EXCLUSIVE inside the
FastAPI lifespan. Same line, same reason, as ``7c1a4f2b9e30``.

THE ``[]`` COLLISION, stated once here because this is one of the two columns
that carries it: ``user_saved_filters.subcategory = '[]'`` means "no filter
selected — show EVERYTHING". On the other side,
``job_listings.enrichment_subcategories = '{}'`` means "evaluated, and no
specialty applies" and is TERMINAL. Same literal, opposite meanings.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c48b0f2e7d19'
down_revision: Union[str, None] = '5a7d3e9c1b46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE user_saved_filters "
        "ADD COLUMN subcategory JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE user_saved_filters DROP COLUMN subcategory")
