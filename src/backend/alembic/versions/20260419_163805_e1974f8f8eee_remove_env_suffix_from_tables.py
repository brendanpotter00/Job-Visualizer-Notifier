"""remove env suffix from tables

Revision ID: e1974f8f8eee
Revises: 050b9adc98e1
Create Date: 2026-04-19 16:38:05.519972+00:00

envAgnosticTables Unit 3: rename every `_{env}`-suffixed user table, index,
and named constraint to its bare name. Tables affected: job_listings_{env},
scrape_runs_{env}, users_{env}, user_enabled_companies_{env}, features_{env},
feature_upvotes_{env}. The same revision file runs against local (`_local`
tables) and prod (`_prod` tables) -- every ALTER is `IF EXISTS`, so only
the variant present fires.

Catalog-only DDL: this migration issues ALTER TABLE RENAME / ALTER INDEX
RENAME / ALTER TABLE RENAME CONSTRAINT plus DROP TABLE IF EXISTS against
the pre-Alembic `schema_migrations_{env}` tracker and the leaked
`alembic_version_{env}` tracker. NO data movement, NO column changes, NO
index rebuilds. Per the 2026-04-18 incident where migrations 0003/0004
filled Railway's 5 GB volume via full-table rewrites, the allow-list is
enforced by a CI grep in Unit 3's Done-when gate.

Cross-schema guard: `SELECT set_config('search_path', current_schema(),
true)` is the first statement of upgrade() and downgrade(). `SET LOCAL`
does not accept function calls as values, so we use `set_config(..., true)`
which has the same transaction-scoped semantics. Under pytest,
current_schema() is the per-worker `test_<hex>` schema, which holds only
bare-named tables (post-Unit-2 create_all) -- every `IF EXISTS` rename
no-ops there. In prod/local, current_schema() is `public`, where the
`_{env}`-suffixed tables live.

Downgrade contract: requires `-x env=<local|prod>` on the command line so
the reverse rename knows which suffix to restore. Example:
    alembic -x env=local downgrade -1
RuntimeError is raised if `env` is missing or not in {local, prod}.

One-way note: `schema_migrations_{env}` (the pre-Alembic hand-rolled
tracker) is dropped by upgrade() and NOT recreated by downgrade() --
there is no automated path to rebuild that table's history. Downgrade
restores the user tables; it does not restore the retired tracker.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import context, op


# revision identifiers, used by Alembic.
revision: str = "e1974f8f8eee"
down_revision: Union[str, None] = "050b9adc98e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_USER_TABLE_BASE_NAMES: tuple[str, ...] = (
    # Rename order: child tables with FK references first, then parents.
    # In Postgres this is cosmetic -- ALTER TABLE RENAME is a pg_class
    # catalog update and FK constraints reference table OID, not name, so
    # rename order does not affect FK validity.
    "feature_upvotes",
    "features",
    "user_enabled_companies",
    "users",
    "scrape_runs",
    "job_listings",
)


def upgrade() -> None:
    # Narrow search_path to the current schema for the duration of this
    # transaction so `ALTER TABLE IF EXISTS <name>` cannot fall through
    # to public.* when running under a pytest `test_<hex>` schema.
    # `SET LOCAL` doesn't accept function calls; set_config(..., is_local=true)
    # is the transaction-scoped equivalent.
    op.execute("SELECT set_config('search_path', current_schema(), true)")

    # Drop pre-Alembic trackers. Tiny, catalog-only.
    op.execute("DROP TABLE IF EXISTS schema_migrations_local")
    op.execute("DROP TABLE IF EXISTS schema_migrations_prod")

    # Rename user tables. Same revision runs against local (_local) and
    # prod (_prod); IF EXISTS means only the present variant fires.
    for base in _USER_TABLE_BASE_NAMES:
        op.execute(f'ALTER TABLE IF EXISTS {base}_local RENAME TO {base}')
        op.execute(f'ALTER TABLE IF EXISTS {base}_prod RENAME TO {base}')

    # Rename named indexes. Enumerated explicitly so the grep-based
    # Done-when gate can verify we didn't slip in a CREATE INDEX.
    _rename_index_pair("idx_job_listings_local_status",          "idx_job_listings_status")
    _rename_index_pair("idx_job_listings_local_company",         "idx_job_listings_company")
    _rename_index_pair("idx_job_listings_local_last_seen",       "idx_job_listings_last_seen")
    _rename_index_pair("idx_job_listings_prod_status",           "idx_job_listings_status")
    _rename_index_pair("idx_job_listings_prod_company",          "idx_job_listings_company")
    _rename_index_pair("idx_job_listings_prod_last_seen",        "idx_job_listings_last_seen")
    _rename_index_pair("idx_users_local_auth0_id",               "idx_users_auth0_id")
    _rename_index_pair("idx_users_local_email",                  "idx_users_email")
    _rename_index_pair("idx_users_prod_auth0_id",                "idx_users_auth0_id")
    _rename_index_pair("idx_users_prod_email",                   "idx_users_email")
    _rename_index_pair("idx_user_enabled_companies_local_user_id", "idx_user_enabled_companies_user_id")
    _rename_index_pair("idx_user_enabled_companies_prod_user_id",  "idx_user_enabled_companies_user_id")
    _rename_index_pair("idx_feature_upvotes_local_feature_id",     "idx_feature_upvotes_feature_id")
    _rename_index_pair("idx_feature_upvotes_local_user_id",        "idx_feature_upvotes_user_id")
    _rename_index_pair("idx_feature_upvotes_prod_feature_id",      "idx_feature_upvotes_feature_id")
    _rename_index_pair("idx_feature_upvotes_prod_user_id",         "idx_feature_upvotes_user_id")

    # Rename named UNIQUE constraints on users.email. (Postgres auto-renames
    # the backing index to match the constraint, so we don't rename the
    # <name>_email_key index separately.) ALTER TABLE IF EXISTS guards only
    # the table, not the constraint -- wrap in DO/EXCEPTION so the absent
    # variant (e.g. users_prod_email_key under local) no-ops instead of
    # aborting the transaction.
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE users RENAME CONSTRAINT users_local_email_key TO users_email_key; "
        "EXCEPTION WHEN undefined_object OR undefined_table THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE users RENAME CONSTRAINT users_prod_email_key TO users_email_key; "
        "EXCEPTION WHEN undefined_object OR undefined_table THEN NULL; "
        "END $$"
    )

    # Clean up orphaned legacy Alembic trackers. Tiny (1 row), catalog-only.
    op.execute("DROP TABLE IF EXISTS alembic_version_local")
    op.execute("DROP TABLE IF EXISTS alembic_version_prod")


def downgrade() -> None:
    # See upgrade() for why this search_path narrowing is critical.
    op.execute("SELECT set_config('search_path', current_schema(), true)")

    # Parse -x env=<env> off the Alembic CLI. get_x_argument lives on
    # EnvironmentContext (alembic.context), not MigrationContext
    # (op.get_context()), so we import context directly.
    x = context.get_x_argument(as_dictionary=True)
    env = x.get("env")
    if env not in {"local", "prod"}:
        raise RuntimeError(
            "Downgrade of 'remove env suffix from tables' requires "
            "-x env=<local|prod> on the alembic CLI so the rename "
            "direction is explicit. Got: "
            f"{env!r} (from {x!r}). Example: "
            "`alembic -x env=local downgrade -1`."
        )

    # Reverse UNIQUE-constraint rename. Wrap in DO/EXCEPTION so an absent
    # constraint (e.g. pre-rename state, or a previous partial downgrade)
    # no-ops instead of aborting the transaction. `env` is validated against
    # {"local","prod"} above, but we still wrap identifiers in double quotes
    # to match the rest of the migration's style and keep defense-in-depth
    # against future edits that relax the validation.
    op.execute(
        'DO $$ BEGIN '
        f'ALTER TABLE "users" RENAME CONSTRAINT "users_email_key" TO "users_{env}_email_key"; '
        'EXCEPTION WHEN undefined_object OR undefined_table THEN NULL; '
        'END $$'
    )

    # Reverse index renames.
    _rename_index_pair("idx_job_listings_status",           f"idx_job_listings_{env}_status")
    _rename_index_pair("idx_job_listings_company",          f"idx_job_listings_{env}_company")
    _rename_index_pair("idx_job_listings_last_seen",        f"idx_job_listings_{env}_last_seen")
    _rename_index_pair("idx_users_auth0_id",                f"idx_users_{env}_auth0_id")
    _rename_index_pair("idx_users_email",                   f"idx_users_{env}_email")
    _rename_index_pair("idx_user_enabled_companies_user_id",
                       f"idx_user_enabled_companies_{env}_user_id")
    _rename_index_pair("idx_feature_upvotes_feature_id",    f"idx_feature_upvotes_{env}_feature_id")
    _rename_index_pair("idx_feature_upvotes_user_id",       f"idx_feature_upvotes_{env}_user_id")

    # Reverse table renames.
    for base in reversed(_USER_TABLE_BASE_NAMES):
        op.execute(f'ALTER TABLE IF EXISTS {base} RENAME TO {base}_{env}')

    # NOT recreated: schema_migrations_<env>. Deliberate. See module docstring.


def _rename_index_pair(old: str, new: str) -> None:
    """ALTER INDEX IF EXISTS <old> RENAME TO <new> -- helper for readability."""
    op.execute(f'ALTER INDEX IF EXISTS "{old}" RENAME TO "{new}"')
