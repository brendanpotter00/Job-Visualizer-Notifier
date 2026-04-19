"""
Migration 0002: Add UNIQUE constraint on users.email.

Matches the code-review fix on main that made users_{env}.email UNIQUE, so that
existing databases (created under the 0001 baseline) pick up the constraint.

Idempotent: checks pg_constraint before adding. Fails fast with a clear error
if duplicate emails already exist, so the migration doesn't leave the table
in a half-constrained state.
"""


def _constraint_name(env):
    return f"users_{env}_email_key"


def upgrade(conn, env):
    cursor = conn.cursor()
    users_table = f"users_{env}"
    constraint = _constraint_name(env)

    # Idempotency: if the constraint is already there (e.g. fresh DB created
    # after the email-UNIQUE line was added to init_schema but before migrations
    # were introduced), skip.
    cursor.execute(
        "SELECT 1 FROM pg_constraint WHERE conname = %s",
        (constraint,),
    )
    if cursor.fetchone() is not None:
        return

    # Precondition: no duplicate emails. If this fails, the ALTER would fail
    # mid-statement with an opaque error; surface it explicitly instead.
    cursor.execute(
        f"SELECT email, COUNT(*) FROM {users_table} GROUP BY email HAVING COUNT(*) > 1"
    )
    duplicates = cursor.fetchall()
    if duplicates:
        raise RuntimeError(
            f"Cannot add UNIQUE constraint on {users_table}.email: "
            f"duplicate emails found ({len(duplicates)} groups). "
            f"Resolve duplicates manually before re-running."
        )

    cursor.execute(
        f"ALTER TABLE {users_table} ADD CONSTRAINT {constraint} UNIQUE (email)"
    )


def downgrade(conn, env):
    cursor = conn.cursor()
    users_table = f"users_{env}"
    constraint = _constraint_name(env)
    cursor.execute(f"ALTER TABLE {users_table} DROP CONSTRAINT IF EXISTS {constraint}")
