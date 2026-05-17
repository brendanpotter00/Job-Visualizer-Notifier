"""job_listings composite (source_id, id) primary key

Revision ID: ebb479b7eed5
Revises: e6cbbb3c2f17
Create Date: 2026-05-17 21:38:35.886073+00:00

Schema + data migration: replaces the single-column PK on ``job_listings.id``
with the composite PK ``(source_id, id)`` and strips the legacy
``greenhouse_`` id prefix that existed because the single-column PK forced
each source to namespace its ids by string convention.

Why composite: ``source_id`` is the actual uniqueness boundary upstream
(Greenhouse ids are globally unique across all 45 boards; Google/Apple/
Microsoft ids are unique within their respective scrapers). Lifting that
guarantee into the schema removes the per-source "do we prefix?" decision
and lets a future ATS source whose id space overlaps with an existing
source's id space coexist for free.

Safety: belt-and-suspenders RAISE EXCEPTION guards in both directions
abort the migration before any destructive write if a collision is
detected. The combined ``ALTER TABLE … DROP CONSTRAINT …, ADD PRIMARY
KEY …`` statement rebuilds the PK index in one pass (per the combined-
ALTER rule in docs/implementations/alembicMigration/DEPLOY.md).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ebb479b7eed5'
down_revision: Union[str, None] = 'e6cbbb3c2f17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Belt-and-suspenders: source_id is already NOT NULL per the schema,
    # but verify before the destructive UPDATE. Cheap, surfaces drift loudly.
    op.execute(
        """
        DO $$
        DECLARE
            null_count int;
        BEGIN
            SELECT count(*) INTO null_count
            FROM job_listings
            WHERE source_id IS NULL;
            IF null_count > 0 THEN
                RAISE EXCEPTION
                    'job_listings has % rows with NULL source_id; '
                    'composite PK requires source_id NOT NULL', null_count;
            END IF;
        END
        $$;
        """
    )

    # Strip the legacy ``greenhouse_`` prefix. Only touches rows that still
    # carry the prefix; idempotent on a re-run after a partial migration.
    op.execute(
        """
        UPDATE job_listings
        SET id = regexp_replace(id, '^greenhouse_', '')
        WHERE source_id = 'greenhouse_api' AND id LIKE 'greenhouse_%'
        """
    )

    # Pre-flight: after the rewrite above, would the new composite PK have
    # any duplicate (source_id, id) pair? If so, RAISE and abort the txn.
    # Mirror of the e6cbbb3c2f17 pattern, generalized to the composite key.
    op.execute(
        """
        DO $$
        DECLARE
            collisions int;
        BEGIN
            SELECT count(*) INTO collisions FROM (
                SELECT source_id, id
                FROM job_listings
                GROUP BY source_id, id
                HAVING count(*) > 1
            ) c;
            IF collisions > 0 THEN
                RAISE EXCEPTION
                    'job_listings would have % (source_id, id) PK collisions '
                    'after id rewrite; aborting', collisions;
            END IF;
        END
        $$;
        """
    )

    # Combined ALTER: one statement so Postgres rebuilds the PK index once.
    op.execute(
        "ALTER TABLE job_listings "
        "DROP CONSTRAINT job_listings_pkey, "
        "ADD PRIMARY KEY (source_id, id)"
    )


def downgrade() -> None:
    # Pre-flight: re-prefixing Greenhouse rows must not collide with any
    # non-Greenhouse row whose id already equals 'greenhouse_' || <raw>.
    op.execute(
        """
        DO $$
        DECLARE
            collisions int;
        BEGIN
            SELECT count(*) INTO collisions
            FROM job_listings a
            JOIN job_listings b
              ON b.id = 'greenhouse_' || a.id
             AND b.source_id <> 'greenhouse_api'
            WHERE a.source_id = 'greenhouse_api';
            IF collisions > 0 THEN
                RAISE EXCEPTION
                    'downgrade would collide with % non-greenhouse rows that '
                    'already use the greenhouse_<raw> id shape; aborting',
                    collisions;
            END IF;
        END
        $$;
        """
    )

    # Re-prefix Greenhouse rows so the single-column PK can be restored.
    op.execute(
        """
        UPDATE job_listings
        SET id = 'greenhouse_' || id
        WHERE source_id = 'greenhouse_api'
        """
    )

    # Combined ALTER, mirror of upgrade.
    op.execute(
        "ALTER TABLE job_listings "
        "DROP CONSTRAINT job_listings_pkey, "
        "ADD PRIMARY KEY (id)"
    )
