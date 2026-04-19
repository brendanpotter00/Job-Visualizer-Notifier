"""rename env-suffixed pk/fk constraints

Revision ID: f4008c4fb790
Revises: e1974f8f8eee
Create Date: 2026-04-19 17:05:00.000000+00:00

envAgnosticTables follow-up: `e1974f8f8eee` renamed the four user tables,
their named indexes, and the `users_{env}_email_key` UNIQUE constraint, but
left the auto-generated PK, FK, and `users_{env}_auth0_id_key` UNIQUE
constraint names carrying the `_{env}` suffix. Postgres identifies
constraints by OID so runtime is unaffected -- but future
`alembic revision --autogenerate` runs would detect drift between the live
schema and `db_models.py`. This revision brings the constraint names into
line with the bare-name scheme.

Constraints renamed (both `_local` and `_prod` variants, same pattern as
`e1974f8f8eee`):

- job_listings_{env}_pkey                    -> job_listings_pkey
- scrape_runs_{env}_pkey                     -> scrape_runs_pkey
- users_{env}_pkey                           -> users_pkey
- users_{env}_auth0_id_key                   -> users_auth0_id_key
- user_enabled_companies_{env}_pkey          -> user_enabled_companies_pkey
- user_enabled_companies_{env}_user_id_fkey  -> user_enabled_companies_user_id_fkey

Catalog-only DDL: every statement is an `ALTER TABLE RENAME CONSTRAINT`
wrapped in `DO $$ ... EXCEPTION WHEN undefined_object OR undefined_table
THEN NULL; END $$`. No data movement, no index rebuilds. Follows the same
allow-list rule as `e1974f8f8eee` (see the 2026-04-18 incident on full-table
rewrites filling Railway's 5 GB volume).

Cross-schema guard: `SELECT set_config('search_path', current_schema(),
true)` is the first statement of upgrade() and downgrade() for the same
reason documented in `e1974f8f8eee` -- under pytest the schema is
`test_<hex>` and only holds bare-named tables (so every rename no-ops),
while prod/local uses `public`.

Downgrade contract: like `e1974f8f8eee`, requires `-x env=<local|prod>`
on the CLI so the reverse rename knows which suffix to restore.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import context, op


# revision identifiers, used by Alembic.
revision: str = "f4008c4fb790"
down_revision: Union[str, None] = "e1974f8f8eee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, old_constraint_suffix_template, new_constraint_name)
# The template has `{env}` replaced with `local`/`prod` at statement time.
_CONSTRAINT_RENAMES: tuple[tuple[str, str, str], ...] = (
    ("job_listings",           "job_listings_{env}_pkey",                    "job_listings_pkey"),
    ("scrape_runs",            "scrape_runs_{env}_pkey",                     "scrape_runs_pkey"),
    ("users",                  "users_{env}_pkey",                           "users_pkey"),
    ("users",                  "users_{env}_auth0_id_key",                   "users_auth0_id_key"),
    ("user_enabled_companies", "user_enabled_companies_{env}_pkey",          "user_enabled_companies_pkey"),
    ("user_enabled_companies", "user_enabled_companies_{env}_user_id_fkey",  "user_enabled_companies_user_id_fkey"),
)


def upgrade() -> None:
    # Narrow search_path to the current schema for the duration of this
    # transaction so constraint renames cannot fall through to public.*
    # under a pytest `test_<hex>` schema. See e1974f8f8eee upgrade() for
    # the full rationale.
    op.execute("SELECT set_config('search_path', current_schema(), true)")

    for table, old_template, new_name in _CONSTRAINT_RENAMES:
        for env in ("local", "prod"):
            old_name = old_template.format(env=env)
            _rename_constraint_if_exists(table, old_name, new_name)


def downgrade() -> None:
    op.execute("SELECT set_config('search_path', current_schema(), true)")

    x = context.get_x_argument(as_dictionary=True)
    env = x.get("env")
    if env not in {"local", "prod"}:
        raise RuntimeError(
            "Downgrade of 'rename env-suffixed pk/fk constraints' requires "
            "-x env=<local|prod> on the alembic CLI so the rename "
            "direction is explicit. Got: "
            f"{env!r} (from {x!r}). Example: "
            "`alembic -x env=prod downgrade -1`."
        )

    for table, old_template, new_name in _CONSTRAINT_RENAMES:
        target_name = old_template.format(env=env)
        _rename_constraint_if_exists(table, new_name, target_name)


def _rename_constraint_if_exists(table: str, old: str, new: str) -> None:
    """Emit `ALTER TABLE <table> RENAME CONSTRAINT <old> TO <new>` guarded
    by a DO block that swallows `undefined_object` / `undefined_table`.

    `ALTER TABLE IF EXISTS` only guards the table, not the constraint, so
    the `IF EXISTS` form is insufficient here -- same pattern as the
    email-constraint rename in e1974f8f8eee.
    """
    op.execute(
        "DO $$ BEGIN "
        f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"; '
        "EXCEPTION WHEN undefined_object OR undefined_table THEN NULL; "
        "END $$"
    )
