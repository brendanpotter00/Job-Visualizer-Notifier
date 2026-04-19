"""
Migration 0004: Convert remaining timestamp-like columns on job_listings
from TEXT to TIMESTAMPTZ.

Columns:
  - created_at      (NOT NULL)
  - closed_on       (nullable)
  - first_seen_at   (NOT NULL)
  - last_seen_at    (NOT NULL, indexed by idx_job_listings_*_last_seen)

All existing values are ISO 8601 strings written by scraper code paths via
shared.database, so the USING <col>::timestamptz pattern parses them in
place. The index on last_seen_at is rebuilt automatically by ALTER COLUMN TYPE.

Memory/disk: a single ALTER TABLE with multiple ALTER COLUMN clauses is one
table rewrite and one WAL stream, not N. Original implementation issued four
separate ALTERs in a Python loop, which on 2026-04-19 pushed job_listings_prod
through four full-table rewrites + four WAL streams and filled the 5 GB Hobby
volume mid-migration (see docs/incidents/2026-04-18-migration-filled-postgres-volume.md).
The combined statement is what Alembic's batch_alter_table emits by default and
is required for future re-runs (e.g. restore-to-new-env) to fit in the volume.

Per-column pre-flight scan (see 0003) catches malformed rows before ALTER so
deploy logs show actionable row ids instead of psycopg2's opaque cast error.
"""

_COLUMNS = ("created_at", "closed_on", "first_seen_at", "last_seen_at")
_ISO_PREFIX_REGEX = r"^\d{4}-\d{2}-\d{2}T"


def _column_type(conn, table, column):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return row["data_type"] if isinstance(row, dict) else row[0]


def _scan_malformed(conn, table, column):
    # f-string-substituting `column` is safe today because every call site
    # passes a value from `_COLUMNS`, but the assertion stops a future copy-
    # paste from inheriting an injection primitive.
    assert column in _COLUMNS, f"_scan_malformed column not allow-listed: {column!r}"
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

    pending = []
    for col in _COLUMNS:
        col_type = _column_type(conn, table, col)
        # Re-run safety: skip columns already converted.
        if col_type == "timestamp with time zone":
            continue

        if col_type is None:
            raise RuntimeError(
                f"Migration 0004_job_timestamps_timestamptz: column {col} "
                f"not found on {table} (env={env}). Schema drift detected; "
                f"0001_initial_schema is expected to have created this column."
            )

        malformed = _scan_malformed(conn, table, col)
        if malformed:
            samples = [m[0] if not isinstance(m, dict) else m["id"] for m in malformed]
            raise RuntimeError(
                f"Migration 0004_job_timestamps_timestamptz: cannot convert "
                f"{table}.{col} to TIMESTAMPTZ: {len(malformed)} row(s) "
                f"do not match the ISO 8601 prefix '^YYYY-MM-DDT'. "
                f"Sample ids: {samples}"
            )

        pending.append(col)

    if not pending:
        return

    # One ALTER TABLE, one full rewrite, one WAL stream for all pending columns.
    clauses = ", ".join(
        f"ALTER COLUMN {col} TYPE TIMESTAMPTZ USING {col}::timestamptz"
        for col in pending
    )
    cursor.execute(f"ALTER TABLE {table} {clauses}")


def downgrade(conn, env):
    cursor = conn.cursor()
    table = f"job_listings_{env}"
    clauses = ", ".join(
        f"ALTER COLUMN {col} TYPE TEXT USING {col}::text" for col in _COLUMNS
    )
    cursor.execute(f"ALTER TABLE {table} {clauses}")
