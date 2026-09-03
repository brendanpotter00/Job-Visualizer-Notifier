"""user_display_name on companies (owner rename)

The owner's own name for a private board he tracks, beside — never instead of —
the URL-derived ``display_name``.

WHY A SECOND COLUMN RATHER THAN A FLAG. ``display_name`` on a custom company is
written by four things, and two of them are UPDATEs that re-run long after the
add: ``custom_companies_service._promote_to_tracked`` rewrites it every time
discovery ACCEPTS the board, and ``restart_refused_discovery`` rewrites it on the
retry of a refused board. A boolean "this name is custom" would oblige every one
of those — and every write added later — to remember a ``CASE WHEN`` guard, and
the first one that forgot would silently revert a user's rename. A separate
column cannot be clobbered by a statement that does not name it, so the
protection is structural rather than remembered. Readers resolve
``COALESCE(user_display_name, display_name)``; see
``custom_companies_service.EFFECTIVE_DISPLAY_NAME_SQL``, which is the one place
that string is spelled.

CATALOG-ONLY. Nullable with no server default, so PostgreSQL records the column
in the catalog and rewrites nothing — the same rule the E7 Phase-1 migration
(``fb8467065dfc``) follows for the seven columns it added to this table, and the
reason ``docs/incidents/2026-04-18-migration-filled-postgres-volume/`` exists.
The brief ACCESS EXCLUSIVE lock is held for the catalog update only, not for a
scan of the ~130 public rows plus every private one.

Every existing row keeps NULL, which means "never renamed" — so this migration
cannot change a single name that renders today.

Revision ID: fe69ff596030
Revises: b4d17c2a9e51
Create Date: 2026-08-30 22:59:01.592073+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe69ff596030'
down_revision: Union[str, None] = 'b4d17c2a9e51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('user_display_name', sa.Text(), nullable=True))


def downgrade() -> None:
    # Drops every rename. That is the honest downgrade: the derived name in
    # ``display_name`` was maintained all along, so a downgraded row falls back
    # to exactly the label it would have had if this feature had never shipped.
    op.drop_column('companies', 'user_display_name')
