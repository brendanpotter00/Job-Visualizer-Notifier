"""
Migration 0004: Convert remaining timestamp-like columns on job_listings
from TEXT to TIMESTAMPTZ.

Columns:
  - created_at      (NOT NULL)
  - closed_on       (nullable)
  - first_seen_at   (NOT NULL)
  - last_seen_at    (NOT NULL, indexed by idx_job_listings_*_last_seen)

All existing values are ISO 8601 strings written by scraper code paths via
shared.database, so the USING posted_on::timestamptz pattern parses them in
place. The index on last_seen_at is rebuilt automatically by ALTER COLUMN TYPE.
"""

_COLUMNS = ("created_at", "closed_on", "first_seen_at", "last_seen_at")


def upgrade(conn, env):
    cursor = conn.cursor()
    table = f"job_listings_{env}"
    for col in _COLUMNS:
        cursor.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {col} TYPE TIMESTAMPTZ "
            f"USING {col}::timestamptz"
        )


def downgrade(conn, env):
    cursor = conn.cursor()
    table = f"job_listings_{env}"
    for col in _COLUMNS:
        cursor.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {col} TYPE TEXT "
            f"USING {col}::text"
        )
