"""add provider_config to companies and seed workday companies

Revision ID: b9714f608e21
Revises: a17b7c0ffee500
Create Date: 2026-05-19 15:43:55.335041+00:00

Combined schema + data migration:

1. Adds a `provider_config` JSONB NOT NULL DEFAULT '{}'::jsonb column to the
   ``companies`` table. Per-row contents are ATS-dependent; the column is the
   designated home for ATS configuration that doesn't fit in scalar columns
   (Workday's `base_url` / `tenant_slug` / `career_site_slug`, and the parallel
   Eightfold PR's `tenant_host` / `domain`). The column name is a frozen
   contract — do not rename without re-confirming with the sibling Eightfold
   migration.

2. Seeds 11 Workday rows. Source of truth at the time of writing:
     src/frontend/src/config/companies.ts (Workday block, lines ~532-614)
   Hand-written data migration (the documented exception to the
   autogenerate-only rule). Alembic's --autogenerate diffs schema, not data,
   so the per-company config blobs have to be transcribed by hand.

The schema half was originally produced by ``alembic revision --autogenerate``
after adding `provider_config` to `db_models.py::Company`. Procrastinate's
runtime-managed tables (`procrastinate_jobs`, `procrastinate_events`,
`procrastinate_periodic_defers`) appear in the autogen diff as "removed" since
they aren't declared in `db_models.py`; those false positives have been
stripped from `upgrade()` / `downgrade()` here — Procrastinate manages those
tables itself via `ensure_schema_async` at lifespan startup.

Future Workday adds should be made via a new migration, NOT by editing this
one — frozen migrations stay frozen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b9714f608e21'
down_revision: Union[str, None] = 'a17b7c0ffee500'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Workday seed rows. `provider_config` is the per-row JSONB blob the
# Procrastinate fetch task reads to construct the POST URL + body.
# `default_facets` is optional; only NVIDIA and Adobe set it today (used
# to narrow the result set to the US Engineering / University population).
WORKDAY_SEED_ROWS: list[dict] = [
    {
        'id': 'nvidia',
        'display_name': 'NVIDIA',
        'board_token': 'nvidia',
        'provider_config': {
            'base_url': 'https://nvidia.wd5.myworkdayjobs.com',
            'tenant_slug': 'nvidia',
            'career_site_slug': 'NVIDIAExternalCareerSite',
            'default_facets': {
                'locationHierarchy1': ['2fcb99c455831013ea52fb338f2932d8'],
                'jobFamilyGroup': ['0c40f6bd1d8f10ae43ffaefd46dc7e78'],
                'timeType': ['5509c0b5959810ac0029943377d47364'],
            },
        },
    },
    {
        'id': 'adobe',
        'display_name': 'Adobe',
        'board_token': 'adobe',
        'provider_config': {
            'base_url': 'https://adobe.wd5.myworkdayjobs.com',
            'tenant_slug': 'adobe',
            'career_site_slug': 'external_experienced',
            'default_facets': {
                'locationCountry': ['bc33aa3152ec42d4995f4791a106ed09'],
                'jobFamilyGroup': [
                    '591af8b812fa10737af39db3d96eed9f',
                    '591af8b812fa10737b43a1662896f01c',
                ],
            },
        },
    },
    {
        'id': 'expedia',
        'display_name': 'Expedia',
        'board_token': 'expedia',
        'provider_config': {
            'base_url': 'https://expedia.wd108.myworkdayjobs.com',
            'tenant_slug': 'expedia',
            'career_site_slug': 'search',
        },
    },
    {
        'id': 'turo',
        'display_name': 'Turo',
        'board_token': 'turo',
        'provider_config': {
            'base_url': 'https://turo.wd12.myworkdayjobs.com',
            'tenant_slug': 'turo',
            'career_site_slug': 'Turo_careers',
        },
    },
    {
        'id': 'blueorigin',
        'display_name': 'Blue Origin',
        'board_token': 'blueorigin',
        'provider_config': {
            'base_url': 'https://blueorigin.wd5.myworkdayjobs.com',
            'tenant_slug': 'blueorigin',
            'career_site_slug': 'BlueOrigin',
        },
    },
    {
        'id': 'snap',
        'display_name': 'Snap',
        'board_token': 'snap',
        'provider_config': {
            'base_url': 'https://snapchat.wd1.myworkdayjobs.com',
            'tenant_slug': 'snapchat',
            'career_site_slug': 'snap',
        },
    },
    {
        'id': 'gm',
        'display_name': 'General Motors',
        'board_token': 'gm',
        'provider_config': {
            'base_url': 'https://generalmotors.wd5.myworkdayjobs.com',
            'tenant_slug': 'generalmotors',
            'career_site_slug': 'Careers_GM',
        },
    },
    {
        'id': 'disney',
        'display_name': 'Disney',
        'board_token': 'disney',
        'provider_config': {
            'base_url': 'https://disney.wd5.myworkdayjobs.com',
            'tenant_slug': 'disney',
            'career_site_slug': 'disneycareer',
        },
    },
    {
        'id': 'slack',
        'display_name': 'Slack',
        'board_token': 'slack',
        'provider_config': {
            'base_url': 'https://salesforce.wd12.myworkdayjobs.com',
            'tenant_slug': 'salesforce',
            'career_site_slug': 'Slack',
        },
    },
    {
        'id': 'capitalone',
        'display_name': 'Capital One',
        'board_token': 'capitalone',
        'provider_config': {
            'base_url': 'https://capitalone.wd12.myworkdayjobs.com',
            'tenant_slug': 'capitalone',
            'career_site_slug': 'Capital_One',
        },
    },
    {
        'id': 'paypal',
        'display_name': 'PayPal',
        'board_token': 'paypal',
        'provider_config': {
            'base_url': 'https://paypal.wd1.myworkdayjobs.com',
            'tenant_slug': 'paypal',
            'career_site_slug': 'jobs',
        },
    },
]


def upgrade() -> None:
    # --- Schema change (autogenerated) ---
    # Adding a NOT NULL column with a server_default is a metadata-only change
    # in PostgreSQL 11+ for the bulk of the rewrite (`PG_DEFAULT` is stored
    # separately, not materialized into existing rows). Existing rows pick up
    # the `'{}'::jsonb` default lazily on SELECT. No table rewrite, no long
    # ACCESS EXCLUSIVE lock. See docs/incidents/2026-04-18-migration-filled-
    # postgres-volume for the cautionary tale of full-table rewrites.
    op.add_column(
        'companies',
        sa.Column(
            'provider_config',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # --- Data seed (hand-written, documented exception to autogen-only rule) ---
    # ON CONFLICT (id) DO NOTHING for idempotency: if any of these rows were
    # backfilled out-of-band (manual repair, partial prior run, prod hotfix),
    # the seed migration must NOT trip a PK-conflict and brick startup.
    # Re-running this migration after manual repair is a supported workflow.
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token, provider_config) "
        "VALUES (:id, :display_name, 'workday', :board_token, CAST(:provider_config AS jsonb)) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in WORKDAY_SEED_ROWS:
        bind.execute(
            insert_sql,
            {
                'id': row['id'],
                'display_name': row['display_name'],
                'board_token': row['board_token'],
                # psycopg2 / SQLAlchemy can't bind a dict directly into the
                # JSONB parameter via the text() interface — serialize to JSON
                # and use an explicit CAST in the SQL above. Same idiom used
                # by the Greenhouse/Ashby/Lever/Gem seeds for symmetry.
                'provider_config': _to_json(row['provider_config']),
            },
        )


def downgrade() -> None:
    # Scoped DELETE — must NOT touch Greenhouse / Ashby / Gem / Lever rows
    # or any out-of-band rows with other ats values. Mirrors the Ashby /
    # Lever / Gem seed downgrades. Runs BEFORE dropping the column so any
    # cleanup queries can still reference provider_config if needed.
    op.execute("DELETE FROM companies WHERE ats = 'workday'")
    op.drop_column('companies', 'provider_config')


def _to_json(value: dict) -> str:
    """Serialize a dict to a JSON string for the CAST(... AS jsonb) bind.

    Standalone so the import stays at the function-call level and the
    revision file doesn't need a `json` import at module load time
    (Alembic loads every revision module to build the dependency graph; we
    keep these light).
    """
    import json
    return json.dumps(value)
