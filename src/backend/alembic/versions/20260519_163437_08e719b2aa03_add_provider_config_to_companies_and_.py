"""add provider_config to companies and seed eightfold companies

Revision ID: 08e719b2aa03
Revises: b29c1ef8800600
Create Date: 2026-05-19 16:34:37.883974+00:00

Combined schema + data migration:

1. Adds a ``provider_config`` JSONB NOT NULL DEFAULT ``'{}'::jsonb`` column to
   the ``companies`` table. Per-row contents are ATS-dependent; the column is
   the designated home for ATS configuration that doesn't fit in scalar columns.
   Eightfold rows carry ``{tenant_host, domain}``. The column name is a frozen
   contract shared with the parallel Workday PR #123, which uses the same
   column for ``{base_url, tenant_slug, career_site_slug, default_facets?}``.

   **Rebase coordination with sibling backend-migration PRs:**
     During the merge that brought this PR up to main, the Lever (#122) and
     Gem (#121) seed migrations had already landed, extending the chain
     Ashby → Lever → Gem. ``down_revision`` was rebased from
     ``'a17b7c0ffee500'`` (Ashby) to ``'b29c1ef8800600'`` (Gem) so Alembic
     has a single head. Neither Lever nor Gem touch ``provider_config``,
     so the ``op.add_column`` add is still safe.

     If Workday PR #123 merges first (its plan also writes
     ``provider_config``), the mechanical rebase is: drop the
     ``op.add_column`` (and ``op.drop_column``) and keep the data
     migration. See
     ``docs/implementations/eightfoldBackendMigration/DEPLOY.md`` for the
     resolution procedure.

2. Seeds 1 Eightfold row (Netflix). Source of truth at the time of writing:
     src/frontend/src/config/companies.ts (Eightfold block, line ~617)
   Hand-written data migration (the documented exception to the
   autogenerate-only rule). Alembic's --autogenerate diffs schema, not data,
   so the per-company config blob has to be transcribed by hand.

The schema half was originally produced by ``alembic revision --autogenerate``
after adding ``provider_config`` to ``db_models.py::Company``. Procrastinate's
runtime-managed tables (``procrastinate_jobs``, ``procrastinate_events``,
``procrastinate_periodic_defers``) appear in the autogen diff as "removed"
since they aren't declared in ``db_models.py``; those false positives have
been stripped from ``upgrade()`` / ``downgrade()`` here — Procrastinate manages
those tables itself via ``ensure_schema_async`` at lifespan startup.

Future Eightfold adds should be made via a new migration, NOT by editing this
one — frozen migrations stay frozen. Vanity-host SSRF allowlist entries in
``src/backend/api/services/eightfold_client.py`` must be kept in sync with any
new ``tenant_host`` value added by a future seed migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '08e719b2aa03'
down_revision: Union[str, None] = 'b29c1ef8800600'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Eightfold seed rows. ``provider_config`` is the per-row JSONB blob the
# Procrastinate fetch task reads to construct the GET URL. ``tenant_host`` is
# validated against the SSRF allowlist in ``eightfold_client.py`` before any
# outbound HTTP call.
EIGHTFOLD_SEED_ROWS: list[dict] = [
    {
        'id': 'netflix',
        'display_name': 'Netflix',
        'board_token': 'netflix',
        'provider_config': {
            'tenant_host': 'explore.jobs.netflix.net',
            'domain': 'netflix.com',
        },
    },
]


def upgrade() -> None:
    # 1. Schema half: add the JSONB column with a NOT NULL ``'{}'`` default so
    #    every existing Greenhouse / Ashby row gets the empty placeholder
    #    without any DML.
    op.add_column(
        'companies',
        sa.Column(
            'provider_config',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # 2. Data half: ON CONFLICT (id) DO NOTHING for idempotency. If any of
    #    these rows were backfilled out-of-band (manual repair, partial prior
    #    run, prod hotfix), the seed migration must NOT trip a PK-conflict and
    #    brick startup. ``enabled`` is omitted from the INSERT; the column has
    #    ``server_default=true``.
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token, provider_config) "
        "VALUES (:id, :display_name, 'eightfold', :board_token, "
        "CAST(:provider_config AS JSONB)) "
        "ON CONFLICT (id) DO NOTHING"
    )
    import json
    for row in EIGHTFOLD_SEED_ROWS:
        bind.execute(
            insert_sql,
            {
                'id': row['id'],
                'display_name': row['display_name'],
                'board_token': row['board_token'],
                'provider_config': json.dumps(row['provider_config']),
            },
        )


def downgrade() -> None:
    # Scoped DELETE — must not touch Greenhouse / Ashby / Workday rows.
    op.execute("DELETE FROM companies WHERE ats = 'eightfold'")
    op.drop_column('companies', 'provider_config')
