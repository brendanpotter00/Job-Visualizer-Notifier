"""
Migration 0003: Change job_listings.posted_on from TEXT to TIMESTAMPTZ.

All populated values are ISO 8601 strings with explicit UTC offsets, written by
the Apple and Microsoft scrapers. Google leaves posted_on NULL. PostgreSQL's
USING clause parses these strings directly into timestamptz.
"""


def upgrade(conn, env):
    cursor = conn.cursor()
    table = f"job_listings_{env}"
    cursor.execute(
        f"ALTER TABLE {table} "
        f"ALTER COLUMN posted_on TYPE TIMESTAMPTZ "
        f"USING posted_on::timestamptz"
    )


def downgrade(conn, env):
    cursor = conn.cursor()
    table = f"job_listings_{env}"
    cursor.execute(
        f"ALTER TABLE {table} "
        f"ALTER COLUMN posted_on TYPE TEXT "
        f"USING posted_on::text"
    )
