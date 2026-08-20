"""Add ``app_settings`` — a tiny key/value table for runtime-tunable settings.

ONE table, ONE revision, ONE owner.

    key        TEXT        PRIMARY KEY
    value      JSONB       NOT NULL
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    updated_by TEXT        NULL          -- admin email from the JWT claim

SEED POLICY: **NO SEED ROW. ABSENT MEANS THE CODE DEFAULT.**

This is the load-bearing decision in the whole step, so it is stated plainly: a
fresh database, a flag an admin deleted, and a rolled-back migration all behave
IDENTICALLY, and the reader can never 500 on a missing row. Seeding a row would
make "no row" an anomalous state that every read path has to handle, and one of
them would handle it wrong.

The set of legal keys is an ALLOWLIST IN CODE (``services/app_settings.py``'s
``_SETTING_SPECS``), deliberately not in the DDL — adding a setting must not need
a migration, and a CHECK constraint on `key` would make one necessary. The single
allowlisted key today is ``swe_subcategories_enabled`` (bool, default ``false``);
it is named nowhere in this file for the same reason.

No indexes. The table holds single-digit rows; every read is either by primary
key or a full scan of all of them.

DEPLOY CONTEXT
--------------
``SET LOCAL lock_timeout = '5s'`` first in BOTH directions — the house rule is
unconditional even for a CREATE TABLE that takes no lock on anything existing,
because "which migrations need it" is not a judgement anyone should have to make
under deploy pressure. Otherwise this is as cheap as a migration gets: one new
empty table, no ALTER on any existing relation.

DOWNGRADE
---------
Drops the table. Lossless in the sense that matters: with no seed row, the
post-downgrade state (no table) and the post-upgrade-never-written state (empty
table) both read as "every setting is at its code default".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b93d5c17a842'
down_revision: Union[str, None] = '7c1a4f2b9e30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.create_table(
        'app_settings',
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            'updated_at',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('updated_by', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('key'),
    )
    # NO INSERT here, on purpose. See "SEED POLICY" above.


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table('app_settings')
