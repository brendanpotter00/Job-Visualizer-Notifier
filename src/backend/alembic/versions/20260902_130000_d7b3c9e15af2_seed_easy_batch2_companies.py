"""seed September 2026 batch-2 companies (Okta, Box, Salesforce, CrowdStrike, Zoom, Intel)

Revision ID: d7b3c9e15af2
Revises: c9f3a7e21b84
Create Date: 2026-09-02 13:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds 6 more large companies to the ``companies`` table — 2 on Greenhouse,
4 on Workday. Every board_token / provider_config below was verified live against
its ATS API before this migration was written:

  Greenhouse:
  - ``okta``        board_token ``okta``     (328 postings)
  - ``box``         board_token ``boxinc``   (147 postings; plain ``box`` 404s)
  Workday (with provider_config; the pod is load-bearing — a wrong wdN 422s):
  - ``salesforce``  tenant ``salesforce``  site ``External_Career_Site``  pod wd12 (1491)
  - ``crowdstrike`` tenant ``crowdstrike`` site ``crowdstrikecareers``    pod wd5  (420)
  - ``zoom``        tenant ``zoom``        site ``Zoom``                  pod wd5  (96)
  - ``intel``       tenant ``intel``       site ``External``              pod wd1  (590)

Chains off ``c9f3a7e21b84`` (the September batch-1 seed, the current single head)
so the alembic chain keeps a single head when this PR merges into main.

``provider_config`` is NOT NULL DEFAULT '{}'::jsonb, so the two Greenhouse rows
insert an empty object (matching every other ATS company); the Workday rows carry
their real config. Uses ``INSERT ... ON CONFLICT (id) DO NOTHING`` (idempotent).
Lands after WORKDAY_SEED_REV, so the per-ATS counts in
``test_migration_companies.py`` are unaffected.

Source of truth for the frontend entries:
  src/frontend/src/config/companies.ts (these 6 rows)
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7b3c9e15af2'
down_revision: Union[str, None] = 'c9f3a7e21b84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    # Greenhouse
    {'id': 'okta', 'display_name': 'Okta', 'ats': 'greenhouse', 'board_token': 'okta',   'provider_config': None},
    {'id': 'box',  'display_name': 'Box',  'ats': 'greenhouse', 'board_token': 'boxinc', 'provider_config': None},
    # Workday (provider_config required)
    {
        'id': 'salesforce', 'display_name': 'Salesforce', 'ats': 'workday', 'board_token': 'External_Career_Site',
        'provider_config': {
            'base_url': 'https://salesforce.wd12.myworkdayjobs.com',
            'tenant_slug': 'salesforce',
            'career_site_slug': 'External_Career_Site',
        },
    },
    {
        'id': 'crowdstrike', 'display_name': 'CrowdStrike', 'ats': 'workday', 'board_token': 'crowdstrikecareers',
        'provider_config': {
            'base_url': 'https://crowdstrike.wd5.myworkdayjobs.com',
            'tenant_slug': 'crowdstrike',
            'career_site_slug': 'crowdstrikecareers',
        },
    },
    {
        'id': 'zoom', 'display_name': 'Zoom', 'ats': 'workday', 'board_token': 'Zoom',
        'provider_config': {
            'base_url': 'https://zoom.wd5.myworkdayjobs.com',
            'tenant_slug': 'zoom',
            'career_site_slug': 'Zoom',
        },
    },
    {
        'id': 'intel', 'display_name': 'Intel', 'ats': 'workday', 'board_token': 'External',
        'provider_config': {
            'base_url': 'https://intel.wd1.myworkdayjobs.com',
            'tenant_slug': 'intel',
            'career_site_slug': 'External',
        },
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token, provider_config) "
        "VALUES (:id, :display_name, :ats, :board_token, CAST(:provider_config AS JSONB)) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in SEED_ROWS:
        pc = row['provider_config']
        bind.execute(
            insert_sql,
            {
                'id': row['id'],
                'display_name': row['display_name'],
                'ats': row['ats'],
                'board_token': row['board_token'],
                # provider_config is NOT NULL DEFAULT '{}'::jsonb.
                'provider_config': json.dumps(pc) if pc is not None else '{}',
            },
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM companies WHERE id IN ("
        "'okta', 'box', 'salesforce', 'crowdstrike', 'zoom', 'intel')"
    )
