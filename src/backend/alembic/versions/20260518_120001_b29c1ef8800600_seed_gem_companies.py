"""seed gem companies

Revision ID: b29c1ef8800600
Revises: b29cd1eef0aab1
Create Date: 2026-05-18 12:00:01.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Alembic's --autogenerate diffs schema, not data — so the 3 Gem
companies that previously lived in src/frontend/src/config/companies.ts
must be transcribed by hand into the per-row INSERT loop below.

Source of truth at the time of writing:
  src/frontend/src/config/companies.ts (Gem block, lines ~526-529)

All three entries use board_token == id — none override `vanityUrlPath`
in the frontend factory. Future Gem adds should be made via a NEW
migration, not by editing this one — frozen migrations stay frozen.

Note: this migration was re-anchored to chain off the Lever seed
(`b29cd1eef0aab1`) instead of the Ashby seed (`a17b7c0ffee500`) when the
Gem PR merged after the Lever PR. The seed data itself is unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b29c1ef8800600'
down_revision: Union[str, None] = 'b29cd1eef0aab1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GEM_SEED_ROWS = [
    {'id': 'nominal', 'display_name': 'Nominal', 'ats': 'gem', 'board_token': 'nominal'},
    {'id': 'retool',  'display_name': 'Retool',  'ats': 'gem', 'board_token': 'retool'},
    {'id': 'gem',     'display_name': 'Gem',     'ats': 'gem', 'board_token': 'gem'},
]


def upgrade() -> None:
    # ON CONFLICT (id) DO NOTHING for idempotency: if any of these rows were
    # backfilled out-of-band (manual repair, partial prior run, prod hotfix),
    # the seed migration must NOT trip a PK-conflict and brick startup.
    # `enabled` is omitted from the INSERT; the column has server_default=true.
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token) "
        "VALUES (:id, :display_name, :ats, :board_token) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in GEM_SEED_ROWS:
        bind.execute(insert_sql, row)


def downgrade() -> None:
    # Scoped DELETE — must not touch Greenhouse / Ashby rows or any
    # out-of-band rows with other ats values. Mirrors the Greenhouse /
    # Ashby seeds' downgrades.
    op.execute("DELETE FROM companies WHERE ats = 'gem'")
