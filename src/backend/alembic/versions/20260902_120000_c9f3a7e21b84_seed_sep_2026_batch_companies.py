"""seed September 2026 batch companies

Revision ID: c9f3a7e21b84
Revises: fe69ff596030
Create Date: 2026-09-02 12:00:00.000000+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule). Adds a batch of 17 companies to the ``companies`` table — 13 on Ashby,
3 on Greenhouse, 1 on Workday. Every ``board_token`` below was verified live
against its ATS posting API before this migration was written; several differ
from the ``id`` (the JVN slug), which is the same id/board_token split the
``sierra`` and quant-firm seeds rely on:

  Ashby:
  - ``suno``                  board_token ``suno``
  - ``cerebras``              board_token ``cerebras``
  - ``physical-intelligence`` board_token ``physicalintelligence``  (hyphenated slug 404s)
  - ``mistral-ai``            board_token ``mistral.ai``             (dotted token)
  - ``replit``                board_token ``replit``
  - ``railway``               board_token ``railway``
  - ``crusoe``                board_token ``Crusoe``                 (matches careers URL)
  - ``raindrop-ai``           board_token ``raindrop``
  - ``wafer``                 board_token ``wafer``
  - ``clay``                  board_token ``claylabs``               (``clay`` is a different, empty board)
  - ``turbopuffer``           board_token ``turbopuffer``
  - ``openevidence``          board_token ``openevidence``
  - ``greptile``              board_token ``greptile``
  Greenhouse:
  - ``warp``                  board_token ``warp``                   (Greenhouse, NOT the unrelated Ashby ``warp``)
  - ``coinbase``              board_token ``coinbase``
  - ``janestreet``            board_token ``janestreet``
  Workday (with provider_config):
  - ``cisco``                 board_token ``Cisco_Careers``          (pod wd5)

Chains off ``fe69ff596030`` (the current single head — confirmed by parsing the
full revision DAG, including the two ``merge_*`` migrations whose tuple
``down_revision`` the ``current_head.py`` helper does not account for) so the
alembic chain keeps a single head when this PR merges into main.

Uses ``INSERT ... ON CONFLICT (id) DO NOTHING`` (idempotent / safe on partial
prior runs). Lands after the frozen per-ATS seed migrations, so the per-ATS
counts asserted in ``test_migration_companies.py`` (which stops at the workday
seed rev) are unaffected.

Source of truth for the frontend entries:
  src/frontend/src/config/companies.ts (these 16 rows)
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9f3a7e21b84'
down_revision: Union[str, None] = 'fe69ff596030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_ROWS = [
    # Ashby
    {'id': 'suno',                  'display_name': 'Suno',                  'ats': 'ashby',      'board_token': 'suno',                 'provider_config': None},
    {'id': 'cerebras',              'display_name': 'Cerebras',              'ats': 'ashby',      'board_token': 'cerebras',             'provider_config': None},
    {'id': 'physical-intelligence', 'display_name': 'Physical Intelligence', 'ats': 'ashby',      'board_token': 'physicalintelligence', 'provider_config': None},
    {'id': 'mistral-ai',            'display_name': 'Mistral AI',            'ats': 'ashby',      'board_token': 'mistral.ai',           'provider_config': None},
    {'id': 'replit',                'display_name': 'Replit',                'ats': 'ashby',      'board_token': 'replit',               'provider_config': None},
    {'id': 'railway',               'display_name': 'Railway',               'ats': 'ashby',      'board_token': 'railway',              'provider_config': None},
    {'id': 'crusoe',                'display_name': 'Crusoe',                'ats': 'ashby',      'board_token': 'Crusoe',               'provider_config': None},
    {'id': 'raindrop-ai',           'display_name': 'Raindrop',              'ats': 'ashby',      'board_token': 'raindrop',             'provider_config': None},
    {'id': 'wafer',                 'display_name': 'Wafer',                 'ats': 'ashby',      'board_token': 'wafer',                'provider_config': None},
    {'id': 'clay',                  'display_name': 'Clay',                  'ats': 'ashby',      'board_token': 'claylabs',             'provider_config': None},
    {'id': 'turbopuffer',           'display_name': 'turbopuffer',           'ats': 'ashby',      'board_token': 'turbopuffer',          'provider_config': None},
    {'id': 'openevidence',          'display_name': 'OpenEvidence',          'ats': 'ashby',      'board_token': 'openevidence',         'provider_config': None},
    {'id': 'greptile',              'display_name': 'Greptile',              'ats': 'ashby',      'board_token': 'greptile',             'provider_config': None},
    # Greenhouse
    {'id': 'warp',                  'display_name': 'Warp',                  'ats': 'greenhouse', 'board_token': 'warp',                 'provider_config': None},
    {'id': 'coinbase',              'display_name': 'Coinbase',              'ats': 'greenhouse', 'board_token': 'coinbase',             'provider_config': None},
    {'id': 'janestreet',            'display_name': 'Jane Street',           'ats': 'greenhouse', 'board_token': 'janestreet',           'provider_config': None},
    # Workday (provider_config required)
    {
        'id': 'cisco',
        'display_name': 'Cisco',
        'ats': 'workday',
        'board_token': 'Cisco_Careers',
        'provider_config': {
            'base_url': 'https://cisco.wd5.myworkdayjobs.com',
            'tenant_slug': 'cisco',
            'career_site_slug': 'Cisco_Careers',
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
                # None -> SQL NULL (CAST(NULL AS JSONB)); a dict -> JSON text.
                'provider_config': json.dumps(pc) if pc is not None else None,
            },
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM companies WHERE id IN ("
        "'suno', 'cerebras', 'physical-intelligence', 'mistral-ai', 'replit', "
        "'railway', 'crusoe', 'raindrop-ai', 'wafer', 'clay', 'turbopuffer', "
        "'openevidence', 'greptile', 'warp', 'coinbase', 'janestreet', 'cisco')"
    )
