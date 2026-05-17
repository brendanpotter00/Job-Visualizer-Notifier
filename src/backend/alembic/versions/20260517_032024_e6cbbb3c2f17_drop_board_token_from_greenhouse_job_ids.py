"""drop_board_token_from_greenhouse_job_ids

Revision ID: e6cbbb3c2f17
Revises: 939331c99a23
Create Date: 2026-05-17 03:20:24.365758+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule in feedback_use_alembic_migrations.md). No schema change — only rewrites
existing job_listings.id values from the legacy ``greenhouse_{board_token}_{raw_id}``
format to ``greenhouse_{raw_id}``.

Why drop the board_token segment: Greenhouse job IDs are globally unique
across the entire Greenhouse Job Board platform, so the ``greenhouse_``
source-namespace prefix alone is enough to avoid collisions with other ATS
providers (Apple, Google, Microsoft) sharing the ``job_listings`` table.
The board_token was redundant for uniqueness.

Safety: no foreign keys reference job_listings.id, so this is a pure value
rewrite — no cascade work. Pre-flight on dev (11,344 rows) confirmed the
raw Greenhouse IDs are themselves unique within the existing greenhouse
rows, so the rewrite cannot produce PK collisions. The upgrade re-verifies
this inside the same transaction before any UPDATE — see RAISE EXCEPTION
guard below — so a collision aborts the migration instead of silently
losing rows to a partial UPDATE.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e6cbbb3c2f17'
down_revision: Union[str, None] = '939331c99a23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard: abort if rewriting the IDs would produce a PK collision. The
    # regex matches the legacy ``greenhouse_{token}_{digits}`` shape; rows
    # already in the new ``greenhouse_{digits}`` form are skipped by the
    # WHERE clause and don't participate in either the guard or the UPDATE.
    op.execute(
        """
        DO $$
        DECLARE
            collisions int;
        BEGIN
            SELECT count(*) INTO collisions FROM (
                SELECT regexp_replace(id, '^greenhouse_.+_([0-9]+)$', 'greenhouse_\\1') AS new_id
                FROM job_listings
                WHERE id ~ '^greenhouse_.+_[0-9]+$'
                GROUP BY 1
                HAVING count(*) > 1
            ) c;
            IF collisions > 0 THEN
                RAISE EXCEPTION 'job_listings id rewrite would produce % PK collisions; aborting', collisions;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        UPDATE job_listings
        SET id = regexp_replace(id, '^greenhouse_.+_([0-9]+)$', 'greenhouse_\\1')
        WHERE id ~ '^greenhouse_.+_[0-9]+$'
        """
    )


def downgrade() -> None:
    # No-op: the legacy format encodes the board_token inline in the id, but
    # the new format does not, so a faithful reverse would require joining
    # job_listings against companies on company == companies.id to recover
    # the board_token. That's possible (board_token is in companies), but
    # it only helps if every row's company still has a row in companies —
    # which is true today but is not a constraint we want to lean on for
    # a rollback path. If you need to roll back, restore from snapshot.
    pass
