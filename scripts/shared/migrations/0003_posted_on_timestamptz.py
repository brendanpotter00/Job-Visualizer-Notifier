"""
Migration 0003: Change job_listings.posted_on from TEXT to TIMESTAMPTZ.

All populated values are ISO 8601 strings with explicit UTC offsets, written by
the Apple and Microsoft scrapers. Google leaves posted_on NULL. PostgreSQL's
USING clause parses these strings directly into timestamptz.

Pre-flight scan: before the ALTER, confirm every non-null value starts with an
ISO 8601 date prefix. If any row fails the scan, raise with a sample so the
deploy log shows which rows need fixing — otherwise ALTER fails with the
opaque "invalid input syntax for type timestamp" message.
"""


_ISO_PREFIX_REGEX = r"^\d{4}-\d{2}-\d{2}T"


def _scan_malformed(conn, table, column):
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT id, {column} FROM {table} "
        f"WHERE {column} IS NOT NULL AND {column}::text !~ %s "
        f"LIMIT 10",
        (_ISO_PREFIX_REGEX,),
    )
    return cursor.fetchall()


def upgrade(conn, env):
    cursor = conn.cursor()
    table = f"job_listings_{env}"

    # Skip the scan if the column is already timestamptz (re-run safety).
    cursor.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = 'posted_on'",
        (table,),
    )
    row = cursor.fetchone()
    current_type = row[0] if row and not isinstance(row, dict) else (row["data_type"] if row else None)
    if current_type == "timestamp with time zone":
        return

    if current_type is None:
        # Either the column is missing or the table doesn't exist. Probe for
        # any columns on the table so we can give the operator a sharper
        # error than psycopg2's opaque UndefinedTable/UndefinedColumn.
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s LIMIT 1",
            (table,),
        )
        any_col = cursor.fetchone()
        if any_col is None:
            raise RuntimeError(
                f"Migration 0003_posted_on_timestamptz: table {table} "
                f"not found (env={env}). Migration 0001_initial_schema may "
                f"not be applied, or schema drift has removed the table."
            )
        raise RuntimeError(
            f"Migration 0003_posted_on_timestamptz: column posted_on "
            f"not found on {table} (env={env}). Schema drift detected; "
            f"0001_initial_schema is expected to have created this column."
        )

    malformed = _scan_malformed(conn, table, "posted_on")
    if malformed:
        samples = [m[0] if not isinstance(m, dict) else m["id"] for m in malformed]
        raise RuntimeError(
            f"Cannot convert {table}.posted_on to TIMESTAMPTZ: "
            f"{len(malformed)} row(s) have non-ISO-8601 values. "
            f"Sample ids: {samples}"
        )

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
