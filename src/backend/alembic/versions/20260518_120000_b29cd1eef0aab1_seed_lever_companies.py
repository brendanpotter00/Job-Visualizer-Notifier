"""seed lever companies

Revision ID: b29cd1eef0aab1
Revises: a17b7c0ffee500
Create Date: 2026-05-18 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Alembic's --autogenerate diffs schema, not data — so the 3 Lever
companies that previously lived in src/frontend/src/config/companies.ts
must be transcribed by hand into the per-row INSERT loop below.

Source of truth at the time of writing:
  src/frontend/src/config/companies.ts (Lever block, lines ~350-362)

All three Lever entries use board_token == id — the frontend never overrides
the Lever slug (`hostedUrl` is constructed as
``https://api.lever.co/v0/postings/<id>``).

Future Lever adds should be made via a new migration, NOT by editing this
one — frozen migrations stay frozen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b29cd1eef0aab1'
down_revision: Union[str, None] = 'a17b7c0ffee500'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEVER_SEED_ROWS = [
    {'id': 'palantir', 'display_name': 'Palantir', 'ats': 'lever', 'board_token': 'palantir'},
    {'id': 'spotify',  'display_name': 'Spotify',  'ats': 'lever', 'board_token': 'spotify'},
    {'id': 'zoox',     'display_name': 'Zoox',     'ats': 'lever', 'board_token': 'zoox'},
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
    for row in LEVER_SEED_ROWS:
        bind.execute(insert_sql, row)


def downgrade() -> None:
    # Scoped DELETE — must not touch Greenhouse / Ashby rows or any
    # out-of-band rows with other ats values. Mirrors the Ashby seed's
    # downgrade.
    op.execute("DELETE FROM companies WHERE ats = 'lever'")
