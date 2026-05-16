"""seed greenhouse companies

Revision ID: 939331c99a23
Revises: 438ad0658e53
Create Date: 2026-05-16 00:14:52.142765+00:00

Hand-written data migration (the documented exception to the autogenerate-only
rule in feedback_use_alembic_migrations.md). Alembic's --autogenerate diffs
schema, not data — so the ~45 Greenhouse companies that previously lived in
src/frontend/src/config/companies.ts must be transcribed by hand into
op.bulk_insert below.

Source of truth at the time of writing:
  src/frontend/src/config/companies.ts (Greenhouse block)

All entries here use the default Greenhouse boardToken == id (none of the
frontend entries override boardToken). Future Greenhouse adds should be made
via a new migration, NOT by editing this one — frozen migrations stay frozen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '939331c99a23'
down_revision: Union[str, None] = '438ad0658e53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


companies_table = sa.table(
    'companies',
    sa.column('id', sa.Text()),
    sa.column('display_name', sa.Text()),
    sa.column('ats', sa.Text()),
    sa.column('board_token', sa.Text()),
)


GREENHOUSE_SEED_ROWS = [
    {'id': 'spacex',           'display_name': 'SpaceX',              'ats': 'greenhouse', 'board_token': 'spacex'},
    {'id': 'andurilindustries','display_name': 'Anduril',             'ats': 'greenhouse', 'board_token': 'andurilindustries'},
    {'id': 'airtable',         'display_name': 'Airtable',            'ats': 'greenhouse', 'board_token': 'airtable'},
    {'id': 'airbnb',           'display_name': 'Airbnb',              'ats': 'greenhouse', 'board_token': 'airbnb'},
    {'id': 'fireworksai',      'display_name': 'Fireworks AI',        'ats': 'greenhouse', 'board_token': 'fireworksai'},
    {'id': 'figma',            'display_name': 'Figma',               'ats': 'greenhouse', 'board_token': 'figma'},
    {'id': 'twitch',           'display_name': 'Twitch',              'ats': 'greenhouse', 'board_token': 'twitch'},
    {'id': 'neuralink',        'display_name': 'Neuralink',           'ats': 'greenhouse', 'board_token': 'neuralink'},
    {'id': 'robinhood',        'display_name': 'Robinhood',           'ats': 'greenhouse', 'board_token': 'robinhood'},
    {'id': 'xai',              'display_name': 'XAI',                 'ats': 'greenhouse', 'board_token': 'xai'},
    {'id': 'anthropic',        'display_name': 'Anthropic',           'ats': 'greenhouse', 'board_token': 'anthropic'},
    {'id': 'reddit',           'display_name': 'Reddit',              'ats': 'greenhouse', 'board_token': 'reddit'},
    {'id': 'cloudflare',       'display_name': 'Cloudflare',          'ats': 'greenhouse', 'board_token': 'cloudflare'},
    {'id': 'scaleai',          'display_name': 'ScaleAI',             'ats': 'greenhouse', 'board_token': 'scaleai'},
    {'id': 'lyft',             'display_name': 'Lyft',                'ats': 'greenhouse', 'board_token': 'lyft'},
    {'id': 'doordashusa',      'display_name': 'Doordash',            'ats': 'greenhouse', 'board_token': 'doordashusa'},
    {'id': 'stripe',           'display_name': 'Stripe',              'ats': 'greenhouse', 'board_token': 'stripe'},
    {'id': 'appliedintuition', 'display_name': 'Applied Intuition',   'ats': 'greenhouse', 'board_token': 'appliedintuition'},
    {'id': 'discord',          'display_name': 'Discord',             'ats': 'greenhouse', 'board_token': 'discord'},
    {'id': 'brex',             'display_name': 'Brex',                'ats': 'greenhouse', 'board_token': 'brex'},
    {'id': 'squarespace',      'display_name': 'Squarespace',         'ats': 'greenhouse', 'board_token': 'squarespace'},
    {'id': 'clear',            'display_name': 'Clear',               'ats': 'greenhouse', 'board_token': 'clear'},
    {'id': 'affirm',           'display_name': 'Affirm',              'ats': 'greenhouse', 'board_token': 'affirm'},
    {'id': 'crunchyroll',      'display_name': 'Crunchyroll',         'ats': 'greenhouse', 'board_token': 'crunchyroll'},
    {'id': 'nuro',             'display_name': 'Nuro',                'ats': 'greenhouse', 'board_token': 'nuro'},
    {'id': 'pallet',           'display_name': 'Pallet',              'ats': 'greenhouse', 'board_token': 'pallet'},
    {'id': 'pinterest',        'display_name': 'Pinterest',           'ats': 'greenhouse', 'board_token': 'pinterest'},
    {'id': 'astranis',         'display_name': 'Astranis',            'ats': 'greenhouse', 'board_token': 'astranis'},
    {'id': 'waymo',            'display_name': 'Waymo',               'ats': 'greenhouse', 'board_token': 'waymo'},
    {'id': 'figureai',         'display_name': 'Figure AI',           'ats': 'greenhouse', 'board_token': 'figureai'},
    {'id': 'gleanwork',        'display_name': 'Glean',               'ats': 'greenhouse', 'board_token': 'gleanwork'},
    {'id': 'merge',            'display_name': 'Merge',               'ats': 'greenhouse', 'board_token': 'merge'},
    {'id': 'databricks',       'display_name': 'Databricks',          'ats': 'greenhouse', 'board_token': 'databricks'},
    {'id': 'datadog',          'display_name': 'Datadog',             'ats': 'greenhouse', 'board_token': 'datadog'},
    {'id': 'dropbox',          'display_name': 'Dropbox',             'ats': 'greenhouse', 'board_token': 'dropbox'},
    {'id': 'instacart',        'display_name': 'Instacart',           'ats': 'greenhouse', 'board_token': 'instacart'},
    {'id': 'mongodb',          'display_name': 'MongoDB',             'ats': 'greenhouse', 'board_token': 'mongodb'},
    {'id': 'twilio',           'display_name': 'Twilio',              'ats': 'greenhouse', 'board_token': 'twilio'},
    {'id': 'block',            'display_name': 'Block',               'ats': 'greenhouse', 'board_token': 'block'},
    {'id': 'gitlab',           'display_name': 'GitLab',              'ats': 'greenhouse', 'board_token': 'gitlab'},
    {'id': 'unity3d',          'display_name': 'Unity',               'ats': 'greenhouse', 'board_token': 'unity3d'},
    {'id': 'vercel',           'display_name': 'Vercel',              'ats': 'greenhouse', 'board_token': 'vercel'},
    {'id': 'thinkingmachines', 'display_name': 'Thinking Machines',   'ats': 'greenhouse', 'board_token': 'thinkingmachines'},
    {'id': 'togetherai',       'display_name': 'Together AI',         'ats': 'greenhouse', 'board_token': 'togetherai'},
    {'id': 'hightouch',        'display_name': 'Hightouch',           'ats': 'greenhouse', 'board_token': 'hightouch'},
]


def upgrade() -> None:
    op.bulk_insert(companies_table, GREENHOUSE_SEED_ROWS)


def downgrade() -> None:
    # The DROP TABLE lives in the schema migration. Here we only remove the
    # rows this revision inserted, so a -1 downgrade leaves an empty companies
    # table behind for the schema migration to drop on the next -1.
    op.execute("DELETE FROM companies WHERE ats = 'greenhouse'")
