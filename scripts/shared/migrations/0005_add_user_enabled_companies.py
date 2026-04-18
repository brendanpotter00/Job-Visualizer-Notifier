"""
Migration 0005: Add user_enabled_companies table.

Tracks which company IDs each user has enabled for the "Recent Jobs Companies"
preference. The table was originally created inline in init_schema on main
(commit 0a64bd3); merged into the migration runner here so a fresh install
applied through migrate_up gets the same shape, and an existing prod database
that already has the table sees a no-op (CREATE TABLE IF NOT EXISTS).
"""


def upgrade(conn, env):
    cursor = conn.cursor()
    users_table = f"users_{env}"
    enabled_companies_table = f"user_enabled_companies_{env}"

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {enabled_companies_table} (
            user_id TEXT NOT NULL REFERENCES {users_table}(id) ON DELETE CASCADE,
            company_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, company_id)
        )
    """)
    cursor.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{enabled_companies_table}_user_id "
        f"ON {enabled_companies_table}(user_id)"
    )


def downgrade(conn, env):
    cursor = conn.cursor()
    cursor.execute(f"DROP TABLE IF EXISTS user_enabled_companies_{env} CASCADE")
