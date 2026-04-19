"""
Migration 0001: Baseline schema.

Captures the schema state immediately before migrations were introduced:
- job_listings_{env} with all 17 columns and three indexes
- scrape_runs_{env} with all 10 columns
- users_{env} with auth0_id UNIQUE but NOT YET email UNIQUE, plus its two indexes

All statements use IF NOT EXISTS so this migration is a no-op against databases
that already have these tables (the common case on first migration run).
The follow-up migration 0002 adds the email UNIQUE constraint.
"""


def upgrade(conn, env):
    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"
    runs_table = f"scrape_runs_{env}"
    users_table = f"users_{env}"

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {jobs_table} (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            url TEXT NOT NULL,
            source_id TEXT NOT NULL,
            details JSONB DEFAULT '{{}}'::jsonb,
            posted_on TEXT,
            created_at TEXT NOT NULL,
            closed_on TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            has_matched BOOLEAN DEFAULT FALSE,
            ai_metadata JSONB DEFAULT '{{}}'::jsonb,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            consecutive_misses INTEGER DEFAULT 0,
            details_scraped BOOLEAN DEFAULT FALSE
        )
    """)

    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{jobs_table}_status ON {jobs_table}(status)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{jobs_table}_company ON {jobs_table}(company)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{jobs_table}_last_seen ON {jobs_table}(last_seen_at)")

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {runs_table} (
            run_id TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            mode TEXT NOT NULL,
            jobs_seen INTEGER DEFAULT 0,
            new_jobs INTEGER DEFAULT 0,
            closed_jobs INTEGER DEFAULT 0,
            details_fetched INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0
        )
    """)

    # Baseline users table: auth0_id is UNIQUE, email is NOT NULL (no UNIQUE yet).
    # The email UNIQUE constraint is added by migration 0002.
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {users_table} (
            id TEXT PRIMARY KEY,
            auth0_id TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            display_name TEXT,
            given_name TEXT,
            family_name TEXT,
            picture_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{users_table}_auth0_id ON {users_table}(auth0_id)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{users_table}_email ON {users_table}(email)")


def downgrade(conn, env):
    cursor = conn.cursor()
    cursor.execute(f"DROP TABLE IF EXISTS users_{env} CASCADE")
    cursor.execute(f"DROP TABLE IF EXISTS scrape_runs_{env} CASCADE")
    cursor.execute(f"DROP TABLE IF EXISTS job_listings_{env} CASCADE")
