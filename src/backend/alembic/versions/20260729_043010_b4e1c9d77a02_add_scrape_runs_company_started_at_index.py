"""add scrape_runs (company, started_at) index

Revision ID: b4e1c9d77a02
Revises: 888b007b89fa
Create Date: 2026-07-29 04:30:10.220417+00:00

Supports ``database.count_consecutive_partial_skips``:

    SELECT guard_reason FROM scrape_runs
    WHERE company = %s ORDER BY started_at DESC LIMIT %s

Measured on production BEFORE this index: Parallel Seq Scan over 452,610
rows, ~70 MB of buffers, ~32 ms — the only index on the table was the
primary key. ``LIMIT`` bounds the top-N heapsort, NOT the scan volume, so
it did not make the query cheap.

Ascending on ``started_at`` rather than DESC on purpose: Postgres reads a
btree backwards at no cost, so ``(company, started_at)`` fully serves
``ORDER BY started_at DESC LIMIT n``, and a plain column index keeps
``test_alembic_parity``'s autogenerate comparison exact (an expression
index risks a spurious diff against ``Base.metadata``).

CONCURRENTLY + autocommit_block: ``scrape_runs`` is on the write path of
every scrape task (~3,100 inserts/day). A plain ``CREATE INDEX`` takes an
SHARE lock that blocks those writes for the duration of the build.
CONCURRENTLY cannot run inside a transaction block, and Alembic wraps each
migration in one, so ``autocommit_block()`` is required — without it this
fails with "CREATE INDEX CONCURRENTLY cannot run inside a transaction
block" at deploy time.

``IF NOT EXISTS`` is deliberate: a CONCURRENTLY build that fails partway
leaves an INVALID index of the same name behind, and a bare retry would
then die on "already exists". If this migration ever fails, check
``pg_index.indisvalid`` and DROP the invalid index before re-running.

Separate revision from 888b007b89fa on purpose — index creation has a
different operational risk profile from a catalog-only ADD COLUMN and
should be reviewable, and revertible, on its own.

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b4e1c9d77a02'
down_revision: Union[str, None] = '888b007b89fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "idx_scrape_runs_company_started_at"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
            "ON scrape_runs (company, started_at)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
